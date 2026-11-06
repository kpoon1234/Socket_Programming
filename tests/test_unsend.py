"""Verify unsend message functionality for private and group conversations."""

import json
from pathlib import Path
import signal
import tempfile
import unittest

from feature.summarize.service import prepare_messages
from protocol import receive_messages, send_message
from state_store import ChatStateStore
from test_chat import ServerTestCase
from test_group_messages import GroupPeerHelpers


class UnsendTests(GroupPeerHelpers, ServerTestCase):
    def room_peer(self, name):
        peer = self.peer()
        peer.skipped = []
        peer.send({"type": "register", "name": name, "capabilities": ["private_rooms", "groups", "group_messages"]})
        self.assertEqual(peer.receive()["type"], "registered")
        self.event(peer, "private_rooms")
        self.event(peer, "groups_updated")
        return peer

    def open_private(self, peer, other=None, room_id=None):
        target = {"to": other} if room_id is None else {"room_id": room_id}
        peer.send({"type": "open_private", "request_id": "open", **target})
        return self.event(peer, "room_opened")

    def send_private(self, peer, room_id, text, request_id="send"):
        peer.send({"type": "private_message", "room_id": room_id, "text": text, "request_id": request_id})
        message = self.event(peer, "private_message")
        self.event(peer, "sent")
        return message

    def test_unsend_private_message_live_and_history(self):
        alice = self.room_peer("alice")
        bob = self.room_peer("bob")
        room = self.open_private(alice, "bob")
        room_id = room["room_id"]
        self.open_private(bob, room_id=room_id)

        msg = self.send_private(alice, room_id, "Secret message to unsend")
        bob_msg = self.event(bob, "private_message")
        self.assertEqual(bob_msg["message_id"], msg["message_id"])

        # Alice unsends the message
        alice.send({
            "type": "unsend_message",
            "room_type": "private",
            "room_id": room_id,
            "message_id": msg["message_id"],
            "request_id": "unsend-1",
        })

        alice_unsent = self.event(alice, "message_unsent")
        self.assertEqual(alice_unsent["message_id"], msg["message_id"])
        self.assertEqual(alice_unsent["room_id"], room_id)
        self.assertEqual(alice_unsent["request_id"], "unsend-1")
        self.assertEqual(alice_unsent["from"], "alice")

        alice_sent = self.event(alice, "sent")
        self.assertEqual(alice_sent["action"], "unsend")
        self.assertEqual(alice_sent["request_id"], "unsend-1")

        # Bob receives message_unsent notification
        bob_unsent = self.event(bob, "message_unsent")
        self.assertEqual(bob_unsent["message_id"], msg["message_id"])
        self.assertEqual(bob_unsent["room_id"], room_id)
        self.assertEqual(bob_unsent["from"], "alice")

        # Check persisted state
        state = json.loads(self.state_path.read_text())
        persisted_msg = next(m for m in state["messages"] if m["message_id"] == msg["message_id"])
        self.assertTrue(persisted_msg.get("unsent"))
        self.assertEqual(persisted_msg["text"], "This message was unsent")

        # When Bob re-opens the room, history has the unsent flag
        bob_room = self.open_private(bob, room_id=room_id)
        hist_msg = next(m for m in bob_room["messages"] if m["message_id"] == msg["message_id"])
        self.assertTrue(hist_msg.get("unsent"))

    def test_unsend_group_message_live_and_history(self):
        alice = self.member("alice")
        bob = self.member("bob")
        carol = self.member("carol")
        group_id = self.create(alice, "Team")
        self.join(bob, group_id)
        self.join(carol, group_id)

        msg = self.send(alice, group_id, "Hello everyone!")
        self.assertEqual(self.event(bob, "group_message")["message_id"], msg["message_id"])
        self.assertEqual(self.event(carol, "group_message")["message_id"], msg["message_id"])

        # Alice unsends the group message
        alice.send({
            "type": "unsend_message",
            "room_type": "group",
            "group_id": group_id,
            "message_id": msg["message_id"],
            "request_id": "unsend-grp",
        })

        alice_unsent = self.event(alice, "message_unsent")
        self.assertEqual(alice_unsent["message_id"], msg["message_id"])
        self.assertEqual(alice_unsent["group_id"], group_id)
        self.assertEqual(alice_unsent["request_id"], "unsend-grp")

        # Bob and Carol receive message_unsent
        bob_unsent = self.event(bob, "message_unsent")
        self.assertEqual(bob_unsent["message_id"], msg["message_id"])
        self.assertEqual(bob_unsent["group_id"], group_id)

        carol_unsent = self.event(carol, "message_unsent")
        self.assertEqual(carol_unsent["message_id"], msg["message_id"])
        self.assertEqual(carol_unsent["group_id"], group_id)

        # Check persisted state in group_messages
        state = json.loads(self.state_path.read_text())
        persisted_msg = next(m for m in state["group_messages"] if m["message_id"] == msg["message_id"])
        self.assertTrue(persisted_msg.get("unsent"))
        self.assertEqual(persisted_msg["text"], "This message was unsent")

    def test_unsend_other_user_message_is_rejected(self):
        alice = self.room_peer("alice")
        bob = self.room_peer("bob")
        room = self.open_private(alice, "bob")
        room_id = room["room_id"]
        msg = self.send_private(alice, room_id, "Alice message")

        # Bob tries to unsend Alice's message
        bob.send({
            "type": "unsend_message",
            "room_type": "private",
            "room_id": room_id,
            "message_id": msg["message_id"],
            "request_id": "hack",
        })

        error = self.event(bob, "error")
        self.assertEqual(error["request_id"], "hack")
        self.assertIn("own messages", error["text"])

        # Ensure message is still not unsent
        state = json.loads(self.state_path.read_text())
        persisted_msg = next(m for m in state["messages"] if m["message_id"] == msg["message_id"])
        self.assertFalse(persisted_msg.get("unsent", False))
        self.assertEqual(persisted_msg["text"], "Alice message")

    def test_unsend_already_unsent_message_is_rejected(self):
        alice = self.room_peer("alice")
        bob = self.room_peer("bob")
        room = self.open_private(alice, "bob")
        room_id = room["room_id"]
        msg = self.send_private(alice, room_id, "Once")

        alice.send({
            "type": "unsend_message",
            "room_type": "private",
            "room_id": room_id,
            "message_id": msg["message_id"],
            "request_id": "first",
        })
        self.event(alice, "message_unsent")
        self.event(alice, "sent")

        # Try to unsend again
        alice.send({
            "type": "unsend_message",
            "room_type": "private",
            "room_id": room_id,
            "message_id": msg["message_id"],
            "request_id": "second",
        })
        error = self.event(alice, "error")
        self.assertEqual(error["request_id"], "second")
        self.assertIn("already unsent", error["text"])

    def test_unsend_nonexistent_message_is_rejected(self):
        alice = self.room_peer("alice")
        bob = self.room_peer("bob")
        room = self.open_private(alice, "bob")
        room_id = room["room_id"]

        alice.send({
            "type": "unsend_message",
            "room_type": "private",
            "room_id": room_id,
            "message_id": "fake_id",
            "request_id": "missing",
        })
        error = self.event(alice, "error")
        self.assertEqual(error["request_id"], "missing")
        self.assertIn("not found", error["text"].lower())

    def test_unsend_survives_server_restart(self):
        alice = self.room_peer("alice")
        bob = self.room_peer("bob")
        room = self.open_private(alice, "bob")
        room_id = room["room_id"]
        msg = self.send_private(alice, room_id, "Before restart")

        alice.send({
            "type": "unsend_message",
            "room_type": "private",
            "room_id": room_id,
            "message_id": msg["message_id"],
            "request_id": "unsend-pre-restart",
        })
        self.event(alice, "message_unsent")
        self.event(alice, "sent")

        # Restart server
        self.server.send_signal(signal.SIGINT)
        self.assertEqual(self.server.wait(timeout=5), 0)
        self.output.finish()
        self.start_server()

        # Connect after restart
        alice = self.room_peer("alice")
        reopened = self.open_private(alice, room_id=room_id)
        reopened_msg = next(m for m in reopened["messages"] if m["message_id"] == msg["message_id"])
        self.assertTrue(reopened_msg.get("unsent"))
        self.assertEqual(reopened_msg["text"], "This message was unsent")

    def test_unsend_group_with_offline_member_and_reconnect(self):
        alice = self.member("alice")
        bob = self.member("bob")
        group_id = self.create(alice, "Offline Unsend")
        self.join(bob, group_id)

        bob.close()
        self.output.wait_for("Client disconnected: bob")

        # Alice sends message while Bob is offline
        msg = self.send(alice, group_id, "Sent while Bob offline")

        # Alice unsends the message while Bob is still offline
        alice.send({
            "type": "unsend_message",
            "room_type": "group",
            "group_id": group_id,
            "message_id": msg["message_id"],
            "request_id": "unsend-offline",
        })
        self.event(alice, "message_unsent")
        self.event(alice, "sent")

        # Bob reconnects
        bob = self.member("bob")
        opened = self.open(bob, group_id)
        hist_msg = next(m for m in opened["messages"] if m["message_id"] == msg["message_id"])
        self.assertTrue(hist_msg.get("unsent"))
        self.assertEqual(hist_msg["text"], "This message was unsent")

    def test_unsend_without_registration_rejected(self):
        anonymous = self.peer()
        anonymous.send({
            "type": "unsend_message",
            "room_type": "private",
            "room_id": "private_test",
            "message_id": "message_test",
            "request_id": "anon",
        })
        reply = anonymous.receive()
        self.assertEqual(reply["type"], "error")
        self.assertIn("Register", reply["text"])

    def test_prepare_messages_ignores_unsent_messages(self):
        messages = [
            {"message_id": "m1", "from": "alice", "text": "Hello", "timestamp": "2026-11-06T00:00:00Z"},
            {"message_id": "m2", "from": "alice", "text": "This message was unsent", "unsent": True, "timestamp": "2026-11-06T00:01:00Z"},
            {"message_id": "m3", "from": "bob", "text": "World", "timestamp": "2026-11-06T00:02:00Z"},
        ]
        prepared = prepare_messages(messages)
        self.assertEqual(prepared.message_count, 2)
        parsed = json.loads(prepared.conversation)
        self.assertEqual([item["text"] for item in parsed], ["Hello", "World"])


if __name__ == "__main__":
    unittest.main()

"""Verify private-room authorization, persistence, and concurrent ordering."""

from concurrent.futures import ThreadPoolExecutor
import json
import signal
import threading
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import server
from protocol import receive_messages
from state_store import ChatStateStore
from test_chat import ChunkConnection, ServerTestCase


class PrivateRoomTests(ServerTestCase):
    def room_peer(self, name):
        peer = self.peer()
        peer.send({"type": "register", "name": name, "capabilities": ["private_rooms"]})
        self.assertEqual(peer.receive()["type"], "registered")
        restored = peer.receive()
        self.assertEqual(restored["type"], "private_rooms")
        return peer, restored["rooms"]

    def event(self, peer, kind):
        while True:
            event = peer.receive()
            if event["type"] == kind:
                return event

    def open_room(self, peer, other=None, room_id=None):
        target = {"to": other} if room_id is None else {"room_id": room_id}
        peer.send({"type": "open_private", "request_id": "open", **target})
        return self.event(peer, "room_opened")

    def test_pair_reuses_room_from_both_directions_even_concurrently(self):
        alice, _ = self.room_peer("alice")
        bob, _ = self.room_peer("bob")
        barrier = threading.Barrier(2)

        def open_pair(item):
            peer, name = item
            barrier.wait(timeout=5)
            return self.open_room(peer, name)["room_id"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(open_pair, ((alice, "bob"), (bob, "alice"))))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(len(json.loads(self.state_path.read_text())["private_rooms"]), 1)

    def test_outsider_cannot_open_send_or_receive_private_content(self):
        alice, _ = self.room_peer("alice")
        bob, _ = self.room_peer("bob")
        carol, _ = self.room_peer("carol")
        room = self.open_room(alice, "bob")
        for kind in ("open_private", "private_message"):
            carol.send({"type": kind, "room_id": room["room_id"], "text": "forged", "request_id": kind})
            error = carol.receive()
            self.assertEqual(error["type"], "error")
            self.assertEqual(error["request_id"], kind)
        alice.send({"type": "private_message", "room_id": room["room_id"], "text": "secret", "request_id": "send", "from": "carol"})
        self.assertEqual(self.event(bob, "private_message")["from"], "alice")
        self.event(alice, "sent")
        own_room = self.open_room(carol, "alice")
        self.assertEqual(own_room["messages"], [])

    def test_server_restart_keeps_room_ids_and_history_but_not_online_users(self):
        alice, _ = self.room_peer("alice")
        bob, _ = self.room_peer("bob")
        room = self.open_room(alice, "bob")
        alice.send({"type": "private_message", "room_id": room["room_id"], "text": "Before restart", "request_id": "send"})
        original = self.event(alice, "private_message")
        original.pop("request_id")
        self.event(alice, "sent")
        self.server.send_signal(signal.SIGINT)
        self.assertEqual(self.server.wait(timeout=5), 0)
        self.output.finish()
        self.start_server()
        alice, restored = self.room_peer("alice")
        self.assertEqual(restored[0]["room_id"], room["room_id"])
        self.assertEqual(alice.wait_users(["alice"])["users"], ["alice"])
        history = self.open_room(alice, room_id=room["room_id"])["messages"]
        self.assertEqual(history, [original])
        alice.send({"type": "private_message", "room_id": room["room_id"], "text": "Offline", "request_id": "offline"})
        self.assertIn("not connected", self.event(alice, "error")["text"])
        bob, _ = self.room_peer("bob")
        self.assertEqual(self.open_room(bob, "alice")["room_id"], room["room_id"])
        bob.send({"type": "private_message", "room_id": room["room_id"], "text": "After restart", "request_id": "reply"})
        self.assertEqual(self.event(alice, "private_message")["sequence"], 2)

    def test_concurrent_senders_see_the_same_order_without_duplicate_messages(self):
        alice, _ = self.room_peer("alice")
        bob, _ = self.room_peer("bob")
        room = self.open_room(alice, "bob")
        self.open_room(bob, "alice")

        def send_batch(item):
            peer, prefix = item
            for index in range(10):
                peer.send({"type": "private_message", "room_id": room["room_id"], "text": f"{prefix}-{index}", "request_id": f"{prefix}-{index}"})

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(send_batch, ((alice, "a"), (bob, "b"))))
        received = []
        for peer in (alice, bob):
            messages = [self.event(peer, "private_message") for _ in range(20)]
            self.assertEqual([item["sequence"] for item in messages], list(range(1, 21)))
            received.append([item["message_id"] for item in messages])
        self.assertEqual(received[0], received[1])
        self.assertEqual(len(set(received[0])), 20)

    def test_legacy_terminal_and_web_clients_share_one_persisted_room(self):
        alice = self.peer("alice")
        bob, _ = self.room_peer("bob")
        alice.send({"type": "message", "to": "bob", "text": "From terminal"})
        first = self.event(bob, "private_message")
        self.assertEqual(alice.receive(), {"type": "sent", "to": "bob"})
        bob.send({"type": "private_message", "room_id": first["room_id"], "text": "From web", "request_id": "reply"})
        self.assertEqual(alice.receive(), {"type": "message", "from": "bob", "to": "alice", "text": "From web"})
        self.event(bob, "sent")
        self.assertEqual([item["text"] for item in self.open_room(bob, "alice")["messages"]], ["From terminal", "From web"])

    def test_empty_invalid_and_offline_sends_do_not_add_history(self):
        alice, _ = self.room_peer("alice")
        bob, _ = self.room_peer("bob")
        room = self.open_room(alice, "bob")
        for text in ("", "  \n", None, 42):
            alice.send({"type": "private_message", "room_id": room["room_id"], "text": text, "request_id": "invalid"})
            self.assertEqual(alice.receive()["type"], "error")
        bob.close()
        alice.wait_users(["alice"])
        alice.send({"type": "private_message", "room_id": room["room_id"], "text": "Offline", "request_id": "offline"})
        self.assertEqual(alice.receive()["type"], "error")
        self.assertEqual(self.open_room(alice, room_id=room["room_id"])["messages"], [])


class PrivateDeliveryFailureTests(unittest.TestCase):
    def test_receiver_failure_after_save_reports_persisted_message_without_sent_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ChatStateStore(Path(directory) / "chat_state.json")
            room = store.get_or_create_room("alice", "bob")
            writer = ChunkConnection()
            alice = server.ClientConnection(writer)
            alice.name, alice.supports_rooms = "alice", True
            bob = server.ClientConnection(Mock())
            bob.name = "bob"
            with patch.object(server, "chat_state", store), patch.object(server, "users_version", 0), \
                    patch.dict(server.clients, {"alice": alice, "bob": bob}, clear=True), \
                    patch.object(bob, "send_private", side_effect=OSError("receiver closed")):
                server.deliver_private(alice, room["room_id"], "Saved once", "send-1")
            events = list(receive_messages(ChunkConnection([writer.sent])))
            self.assertEqual(sum(event["type"] == "private_message" for event in events), 1)
            self.assertFalse(any(event["type"] == "sent" for event in events))
            failure = next(event for event in events if event["type"] == "error")
            self.assertTrue(failure["persisted"])
            self.assertEqual(failure["request_id"], "send-1")
            history = ChatStateStore(store.path).snapshot(room["room_id"], "bob")["messages"]
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["message_id"], failure["message_id"])

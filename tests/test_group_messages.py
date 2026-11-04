"""Verify group message audiences, durable history, and delivery ordering."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import Mock, patch

from protocol import receive_messages
import server
from state_store import ChatStateStore
from test_chat import ChunkConnection, ServerTestCase


class GroupMessageTests(ServerTestCase):
    def event(self, peer, kind, predicate=lambda item: True):
        while True:
            event = peer.receive()
            if event["type"] == kind and predicate(event):
                return event
            if not hasattr(peer, "skipped"):
                peer.skipped = []
            peer.skipped.append(event)

    def member(self, name):
        peer = self.peer()
        peer.skipped = []
        peer.send({"type": "register", "name": name, "capabilities": ["private_rooms", "groups", "group_messages"]})
        self.assertEqual(peer.receive(), {"type": "registered", "name": name})
        self.event(peer, "private_rooms")
        self.event(peer, "groups_updated")
        return peer

    def create(self, peer, name="Study group"):
        peer.send({"type": "create_group", "name": name, "request_id": "create"})
        return self.event(peer, "group_created")["group_id"]

    def join(self, peer, group_id):
        peer.send({"type": "join_group", "group_id": group_id, "request_id": "join"})
        self.event(peer, "group_joined")

    def open(self, peer, group_id):
        peer.send({"type": "open_group", "group_id": group_id, "request_id": "open"})
        return self.event(peer, "group_opened", lambda event: event.get("request_id") == "open")

    def send(self, peer, group_id, text, **extra):
        peer.send({"type": "group_message", "group_id": group_id, "text": text, "request_id": "send", **extra})
        message = self.event(peer, "group_message")
        acknowledgement = self.event(peer, "sent")
        self.assertEqual(acknowledgement["group_id"], group_id)
        self.assertEqual(acknowledgement["message_id"], message["message_id"])
        self.assertEqual(acknowledgement["request_id"], "send")
        return {key: value for key, value in message.items() if key != "request_id"}

    def test_live_echo_identity_and_history_exclude_messages_before_join(self):
        alice, bob, carol = [self.member(name) for name in ("alice", "bob", "carol")]
        group_id = self.create(alice)
        before = self.send(alice, group_id, "Before Bob")
        self.join(bob, group_id)
        after = self.send(alice, group_id, "สวัสดี Bob\nSecond line", **{"from": "carol", "visible_to": ["carol"]})
        self.assertEqual(self.event(bob, "group_message"), after)
        self.assertEqual(after["from"], "alice")
        self.assertNotIn("visible_to", after)
        self.assertEqual(self.open(bob, group_id)["messages"], [after])
        carol.send({"type": "open_group", "group_id": group_id, "request_id": "outsider"})
        self.assertEqual(self.event(carol, "error")["request_id"], "outsider")
        self.assertFalse(any(item["type"] in ("group_opened", "group_message") for item in carol.skipped))
        self.join(carol, group_id)
        latest = self.send(bob, group_id, "After Carol")
        self.assertEqual(self.event(carol, "group_message"), latest)
        self.assertEqual(self.open(carol, group_id)["messages"], [latest])
        self.assertEqual(self.open(bob, group_id)["messages"], [after, latest])
        self.assertEqual(self.open(alice, group_id)["messages"], [before, after, latest])
        stored = json.loads(self.state_path.read_text())["group_messages"]
        self.assertEqual([item["visible_to"] for item in stored], [["alice"], ["alice", "bob"], ["alice", "bob", "carol"]])

    def test_offline_members_receive_eligible_history_after_reconnect_and_restart(self):
        alice, bob = self.member("alice"), self.member("bob")
        group_id = self.create(alice)
        self.send(alice, group_id, "Before joining")
        self.join(bob, group_id)
        bob.close()
        self.output.wait_for("Client disconnected: bob")
        offline = self.send(alice, group_id, "Saved while Bob is offline")
        bob = self.member("bob")
        self.assertEqual(self.open(bob, group_id)["messages"], [offline])
        self.server.send_signal(signal.SIGINT)
        self.assertEqual(self.server.wait(timeout=5), 0)
        self.output.finish()
        self.start_server()
        bob = self.member("bob")
        self.assertEqual(self.open(bob, group_id)["messages"], [offline])
        # ส่งได้แม้ไม่มีสมาชิกคนอื่นออนไลน์ และใช้ลำดับต่อจากข้อความเดิม
        own = self.send(bob, group_id, "Only Bob is online")
        self.assertEqual(own["sequence"], 3)
        self.assertEqual(self.open(bob, group_id)["messages"], [offline, own])

    def test_duplicate_group_names_and_private_rooms_keep_content_separate(self):
        alice, bob = self.member("alice"), self.member("bob")
        first, second = self.create(alice), self.create(alice)
        self.join(bob, first)
        shared = self.send(alice, first, "Shared group")
        self.assertEqual(self.event(bob, "group_message"), shared)
        isolated = self.send(alice, second, "Other group")
        bob.send({"type": "group_message", "group_id": second, "text": "Forbidden", "request_id": "deny"})
        self.assertEqual(self.event(bob, "error")["request_id"], "deny")
        self.assertFalse(any(item["type"] == "group_message" and item["group_id"] == second for item in bob.skipped))
        alice.send({"type": "message", "to": "bob", "text": "Private content"})
        self.event(alice, "sent")
        self.assertEqual(self.event(bob, "private_message")["text"], "Private content")
        self.assertEqual(self.open(alice, first)["messages"], [shared])
        self.assertEqual(self.open(alice, second)["messages"], [isolated])

    def test_invalid_requests_and_outsider_commands_never_append_messages(self):
        anonymous = self.peer()
        anonymous.send({"type": "group_message", "group_id": "missing", "text": "Early", "request_id": "early"})
        self.assertIn("Register", anonymous.receive()["text"])
        alice, bob = self.member("alice"), self.member("bob")
        group_id = self.create(alice)
        for kind in ("open_group", "group_message"):
            bob.send({"type": kind, "group_id": group_id, "text": "Forbidden", "request_id": "outsider"})
            self.assertEqual(self.event(bob, "error")["request_id"], "outsider")
        for text in (None, 42, "", " \n"):
            alice.send({"type": "group_message", "group_id": group_id, "text": text, "request_id": "invalid"})
            self.assertEqual(self.event(alice, "error")["request_id"], "invalid")
        for identifier in (None, [], "", "missing"):
            for kind in ("open_group", "group_message"):
                alice.send({"type": kind, "group_id": identifier, "text": "Invalid ID", "request_id": "invalid"})
                self.assertEqual(self.event(alice, "error")["request_id"], "invalid")
        for kind in ("open_group", "group_message"):
            alice.send({"type": kind, "group_id": group_id, "text": "No request ID"})
            self.assertIn("request_id", self.event(alice, "error")["text"])
        self.assertEqual(self.open(alice, group_id)["messages"], [])

    def test_concurrent_senders_and_history_loading_preserve_one_order(self):
        alice, bob = self.member("alice"), self.member("bob")
        group_id = self.create(alice)
        self.join(bob, group_id)
        self.open(alice, group_id)
        self.open(bob, group_id)

        def send_batch(item):
            peer, prefix = item
            for index in range(10):
                peer.send({"type": "group_message", "group_id": group_id, "text": f"{prefix}-{index}", "request_id": f"{prefix}-{index}"})

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(send_batch, ((alice, "a"), (bob, "b"))))
        # ขอประวัติระหว่างที่ Server อาจยังส่งข้อความสดไม่ครบ
        alice.send({"type": "open_group", "group_id": group_id, "request_id": "during-send"})
        received = []
        for peer in (alice, bob):
            messages = [self.event(peer, "group_message") for _ in range(20)]
            self.assertEqual([message["sequence"] for message in messages], list(range(1, 21)))
            received.append([message["message_id"] for message in messages])
        self.assertEqual(received[0], received[1])
        self.assertEqual(len(set(received[0])), 20)
        snapshot = self.open(alice, group_id)
        self.assertEqual([message["message_id"] for message in snapshot["messages"]], received[0])


class GroupMessageFailureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = ChatStateStore(Path(directory.name) / "state.json")
        self.group_id = self.store.create_group("Group", "alice")["group_id"]
        self.store.join_group(self.group_id, "bob")
        self.store.join_group(self.group_id, "carol")

    def test_one_broken_recipient_does_not_block_others_or_erase_saved_message(self):
        alice, carol = server.ClientConnection(ChunkConnection()), server.ClientConnection(ChunkConnection())
        alice.name, carol.name = "alice", "carol"
        alice.supports_group_messages = carol.supports_group_messages = True
        bob = Mock()
        bob.name = "bob"
        bob.supports_group_messages = True
        bob.send_group.side_effect = OSError("Disconnected")
        with patch.object(server, "chat_state", self.store), patch.dict(server.clients, {"alice": alice, "bob": bob, "carol": carol}, clear=True):
            with patch.object(server, "broadcast_users"), patch.object(server, "users_version", 0):
                server.deliver_group(alice, {"group_id": self.group_id, "text": "Saved", "request_id": "send"})
        sender_events = list(receive_messages(ChunkConnection([alice.connection.sent])))
        recipient_events = list(receive_messages(ChunkConnection([carol.connection.sent])))
        error = next(item for item in sender_events if item["type"] == "error")
        self.assertTrue(error["persisted"])
        self.assertEqual(error["request_id"], "send")
        self.assertNotIn("sent", [item["type"] for item in sender_events])
        self.assertEqual([item["text"] for item in recipient_events if item["type"] == "group_message"], ["Saved"])
        self.assertEqual(len(self.store.group_snapshot(self.group_id, "bob")["messages"]), 1)

    def test_save_failure_does_not_fan_out_or_report_success(self):
        sender = Mock()
        sender.name = "alice"
        previous = self.store.path.read_bytes()
        with patch.object(server, "chat_state", self.store), patch("state_store.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                server.deliver_group(sender, {"group_id": self.group_id, "text": "Not saved", "request_id": "fail"})
        sender.send.assert_not_called()
        sender.send_group.assert_not_called()
        self.assertEqual(self.store.path.read_bytes(), previous)
        self.assertEqual(self.store.group_snapshot(self.group_id, "alice")["messages"], [])


class GroupMessageStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state.json"
        self.store = ChatStateStore(self.path)

    def test_old_file_upgrades_without_resetting_groups_or_private_history(self):
        room = self.store.get_or_create_room("alice", "bob")
        private = self.store.append_message(room["room_id"], "alice", "Private history")
        group = self.store.create_group("ทีมงาน", "alice")
        self.store.join_group(group["group_id"], "bob")
        data = json.loads(self.path.read_text())
        del data["group_messages"]
        original = json.dumps(data, ensure_ascii=False)
        self.path.write_text(original)
        restored = ChatStateStore(self.path)
        self.assertEqual(self.path.read_text(), original)
        self.assertEqual(restored.group_snapshot(group["group_id"], "bob")["messages"], [])
        restored.append_group_message(group["group_id"], "bob", "สวัสดี\nNew group history")
        reloaded = ChatStateStore(self.path)
        self.assertEqual(reloaded.snapshot(room["room_id"], "bob")["messages"], [private])
        self.assertEqual(reloaded.group_snapshot(group["group_id"], "alice")["members"], ["alice", "bob"])
        self.assertEqual(len(reloaded.group_snapshot(group["group_id"], "bob")["messages"]), 1)

    def test_join_and_append_capture_one_consistent_audience(self):
        group_id = self.store.create_group("Group", "alice")["group_id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            joining = pool.submit(self.store.join_group, group_id, "bob")
            sending = pool.submit(self.store.append_group_message, group_id, "alice", "Concurrent")
            joining.result(timeout=5)
            message = sending.result(timeout=5)
        self.assertEqual(bool(self.store.group_snapshot(group_id, "bob")["messages"]), "bob" in message["visible_to"])
        self.store.append_group_message(group_id, "alice", "After join")
        self.assertEqual(self.store.group_snapshot(group_id, "bob")["messages"][-1]["text"], "After join")

    def test_invalid_group_message_records_are_rejected_without_overwriting(self):
        group_id = self.store.create_group("Group", "alice")["group_id"]
        message = self.store.append_group_message(group_id, "alice", "Valid")
        original = json.loads(self.path.read_text())
        for changes in ({"group_id": "missing"}, {"visible_to": []}, {"visible_to": ["alice", "alice"]},
                        {"visible_to": ["bob"]}, {"sequence": 2}, {"type": "private_message"}, {"text": " "}):
            data = {**original, "group_messages": [{**message, **changes}]}
            encoded = json.dumps(data)
            self.path.write_text(encoded)
            with self.assertRaises(ValueError):
                ChatStateStore(self.path)
            self.assertEqual(self.path.read_text(), encoded)

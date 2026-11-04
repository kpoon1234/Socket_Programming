"""Verify explicit leaving, history rights, deletion, and concurrent delivery."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import signal
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import server
from state_store import ChatStateStore
from test_chat import ServerTestCase
from test_group_messages import GroupPeerHelpers


class GroupLeaveTests(GroupPeerHelpers, ServerTestCase):
    def leave(self, peer, group_id, **extra):
        peer.send({"type": "leave_group", "group_id": group_id, "request_id": "leave", **extra})
        return self.event(peer, "group_left")

    def test_creator_leaves_only_self_and_stays_online_for_private_chat(self):
        alice, bob = self.member("alice"), self.member("bob")
        group_id = self.create(alice)
        self.join(bob, group_id)
        result = self.leave(alice, group_id, name="bob", members=[])
        self.assertEqual(result, {"type": "group_left", "group_id": group_id,
                                  "deleted": False, "version": 3, "request_id": "leave"})
        snapshot = self.event(alice, "groups_updated", lambda item: item["version"] >= result["version"])
        self.assertEqual(snapshot["groups"][0]["members"], ["bob"])
        self.assertEqual(snapshot["groups"][0]["creator"], "alice")
        alice.send({"type": "message", "to": "bob", "text": "Still connected"})
        self.event(alice, "sent")
        self.assertEqual(self.event(bob, "private_message")["text"], "Still connected")
        self.assertEqual(self.send(bob, group_id, "Still a member")["from"], "bob")

    def test_rejoin_restores_old_rights_but_excludes_absent_interval(self):
        alice, bob = self.member("alice"), self.member("bob")
        group_id = self.create(alice)
        self.send(alice, group_id, "Before first join")
        self.join(bob, group_id)
        old = self.send(alice, group_id, "Before leaving")
        self.event(bob, "group_message")
        self.leave(bob, group_id)
        self.send(alice, group_id, "While Bob was absent")
        for kind in ("open_group", "group_message"):
            bob.send({"type": kind, "group_id": group_id, "text": "Denied", "request_id": "deny"})
            self.assertEqual(self.event(bob, "error")["request_id"], "deny")
        self.join(bob, group_id)
        new = self.send(alice, group_id, "After rejoining")
        # Leave ล้าง announced_groups จึงส่งประวัติที่กรองแล้วก่อนข้อความสดใหม่
        automatic = self.event(bob, "group_opened")
        self.assertEqual(automatic["messages"], [old])
        self.assertEqual(self.event(bob, "group_message"), new)
        self.assertEqual(self.open(bob, group_id)["messages"], [old, new])

    def test_offline_member_prevents_deletion_and_survives_server_restart(self):
        alice, bob = self.member("alice"), self.member("bob")
        group_id = self.create(alice)
        self.join(bob, group_id)
        saved = self.send(alice, group_id, "Keep this history")
        bob.close()
        self.output.wait_for("Client disconnected: bob")
        self.assertFalse(self.leave(alice, group_id)["deleted"])
        self.server.send_signal(signal.SIGINT)
        self.assertEqual(self.server.wait(timeout=5), 0)
        self.output.finish()
        self.start_server()
        bob = self.member("bob")
        history = self.open(bob, group_id)
        self.assertEqual(history["members"], ["bob"])
        self.assertEqual(history["messages"], [saved])
        self.send(bob, group_id, "Back online")

    def test_last_leave_deletes_only_target_group_and_never_reuses_its_id(self):
        alice, bob = self.member("alice"), self.member("bob")
        deleted, kept = self.create(alice), self.create(alice)
        self.send(alice, deleted, "Delete me")
        keep_message = self.send(alice, kept, "Keep me")
        alice.send({"type": "message", "to": "bob", "text": "Keep private history"})
        self.event(alice, "sent")
        before = json.loads(self.state_path.read_text())
        result = self.leave(alice, deleted)
        self.assertTrue(result["deleted"])
        after = ChatStateStore(self.state_path).data
        self.assertNotIn(deleted, after["groups"])
        self.assertEqual(after["groups"][kept], before["groups"][kept])
        self.assertEqual([item["message_id"] for item in after["group_messages"]], [keep_message["message_id"]])
        self.assertEqual(after["private_rooms"], before["private_rooms"])
        self.assertEqual(after["messages"], before["messages"])
        for kind in ("join_group", "open_group", "group_message", "leave_group"):
            alice.send({"type": kind, "group_id": deleted, "text": "No resurrection", "request_id": "old"})
            self.assertEqual(self.event(alice, "error")["request_id"], "old")
        self.assertNotEqual(self.create(alice), deleted)

    def test_invalid_and_repeated_leave_do_not_mutate_state(self):
        anonymous = self.peer()
        anonymous.send({"type": "leave_group", "group_id": "missing", "request_id": "early"})
        self.assertIn("Register", anonymous.receive()["text"])
        alice, bob = self.member("alice"), self.member("bob")
        group_id = self.create(alice)
        before = self.state_path.read_bytes()
        for value in (None, [], "", "missing", group_id):
            bob.send({"type": "leave_group", "group_id": value, "request_id": "invalid"})
            self.assertEqual(self.event(bob, "error")["request_id"], "invalid")
        for request_id in (None, 42, ""):
            alice.send({"type": "leave_group", "group_id": group_id, "request_id": request_id})
            self.assertIn("request_id", self.event(alice, "error")["text"])
        self.assertEqual(self.state_path.read_bytes(), before)
        self.join(bob, group_id)
        self.leave(bob, group_id)
        before = self.state_path.read_bytes()
        bob.send({"type": "leave_group", "group_id": group_id, "request_id": "again"})
        self.assertEqual(self.event(bob, "error")["request_id"], "again")
        self.assertEqual(self.state_path.read_bytes(), before)
        self.join(bob, group_id)
        self.assertEqual(self.send(bob, group_id, "Session still works")["from"], "bob")

    def test_concurrent_sends_never_arrive_after_leave_ack(self):
        alice, bob = self.member("alice"), self.member("bob")
        group_id = self.create(alice)
        self.join(bob, group_id)
        barrier = threading.Barrier(2)

        def sending():
            barrier.wait(timeout=5)
            for index in range(12):
                self.send(alice, group_id, f"Concurrent {index}")

        def leaving():
            barrier.wait(timeout=5)
            return self.leave(bob, group_id)

        with ThreadPoolExecutor(max_workers=2) as pool:
            sends, leave = pool.submit(sending), pool.submit(leaving)
            self.assertFalse(leave.result(timeout=10)["deleted"])
            sends.result(timeout=10)
        bob.skipped.clear()
        bob.send({"type": "open_group", "group_id": group_id, "request_id": "probe"})
        self.event(bob, "error")
        self.assertFalse(any(item["type"] in ("group_opened", "group_message") for item in bob.skipped))
        self.send(alice, group_id, "Definitely after Leave")
        self.assertEqual(json.loads(self.state_path.read_text())["group_messages"][-1]["visible_to"], ["alice"])

    def test_last_leave_racing_join_has_one_consistent_outcome(self):
        alice, bob = self.member("alice"), self.member("bob")
        for _ in range(6):
            group_id = self.create(alice)
            self.send(alice, group_id, "Before race")
            barrier = threading.Barrier(2)

            def joining():
                barrier.wait(timeout=5)
                bob.send({"type": "join_group", "group_id": group_id, "request_id": "race"})
                while True:
                    event = bob.receive()
                    if event.get("request_id") == "race":
                        return event

            def leaving():
                barrier.wait(timeout=5)
                return self.leave(alice, group_id)

            with ThreadPoolExecutor(max_workers=2) as pool:
                join, leave = pool.submit(joining), pool.submit(leaving)
                joined, left = join.result(timeout=10), leave.result(timeout=10)
            data = ChatStateStore(self.state_path).data
            if left["deleted"]:
                self.assertEqual(joined["type"], "error")
                self.assertNotIn(group_id, data["groups"])
                self.assertFalse(any(item["group_id"] == group_id for item in data["group_messages"]))
            else:
                self.assertEqual(joined["type"], "group_joined")
                self.assertEqual(data["groups"][group_id]["members"], ["bob"])
                self.assertEqual(self.open(bob, group_id)["messages"], [])


class LeavePersistenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = ChatStateStore(Path(directory.name) / "state.json")
        self.group_id = self.store.create_group("Group", "alice")["group_id"]
        self.store.append_group_message(self.group_id, "alice", "Saved history")

    def test_failed_save_preserves_memory_disk_version_and_sends_nothing(self):
        for last_member in (True, False):
            if not last_member:
                self.store.join_group(self.group_id, "bob")
            before, version = deepcopy(self.store.data), self.store.groups_version
            disk = self.store.path.read_bytes()
            sender = Mock()
            sender.name = "alice"
            with patch.object(server, "chat_state", self.store), patch.object(server, "broadcast_groups") as broadcast:
                with patch("state_store.os.replace", side_effect=OSError("disk unavailable")):
                    with self.assertRaises(OSError):
                        server.leave_group(sender, {"group_id": self.group_id, "request_id": "fail"})
            self.assertEqual(self.store.data, before)
            self.assertEqual(self.store.groups_version, version)
            self.assertEqual(self.store.path.read_bytes(), disk)
            sender.send_group_left.assert_not_called()
            broadcast.assert_not_called()

    def test_disconnect_after_commit_still_broadcasts_committed_deletion(self):
        sender = Mock()
        sender.name = "alice"
        sender.send_group_left.side_effect = OSError("peer closed")
        with patch.object(server, "chat_state", self.store), patch.object(server, "broadcast_groups") as broadcast:
            with self.assertRaises(OSError):
                server.leave_group(sender, {"group_id": self.group_id, "request_id": "leave"})
        broadcast.assert_called_once_with()
        self.assertEqual(self.store.data["groups"], {})
        self.assertEqual(ChatStateStore(self.store.path).data["group_messages"], [])

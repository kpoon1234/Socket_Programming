"""Check group creation, public metadata, persistence, and snapshot ordering."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import signal
import socket
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from client_network import NetworkClient
from protocol import receive_messages, send_message
import server
from state_store import ChatStateStore
from test_chat import ChunkConnection, ServerTestCase


class GroupTests(ServerTestCase):
    def group_peer(self, name):
        peer = self.peer()
        peer.send({"type": "register", "name": name, "capabilities": ["groups"]})
        self.assertEqual(peer.receive(), {"type": "registered", "name": name})
        snapshot = peer.receive()
        self.assertEqual(snapshot["type"], "groups_updated")
        return peer, snapshot

    def event(self, peer, kind):
        while True:
            event = peer.receive()
            if event["type"] == kind:
                return event

    def create(self, peer, name, request_id="create", **extra):
        peer.send({"type": "create_group", "name": name, "request_id": request_id, **extra})
        reply = self.event(peer, "group_created")
        self.assertEqual(reply["request_id"], request_id)
        return reply["group_id"]

    def test_creator_only_duplicate_names_and_late_client_get_public_metadata(self):
        alice, empty = self.group_peer("alice")
        self.assertEqual(empty, {"type": "groups_updated", "version": 0, "groups": []})
        bob, _ = self.group_peer("bob")
        legacy = self.peer("legacy")
        first = self.create(alice, "  กลุ่มอ่านหนังสือ  ", creator="bob", members=["bob", "legacy"])
        expected = {"group_id": first, "name": "กลุ่มอ่านหนังสือ", "creator": "alice", "members": ["alice"]}
        self.assertEqual(self.event(alice, "groups_updated")["groups"], [expected])
        self.assertEqual(self.event(bob, "groups_updated")["groups"], [expected])
        second = self.create(alice, "กลุ่มอ่านหนังสือ", "second")
        third = self.create(bob, "Bob's group", "third")
        self.assertEqual(len({first, second, third}), 3)
        carol, snapshot = self.group_peer("carol")
        self.assertEqual(snapshot["version"], 3)
        self.assertEqual(len(snapshot["groups"]), 3)
        self.assertEqual(snapshot["groups"][0], expected)
        self.assertEqual(snapshot["groups"][1]["name"], expected["name"])
        self.assertEqual(snapshot["groups"][2]["members"], ["bob"])
        # Client เดิมที่ไม่ได้ประกาศ groups ไม่ได้รับเหตุการณ์ใหม่แทรกในแชต
        legacy.send({"type": "message", "to": "legacy", "text": "Still works"})
        self.assertEqual(legacy.receive()["type"], "message")
        self.assertEqual(legacy.receive(), {"type": "sent", "to": "legacy"})

    def test_registration_name_and_request_id_are_required_without_mutation(self):
        anonymous = self.peer()
        anonymous.send({"type": "create_group", "name": "No identity", "request_id": "anonymous"})
        self.assertIn("Register", anonymous.receive()["text"])
        alice, _ = self.group_peer("alice")
        for name in (None, 42, "", "  \n"):
            alice.send({"type": "create_group", "name": name, "request_id": "invalid"})
            error = self.event(alice, "error")
            self.assertEqual(error["request_id"], "invalid")
        for request_id in (None, "", 9):
            alice.send({"type": "create_group", "name": "Valid name", "request_id": request_id})
            self.assertIn("request_id", self.event(alice, "error")["text"])
        _, snapshot = self.group_peer("bob")
        self.assertEqual(snapshot["groups"], [])
        self.assertEqual(snapshot["version"], 0)

    def test_simultaneous_creators_keep_all_groups_and_monotonic_snapshots(self):
        observer, _ = self.group_peer("observer")
        peers = [self.group_peer(f"user-{index}")[0] for index in range(6)]
        barrier = threading.Barrier(len(peers))

        def create(item):
            index, peer = item
            barrier.wait(timeout=5)
            return self.create(peer, "Same name", str(index))

        with ThreadPoolExecutor(max_workers=len(peers)) as pool:
            identifiers = set(pool.map(create, enumerate(peers)))
        versions = []
        while True:
            snapshot = self.event(observer, "groups_updated")
            versions.append(snapshot["version"])
            if len(snapshot["groups"]) == len(peers):
                break
        self.assertEqual(versions, sorted(set(versions)))
        self.assertEqual(snapshot["version"], 6)
        self.assertEqual({group["group_id"] for group in snapshot["groups"]}, identifiers)
        persisted = json.loads(self.state_path.read_text())
        self.assertEqual(set(persisted["groups"]), identifiers)

    def test_all_offline_and_server_restart_preserve_groups_and_members(self):
        alice, _ = self.group_peer("alice")
        group_id = self.create(alice, "Persistent group")
        alice.close()
        self.output.wait_for("Client disconnected: alice")
        bob, snapshot = self.group_peer("bob")
        expected = [{"group_id": group_id, "name": "Persistent group", "creator": "alice", "members": ["alice"]}]
        self.assertEqual(snapshot["groups"], expected)
        bob.close()
        self.output.wait_for("Client disconnected: bob")
        self.server.send_signal(signal.SIGINT)
        self.assertEqual(self.server.wait(timeout=5), 0)
        self.output.finish()
        self.start_server()
        alice, snapshot = self.group_peer("alice")
        self.assertEqual(snapshot["groups"], expected)
        self.assertEqual(snapshot["version"], 0)
        self.assertEqual(alice.wait_users(["alice"])["users"], ["alice"])
        new_id = self.create(alice, "Persistent group")
        self.assertNotEqual(new_id, group_id)
        self.assertEqual(len(self.event(alice, "groups_updated")["groups"]), 2)


    def test_join_uses_socket_identity_and_updates_everyone_without_joining_other_groups(self):
        alice, _ = self.group_peer("alice")
        bob, _ = self.group_peer("bob")
        carol, _ = self.group_peer("carol")
        first = self.create(alice, "Same name", "first")
        second = self.create(alice, "Same name", "second")
        for peer in (alice, bob, carol):
            while self.event(peer, "groups_updated")["version"] < 2:
                pass
        bob.send({"type": "join_group", "group_id": first, "request_id": "join",
                  "name": "carol", "members": ["carol"], "from": "alice"})
        self.assertEqual(self.event(bob, "group_joined"),
                         {"type": "group_joined", "group_id": first, "request_id": "join"})
        snapshots = [self.event(peer, "groups_updated") for peer in (alice, bob, carol)]
        self.assertEqual(snapshots, [snapshots[0]] * 3)
        self.assertEqual(snapshots[0]["version"], 3)
        groups = {group["group_id"]: group for group in snapshots[0]["groups"]}
        self.assertEqual(groups[first]["members"], ["alice", "bob"])
        self.assertEqual(groups[second]["members"], ["alice"])
        _, late = self.group_peer("late")
        self.assertEqual(late, snapshots[0])

    def test_repeat_join_succeeds_without_duplicate_member_or_new_version(self):
        alice, _ = self.group_peer("alice")
        group_id = self.create(alice, "Group")
        for request_id in ("creator", "repeat"):
            alice.send({"type": "join_group", "group_id": group_id, "request_id": request_id})
            self.assertEqual(self.event(alice, "group_joined")["request_id"], request_id)
        bob, snapshot = self.group_peer("bob")
        self.assertEqual(snapshot["version"], 1)
        self.assertEqual(snapshot["groups"][0]["members"], ["alice"])
        for request_id in ("first", "second"):
            bob.send({"type": "join_group", "group_id": group_id, "request_id": request_id})
            self.assertEqual(self.event(bob, "group_joined")["request_id"], request_id)
        _, snapshot = self.group_peer("carol")
        self.assertEqual(snapshot["version"], 2)
        self.assertEqual(snapshot["groups"][0]["members"], ["alice", "bob"])

    def test_invalid_join_and_unregistered_requests_leave_members_unchanged(self):
        anonymous = self.peer()
        anonymous.send({"type": "join_group", "group_id": "missing", "request_id": "early"})
        self.assertIn("Register", anonymous.receive()["text"])
        alice, _ = self.group_peer("alice")
        group_id = self.create(alice, "Group")
        bob, before = self.group_peer("bob")
        for group in (None, "", "  ", 9, [], "missing"):
            bob.send({"type": "join_group", "group_id": group, "request_id": "invalid"})
            self.assertEqual(self.event(bob, "error")["request_id"], "invalid")
        bob.send({"type": "join_group", "group_id": group_id})
        self.assertIn("request_id", self.event(bob, "error")["text"])
        _, after = self.group_peer("carol")
        self.assertEqual(after, before)

    def test_simultaneous_joiners_keep_every_member_and_snapshot_order(self):
        alice, _ = self.group_peer("alice")
        group_id = self.create(alice, "Group")
        self.event(alice, "groups_updated")
        peers = [self.group_peer(f"user-{index}")[0] for index in range(6)]
        barrier = threading.Barrier(len(peers))

        def join(item):
            index, peer = item
            barrier.wait(timeout=5)
            peer.send({"type": "join_group", "group_id": group_id, "request_id": str(index)})
            return self.event(peer, "group_joined")

        with ThreadPoolExecutor(max_workers=len(peers)) as pool:
            replies = list(pool.map(join, enumerate(peers)))
        self.assertTrue(all(reply["group_id"] == group_id for reply in replies))
        versions = []
        while True:
            snapshot = self.event(alice, "groups_updated")
            versions.append(snapshot["version"])
            if len(snapshot["groups"][0]["members"]) == 7:
                break
        self.assertEqual(versions, sorted(set(versions)))
        self.assertEqual(snapshot["version"], 7)
        self.assertCountEqual(snapshot["groups"][0]["members"], ["alice"] + [f"user-{i}" for i in range(6)])
        self.assertEqual(ChatStateStore(self.state_path).groups_snapshot()["groups"], snapshot["groups"])

    def test_joined_member_returns_after_disconnect_and_server_restart(self):
        alice, _ = self.group_peer("alice")
        group_id = self.create(alice, "Persistent group")
        bob, _ = self.group_peer("bob")
        bob.send({"type": "join_group", "group_id": group_id, "request_id": "join"})
        self.event(bob, "group_joined")
        expected = self.event(bob, "groups_updated")["groups"]
        bob.close()
        self.output.wait_for("Client disconnected: bob")
        _, restored = self.group_peer("bob")
        self.assertEqual(restored["groups"], expected)
        self.server.send_signal(signal.SIGINT)
        self.assertEqual(self.server.wait(timeout=5), 0)
        self.output.finish()
        self.start_server()
        bob, restored = self.group_peer("bob")
        self.assertEqual(restored["groups"], expected)
        self.assertEqual(restored["version"], 0)
        self.assertEqual(restored["groups"][0]["members"], ["alice", "bob"])
        self.assertEqual(bob.wait_users(["bob"])["users"], ["bob"])


class GroupFailureTests(unittest.TestCase):
    def test_join_save_failure_preserves_members_version_and_disk_without_success(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ChatStateStore(Path(directory) / "state.json")
            group = store.create_group("Group", "alice")
            previous = store.path.read_bytes()
            sender = Mock()
            sender.name = "bob"
            with patch.object(server, "chat_state", store), patch.object(server, "broadcast_groups") as broadcast:
                with patch("state_store.os.replace", side_effect=OSError("disk unavailable")):
                    with self.assertRaises(OSError):
                        server.join_group(sender, {"group_id": group["group_id"], "request_id": "fail"})
                sender.send.assert_not_called()
                broadcast.assert_not_called()
            self.assertEqual(store.path.read_bytes(), previous)
            self.assertEqual(store.groups_snapshot(), {"type": "groups_updated", "version": 1, "groups": [group]})

    def test_joiner_disconnect_after_save_still_broadcasts_membership(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ChatStateStore(Path(directory) / "state.json")
            group = store.create_group("Group", "alice")
            sender = Mock()
            sender.name = "bob"
            sender.send.side_effect = OSError("Disconnected")
            with patch.object(server, "chat_state", store), patch.object(server, "broadcast_groups") as broadcast:
                with self.assertRaises(OSError):
                    server.join_group(sender, {"group_id": group["group_id"], "request_id": "join"})
                broadcast.assert_called_once()
            self.assertEqual(ChatStateStore(store.path).groups_snapshot()["groups"][0]["members"], ["alice", "bob"])

    def test_save_failure_sends_no_success_or_broadcast_and_preserves_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ChatStateStore(Path(directory) / "state.json")
            store.create_group("Existing", "alice")
            previous = store.path.read_bytes()
            sender = Mock(name="sender")
            sender.name = "alice"
            with patch.object(server, "chat_state", store), patch.object(server, "broadcast_groups") as broadcast:
                with patch("state_store.os.replace", side_effect=OSError("disk unavailable")):
                    with self.assertRaises(OSError):
                        server.create_group(sender, {"name": "Must not appear", "request_id": "fail"})
                sender.send.assert_not_called()
                broadcast.assert_not_called()
            self.assertEqual(store.path.read_bytes(), previous)
            self.assertEqual(store.groups_snapshot()["version"], 1)
            self.assertEqual(len(store.groups_snapshot()["groups"]), 1)

    def test_creator_disconnect_after_save_still_broadcasts_committed_group(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ChatStateStore(Path(directory) / "state.json")
            sender = Mock()
            sender.name = "alice"
            sender.send.side_effect = OSError("Disconnected")
            with patch.object(server, "chat_state", store), patch.object(server, "broadcast_groups") as broadcast:
                with self.assertRaises(OSError):
                    server.create_group(sender, {"name": "Saved", "request_id": "create"})
                broadcast.assert_called_once()
            self.assertEqual(store.groups_snapshot()["groups"][0]["members"], ["alice"])


class GroupSnapshotTests(unittest.TestCase):
    def test_server_skips_out_of_order_group_snapshots(self):
        writer = ChunkConnection()
        client = server.ClientConnection(writer)
        for version in (3, 1, 3, 4, 2):
            client.send_groups({"type": "groups_updated", "version": version, "groups": []})
        messages = receive_messages(ChunkConnection([writer.sent]))
        self.assertEqual([message["version"] for message in messages], [3, 4])

    def test_network_skips_old_snapshots_and_accepts_zero_after_reconnect(self):
        for sequence, expected in (((5, 3, 6, 6), [5, 6]), ((0, 0, 1), [0, 1])):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen()
                listener.settimeout(5)
                network = NetworkClient()
                self.addCleanup(network.close)
                network.connect("127.0.0.1", listener.getsockname()[1], "alice", capabilities=["groups"])
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(5)
                    self.assertEqual(next(receive_messages(connection))["type"], "register")
                    for version in sequence:
                        send_message(connection, {"type": "groups_updated", "version": version, "groups": []})
                versions = []
                while True:
                    event = network.events.get(timeout=5)
                    if event["type"] == "groups_updated":
                        versions.append(event["version"])
                    if event["type"] == "disconnected":
                        break
                self.assertTrue(network.wait_closed())
                self.assertEqual(versions, expected)

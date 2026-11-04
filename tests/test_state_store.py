"""Check durable state integrity and access control under failures."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from state_store import ChatStateStore


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "chat_state.json"
        self.store = ChatStateStore(self.path)

    def test_reload_preserves_unicode_room_ids_and_authorized_history(self):
        room = self.store.get_or_create_room("alice", "bob")
        message = self.store.append_message(room["room_id"], "alice", "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35\nHello")
        restored = ChatStateStore(self.path)
        self.assertEqual(restored.snapshot(room["room_id"], "bob")["messages"], [message])
        self.assertEqual(restored.list_rooms("carol"), [])
        with self.assertRaises(ValueError):
            restored.snapshot(room["room_id"], "carol")

    def test_replace_failure_preserves_both_disk_and_memory(self):
        room = self.store.get_or_create_room("alice", "bob")
        previous = self.path.read_bytes()
        with patch("state_store.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.store.append_message(room["room_id"], "alice", "Must not appear")
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(self.store.snapshot(room["room_id"], "alice")["messages"], [])
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_concurrent_creation_and_writes_keep_one_room_and_all_messages(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            rooms = list(pool.map(lambda _: self.store.get_or_create_room("alice", "bob"), range(16)))
            ids = {room["room_id"] for room in rooms}
            self.assertEqual(len(ids), 1)
            room_id = rooms[0]["room_id"]
            list(pool.map(lambda index: self.store.append_message(room_id, "alice", str(index)), range(25)))
        history = ChatStateStore(self.path).snapshot(room_id, "bob")["messages"]
        self.assertEqual([item["sequence"] for item in history], list(range(1, 26)))
        self.assertEqual(len({item["message_id"] for item in history}), 25)

    def test_invalid_existing_file_is_reported_without_overwriting(self):
        for value in ("broken-json", json.dumps({"schema_version": 999})):
            self.path.write_text(value)
            with self.assertRaises(ValueError):
                ChatStateStore(self.path)
            self.assertEqual(self.path.read_text(), value)

    def test_groups_and_private_history_survive_each_others_writes(self):
        room = self.store.get_or_create_room("alice", "bob")
        first = self.store.create_group("ทีมงาน", "alice")
        message = self.store.append_message(room["room_id"], "bob", "Private content")
        second = self.store.create_group("ทีมงาน", "bob")
        snapshot = ChatStateStore(self.path).groups_snapshot()
        self.assertEqual(snapshot["groups"], [first, second])
        self.assertNotIn("Private content", json.dumps(snapshot))
        self.assertEqual(ChatStateStore(self.path).snapshot(room["room_id"], "alice")["messages"], [message])
        snapshot["groups"][0]["members"].append("outsider")
        self.assertEqual(self.store.groups_snapshot()["groups"][0]["members"], ["alice"])

    def test_invalid_group_records_are_rejected_without_overwriting(self):
        group = self.store.create_group("Valid", "alice")
        for changes in ({"group_id": "other"}, {"name": "  "}, {"creator": 3},
                        {"members": []}, {"members": ["alice", "alice"]}, {"members": [None]}):
            data = json.loads(self.path.read_text())
            data["groups"][group["group_id"]] = {**group, **changes}
            encoded = json.dumps(data)
            self.path.write_text(encoded)
            with self.assertRaises(ValueError):
                ChatStateStore(self.path)
            self.assertEqual(self.path.read_text(), encoded)

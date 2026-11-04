"""Keep rooms, groups, and messages in an atomically replaced JSON file."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid


class ChatStateStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.groups_version = 0
        self.data = {"schema_version": 1, "groups": {}, "private_rooms": {}, "messages": []}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.validate(data)
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError(f"Invalid chat state in {self.path}: {error}") from error
            self.data = data

    @staticmethod
    def validate(data):
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise ValueError("Unsupported state schema.")
        if not isinstance(data.get("groups"), dict) or not isinstance(data.get("private_rooms"), dict):
            raise ValueError("Rooms and groups must be objects.")
        if not isinstance(data.get("messages"), list):
            raise ValueError("Messages must be a list.")
        for group_id, group in data["groups"].items():
            if not isinstance(group_id, str) or not group_id or not isinstance(group, dict) or group.get("group_id") != group_id:
                raise ValueError("Invalid group ID.")
            if not all(isinstance(group.get(key), str) and group[key].strip() for key in ("name", "creator")):
                raise ValueError("A group must have a name and creator.")
            members = group.get("members")
            if not isinstance(members, list) or not members or not all(isinstance(name, str) and name.strip() for name in members):
                raise ValueError("A group must have named members.")
            if len(set(members)) != len(members):
                raise ValueError("Duplicate group member.")
        pairs = set()
        for room_id, room in data["private_rooms"].items():
            if not isinstance(room, dict) or room.get("room_id") != room_id or room.get("kind") != "private":
                raise ValueError("Invalid private room.")
            members = room.get("members")
            if not isinstance(members, list) or len(members) != 2 or not all(isinstance(name, str) and name.strip() for name in members):
                raise ValueError("A private room must have two named members.")
            pair = tuple(sorted(members))
            if members != sorted(members) or members[0] == members[1] or pair in pairs:
                raise ValueError("Duplicate private room or member.")
            pairs.add(pair)
        message_ids = set()
        sequences = {}
        for message in data["messages"]:
            if not isinstance(message, dict):
                raise ValueError("Invalid message record.")
            room = data["private_rooms"].get(message.get("room_id"))
            if room is None or message.get("from") not in room["members"] or message.get("to") not in room["members"]:
                raise ValueError("A message must belong to its private room.")
            identifier = message.get("message_id")
            if not isinstance(identifier, str) or not identifier or identifier in message_ids:
                raise ValueError("Invalid or duplicate message ID.")
            if message.get("type") != "private_message" or message["from"] == message["to"] or not isinstance(message.get("text"), str):
                raise ValueError("Invalid private message content.")
            sequence = sequences.get(message["room_id"], 0) + 1
            if type(message.get("sequence")) is not int or message["sequence"] != sequence:
                raise ValueError("Invalid message sequence.")
            if not isinstance(message.get("timestamp"), str):
                raise ValueError("A message must have a timestamp.")
            sequences[message["room_id"]] = sequence
            message_ids.add(identifier)

    def save(self, data):
        # เขียนไฟล์ใหม่ให้ครบก่อนแทนไฟล์เดิม และเปลี่ยนข้อมูลในหน่วยความจำเมื่อบันทึกสำเร็จ
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=f".{self.path.name}.", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.data = data

    def groups_snapshot(self):
        with self.lock:
            # อ่านเลขรุ่นกับรายการพร้อมกัน เพื่อไม่ให้เลขรุ่นใหม่ติดไปกับข้อมูลเก่า
            return {"type": "groups_updated", "version": self.groups_version,
                    "groups": deepcopy(list(self.data["groups"].values()))}

    def create_group(self, name, creator):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Group name must not be empty.")
        if not isinstance(creator, str) or not creator.strip():
            raise ValueError("A registered creator is required.")
        with self.lock:
            group_id = f"group_{uuid.uuid4().hex}"
            group = {"group_id": group_id, "name": name.strip(),
                     "creator": creator, "members": [creator]}
            data = deepcopy(self.data)
            data["groups"][group_id] = group
            self.save(data)
            # เพิ่มรุ่นเมื่อบันทึกสำเร็จเท่านั้น และเริ่มนับใหม่เมื่อเปิด Server รอบใหม่
            self.groups_version += 1
            return deepcopy(group)

    def list_rooms(self, name):
        with self.lock:
            return deepcopy([room for room in self.data["private_rooms"].values() if name in room["members"]])

    def find_room(self, name, other):
        with self.lock:
            members = sorted((name, other))
            for room in self.data["private_rooms"].values():
                if room["members"] == members:
                    return deepcopy(room)
        return None

    def get_or_create_room(self, name, other):
        if not isinstance(other, str) or not other.strip() or name == other:
            raise ValueError("Choose another user for a private room.")
        members = sorted((name, other))
        with self.lock:
            for room in self.data["private_rooms"].values():
                if room["members"] == members:
                    return deepcopy(room)
            room_id = f"private_{uuid.uuid4().hex}"
            room = {"room_id": room_id, "kind": "private", "members": members}
            data = deepcopy(self.data)
            data["private_rooms"][room_id] = room
            self.save(data)
            return deepcopy(room)

    def snapshot(self, room_id, name):
        with self.lock:
            room = self.data["private_rooms"].get(room_id)
            if room is None or name not in room["members"]:
                raise ValueError("This private room is not available to you.")
            return deepcopy({**room, "messages": [item for item in self.data["messages"] if item["room_id"] == room_id]})

    def append_message(self, room_id, sender, text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Message must not be empty.")
        with self.lock:
            room = self.data["private_rooms"].get(room_id)
            if room is None or sender not in room["members"]:
                raise ValueError("This private room is not available to you.")
            recipient = next(name for name in room["members"] if name != sender)
            sequence = sum(item["room_id"] == room_id for item in self.data["messages"]) + 1
            message = {
                "type": "private_message", "message_id": f"message_{uuid.uuid4().hex}",
                "room_id": room_id, "sequence": sequence, "from": sender, "to": recipient,
                "text": text, "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            data = deepcopy(self.data)
            data["messages"].append(message)
            self.save(data)
            return deepcopy(message)

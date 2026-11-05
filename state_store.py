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
        self.data = {"schema_version": 1, "groups": {}, "private_rooms": {}, "messages": [], "group_messages": []}
        if self.path.exists():
            try:
                raw = self.path.read_text(encoding="utf-8").strip()
                if not raw or raw == "{}":
                    data = {"schema_version": 1, "groups": {}, "private_rooms": {}, "messages": [], "group_messages": []}
                else:
                    data = json.loads(raw)
                    # ไฟล์ก่อน Step 6 ยังไม่มีข้อความกลุ่ม ให้เติมเฉพาะช่องใหม่โดยเก็บข้อมูลเดิม
                    if isinstance(data, dict):
                        data.setdefault("schema_version", 1)
                        data.setdefault("groups", {})
                        data.setdefault("private_rooms", {})
                        data.setdefault("messages", [])
                        data.setdefault("group_messages", [])
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

        if not isinstance(data.get("group_messages"), list):
            raise ValueError("Group messages must be a list.")
        sequences = {}
        for message in data["group_messages"]:
            if not isinstance(message, dict):
                raise ValueError("Invalid group message record.")
            group_id = message.get("group_id")
            if not isinstance(group_id, str) or group_id not in data["groups"]:
                raise ValueError("A group message must belong to its group.")
            audience = message.get("visible_to")
            if not isinstance(audience, list) or not audience or not all(isinstance(name, str) and name.strip() for name in audience):
                raise ValueError("A group message must have an audience.")
            if len(set(audience)) != len(audience) or message.get("from") not in audience:
                raise ValueError("Invalid group message audience.")
            identifier = message.get("message_id")
            if not isinstance(identifier, str) or not identifier or identifier in message_ids:
                raise ValueError("Invalid or duplicate message ID.")
            if message.get("type") != "group_message" or not isinstance(message.get("text"), str) or not message["text"].strip():
                raise ValueError("Invalid group message content.")
            sequence = sequences.get(group_id, 0) + 1
            if type(message.get("sequence")) is not int or message["sequence"] != sequence:
                raise ValueError("Invalid group message sequence.")
            if not isinstance(message.get("timestamp"), str):
                raise ValueError("A group message must have a timestamp.")
            sequences[group_id] = sequence
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
            groups = []
            for group in self.data["groups"].values():
                item = deepcopy(group)
                if item.get("is_secret") is None:
                    has_secret = any(msg["group_id"] == group["group_id"] and (msg["text"].startswith("🔒 pin:sync:") or msg["text"].startswith("🔒 enc:v1:")) for msg in self.data["group_messages"])
                    has_normal = any(msg["group_id"] == group["group_id"] and msg["text"].startswith("💬 mode:normal") for msg in self.data["group_messages"])
                    if has_secret:
                        item["is_secret"] = True
                        group["is_secret"] = True
                    elif has_normal:
                        item["is_secret"] = False
                        group["is_secret"] = False
                groups.append(item)
            return {"type": "groups_updated", "version": self.groups_version,
                    "groups": groups}

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

    def join_group(self, group_id, name):
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError("A non-empty group_id is required.")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("A registered member is required.")
        with self.lock:
            group = self.data["groups"].get(group_id)
            if group is None:
                raise ValueError("Group does not exist.")
            # กด Join ซ้ำหรือกลับมาใช้ชื่อเดิม ไม่เพิ่มสมาชิกและไม่เขียนไฟล์ซ้ำ
            if name in group["members"]:
                return deepcopy(group)
            data = deepcopy(self.data)
            data["groups"][group_id]["members"].append(name)
            # Sync ข้อความประเภท sync/mode ให้กับสมาชิกใหม่ที่เพิ่งเข้ากลุ่มด้วย
            for msg in data["group_messages"]:
                if msg["group_id"] == group_id and (msg["text"].startswith("🔒 pin:sync:") or msg["text"].startswith("💬 mode:normal")):
                    if name not in msg["visible_to"]:
                        msg["visible_to"].append(name)
            self.save(data)
            self.groups_version += 1
            return deepcopy(data["groups"][group_id])

    def leave_group(self, group_id, name):
        with self.lock:
            self.group_for_member(group_id, name)
            data = deepcopy(self.data)
            members = data["groups"][group_id]["members"]
            members.remove(name)
            deleted = not members
            if deleted:
                del data["groups"][group_id]
                # ลบเฉพาะประวัติของกลุ่มที่ว่าง ในการบันทึกครั้งเดียวกับการลบกลุ่ม
                data["group_messages"] = [item for item in data["group_messages"] if item["group_id"] != group_id]
            self.save(data)
            self.groups_version += 1
            return {"group_id": group_id, "deleted": deleted, "version": self.groups_version}

    def group_for_member(self, group_id, name):
        # เรียกขณะถือ self.lock เพื่อให้การตรวจสมาชิกกับการอ่าน/เพิ่มข้อความเป็นงานเดียวกัน
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError("A non-empty group_id is required.")
        group = self.data["groups"].get(group_id)
        if group is None or name not in group["members"]:
            raise ValueError("This group is not available to you.")
        return group

    @staticmethod
    def public_group_message(message):
        return {key: deepcopy(value) for key, value in message.items() if key != "visible_to"}

    def group_snapshot(self, group_id, name):
        with self.lock:
            group = self.group_for_member(group_id, name)
            history = [self.public_group_message(item) for item in self.data["group_messages"]
                       if item["group_id"] == group_id and name in item["visible_to"]]
            result = {**deepcopy(group), "messages": history}
            if result.get("is_secret") is None:
                has_secret = any(msg["group_id"] == group_id and (msg["text"].startswith("🔒 pin:sync:") or msg["text"].startswith("🔒 enc:v1:")) for msg in self.data["group_messages"])
                has_normal = any(msg["group_id"] == group_id and msg["text"].startswith("💬 mode:normal") for msg in self.data["group_messages"])
                if has_secret:
                    result["is_secret"] = True
                    group["is_secret"] = True
                elif has_normal:
                    result["is_secret"] = False
                    group["is_secret"] = False
            return result

    def append_group_message(self, group_id, sender, text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Message must not be empty.")
        with self.lock:
            group = self.group_for_member(group_id, sender)
            data = deepcopy(self.data)
            if text.startswith("🔒 pin:sync:") or text.startswith("🔒 enc:v1:"):
                data["groups"][group_id]["is_secret"] = True
                group["is_secret"] = True
            elif text.startswith("💬 mode:normal"):
                data["groups"][group_id]["is_secret"] = False
                group["is_secret"] = False
            sequence = sum(item["group_id"] == group_id for item in self.data["group_messages"]) + 1
            message = {
                "type": "group_message", "message_id": f"message_{uuid.uuid4().hex}",
                "group_id": group_id, "sequence": sequence, "from": sender, "text": text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                # ตรึงสิทธิ์ขณะส่ง รวมสมาชิกออฟไลน์ คนที่ Join ทีหลังจะไม่ได้ประวัตินี้
                "visible_to": list(group["members"]),
            }
            data["group_messages"].append(message)
            self.save(data)
            return deepcopy(message)

    def list_rooms(self, name):
        with self.lock:
            rooms = []
            for room in self.data["private_rooms"].values():
                if name in room["members"]:
                    item = deepcopy(room)
                    if item.get("is_secret") is None:
                        has_secret = any(msg["room_id"] == room["room_id"] and (msg["text"].startswith("🔒 pin:sync:") or msg["text"].startswith("🔒 enc:v1:")) for msg in self.data["messages"])
                        has_normal = any(msg["room_id"] == room["room_id"] and msg["text"].startswith("💬 mode:normal") for msg in self.data["messages"])
                        if has_secret:
                            item["is_secret"] = True
                        elif has_normal:
                            item["is_secret"] = False
                    rooms.append(item)
            return rooms

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
            item = deepcopy(room)
            if item.get("is_secret") is None:
                has_secret = any(msg["room_id"] == room_id and (msg["text"].startswith("🔒 pin:sync:") or msg["text"].startswith("🔒 enc:v1:")) for msg in self.data["messages"])
                has_normal = any(msg["room_id"] == room_id and msg["text"].startswith("💬 mode:normal") for msg in self.data["messages"])
                if has_secret:
                    item["is_secret"] = True
                elif has_normal:
                    item["is_secret"] = False
            return deepcopy({**item, "messages": [item_msg for item_msg in self.data["messages"] if item_msg["room_id"] == room_id]})

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
            if text.startswith("🔒 pin:sync:") or text.startswith("🔒 enc:v1:"):
                data["private_rooms"][room_id]["is_secret"] = True
                room["is_secret"] = True
            elif text.startswith("💬 mode:normal"):
                data["private_rooms"][room_id]["is_secret"] = False
                room["is_secret"] = False
            data["messages"].append(message)
            self.save(data)
            return deepcopy(message)

    def unsend_private_message(self, room_id, sender, message_id):
        if not isinstance(room_id, str) or not room_id.strip():
            raise ValueError("A non-empty room_id is required.")
        if not isinstance(message_id, str) or not message_id.strip():
            raise ValueError("A non-empty message_id is required.")
        with self.lock:
            room = self.data["private_rooms"].get(room_id)
            if room is None or sender not in room["members"]:
                raise ValueError("This private room is not available to you.")
            target_msg = None
            for msg in self.data["messages"]:
                if msg["room_id"] == room_id and msg["message_id"] == message_id:
                    target_msg = msg
                    break
            if target_msg is None:
                raise ValueError("Message not found.")
            if target_msg["from"] != sender:
                raise ValueError("You can only unsend your own messages.")
            if target_msg.get("unsent"):
                raise ValueError("Message is already unsent.")
            data = deepcopy(self.data)
            updated_msg = None
            for msg in data["messages"]:
                if msg["room_id"] == room_id and msg["message_id"] == message_id:
                    msg["unsent"] = True
                    msg["unsent_at"] = datetime.now(timezone.utc).isoformat()
                    msg["text"] = "This message was unsent"
                    updated_msg = deepcopy(msg)
                    break
            self.save(data)
            return updated_msg

    def unsend_group_message(self, group_id, sender, message_id):
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError("A non-empty group_id is required.")
        if not isinstance(message_id, str) or not message_id.strip():
            raise ValueError("A non-empty message_id is required.")
        with self.lock:
            group = self.group_for_member(group_id, sender)
            target_msg = None
            for msg in self.data["group_messages"]:
                if msg["group_id"] == group_id and msg["message_id"] == message_id:
                    target_msg = msg
                    break
            if target_msg is None:
                raise ValueError("Message not found.")
            if target_msg["from"] != sender:
                raise ValueError("You can only unsend your own messages.")
            if target_msg.get("unsent"):
                raise ValueError("Message is already unsent.")
            data = deepcopy(self.data)
            updated_msg = None
            for msg in data["group_messages"]:
                if msg["group_id"] == group_id and msg["message_id"] == message_id:
                    msg["unsent"] = True
                    msg["unsent_at"] = datetime.now(timezone.utc).isoformat()
                    msg["text"] = "This message was unsent"
                    updated_msg = deepcopy(msg)
                    break
            self.save(data)
            return updated_msg

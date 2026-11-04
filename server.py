"""Route private and group messages between multiple TCP clients."""

import os
from pathlib import Path
import socket
import threading

from protocol import receive_messages, send_message
from state_store import ChatStateStore

HOST = "127.0.0.1"
PORT = 5000
STATE_PATH = Path(os.environ.get("CHAT_STATE_PATH", Path(__file__).resolve().parent / "output" / "chat_state.json"))

# กุญแจนี้ป้องกันการอ่านและแก้รายชื่อพร้อมกันจากหลาย thread
clients = {}
connections = set()
clients_lock = threading.Lock()
users_version = 0
server_stopping = threading.Event()
chat_state = None
room_locks = {}
room_locks_lock = threading.Lock()


class ClientConnection:
    """Keep a socket, its registered name, and its send lock together."""

    def __init__(self, connection):
        self.connection = connection
        self.name = None
        # หลาย thread อาจส่งหาคนเดียวกัน ต้องส่ง JSON ให้จบทีละข้อความ
        self.send_lock = threading.Lock()
        self.last_users_version = -1
        self.supports_rooms = False
        self.supports_groups = False
        self.supports_group_messages = False
        self.last_groups_version = -1
        self.announced_rooms = set()
        self.announced_groups = set()

    def send(self, message):
        with self.send_lock:
            send_message(self.connection, message)

    def send_users(self, message):
        with self.send_lock:
            # ถ้ารายการใหม่ส่งไปก่อนแล้ว ไม่ส่งรายการเก่าย้อนตามไป
            if message["version"] <= self.last_users_version:
                return
            send_message(self.connection, message)
            self.last_users_version = message["version"]

    def send_groups(self, message):
        with self.send_lock:
            if message["version"] <= self.last_groups_version:
                return
            send_message(self.connection, message)
            self.last_groups_version = message["version"]

    def send_room(self, room, request_id=None):
        with self.send_lock:
            response = {"type": "room_opened", **room}
            if request_id is not None:
                response["request_id"] = request_id
            send_message(self.connection, response)
            self.announced_rooms.add(room["room_id"])

    def send_private(self, room, message, request_id=None):
        with self.send_lock:
            if self.supports_rooms:
                if room["room_id"] not in self.announced_rooms:
                    # ส่งข้อมูลห้องและประวัติก่อนข้อความสด โดยไม่ใส่ข้อความล่าสุดซ้ำในประวัติ
                    history = [item for item in room["messages"] if item["message_id"] != message["message_id"]]
                    send_message(self.connection, {"type": "room_opened", **room, "messages": history})
                    self.announced_rooms.add(room["room_id"])
                event = dict(message)
                if request_id is not None:
                    event["request_id"] = request_id
                send_message(self.connection, event)
            else:
                send_message(self.connection, {
                    "type": "message", "from": message["from"], "to": message["to"], "text": message["text"],
                })

    def send_group_room(self, group, request_id):
        with self.send_lock:
            send_message(self.connection, {"type": "group_opened", **group, "request_id": request_id})
            self.announced_groups.add(group["group_id"])

    def send_group_left(self, result, request_id):
        with self.send_lock:
            # เมื่อ Join กลับ ต้องประกาศห้องพร้อมประวัติที่มีสิทธิ์ใหม่อีกครั้ง
            self.announced_groups.discard(result["group_id"])
            send_message(self.connection, {"type": "group_left", **result, "request_id": request_id})

    def send_group(self, group, message, request_id=None):
        with self.send_lock:
            if group["group_id"] not in self.announced_groups:
                history = [item for item in group["messages"] if item["message_id"] != message["message_id"]]
                send_message(self.connection, {"type": "group_opened", **group, "messages": history})
                self.announced_groups.add(group["group_id"])
            event = dict(message)
            if request_id is not None:
                event["request_id"] = request_id
            send_message(self.connection, event)

    def close(self):
        try:
            # ปลุกงานที่ติดอยู่ใน recv หรือ send ให้จบได้ด้วย
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()


def disconnect_client(client, notify=True):
    global users_version
    changed = False
    with clients_lock:
        # ตรวจว่าเป็นการเชื่อมต่อเดิม ก่อนลบชื่อที่อาจมีคนเข้ามาใช้ใหม่
        if clients.get(client.name) is client:
            del clients[client.name]
            users_version += 1
            changed = True
        connections.discard(client)
    client.close()
    if changed and notify:
        broadcast_users()
    return changed


def broadcast_users():
    while not server_stopping.is_set():
        # จับภาพรายชื่อและเลขรุ่นพร้อมกัน แล้วปล่อยกุญแจก่อนส่งเครือข่าย
        with clients_lock:
            message = {
                "type": "users_updated",
                "version": users_version,
                "users": sorted(clients),
            }
            recipients = list(clients.values())

        changed = False
        for recipient in recipients:
            try:
                recipient.send_users(message)
            except OSError:
                # ถ้าพบคนหลุด ให้แก้สถานะแล้ววนส่งภาพล่าสุด ไม่เรียกซ้อนกันไม่สิ้นสุด
                changed = disconnect_client(recipient, notify=False) or changed
        if not changed:
            return


def broadcast_groups():
    message = chat_state.groups_snapshot()
    with clients_lock:
        recipients = [client for client in clients.values() if client.supports_groups]
    for recipient in recipients:
        try:
            recipient.send_groups(message)
        except OSError:
            disconnect_client(recipient)


def register_client(client, message):
    global users_version
    name = message.get("name")
    if not isinstance(name, str) or not name.strip():
        client.send({"type": "error", "text": "Name must be a non-empty string."})
        return

    name = name.strip()
    if name == "/quit":
        client.send({"type": "error", "text": "The name '/quit' is reserved for the exit command."})
        return

    # ล็อกฝั่งส่งก่อนเผยแพร่ชื่อ เพื่อให้ registered มาก่อนข้อความจากคนอื่น
    with client.send_lock:
        with clients_lock:
            if name in clients:
                response = {"type": "error", "text": "Name is already in use. Choose another name."}
            else:
                client.name = name
                capabilities = message.get("capabilities", [])
                client.supports_rooms = isinstance(capabilities, list) and "private_rooms" in capabilities
                client.supports_groups = isinstance(capabilities, list) and "groups" in capabilities
                client.supports_group_messages = isinstance(capabilities, list) and "group_messages" in capabilities
                clients[name] = client
                users_version += 1
                response = {"type": "registered", "name": name}
        # ปล่อยกุญแจรายชื่อแล้ว จึงส่งข้อมูลผ่านเครือข่าย
        send_message(client.connection, response)

    if client.name is not None:
        print(f"Registered: {client.name}")
        if client.supports_rooms:
            client.send({"type": "private_rooms", "rooms": chat_state.list_rooms(client.name)})
        if client.supports_groups:
            client.send_groups(chat_state.groups_snapshot())
        broadcast_users()


def room_lock(room_id):
    with room_locks_lock:
        return room_locks.setdefault(room_id, threading.Lock())


def request_id_for(message):
    request_id = message.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("A non-empty request_id is required.")
    return request_id


def create_group(sender, message):
    request_id = request_id_for(message)
    # ไม่ใช้ creator หรือ members ที่ Client ส่งมา ผู้สร้างคือเจ้าของการเชื่อมต่อนี้เสมอ
    group = chat_state.create_group(message.get("name"), sender.name)
    try:
        sender.send({"type": "group_created", "request_id": request_id, "group_id": group["group_id"]})
    finally:
        # แม้ผู้สร้างหลุดตอนรับคำตอบ คนอื่นต้องได้รับรายการที่บันทึกแล้ว
        broadcast_groups()


def join_group(sender, message):
    request_id = request_id_for(message)
    group_id = message.get("group_id")
    if not isinstance(group_id, str) or not group_id.strip():
        raise ValueError("A non-empty group_id is required.")
    with room_lock(group_id):
        # อนุญาตให้เข้าร่วมได้เฉพาะชื่อตัวเอง ไม่ใช้ name หรือ members ที่แนบมา
        group = chat_state.join_group(group_id, sender.name)
        try:
            sender.send({"type": "group_joined", "request_id": request_id, "group_id": group["group_id"]})
        finally:
            broadcast_groups()


def leave_group(sender, message):
    request_id = request_id_for(message)
    group_id = message.get("group_id")
    if not isinstance(group_id, str) or not group_id.strip():
        raise ValueError("A non-empty group_id is required.")
    # ล็อกเดียวกับ Join/Open/Send ให้ข้อความก่อนออกส่งจบก่อนตอบว่า Leave สำเร็จ
    with room_lock(group_id):
        result = chat_state.leave_group(group_id, sender.name)
        try:
            sender.send_group_left(result, request_id)
        finally:
            broadcast_groups()


def open_group(sender, message):
    request_id = request_id_for(message)
    group_id = message.get("group_id")
    if not isinstance(group_id, str) or not group_id.strip():
        raise ValueError("A non-empty group_id is required.")
    # ล็อกเดียวกับการส่ง เพื่อให้ประวัติและข้อความสดของกลุ่มเรียงกัน
    with room_lock(group_id):
        sender.send_group_room(chat_state.group_snapshot(group_id, sender.name), request_id)


def deliver_group(sender, message):
    request_id = request_id_for(message)
    group_id = message.get("group_id")
    if not isinstance(group_id, str) or not group_id.strip():
        raise ValueError("A non-empty group_id is required.")
    with room_lock(group_id):
        saved = chat_state.append_group_message(group_id, sender.name, message.get("text"))
        event = chat_state.public_group_message(saved)
        # เลือกผู้รับจากสิทธิ์ที่บันทึกแล้ว ไม่ใช้สมาชิกใหม่ที่อาจ Join ระหว่างส่ง
        with clients_lock:
            recipients = [clients[name] for name in saved["visible_to"]
                          if name in clients and (clients[name].supports_group_messages or clients[name] is sender)]
        failed = []
        for recipient in recipients:
            try:
                group = chat_state.group_snapshot(group_id, recipient.name)
                recipient.send_group(group, event, request_id if recipient is sender else None)
            except OSError:
                failed.append(recipient.name)
                disconnect_client(recipient)
        response = {"request_id": request_id, "group_id": group_id, "message_id": event["message_id"]}
        if failed:
            sender.send({"type": "error", **response, "persisted": True,
                         "text": "Message was saved, but live delivery failed for: " + ", ".join(failed) + "."})
        else:
            sender.send({"type": "sent", **response})


def open_private(sender, message):
    request_id = request_id_for(message)
    room_id = message.get("room_id")
    if room_id is not None:
        if not isinstance(room_id, str):
            raise ValueError("room_id must be a string.")
        room = chat_state.snapshot(room_id, sender.name)
    else:
        other = message.get("to")
        if not isinstance(other, str) or not other.strip() or other.strip() == sender.name:
            raise ValueError("Choose another user for a private room.")
        other = other.strip()
        room = chat_state.find_room(sender.name, other)
        if room is None:
            with clients_lock:
                available = other in clients
            if not available:
                raise ValueError(f"Recipient '{other}' is not connected.")
            room = chat_state.get_or_create_room(sender.name, other)
    with room_lock(room["room_id"]):
        sender.send_room(chat_state.snapshot(room["room_id"], sender.name), request_id)


def deliver_private(sender, room_id, text, request_id=None, legacy=False):
    # ล็อกเฉพาะห้องเพื่อรักษาลำดับประวัติและข้อความสด ไม่ถือ clients_lock ระหว่างส่งเครือข่าย
    with room_lock(room_id):
        room = chat_state.snapshot(room_id, sender.name)
        other = next(name for name in room["members"] if name != sender.name)
        with clients_lock:
            recipient = clients.get(other)
        if recipient is None:
            raise ValueError(f"Recipient '{other}' is not connected.")
        message = chat_state.append_message(room_id, sender.name, text)
        room = chat_state.snapshot(room_id, sender.name)
        forwarded = True
        try:
            recipient.send_private(room, message)
        except OSError:
            forwarded = False
            disconnect_client(recipient)
        if not legacy:
            sender.send_private(room, message, request_id)
        if not forwarded:
            sender.send({"type": "error", "request_id": request_id, "room_id": room_id,
                         "message_id": message["message_id"], "persisted": True,
                         "text": f"Message was saved, but recipient '{other}' disconnected before live delivery completed."})
            return
        response = {"type": "sent", "to": other}
        if not legacy:
            response.update(request_id=request_id, room_id=room_id, message_id=message["message_id"])
        sender.send(response)


def route_message(sender, message):
    recipient_name = message.get("to")
    text = message.get("text")
    if not isinstance(recipient_name, str) or not recipient_name.strip():
        sender.send({"type": "error", "text": "Recipient must be a non-empty string."})
        return
    if not isinstance(text, str):
        sender.send({"type": "error", "text": "Message text must be a string."})
        return

    recipient_name = recipient_name.strip()
    with clients_lock:
        recipient = clients.get(recipient_name)

    if recipient is None:
        sender.send({"type": "error", "text": f"Recipient '{recipient_name}' is not connected."})
        return

    if recipient_name != sender.name:
        try:
            room = chat_state.get_or_create_room(sender.name, recipient_name)
            deliver_private(sender, room["room_id"], text, legacy=True)
        except (ValueError, OSError) as error:
            sender.send({"type": "error", "text": str(error)})
        return

    try:
        recipient.send({
            "type": "message",
            # ใช้ชื่อจากการเชื่อมต่อ ไม่เชื่อฟิลด์ from ที่ Client อาจแนบมาเอง
            "from": sender.name,
            "to": recipient_name,
            "text": text,
        })
    except OSError:
        # ผู้รับอาจหลุดหลังค้นชื่อเจอ ต้องไม่ทำให้ผู้ส่งหลุดตาม
        disconnect_client(recipient)
        sender.send({"type": "error", "text": f"Recipient '{recipient_name}' disconnected before forwarding completed."})
        return

    # ยืนยันว่า Server ส่งผ่าน Socket แล้ว ไม่ใช่การยืนยันว่าอีกฝ่ายอ่านแล้ว
    sender.send({"type": "sent", "to": recipient_name})
    print(f"Forwarded: {sender.name} -> {recipient_name}")


def handle_client(client, address):
    print(f"Client connected: {address}")
    try:
        for message in receive_messages(client.connection):
            message_type = message.get("type")
            if client.name is None:
                if message_type == "register":
                    register_client(client, message)
                else:
                    client.send({"type": "error", "text": "Register a name before sending messages."})
            elif message_type == "message":
                route_message(client, message)
            elif message_type in ("create_group", "join_group", "leave_group"):
                try:
                    if message_type == "create_group":
                        create_group(client, message)
                    elif message_type == "join_group":
                        join_group(client, message)
                    else:
                        leave_group(client, message)
                except (ValueError, OSError) as error:
                    client.send({"type": "error", "request_id": message.get("request_id"), "text": str(error)})
            elif message_type in ("open_private", "private_message"):
                try:
                    if message_type == "open_private":
                        open_private(client, message)
                    else:
                        request_id = request_id_for(message)
                        room_id = message.get("room_id")
                        if not isinstance(room_id, str):
                            raise ValueError("room_id must be a string.")
                        deliver_private(client, room_id, message.get("text"), request_id)
                except (ValueError, OSError) as error:
                    client.send({"type": "error", "request_id": message.get("request_id"),
                                 "room_id": message.get("room_id"), "text": str(error)})
            elif message_type in ("open_group", "group_message"):
                try:
                    if message_type == "open_group":
                        open_group(client, message)
                    else:
                        deliver_group(client, message)
                except (ValueError, OSError) as error:
                    client.send({"type": "error", "request_id": message.get("request_id"),
                                 "group_id": message.get("group_id"), "text": str(error)})
            else:
                client.send({"type": "error", "text": "Unknown command after registration."})
    except ValueError as error:
        try:
            client.send({"type": "error", "text": str(error)})
        except OSError:
            pass
        print(f"Invalid data from {client.name or address}: {error}")
    except OSError as error:
        print(f"Connection ended for {client.name or address}: {error}")
    finally:
        disconnect_client(client)
        print(f"Client disconnected: {client.name or address}")


def main():
    global chat_state
    chat_state = ChatStateStore(STATE_PATH)
    server_stopping.clear()
    workers = set()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen()
        host, port = server.getsockname()
        print(f"Server listening on {host}:{port}")
        try:
            while True:
                # Socket นี้รอรับคนใหม่ ส่วนการคุยใช้ Socket ที่ accept คืนมา
                connection, address = server.accept()
                client = ClientConnection(connection)
                with clients_lock:
                    connections.add(client)
                worker = threading.Thread(
                    target=handle_client, args=(client, address), daemon=True
                )
                worker.start()
                workers = {thread for thread in workers if thread.is_alive()}
                workers.add(worker)
        except KeyboardInterrupt:
            print("\nStopping server...")
        finally:
            server_stopping.set()
            with clients_lock:
                active_connections = list(connections)
            # ปิดทั้งคนที่ลงชื่อแล้วและคนที่ยังไม่ได้ลงชื่อ โดยไม่ถือกุญแจรายชื่อ
            for client in active_connections:
                client.close()
            for worker in workers:
                worker.join()
    print("Server stopped.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"Server error: {error}")
        raise SystemExit(1)

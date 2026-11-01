"""Route private messages between multiple TCP clients."""

import socket
import threading

from protocol import receive_messages, send_message

HOST = "127.0.0.1"
PORT = 5000

# กุญแจนี้ป้องกันการอ่านและแก้รายชื่อพร้อมกันจากหลาย thread
clients = {}
connections = set()
clients_lock = threading.Lock()
users_version = 0
server_stopping = threading.Event()


class ClientConnection:
    """Keep a socket, its registered name, and its send lock together."""

    def __init__(self, connection):
        self.connection = connection
        self.name = None
        # หลาย thread อาจส่งหาคนเดียวกัน ต้องส่ง JSON ให้จบทีละข้อความ
        self.send_lock = threading.Lock()
        self.last_users_version = -1

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
                clients[name] = client
                users_version += 1
                response = {"type": "registered", "name": name}
        # ปล่อยกุญแจรายชื่อแล้ว จึงส่งข้อมูลผ่านเครือข่าย
        send_message(client.connection, response)

    if client.name is not None:
        print(f"Registered: {client.name}")
        broadcast_users()


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
            else:
                client.send({"type": "error", "text": "Only message commands are allowed after registration."})
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
    except OSError as error:
        print(f"Server error: {error}")
        raise SystemExit(1)

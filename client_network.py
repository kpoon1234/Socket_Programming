"""Run socket I/O in background threads and expose events through a queue."""

import queue
import socket
import threading
import time

from protocol import receive_messages, send_message


class NetworkClient:
    """One connection attempt with an independent receiver and sender."""

    def __init__(self):
        self.events = queue.Queue()
        self.outgoing = queue.Queue()
        self.stopped = threading.Event()
        self.ready = threading.Event()
        self.connection_lock = threading.Lock()
        self.connection = None
        self.receiver = None
        self.sender = None
        self.name = None
        self.last_users_version = -1
        self.last_groups_version = -1
        self.reason = "Server disconnected."
        self.intentional = False

    def connect(self, host, port, name, capabilities=None):
        if self.receiver is not None or self.stopped.is_set():
            raise RuntimeError("Create a new NetworkClient for each connection attempt.")
        registration = {"type": "register", "name": name}
        if capabilities:
            registration["capabilities"] = capabilities
        self.outgoing.put(registration)
        self.receiver = threading.Thread(
            target=self.receive_loop, args=(host, port), name="chat-receiver", daemon=True
        )
        self.sender = threading.Thread(
            target=self.send_loop, name="chat-sender", daemon=True
        )
        self.receiver.start()
        self.sender.start()

    def send(self, message):
        if not self.ready.is_set() or self.stopped.is_set():
            raise ConnectionError("Client is not connected.")
        self.outgoing.put(message)

    def receive_loop(self, host, port):
        reason = "Server disconnected."
        try:
            connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            with self.connection_lock:
                self.connection = connection
                if self.stopped.is_set():
                    connection.close()
                    return

            # connect อยู่ในงานเบื้องหลัง และกำหนดเวลารอเพื่อยกเลิกได้
            connection.settimeout(5)
            connection.connect((host, port))
            connection.settimeout(None)
            if self.stopped.is_set():
                return
            self.events.put({"type": "connected", "host": host, "port": port})
            self.ready.set()

            for message in receive_messages(connection):
                if self.stopped.is_set():
                    break
                if message.get("type") == "registered":
                    self.name = message["name"]
                elif message.get("type") == "users_updated":
                    version = message.get("version")
                    users = message.get("users")
                    if type(version) is not int or version < 0:
                        raise ValueError("Invalid online users version.")
                    if not isinstance(users, list) or not all(isinstance(name, str) for name in users):
                        raise ValueError("Invalid online users list.")
                    if version <= self.last_users_version:
                        continue
                    self.last_users_version = version
                elif message.get("type") == "groups_updated":
                    version = message.get("version")
                    groups = message.get("groups")
                    if type(version) is not int or version < 0:
                        raise ValueError("Invalid groups version.")
                    if not isinstance(groups, list) or not all(isinstance(group, dict) for group in groups):
                        raise ValueError("Invalid groups list.")
                    if version <= self.last_groups_version:
                        continue
                    self.last_groups_version = version
                self.events.put(message)
        except (OSError, ValueError) as error:
            reason = f"Connection error: {error}"
        finally:
            self.close(reason=reason, intentional=False)
            self.events.put({
                "type": "disconnected", "text": self.reason,
                "intentional": self.intentional,
            })

    def send_loop(self):
        self.ready.wait()
        try:
            while not self.stopped.is_set():
                message = self.outgoing.get()
                if message is None or self.stopped.is_set():
                    return
                with self.connection_lock:
                    connection = self.connection
                send_message(connection, message)
        except (OSError, ValueError, TypeError) as error:
            self.close(reason=f"Send error: {error}", intentional=False)

    def close(self, reason="Disconnected.", intentional=True):
        with self.connection_lock:
            # เก็บสาเหตุแรกไว้ ไม่ให้ข้อผิดพลาดจากการปิด Socket ทับเหตุผลเดิม
            if not self.stopped.is_set():
                self.reason = reason
                self.intentional = intentional
            self.stopped.set()
            connection = self.connection
        self.ready.set()
        self.outgoing.put(None)
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()

    def wait_closed(self, timeout=5):
        """Wait in tests or shutdown helpers, outside GUI event handlers."""
        deadline = time.monotonic() + timeout
        for worker in (self.receiver, self.sender):
            if worker is not None:
                worker.join(max(0, deadline - time.monotonic()))
        return all(worker is None or not worker.is_alive() for worker in (self.receiver, self.sender))

"""Test message framing, private routing, and concurrent client lifecycles."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import queue
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from protocol import receive_messages, send_message

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ChunkConnection:
    """Return predetermined chunks to exercise TCP message boundaries."""

    def __init__(self, chunks=()):
        self.chunks = iter(chunks)
        self.sent = b""
        self.reads = 0

    def recv(self, size):
        self.reads += 1
        return next(self.chunks, b"")

    def sendall(self, data):
        self.sent += data


class ProtocolTests(unittest.TestCase):
    def test_utf8_and_embedded_newline_split_at_every_byte(self):
        message = {"type": "message", "text": "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35\n\U0001f642"}
        writer = ChunkConnection()
        send_message(writer, message)
        self.assertEqual(writer.sent.count(b"\n"), 1)
        reader = ChunkConnection(bytes([byte]) for byte in writer.sent)
        self.assertEqual(list(receive_messages(reader)), [message])

    def test_combined_frames_preserve_partial_tail(self):
        messages = [{"type": "message", "text": str(index)} for index in range(3)]
        payload = b"".join((json.dumps(item) + "\n").encode() for item in messages)
        reader = ChunkConnection([payload[:-5], payload[-5:]])
        incoming = receive_messages(reader)
        self.assertEqual(next(incoming), messages[0])
        self.assertEqual(next(incoming), messages[1])
        self.assertEqual(reader.reads, 1)
        self.assertEqual(next(incoming), messages[2])
        self.assertEqual(list(incoming), [])

    def test_invalid_or_incomplete_frames_are_rejected(self):
        for payload in (b"bad-json\n", b"[]\n", b"\xff\n", b'{"type":'):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    list(receive_messages(ChunkConnection([payload])))
        self.assertEqual(list(receive_messages(ChunkConnection())), [])


class Peer:
    """A small protocol client for integration tests."""

    def __init__(self, port):
        self.connection = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.messages = receive_messages(self.connection)
        self.presence_updates = []

    def send(self, message):
        send_message(self.connection, message)

    def receive(self):
        while True:
            message = next(self.messages)
            if message.get("type") == "users_updated":
                self.presence_updates.append(message)
            else:
                return message

    def wait_users(self, expected):
        while True:
            if self.presence_updates:
                message = self.presence_updates.pop(0)
            else:
                message = next(self.messages)
            if message.get("type") != "users_updated":
                raise AssertionError(f"Expected a presence update, got {message}")
            if message["users"] == sorted(expected):
                return message

    def close(self):
        self.connection.close()


class ProcessOutput:
    """Drain process output so log pipes cannot block network threads."""

    def __init__(self, process):
        self.process = process
        self.lines = queue.Queue()
        self.history = []
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()

    def read(self):
        for line in self.process.stdout:
            self.history.append(line)
            self.lines.put(line)

    def wait_for(self, text):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if text in line:
                return line
        raise AssertionError(f"Missing output: {text!r}\n{''.join(self.history)}")

    def finish(self):
        self.reader.join(timeout=5)
        self.process.stdout.close()


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.peers = []
        # ประวัติทดสอบอยู่ในโฟลเดอร์ชั่วคราว ไม่แตะประวัติที่ผู้ใช้ทดลองจริง
        self.state_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.state_directory.cleanup)
        self.state_path = Path(self.state_directory.name) / "chat_state.json"
        self.start_server()
        self.addCleanup(self.cleanup)

    def start_server(self):
        # ใช้พอร์ตว่างของระบบ เพื่อไม่ชนกับ Server ที่ผู้ใช้กำลังทดลอง
        self.server = subprocess.Popen(
            [sys.executable, "-B", "-u", "-c", "import server; server.PORT = 0; server.main()"],
            cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", env={**os.environ, "CHAT_STATE_PATH": str(self.state_path)},
        )
        self.output = ProcessOutput(self.server)
        ready = self.output.wait_for("Server listening on ")
        self.port = int(ready.rsplit(":", 1)[1])

    def cleanup(self):
        for peer in self.peers:
            peer.close()
        if self.server.poll() is None:
            self.server.send_signal(signal.SIGINT)
            try:
                self.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=5)
                self.fail("Server did not shut down cleanly.")
        self.output.finish()

    def peer(self, name=None):
        peer = Peer(self.port)
        self.peers.append(peer)
        if name is not None:
            peer.send({"type": "register", "name": name})
            self.assertEqual(peer.receive(), {"type": "registered", "name": name.strip()})
        return peer


class ChatTests(ServerTestCase):
    def test_private_routing_identity_and_unknown_recipient(self):
        alice, bob, carol = self.peer("alice"), self.peer("bob"), self.peer("carol")
        alice.send({"type": "message", "to": "bob", "text": "Hello", "from": "forged"})
        self.assertEqual(bob.receive(), {"type": "message", "from": "alice", "to": "bob", "text": "Hello"})
        self.assertEqual(alice.receive(), {"type": "sent", "to": "bob"})
        # ถ้า carol ได้ข้อความที่ไม่ได้ส่งหา การอ่านถัดไปจะไม่ตรงกับ probe
        carol.send({"type": "message", "to": "carol", "text": "probe"})
        self.assertEqual(carol.receive()["text"], "probe")
        self.assertEqual(carol.receive()["type"], "sent")
        alice.send({"type": "message", "to": "missing", "text": "Hello"})
        self.assertEqual(alice.receive()["type"], "error")
        bob.send({"type": "message", "to": "alice", "text": "Reply"})
        self.assertEqual(alice.receive()["text"], "Reply")
        self.assertEqual(bob.receive()["type"], "sent")

    def test_duplicate_registration_is_atomic_and_name_can_be_reused(self):
        first, second = self.peer(), self.peer()
        barrier = threading.Barrier(2)

        def register(peer):
            barrier.wait(timeout=5)
            peer.send({"type": "register", "name": "shared"})
            return peer.receive()

        with ThreadPoolExecutor(max_workers=2) as executor:
            replies = list(executor.map(register, (first, second)))
        self.assertCountEqual([reply["type"] for reply in replies], ["registered", "error"])
        winner = 0 if replies[0]["type"] == "registered" else 1
        peers = (first, second)
        peers[winner].close()
        self.output.wait_for("Client disconnected: shared")
        peers[1 - winner].send({"type": "register", "name": "shared"})
        self.assertEqual(peers[1 - winner].receive()["type"], "registered")

    def test_concurrent_senders_to_one_recipient_preserve_frames(self):
        recipient = self.peer("receiver")
        senders = [(name, self.peer(name)) for name in ("alice", "bob", "carol")]
        expected = set()
        for name, peer in senders:
            for index in range(6):
                expected.add((name, f"{index}:" + "\u0e01" * 1600))

        def send_many(item):
            name, peer = item
            for index in range(6):
                peer.send({"type": "message", "to": "receiver", "text": f"{index}:" + "\u0e01" * 1600})
                self.assertEqual(peer.receive(), {"type": "sent", "to": "receiver"})

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(send_many, item) for item in senders]
            received = [recipient.receive() for _ in range(18)]
            for future in futures:
                future.result(timeout=5)
        self.assertTrue(all(message["to"] == "receiver" for message in received))
        self.assertEqual({(message["from"], message["text"]) for message in received}, expected)

    def test_bad_client_does_not_stop_other_clients(self):
        alice, bob = self.peer("alice"), self.peer("bob")
        for payload in (b"invalid\n", b"[]\n", b"\xff\n", b'{"type":'):
            broken = self.peer()
            broken.connection.sendall(payload)
            broken.connection.shutdown(socket.SHUT_WR)
            self.assertEqual(broken.receive()["type"], "error")
            self.assertIsNone(next(broken.messages, None))
        pending = self.peer()
        for request in (
            {"type": "message", "to": "bob", "text": "Too early"},
            {"type": "register", "name": " "},
            {"type": "register", "name": "/quit"},
        ):
            pending.send(request)
            self.assertEqual(pending.receive()["type"], "error")
        pending.send({"type": "register", "name": "new client"})
        self.assertEqual(pending.receive()["name"], "new client")
        alice.send({"type": "message", "to": "bob", "text": "Still connected"})
        self.assertEqual(bob.receive()["text"], "Still connected")
        self.assertEqual(alice.receive()["type"], "sent")
        for request in (
            {"type": "message", "to": " ", "text": "Hello"},
            {"type": "message", "to": "bob", "text": 123},
            {"type": "register", "name": "renamed"},
        ):
            alice.send(request)
            self.assertEqual(alice.receive()["type"], "error")
        self.assertIsNone(self.server.poll())

    def test_shutdown_closes_registered_and_unregistered_clients(self):
        pending = self.peer()
        registered = self.peer("alice")
        registered.wait_users(["alice"])
        self.server.send_signal(signal.SIGINT)
        self.assertEqual(self.server.wait(timeout=5), 0)
        self.assertEqual(pending.connection.recv(1), b"")
        self.assertEqual(registered.connection.recv(1), b"")


if __name__ == "__main__":
    unittest.main(verbosity=2)

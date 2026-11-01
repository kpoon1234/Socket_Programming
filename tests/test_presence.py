"""Test online-user snapshots and the GUI network worker lifecycle."""

from concurrent.futures import ThreadPoolExecutor
import signal
import socket
import threading
import time
import unittest

from client_network import NetworkClient
from protocol import receive_messages, send_message
from server import ClientConnection
from test_chat import ChunkConnection, ServerTestCase


def wait_event(network, event_type, predicate=lambda event: True):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        event = network.events.get(timeout=max(0.01, deadline - time.monotonic()))
        if event.get("type") == event_type and predicate(event):
            return event
    raise AssertionError(f"Missing network event: {event_type}")


class PresenceTests(ServerTestCase):
    def network_client(self, name):
        network = NetworkClient()
        self.addCleanup(self.close_network, network)
        network.connect("127.0.0.1", self.port, name)
        return network

    def close_network(self, network):
        network.close()
        self.assertTrue(network.wait_closed())

    def test_join_leave_and_reconnect_include_own_name(self):
        alice = self.peer("alice")
        first = alice.wait_users(["alice"])
        bob = self.peer("bob")
        second = alice.wait_users(["alice", "bob"])
        bob.wait_users(["alice", "bob"])
        carol = self.peer("carol")
        third = alice.wait_users(["alice", "bob", "carol"])
        bob.wait_users(["alice", "bob", "carol"])
        carol.wait_users(["alice", "bob", "carol"])
        bob.close()
        fourth = alice.wait_users(["alice", "carol"])
        carol.wait_users(["alice", "carol"])
        returning = self.peer("bob")
        fifth = returning.wait_users(["alice", "bob", "carol"])
        alice.wait_users(["alice", "bob", "carol"])
        versions = [event["version"] for event in (first, second, third, fourth, fifth)]
        self.assertEqual(versions, sorted(set(versions)))

    def test_registration_acknowledgement_always_precedes_presence(self):
        self.peer("existing")
        peers = [self.peer() for _ in range(6)]
        barrier = threading.Barrier(len(peers))

        def register(item):
            index, peer = item
            barrier.wait(timeout=5)
            peer.send({"type": "register", "name": f"user-{index}"})
            # อ่านเฟรมแรกโดยตรง ไม่ให้ helper ข้ามเหตุการณ์รายชื่อ
            return next(peer.messages)

        with ThreadPoolExecutor(max_workers=len(peers)) as executor:
            replies = list(executor.map(register, enumerate(peers)))
        self.assertTrue(all(reply["type"] == "registered" for reply in replies))
        expected = ["existing"] + [f"user-{index}" for index in range(6)]
        for peer in peers:
            peer.wait_users(expected)

    def test_network_client_sends_and_receives_without_gui_calls(self):
        bob = self.peer("bob")
        network = self.network_client("alice")
        self.assertEqual(wait_event(network, "registered")["name"], "alice")
        self.assertEqual(wait_event(network, "users_updated")["users"], ["alice", "bob"])
        network.send({"type": "message", "to": "bob", "text": "Hello"})
        self.assertEqual(bob.receive()["text"], "Hello")
        self.assertEqual(wait_event(network, "sent")["to"], "bob")
        bob.send({"type": "message", "to": "alice", "text": "Reply"})
        self.assertEqual(wait_event(network, "message")["text"], "Reply")

    def test_network_workers_stop_on_disconnect_and_server_shutdown(self):
        first = self.network_client("alice")
        wait_event(first, "registered")
        first.close()
        event = wait_event(first, "disconnected")
        self.assertTrue(event["intentional"])
        self.assertTrue(first.wait_closed())

        second = self.network_client("bob")
        wait_event(second, "registered")
        self.server.send_signal(signal.SIGINT)
        self.assertEqual(self.server.wait(timeout=5), 0)
        event = wait_event(second, "disconnected")
        self.assertFalse(event["intentional"])
        self.assertTrue(second.wait_closed())

    def test_rejected_name_can_retry_using_a_new_connection(self):
        self.peer("alice")
        first = self.network_client("alice")
        self.assertIn("already in use", wait_event(first, "error")["text"])
        first.close()
        self.assertTrue(first.wait_closed())
        second = self.network_client("charlie")
        self.assertEqual(wait_event(second, "registered")["name"], "charlie")
        self.assertEqual(wait_event(second, "users_updated")["users"], ["alice", "charlie"])


class SnapshotTests(unittest.TestCase):
    def test_server_does_not_send_an_old_snapshot_after_a_new_one(self):
        writer = ChunkConnection()
        client = ClientConnection(writer)
        for version in (3, 1, 3, 4, 2):
            client.send_users({"type": "users_updated", "version": version, "users": ["alice"]})
        reader = ChunkConnection([writer.sent])
        self.assertEqual([message["version"] for message in receive_messages(reader)], [3, 4])

    def test_network_client_ignores_old_snapshots(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            network = NetworkClient()
            self.addCleanup(network.close)
            network.connect("127.0.0.1", listener.getsockname()[1], "alice")
            listener.settimeout(5)
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(5)
                incoming = receive_messages(connection)
                self.assertEqual(next(incoming)["type"], "register")
                send_message(connection, {"type": "registered", "name": "alice"})
                for version, users in ((5, ["alice", "bob"]), (3, ["alice"]), (6, ["alice", "carol"])):
                    send_message(connection, {"type": "users_updated", "version": version, "users": users})
            versions = []
            while True:
                event = network.events.get(timeout=5)
                if event["type"] == "users_updated":
                    versions.append(event["version"])
                if event["type"] == "disconnected":
                    break
            self.assertTrue(network.wait_closed())
            self.assertEqual(versions, [5, 6])
            self.assertEqual(network.last_users_version, 6)

    def test_connection_refused_reports_an_event_and_stops_workers(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
            network = NetworkClient()
            self.addCleanup(network.close)
            network.connect("127.0.0.1", port, "alice")
            event = wait_event(network, "disconnected")
            self.assertIn("Connection error:", event["text"])
            self.assertTrue(network.wait_closed())


if __name__ == "__main__":
    unittest.main(verbosity=2)

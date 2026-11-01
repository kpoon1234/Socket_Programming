"""Exercise real Tk widgets and socket workers under a graphical display."""

import os
import signal
import socket
import time
import unittest

try:
    import tkinter as tk
except ImportError:
    tk = None

from protocol import receive_messages, send_message
from test_chat import ServerTestCase


@unittest.skipUnless(tk is not None and os.environ.get("DISPLAY"), "Tkinter and a display are required.")
class GuiTests(ServerTestCase):
    def setUp(self):
        super().setUp()
        from gui_client import ChatApp

        self.root = tk.Tk()
        self.root.withdraw()
        self.app = ChatApp(self.root)
        self.app.port_var.set(str(self.port))
        self.app.name_var.set("alice")
        self.addCleanup(self.close_gui)

    def close_gui(self):
        if not self.app.closing:
            self.app.close()
        if self.app.network is not None:
            self.assertTrue(self.app.network.wait_closed())

    def pump_until(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail(f"GUI condition timed out; status: {self.app.status_var.get()}")

    def test_online_list_updates_and_can_disconnect_and_reconnect(self):
        self.app.connect()
        self.pump_until(lambda: self.app.online_users == ["alice"])
        self.assertEqual(self.app.users_list.get(0, tk.END), ("alice (you)",))
        bob = self.peer("bob")
        self.pump_until(lambda: self.app.online_users == ["alice", "bob"])
        self.assertEqual(self.app.users_list.get(0, tk.END), ("alice (you)", "bob"))
        bob.close()
        self.pump_until(lambda: self.app.online_users == ["alice"])
        first_network = self.app.network
        self.app.disconnect()
        self.assertEqual(self.app.online_users, [])
        self.assertTrue(first_network.wait_closed())
        self.output.wait_for("Client disconnected: alice")
        self.app.connect()
        self.pump_until(lambda: self.app.online_users == ["alice"])
        self.assertIsNot(self.app.network, first_network)

    def test_duplicate_name_is_visible_and_editable_for_retry(self):
        self.peer("alice")
        self.app.connect()
        self.pump_until(lambda: "already in use" in self.app.status_var.get())
        self.assertFalse(self.app.registered)
        self.assertEqual(str(self.app.name_entry.cget("state")), "normal")
        rejected = self.app.network
        self.assertTrue(rejected.wait_closed())
        self.app.name_var.set("carol")
        self.app.connect()
        self.pump_until(lambda: self.app.online_users == ["alice", "carol"])
        self.assertEqual(self.app.current_name, "carol")

    def test_server_shutdown_clears_users_without_waiting_for_enter(self):
        self.app.connect()
        self.pump_until(lambda: self.app.online_users == ["alice"])
        self.server.send_signal(signal.SIGINT)
        self.assertEqual(self.server.wait(timeout=5), 0)
        self.pump_until(lambda: not self.app.registered)
        self.assertEqual(self.app.online_users, [])
        self.assertIn("disconnected", self.app.status_var.get().lower())
        self.assertEqual(str(self.app.connect_button.cget("state")), "normal")

    def test_window_processes_timers_while_registration_is_pending(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(5)
            self.app.port_var.set(str(listener.getsockname()[1]))
            self.app.connect()
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(5)
                incoming = receive_messages(connection)
                self.assertEqual(next(incoming)["type"], "register")
                pulses = []

                def pulse():
                    pulses.append(True)
                    if len(pulses) < 4:
                        self.root.after(10, pulse)

                self.root.after(10, pulse)
                self.pump_until(lambda: len(pulses) == 4)
                self.assertFalse(self.app.registered)
                send_message(connection, {"type": "registered", "name": "alice"})
                send_message(connection, {"type": "users_updated", "version": 1, "users": ["alice"]})
                self.pump_until(lambda: self.app.online_users == ["alice"])
                self.app.disconnect()
                self.assertTrue(self.app.network.wait_closed())


if __name__ == "__main__":
    unittest.main(verbosity=2)

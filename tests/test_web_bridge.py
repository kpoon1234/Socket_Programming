"""Exercise isolated browser sessions against the real TCP server."""

import asyncio
import signal
import socket
import unittest

try:
    import aiohttp
except ImportError:
    aiohttp = None

if aiohttp is not None:
    from aiohttp.test_utils import TestClient, TestServer
    from web_bridge import create_app

from test_chat import ServerTestCase


@unittest.skipUnless(aiohttp is not None, "Install requirements.txt to test the web bridge.")
class WebBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = ServerTestCase()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client = TestClient(TestServer(create_app()))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def event(self, websocket, event_type):
        async with asyncio.timeout(5):
            while True:
                event = await websocket.receive_json()
                if event["type"] == event_type:
                    return event

    async def users(self, websocket, expected):
        async with asyncio.timeout(5):
            while True:
                event = await self.event(websocket, "users_updated")
                if event["users"] == sorted(expected):
                    return event

    async def connect(self, name):
        websocket = await self.client.ws_connect("/ws")
        await websocket.send_json({"type": "connect", "host": "127.0.0.1", "port": self.fixture.port, "name": name})
        return websocket

    async def registered(self, name):
        websocket = await self.connect(name)
        self.assertEqual(await self.event(websocket, "registered"), {"type": "registered", "name": name})
        return websocket

    async def test_serves_only_web_assets_and_rejects_another_origin(self):
        response = await self.client.get("/")
        self.assertEqual(response.status, 200)
        self.assertIn("Socket Chat", await response.text())
        response = await self.client.get("/app.js")
        self.assertEqual(response.status, 200)
        self.assertIn("new WebSocket", await response.text())
        self.assertEqual((await self.client.get("/server.py")).status, 404)
        with self.assertRaises(aiohttp.WSServerHandshakeError) as raised:
            await self.client.ws_connect("/ws", origin="https://another-site.example")
        self.assertEqual(raised.exception.status, 403)

    async def test_tabs_have_independent_names_and_reconnect_after_disconnect(self):
        alice = await self.registered("alice")
        await self.users(alice, ["alice"])
        bob = await self.registered("bob")
        await self.users(alice, ["alice", "bob"])
        await self.users(bob, ["alice", "bob"])
        await bob.send_json({"type": "disconnect"})
        self.assertTrue((await self.event(bob, "disconnected"))["intentional"])
        await self.users(alice, ["alice"])
        bob_again = await self.registered("bob")
        await self.users(bob_again, ["alice", "bob"])
        await self.users(alice, ["alice", "bob"])

    async def test_duplicate_name_error_can_retry_on_new_session(self):
        alice = await self.registered("alice")
        duplicate = await self.connect("alice")
        self.assertIn("already in use", (await self.event(duplicate, "error"))["text"])
        await self.event(duplicate, "disconnected")
        carol = await self.registered("carol")
        await self.users(carol, ["alice", "carol"])
        await self.users(alice, ["alice", "carol"])

    async def test_closing_one_browser_tab_removes_only_its_tcp_client(self):
        alice = await self.registered("alice")
        bob = await self.registered("bob")
        await self.users(alice, ["alice", "bob"])
        await bob.close()
        await self.users(alice, ["alice"])

    async def test_private_messages_keep_existing_routing_and_utf8(self):
        alice = await self.registered("alice")
        bob = await self.registered("bob")
        carol = await self.registered("carol")
        await alice.send_json({"type": "message", "to": "bob", "text": "Hello \u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35", "from": "carol"})
        self.assertEqual(await self.event(bob, "message"), {
            "type": "message", "from": "alice", "to": "bob", "text": "Hello \u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35",
        })
        self.assertEqual(await self.event(alice, "sent"), {"type": "sent", "to": "bob"})
        await carol.send_json({"type": "message", "to": "carol", "text": "probe"})
        self.assertEqual((await self.event(carol, "message"))["text"], "probe")

    async def test_invalid_browser_commands_do_not_break_other_tabs(self):
        bad = await self.client.ws_connect("/ws")
        for command in ("not-json", "[]", '{"type":"message"}',
                        '{"type":"connect","host":"127.0.0.1","port":true,"name":"bad"}'):
            await bad.send_str(command)
            self.assertEqual((await self.event(bad, "error"))["type"], "error")
        good = await self.registered("alice")
        await self.users(good, ["alice"])

    async def test_tcp_server_shutdown_reports_disconnect(self):
        alice = await self.registered("alice")
        await self.users(alice, ["alice"])
        self.fixture.server.send_signal(signal.SIGINT)
        await asyncio.to_thread(self.fixture.server.wait, timeout=5)
        event = await self.event(alice, "disconnected")
        self.assertFalse(event["intentional"])
        self.assertIn("disconnected", event["text"].lower())

    async def test_bridge_shutdown_disconnects_its_tabs_but_keeps_server_running(self):
        observer = self.fixture.peer("observer")
        await self.registered("alice")
        await self.client.close()
        update = await asyncio.to_thread(observer.wait_users, ["observer"])
        self.assertEqual(update["users"], ["observer"])
        self.assertIsNone(self.fixture.server.poll())

    async def test_connection_refused_can_be_retried(self):
        with socket.socket() as unavailable:
            unavailable.bind(("127.0.0.1", 0))
            websocket = await self.client.ws_connect("/ws")
            await websocket.send_json({"type": "connect", "host": "127.0.0.1", "port": unavailable.getsockname()[1], "name": "alice"})
            event = await self.event(websocket, "disconnected")
            self.assertIn("Connection error", event["text"])
        alice = await self.registered("alice")
        await self.users(alice, ["alice"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

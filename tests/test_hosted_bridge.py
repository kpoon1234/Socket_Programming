"""Check the central bridge through a tunnel-like local HTTP connection."""

import asyncio
import unittest

import aiohttp
from aiohttp.test_utils import TestClient, TestServer

from web_bridge import create_app
from test_chat import ServerTestCase


class HostedBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = ServerTestCase()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client = TestClient(TestServer(create_app(
            public_origin="https://chat.andyntk.online", tcp_host="127.0.0.1", tcp_port=self.fixture.port,
        )))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def event(self, websocket, kind):
        async with asyncio.timeout(5):
            while True:
                event = await websocket.receive_json()
                if event["type"] == kind:
                    return event

    async def connect(self, name, **extra):
        websocket = await self.client.ws_connect("/ws", origin="https://chat.andyntk.online")
        await websocket.send_json({"type": "connect", "name": name, **extra})
        self.assertEqual((await self.event(websocket, "registered"))["name"], name)
        return websocket

    async def test_separate_users_fixed_target_and_private_history(self):
        alice = await self.connect("alice")
        # ผู้เรียกที่ปลอม host/port ก็ยังต้องเชื่อมไป Server ที่ผู้ดูแลกำหนด
        bob = await self.connect("bob", host="192.0.2.1", port=1)
        await alice.send_json({"type": "open_private", "to": "bob", "request_id": "open"})
        room_id = (await self.event(alice, "room_opened"))["room_id"]
        for text in ("สวัสดีจากเว็บส่วนกลาง", "🔒 enc:v1:nonce:tag:ciphertext"):
            await alice.send_json({"type": "private_message", "room_id": room_id,
                                   "text": text, "request_id": "send"})
            incoming = await self.event(bob, "private_message")
            self.assertEqual((incoming["from"], incoming["text"]), ("alice", text))
            self.assertEqual((await self.event(alice, "sent"))["message_id"], incoming["message_id"])
        await bob.send_json({"type": "disconnect"})
        await self.event(bob, "disconnected")
        returning = await self.connect("bob")
        await returning.send_json({"type": "open_private", "room_id": room_id, "request_id": "history"})
        self.assertEqual((await self.event(returning, "room_opened"))["messages"][-1]["text"], incoming["text"])

    async def test_group_join_and_chat_through_fixed_target(self):
        alice, bob = await self.connect("alice"), await self.connect("bob")
        await alice.send_json({"type": "create_group", "name": "Team", "request_id": "create"})
        group_id = (await self.event(alice, "group_created"))["group_id"]
        await bob.send_json({"type": "join_group", "group_id": group_id, "request_id": "join"})
        await self.event(bob, "group_joined")
        await bob.send_json({"type": "group_message", "group_id": group_id,
                             "text": "Group through central bridge", "request_id": "send"})
        self.assertEqual((await self.event(alice, "group_message"))["text"], "Group through central bridge")
        self.assertEqual((await self.event(bob, "sent"))["request_id"], "send")

    async def test_public_mode_rejects_missing_foreign_and_forged_origins(self):
        for origin in (None, "null", "http://chat.andyntk.online", "https://evil.example"):
            with self.subTest(origin=origin), self.assertRaises(aiohttp.WSServerHandshakeError) as raised:
                await self.client.ws_connect("/ws", origin=origin, headers={
                    "X-Forwarded-Proto": "https", "X-Forwarded-Host": "chat.andyntk.online",
                    "Forwarded": "proto=https;host=chat.andyntk.online",
                })
            self.assertEqual(raised.exception.status, 403)
        await self.connect("alice")

    async def test_unsend_private_and_group_messages_through_fixed_target(self):
        alice, bob = await self.connect("alice"), await self.connect("bob")
        await alice.send_json({"type": "open_private", "to": "bob", "request_id": "open"})
        room_id = (await self.event(alice, "room_opened"))["room_id"]
        await alice.send_json({"type": "create_group", "name": "Unsend", "request_id": "create"})
        group_id = (await self.event(alice, "group_created"))["group_id"]
        await bob.send_json({"type": "join_group", "group_id": group_id, "request_id": "join"})
        await self.event(bob, "group_joined")

        for kind, target, key in (("private", room_id, "room_id"), ("group", group_id, "group_id")):
            with self.subTest(room_type=kind):
                await alice.send_json({"type": kind + "_message", key: target,
                                       "text": "Remove through hosted bridge", "request_id": "send"})
                message = await self.event(bob, kind + "_message")
                await self.event(alice, "sent")
                # Bridge ต้องส่ง message_id/room_type ต่อ และให้ Server ตรวจเจ้าของข้อความจริง
                await bob.send_json({"type": "unsend_message", "room_type": kind, key: target,
                                     "message_id": message["message_id"], "request_id": "forged", "from": "alice"})
                self.assertEqual((await self.event(bob, "error"))["code"], "unsend_failed")
                await alice.send_json({"type": "unsend_message", "room_type": kind, key: target,
                                       "message_id": message["message_id"], "request_id": "unsend"})
                own = await self.event(alice, "message_unsent")
                received = await self.event(bob, "message_unsent")
                self.assertEqual(own["request_id"], "unsend")
                self.assertEqual(received["message_id"], message["message_id"])
                self.assertEqual(received["from"], "alice")
                self.assertEqual((await self.event(alice, "sent"))["action"], "unsend")
                await bob.send_json({"type": "open_" + kind, key: target, "request_id": "history"})
                opened = await self.event(bob, "room_opened" if kind == "private" else "group_opened")
                self.assertTrue(opened["messages"][-1]["unsent"])
                self.assertEqual(opened["messages"][-1]["text"], "This message was unsent")

    async def test_config_and_secret_chat_assets_without_exposing_private_files(self):
        response = await self.client.get("/config")
        self.assertEqual(await response.json(), {"fixed_server": True})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        source = None
        for path in ("/e2ee.js", "/feature/E2EE/e2ee.js", "/assets/e2ee.js"):
            response = await self.client.get(path)
            self.assertEqual(response.status, 200)
            content = await response.text()
            self.assertIn("window.E2EE", content)
            if source is None:
                source = content
            self.assertEqual(content, source)
        for path in ("/.env", "/.env.deploy", "/server.py", "/output/chat_state.json"):
            self.assertEqual((await self.client.get(path)).status, 404)


class HostedConfigTests(unittest.TestCase):
    def test_public_mode_requires_fixed_target_and_an_https_origin(self):
        with self.assertRaises(ValueError):
            create_app(public_origin="https://chat.andyntk.online")
        for origin in ("http://chat.andyntk.online", "https://chat.andyntk.online/",
                       "https://chat.andyntk.online/ws", "https://chat.andyntk.online?x=1",
                       "https://user@chat.andyntk.online", "https://chat.andyntk.online:bad"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                create_app(public_origin=origin, tcp_host="127.0.0.1")
        for port in (0, 65536, True):
            with self.subTest(port=port), self.assertRaises(ValueError):
                create_app(tcp_host="127.0.0.1", tcp_port=port)


class LocalConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_keeps_manual_target_and_same_origin_websocket(self):
        async with TestClient(TestServer(create_app())) as client:
            self.assertEqual(await (await client.get("/config")).json(), {"fixed_server": False})
            origin = str(client.make_url("/")).rstrip("/")
            async with client.ws_connect("/ws", origin=origin) as websocket:
                await websocket.send_json({"type": "connect", "name": "alice"})
                self.assertIn("server address", (await websocket.receive_json())["text"])

    async def test_fixed_target_also_accepts_localhost_http_origin(self):
        async with TestClient(TestServer(create_app(tcp_host="server"))) as client:
            self.assertEqual(await (await client.get("/config")).json(), {"fixed_server": True})
            origin = str(client.make_url("/")).rstrip("/")
            async with client.ws_connect("/ws", origin=origin):
                pass

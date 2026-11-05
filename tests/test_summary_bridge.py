"""Check summary commands through WebSocket, NetworkClient and the TCP server."""

import asyncio
import json
import threading
import unittest
from unittest.mock import AsyncMock, Mock

from aiohttp.test_utils import TestClient, TestServer

import test_summary_socket as summary_fixture
from web_bridge import BrowserSession, create_app


class SummaryBridgeCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_summary_identifiers_are_forwarded(self):
        session = BrowserSession(AsyncMock())
        session.network = Mock()
        session.network.stopped = threading.Event()
        session.registered = True
        await session.handle_command({
            "type": "summarize_room", "room_type": "group", "room_id": "group-test", "request_id": "summary",
            "messages": [{"text": "forged"}], "from": "someone-else", "api_key": "fake-browser-key",
        })
        session.network.send.assert_called_once_with({
            "type": "summarize_room", "room_type": "group", "room_id": "group-test", "request_id": "summary",
        })


class SummaryBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = summary_fixture.SummarySocketTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client = TestClient(TestServer(create_app()))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def event(self, websocket, kind):
        async with asyncio.timeout(5):
            while True:
                event = await websocket.receive_json()
                if event["type"] == kind:
                    return event

    async def member(self, name):
        websocket = await self.client.ws_connect("/ws")
        await websocket.send_json({"type": "connect", "host": "127.0.0.1", "port": self.fixture.port, "name": name})
        await self.event(websocket, "registered")
        return websocket

    async def test_summary_and_chat_use_the_same_socket_without_sharing_results(self):
        alice, bob = await self.member("alice"), await self.member("bob")
        await alice.send_json({"type": "create_group", "name": "Team", "request_id": "create"})
        group_id = (await self.event(alice, "group_created"))["group_id"]
        await bob.send_json({"type": "join_group", "group_id": group_id, "request_id": "join"})
        await self.event(bob, "group_joined")
        await alice.send_json({"type": "group_message", "group_id": group_id,
                               "text": "hold-ai งานส่งวันศุกร์", "request_id": "send"})
        await self.event(alice, "sent")
        await alice.send_json({"type": "summarize_room", "room_type": "group", "room_id": group_id,
                               "request_id": "summary", "messages": [{"text": "forged"}]})
        await asyncio.to_thread(self.fixture.output.wait_for, "Summary provider started")
        await bob.send_json({"type": "group_message", "group_id": group_id, "text": "Chat while waiting", "request_id": "live"})
        await self.event(bob, "sent")
        self.fixture.release_path.touch()
        summary = await self.event(alice, "room_summary")
        self.assertEqual(summary["request_id"], "summary")
        self.assertEqual(summary["message_count"], 1)
        self.assertEqual(json.loads(summary["summary"])[0]["text"], "hold-ai งานส่งวันศุกร์")
        await bob.send_json({"type": "message", "to": "bob", "text": "probe"})
        observed = []
        async with asyncio.timeout(5):
            while True:
                event = await bob.receive_json()
                observed.append(event["type"])
                if event["type"] == "sent":
                    break
        self.assertNotIn("room_summary", observed)

    async def test_summary_errors_keep_websocket_connected(self):
        alice = await self.member("alice")
        await alice.send_json({"type": "create_group", "name": "Empty", "request_id": "create"})
        group_id = (await self.event(alice, "group_created"))["group_id"]
        await alice.send_json({"type": "summarize_room", "room_type": "group", "room_id": group_id, "request_id": "empty"})
        error = await self.event(alice, "error")
        self.assertEqual(error["request_id"], "empty")
        self.assertEqual(error["code"], "no_messages")
        await alice.send_json({"type": "group_message", "group_id": group_id, "text": "Still connected", "request_id": "send"})
        self.assertEqual((await self.event(alice, "sent"))["request_id"], "send")

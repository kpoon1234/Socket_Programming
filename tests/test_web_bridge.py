"""Exercise isolated browser sessions against the real TCP server."""

import asyncio
import signal
import socket
import unittest

try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    from asyncio import timeout as async_timeout
except ImportError:
    try:
        from async_timeout import timeout as async_timeout
    except ImportError:
        async_timeout = None

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
        async with async_timeout(5):
            while True:
                event = await websocket.receive_json()
                if event["type"] == event_type:
                    return event

    async def users(self, websocket, expected):
        async with async_timeout(5):
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

    async def test_group_creation_reaches_other_tabs_and_late_joiners_without_forged_members(self):
        alice = await self.registered("alice")
        self.assertEqual((await self.event(alice, "groups_updated"))["groups"], [])
        bob = await self.registered("bob")
        await self.event(bob, "groups_updated")
        await alice.send_json({"type": "create_group", "name": "กลุ่มเรียน", "request_id": "create",
                               "creator": "bob", "members": ["bob"]})
        created = await self.event(alice, "group_created")
        self.assertEqual(created["request_id"], "create")
        snapshot = await self.event(alice, "groups_updated")
        self.assertEqual(await self.event(bob, "groups_updated"), snapshot)
        self.assertEqual(snapshot["groups"], [{"group_id": created["group_id"], "name": "กลุ่มเรียน",
                                              "creator": "alice", "members": ["alice"]}])
        carol = await self.registered("carol")
        self.assertEqual(await self.event(carol, "groups_updated"), snapshot)

    async def test_leave_uses_self_identity_and_keeps_websocket_and_private_chat_alive(self):
        alice, bob = await self.registered("alice"), await self.registered("bob")
        await alice.send_json({"type": "create_group", "name": "Group", "request_id": "create"})
        group_id = (await self.event(alice, "group_created"))["group_id"]
        await bob.send_json({"type": "join_group", "group_id": group_id, "request_id": "join"})
        await self.event(bob, "group_joined")
        await bob.send_json({"type": "leave_group", "group_id": group_id, "request_id": "leave",
                             "name": "alice", "from": "alice", "members": []})
        left = await self.event(bob, "group_left")
        self.assertEqual(left["request_id"], "leave")
        self.assertFalse(left["deleted"])
        snapshot = await self.event(bob, "groups_updated")
        self.assertEqual(snapshot["version"], left["version"])
        self.assertEqual(snapshot["groups"][0]["members"], ["alice"])
        await bob.send_json({"type": "message", "to": "alice", "text": "Still here"})
        self.assertEqual((await self.event(alice, "private_message"))["text"], "Still here")
        await self.event(bob, "sent")
        await alice.send_json({"type": "leave_group", "group_id": group_id, "request_id": "last"})
        self.assertTrue((await self.event(alice, "group_left"))["deleted"])
        self.assertEqual((await self.event(bob, "groups_updated"))["groups"], [])

    async def test_leave_validation_errors_are_correlated_and_session_can_continue(self):
        websocket = await self.client.ws_connect("/ws")
        await websocket.send_json({"type": "leave_group", "group_id": "missing", "request_id": "early"})
        self.assertEqual((await self.event(websocket, "error"))["request_id"], "early")
        await websocket.send_json({"type": "connect", "host": "127.0.0.1", "port": self.fixture.port, "name": "alice"})
        await self.event(websocket, "registered")
        await websocket.send_json({"type": "leave_group", "group_id": "missing", "request_id": "invalid"})
        self.assertEqual((await self.event(websocket, "error"))["request_id"], "invalid")
        await websocket.send_json({"type": "create_group", "name": "Valid", "request_id": "valid"})
        self.assertEqual((await self.event(websocket, "group_created"))["request_id"], "valid")

    async def test_invalid_group_request_keeps_browser_connected_and_echoes_request_id(self):
        websocket = await self.client.ws_connect("/ws")
        await websocket.send_json({"type": "create_group", "name": "No login", "request_id": "early"})
        self.assertEqual((await self.event(websocket, "error"))["request_id"], "early")
        await websocket.send_json({"type": "connect", "host": "127.0.0.1", "port": self.fixture.port, "name": "alice"})
        await self.event(websocket, "registered")
        await self.event(websocket, "groups_updated")
        await websocket.send_json({"type": "create_group", "name": "  ", "request_id": "empty"})
        error = await self.event(websocket, "error")
        self.assertEqual(error["request_id"], "empty")
        self.assertIn("must not be empty", error["text"])
        await websocket.send_json({"type": "create_group", "name": "Valid", "request_id": "valid"})
        self.assertEqual((await self.event(websocket, "group_created"))["request_id"], "valid")
        self.assertEqual(len((await self.event(websocket, "groups_updated"))["groups"]), 1)

    async def test_join_group_broadcasts_self_membership_and_restores_it_on_reconnect(self):
        alice = await self.registered("alice")
        bob = await self.registered("bob")
        carol = await self.registered("carol")
        for websocket in (alice, bob, carol):
            await self.event(websocket, "groups_updated")
        await alice.send_json({"type": "create_group", "name": "Study group", "request_id": "create"})
        group_id = (await self.event(alice, "group_created"))["group_id"]
        for websocket in (alice, bob, carol):
            await self.event(websocket, "groups_updated")
        await bob.send_json({"type": "join_group", "group_id": group_id, "request_id": "join",
                             "name": "carol", "members": ["carol"]})
        self.assertEqual(await self.event(bob, "group_joined"),
                         {"type": "group_joined", "group_id": group_id, "request_id": "join"})
        snapshot = await self.event(bob, "groups_updated")
        self.assertEqual(snapshot["groups"][0]["members"], ["alice", "bob"])
        self.assertEqual(await self.event(alice, "groups_updated"), snapshot)
        self.assertEqual(await self.event(carol, "groups_updated"), snapshot)
        await bob.send_json({"type": "join_group", "group_id": group_id, "request_id": "repeat"})
        self.assertEqual((await self.event(bob, "group_joined"))["request_id"], "repeat")
        await bob.send_json({"type": "disconnect"})
        await self.event(bob, "disconnected")
        await self.users(alice, ["alice", "carol"])
        returning = await self.registered("bob")
        self.assertEqual(await self.event(returning, "groups_updated"), snapshot)

    async def test_invalid_join_echoes_request_id_and_keeps_browser_connected(self):
        websocket = await self.client.ws_connect("/ws")
        await websocket.send_json({"type": "join_group", "group_id": "missing", "request_id": "early"})
        self.assertEqual((await self.event(websocket, "error"))["request_id"], "early")
        await websocket.send_json({"type": "connect", "host": "127.0.0.1", "port": self.fixture.port, "name": "alice"})
        await self.event(websocket, "registered")
        await self.event(websocket, "groups_updated")
        await websocket.send_json({"type": "join_group", "group_id": "missing", "request_id": "missing"})
        error = await self.event(websocket, "error")
        self.assertEqual(error["request_id"], "missing")
        self.assertIn("does not exist", error["text"])
        await websocket.send_json({"type": "create_group", "name": "Valid", "request_id": "create"})
        self.assertEqual((await self.event(websocket, "group_created"))["request_id"], "create")

    async def test_group_messages_and_filtered_history_cross_the_bridge(self):
        alice = await self.registered("alice")
        bob = await self.registered("bob")
        carol = await self.registered("carol")
        await alice.send_json({"type": "create_group", "name": "Study group", "request_id": "create"})
        group_id = (await self.event(alice, "group_created"))["group_id"]
        await alice.send_json({"type": "group_message", "group_id": group_id, "text": "Before Bob",
                               "request_id": "before", "from": "bob", "visible_to": ["bob", "carol"]})
        before = await self.event(alice, "group_message")
        self.assertEqual(before["from"], "alice")
        self.assertNotIn("visible_to", before)
        await self.event(alice, "sent")
        await bob.send_json({"type": "join_group", "group_id": group_id, "request_id": "join"})
        await self.event(bob, "group_joined")
        await bob.send_json({"type": "open_group", "group_id": group_id, "request_id": "open"})
        self.assertEqual((await self.event(bob, "group_opened"))["messages"], [])
        await bob.send_json({"type": "group_message", "group_id": group_id, "text": "สวัสดี\nAfter joining", "request_id": "send"})
        own = await self.event(bob, "group_message")
        received = await self.event(alice, "group_message")
        self.assertEqual({key: value for key, value in own.items() if key != "request_id"}, received)
        self.assertEqual(own["request_id"], "send")
        self.assertEqual((await self.event(bob, "sent"))["message_id"], own["message_id"])
        await carol.send_json({"type": "open_group", "group_id": group_id, "request_id": "deny"})
        self.assertEqual((await self.event(carol, "error"))["request_id"], "deny")
        await bob.send_json({"type": "open_group", "group_id": group_id, "request_id": "history"})
        self.assertEqual((await self.event(bob, "group_opened"))["messages"], [received])

    async def test_group_validation_errors_keep_session_connected(self):
        websocket = await self.client.ws_connect("/ws")
        await websocket.send_json({"type": "group_message", "group_id": "missing", "text": "Early", "request_id": "early"})
        self.assertEqual((await self.event(websocket, "error"))["request_id"], "early")
        await websocket.send_json({"type": "connect", "host": "127.0.0.1", "port": self.fixture.port, "name": "alice"})
        await self.event(websocket, "registered")
        await websocket.send_json({"type": "create_group", "name": "Group", "request_id": "create"})
        group_id = (await self.event(websocket, "group_created"))["group_id"]
        for text in (None, " \n"):
            await websocket.send_json({"type": "group_message", "group_id": group_id, "text": text, "request_id": "invalid"})
            self.assertEqual((await self.event(websocket, "error"))["request_id"], "invalid")
        await websocket.send_json({"type": "group_message", "group_id": group_id, "text": "Still connected", "request_id": "valid"})
        self.assertEqual((await self.event(websocket, "group_message"))["text"], "Still connected")
        self.assertEqual((await self.event(websocket, "sent"))["request_id"], "valid")

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
        received = await self.event(bob, "private_message")
        self.assertEqual((received["from"], received["to"], received["text"]), ("alice", "bob", "Hello \u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35"))
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

    async def test_private_room_commands_echo_once_and_keep_rooms_separate(self):
        alice, bob, carol = await self.registered("alice"), await self.registered("bob"), await self.registered("carol")
        await alice.send_json({"type": "open_private", "to": "bob", "request_id": "open-bob"})
        room = await self.event(alice, "room_opened")
        self.assertEqual(room["request_id"], "open-bob")
        await alice.send_json({"type": "open_private", "to": "carol", "request_id": "open-carol"})
        other = await self.event(alice, "room_opened")
        self.assertNotEqual(room["room_id"], other["room_id"])
        await alice.send_json({"type": "private_message", "room_id": room["room_id"], "text": "Hello Bob", "request_id": "send-1", "from": "carol"})
        opened = await self.event(bob, "room_opened")
        self.assertEqual(opened["messages"], [])
        incoming = await self.event(bob, "private_message")
        own = await self.event(alice, "private_message")
        self.assertEqual(incoming["message_id"], own["message_id"])
        self.assertEqual(own["request_id"], "send-1")
        self.assertEqual(own["from"], "alice")
        self.assertEqual((await self.event(alice, "sent"))["message_id"], own["message_id"])
        await carol.send_json({"type": "open_private", "room_id": room["room_id"], "request_id": "forged"})
        denied = await self.event(carol, "error")
        self.assertEqual(denied["request_id"], "forged")
        self.assertIn("not available", denied["text"])
        await carol.send_json({"type": "open_private", "room_id": other["room_id"], "request_id": "own-room"})
        self.assertEqual((await self.event(carol, "room_opened"))["messages"], [])

    async def test_private_history_returns_after_websocket_reconnect(self):
        alice, bob = await self.registered("alice"), await self.registered("bob")
        await alice.send_json({"type": "open_private", "to": "bob", "request_id": "open"})
        room = await self.event(alice, "room_opened")
        await alice.send_json({"type": "private_message", "room_id": room["room_id"], "text": "Remember me", "request_id": "send"})
        await self.event(alice, "sent")
        await bob.close()
        await self.users(alice, ["alice"])
        bob = await self.registered("bob")
        restored = await self.event(bob, "private_rooms")
        self.assertEqual([item["room_id"] for item in restored["rooms"]], [room["room_id"]])
        await bob.send_json({"type": "open_private", "room_id": room["room_id"], "request_id": "history"})
        self.assertEqual([item["text"] for item in (await self.event(bob, "room_opened"))["messages"]], ["Remember me"])

    async def test_room_validation_error_keeps_session_connected(self):
        alice, bob = await self.registered("alice"), await self.registered("bob")
        await alice.send_json({"type": "open_private", "to": "bob", "request_id": "open"})
        room = await self.event(alice, "room_opened")
        await alice.send_json({"type": "private_message", "room_id": room["room_id"], "text": "   ", "request_id": "empty"})
        self.assertEqual((await self.event(alice, "error"))["request_id"], "empty")
        await alice.send_json({"type": "private_message", "room_id": room["room_id"], "text": "Valid", "request_id": "valid"})
        self.assertEqual((await self.event(bob, "private_message"))["text"], "Valid")
        self.assertEqual((await self.event(alice, "sent"))["request_id"], "valid")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Exercise a running Compose stack, then verify history after recreation.

Use a dedicated test project: this script creates chat users, a room and a group.
Run --write FILE first; recreate containers; then run --verify FILE.
"""

import argparse
import asyncio
from contextlib import AsyncExitStack
import json
from pathlib import Path
from uuid import uuid4

import aiohttp


async def event(websocket, kind):
    async with asyncio.timeout(10):
        while True:
            item = await websocket.receive_json()
            if item["type"] == "error":
                raise AssertionError(item["text"])
            if item["type"] == kind:
                return item


async def run(args):
    origin = args.origin or args.url.rstrip("/")
    async with AsyncExitStack() as stack:
        client = await stack.enter_async_context(aiohttp.ClientSession())
        for path in ("/", "/app.js", "/assets/styles.css", "/feature/E2EE/e2ee.js"):
            async with client.get(args.url + path) as response:
                assert response.status == 200, (path, response.status)
                assert await response.read(), path
        async with client.get(args.url + "/config") as response:
            assert await response.json() == {"fixed_server": True}
        try:
            websocket = await client.ws_connect(args.url + "/ws", origin="https://evil.example")
        except aiohttp.WSServerHandshakeError as error:
            assert error.status == 403
        else:
            await websocket.close()
            raise AssertionError("A foreign WebSocket origin was accepted")

        if args.write:
            suffix = uuid4().hex[:10]
            state = {"alice": "smoke-a-" + suffix, "bob": "smoke-b-" + suffix,
                     "text": "Deployment สวัสดี " + suffix}
        else:
            state = json.loads(args.verify.read_text())

        peers = []
        for name in (state["alice"], state["bob"]):
            websocket = await stack.enter_async_context(client.ws_connect(args.url + "/ws", origin=origin))
            # A forged destination must not override the bridge's fixed TCP target.
            await websocket.send_json({"type": "connect", "name": name, "host": "192.0.2.1", "port": 1})
            assert (await event(websocket, "registered"))["name"] == name
            peers.append(websocket)
        alice, bob = peers

        if args.write:
            await alice.send_json({"type": "open_private", "to": state["bob"], "request_id": "open"})
            state["room_id"] = (await event(alice, "room_opened"))["room_id"]
            await alice.send_json({"type": "private_message", "room_id": state["room_id"],
                                   "text": state["text"], "request_id": "private"})
            assert (await event(bob, "private_message"))["text"] == state["text"]
            await event(alice, "sent")
            await alice.send_json({"type": "create_group", "name": "Deployment smoke", "request_id": "create"})
            state["group_id"] = (await event(alice, "group_created"))["group_id"]
            await bob.send_json({"type": "join_group", "group_id": state["group_id"], "request_id": "join"})
            await event(bob, "group_joined")
            await bob.send_json({"type": "group_message", "group_id": state["group_id"],
                                 "text": state["text"], "request_id": "group"})
            assert (await event(alice, "group_message"))["text"] == state["text"]
            await event(bob, "sent")
            args.write.write_text(json.dumps(state, ensure_ascii=False))
            print("PASS: assets, origin rejection, fixed target, two users, private and group chat")
        else:
            await alice.send_json({"type": "open_private", "room_id": state["room_id"], "request_id": "history"})
            assert (await event(alice, "room_opened"))["messages"][-1]["text"] == state["text"]
            await bob.send_json({"type": "open_group", "group_id": state["group_id"], "request_id": "group-history"})
            assert (await event(bob, "group_opened"))["messages"][-1]["text"] == state["text"]
            print("PASS: private history, group membership and group history survive container recreation")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:3000")
    parser.add_argument("--origin", help="Public HTTPS origin when testing tunnel mode over local HTTP")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", type=Path)
    mode.add_argument("--verify", type=Path)
    asyncio.run(run(parser.parse_args()))

"""Serve the browser UI and relay each WebSocket to its own TCP client."""

import argparse
import asyncio
from contextlib import suppress
import json
from pathlib import Path
import queue

from aiohttp import WSMsgType, web

from client_network import NetworkClient

WEB_ROOT = Path(__file__).resolve().parent / "web"
SOCKETS = web.AppKey("sockets", set)


class BrowserSession:
    """Keep one browser tab isolated from every other tab."""

    def __init__(self, websocket):
        self.websocket = websocket
        self.network = None
        self.forward_task = None
        self.registered = False

    async def error(self, text, request_id=None):
        await self.websocket.send_json({"type": "error", "text": text, "request_id": request_id})

    async def handle_command(self, command):
        if not isinstance(command, dict):
            raise ValueError("A command must be a JSON object.")
        command_type = command.get("type")
        if command_type == "connect":
            if self.network is not None:
                raise ValueError("This tab already has a connection attempt.")
            host, port, name = command.get("host"), command.get("port"), command.get("name")
            if not isinstance(host, str) or not host.strip():
                raise ValueError("Enter a server address.")
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("Port must be an integer between 1 and 65535.")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Enter a name.")
            self.network = NetworkClient()
            self.network.connect(host.strip(), port, name.strip(), capabilities=["private_rooms", "groups", "group_messages"])
            self.forward_task = asyncio.create_task(self.forward_events())
        elif command_type == "disconnect":
            if self.network is not None:
                self.network.close()
            else:
                await self.websocket.close()
        elif command_type in ("message", "open_private", "private_message", "create_group", "join_group", "leave_group", "open_group", "group_message"):
            if not self.registered or self.network.stopped.is_set():
                raise ValueError("Register a name before sending messages.")
            # ส่งเฉพาะฟิลด์ของคำสั่ง โดยให้ Server เป็นผู้ตรวจสมาชิกและกำหนดผู้ส่งจริง
            fields = {
                "message": ("to", "text"),
                "open_private": ("to", "room_id", "request_id"),
                "private_message": ("room_id", "text", "request_id"),
                "create_group": ("name", "request_id"),
                "join_group": ("group_id", "request_id"),
                "leave_group": ("group_id", "request_id"),
                "open_group": ("group_id", "request_id"),
                "group_message": ("group_id", "text", "request_id"),
            }[command_type]
            self.network.send({"type": command_type, **{key: command[key] for key in fields if key in command}})
        else:
            raise ValueError("Unknown browser command.")

    async def forward_events(self):
        try:
            while not self.websocket.closed:
                # อ่านคิวโดยไม่รอ เพื่อให้ event loop ดูแลแท็บอื่นต่อได้
                for _ in range(100):
                    try:
                        event = self.network.events.get_nowait()
                    except queue.Empty:
                        break
                    if event["type"] == "registered":
                        self.registered = True
                    await self.websocket.send_json(event)
                    if event["type"] == "error" and not self.registered:
                        self.network.close(reason=f"Error: {event['text']}")
                    if event["type"] == "disconnected":
                        await self.websocket.close()
                        return
                await asyncio.sleep(0.02)
        except (ConnectionError, RuntimeError):
            await self.websocket.close()

    async def close(self):
        if self.network is not None:
            self.network.close()
        if self.forward_task is not None:
            self.forward_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.forward_task
        if self.network is not None:
            # การรอ thread จบไม่ขวาง event loop ของแท็บอื่น
            await asyncio.to_thread(self.network.wait_closed)


async def websocket_handler(request):
    origin = request.headers.get("Origin")
    if origin is not None and origin != f"{request.scheme}://{request.host}":
        raise web.HTTPForbidden(text="Open the client from this bridge's own URL.")
    websocket = web.WebSocketResponse(heartbeat=20, max_msg_size=1024 * 1024)
    await websocket.prepare(request)
    request.app[SOCKETS].add(websocket)
    session = BrowserSession(websocket)
    try:
        async for message in websocket:
            if message.type == WSMsgType.TEXT:
                command = None
                try:
                    command = json.loads(message.data)
                    await session.handle_command(command)
                except (ValueError, ConnectionError) as error:
                    await session.error(str(error), command.get("request_id") if isinstance(command, dict) else None)
            elif message.type == WSMsgType.BINARY:
                await session.error("Use JSON text commands.")
    finally:
        await session.close()
        request.app[SOCKETS].discard(websocket)
    return websocket


async def index_handler(request):
    return web.FileResponse(WEB_ROOT / "index.html", headers={"Cache-Control": "no-store"})


async def javascript_handler(request):
    return web.FileResponse(WEB_ROOT / "app.js", headers={"Cache-Control": "no-store"})


async def shutdown(app):
    await asyncio.gather(*(socket.close(code=1001, message=b"Bridge shutting down") for socket in list(app[SOCKETS])))


def create_app():
    app = web.Application()
    app[SOCKETS] = set()
    app.router.add_get("/", index_handler)
    app.router.add_get("/app.js", javascript_handler)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_static("/assets/", WEB_ROOT / "assets")
    app.on_shutdown.append(shutdown)
    return app


def main():
    parser = argparse.ArgumentParser(description="Run the local Socket Chat web client.")
    parser.add_argument("--port", type=int, default=3000, help="Local web port (default: 3000)")
    args = parser.parse_args()
    if not (WEB_ROOT / "assets" / "styles.css").exists():
        parser.error("Build the Tailwind stylesheet first: npm install && npm run build:css")
    web.run_app(create_app(), host="127.0.0.1", port=args.port, shutdown_timeout=5)


if __name__ == "__main__":
    main()

"""Serve the browser UI and relay each WebSocket to its own TCP client."""

import argparse
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import queue
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web

from client_network import NetworkClient

WEB_ROOT = Path(__file__).resolve().parent / "web"
PROJECT_ROOT = Path(__file__).resolve().parent
SOCKETS = web.AppKey("sockets", set)
PUBLIC_ORIGIN = web.AppKey("public_origin", str)
TCP_TARGET = web.AppKey("tcp_target", tuple)


class BrowserSession:
    """Keep one browser tab isolated from every other tab."""

    def __init__(self, websocket, tcp_target=None):
        self.websocket = websocket
        self.tcp_target = tcp_target
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
            # โหมดเว็บส่วนกลางใช้ปลายทางที่ผู้ดูแลกำหนด ไม่รับปลายทางจาก Browser
            host, port = self.tcp_target or (command.get("host"), command.get("port"))
            name = command.get("name")
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
        elif command_type in ("message", "open_private", "private_message", "create_group", "join_group", "leave_group", "open_group", "group_message", "summarize_room", "unsend_message"):
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
                "summarize_room": ("room_type", "room_id", "request_id"),
                "unsend_message": ("room_type", "room_id", "group_id", "message_id", "request_id"),
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
    public_origin = request.app.get(PUBLIC_ORIGIN)
    # HTTPS สิ้นสุดที่ Tunnel แล้วส่ง HTTP เข้า bridge จึงระบุ origin ภายนอกโดยตรง
    # ไม่เชื่อ Forwarded headers ที่ผู้เรียกสามารถปลอมมาเองได้
    allowed_origin = public_origin or f"{request.scheme}://{request.host}"
    if (public_origin is not None or origin is not None) and origin != allowed_origin:
        raise web.HTTPForbidden(text="Open the client from this bridge's own URL.")
    websocket = web.WebSocketResponse(heartbeat=20, max_msg_size=1024 * 1024)
    await websocket.prepare(request)
    request.app[SOCKETS].add(websocket)
    session = BrowserSession(websocket, request.app.get(TCP_TARGET))
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


async def e2ee_javascript_handler(request):
    e2ee_path = PROJECT_ROOT / "feature" / "E2EE" / "e2ee.js"
    return web.FileResponse(e2ee_path, headers={"Cache-Control": "no-store"})


async def config_handler(request):
    # หน้าเว็บต้องรู้เพียงโหมด ไม่ต้องได้รับ host/port ภายในหรือค่าลับ
    return web.json_response({"fixed_server": TCP_TARGET in request.app},
                             headers={"Cache-Control": "no-store"})


async def shutdown(app):
    await asyncio.gather(*(socket.close(code=1001, message=b"Bridge shutting down") for socket in list(app[SOCKETS])))


def create_app(*, public_origin=None, tcp_host=None, tcp_port=5000):
    if public_origin is not None:
        parsed = urlsplit(public_origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("Public origin must be HTTPS without a path, for example https://chat.andyntk.online")
        parsed.port  # ปฏิเสธค่าพอร์ตที่ผิดรูปแบบด้วย
        if not tcp_host:
            raise ValueError("Public mode requires a fixed TCP host.")
    if tcp_host is not None and (not isinstance(tcp_host, str) or not tcp_host.strip()):
        raise ValueError("TCP host must not be empty.")
    if type(tcp_port) is not int or not 1 <= tcp_port <= 65535:
        raise ValueError("TCP port must be between 1 and 65535.")
    app = web.Application()
    app[SOCKETS] = set()
    if public_origin is not None:
        app[PUBLIC_ORIGIN] = public_origin
    if tcp_host is not None:
        app[TCP_TARGET] = (tcp_host.strip(), tcp_port)
    app.router.add_get("/", index_handler)
    app.router.add_get("/config", config_handler)
    app.router.add_get("/app.js", javascript_handler)
    app.router.add_get("/e2ee.js", e2ee_javascript_handler)
    app.router.add_get("/feature/E2EE/e2ee.js", e2ee_javascript_handler)
    app.router.add_get("/assets/e2ee.js", e2ee_javascript_handler)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_static("/assets/", WEB_ROOT / "assets")
    app.on_shutdown.append(shutdown)
    return app


def main():
    parser = argparse.ArgumentParser(description="Run the Socket Chat web bridge.")
    parser.add_argument("--host", default="127.0.0.1", help="Web bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=3000, help="Local web port (default: 3000)")
    parser.add_argument("--public-origin", default=os.environ.get("CHAT_PUBLIC_ORIGIN") or None,
                        help="Allowed HTTPS origin behind a tunnel; also CHAT_PUBLIC_ORIGIN")
    parser.add_argument("--tcp-host", help="Fixed TCP server; users only enter a name")
    parser.add_argument("--tcp-port", type=int, default=5000, help="Fixed TCP port (default: 5000)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Web port must be between 1 and 65535.")
    if not (WEB_ROOT / "assets" / "styles.css").exists():
        parser.error("Build the Tailwind stylesheet first: npm install && npm run build:css")
    try:
        app = create_app(public_origin=args.public_origin, tcp_host=args.tcp_host, tcp_port=args.tcp_port)
    except ValueError as error:
        parser.error(str(error))
    web.run_app(app, host=args.host, port=args.port, shutdown_timeout=5)


if __name__ == "__main__":
    main()

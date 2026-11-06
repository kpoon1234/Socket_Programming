# โค้ด deployment สำหรับพรีเซนต์ประมาณ 2 หน้า

## หน้า 1 — จากโค้ดเดิมเป็นสอง services

พูดเปิด: “งานนี้เพิ่มวิธีติดตั้งแชตให้เหมือนกันทั้งเครื่องเราและ Ubuntu
โดยคง Python TCP server และ protocol เดิมไว้ Browser ติดต่อ Python web bridge
แล้ว bridge เปิด TCP connection แยกให้แต่ละแท็บ”

```text
Browser ── HTTP/WS local หรือ HTTPS/WSS ผ่าน Cloudflare Tunnel เดิม
    └── web:3000 ── TCP ภายใน Docker network ── server:5000
                                                   ├── Groq (API key)
                                                   └── chat-data volume (JSON)
```

**1. Dockerfile: แยกเครื่องมือ build ออกจาก runtime**

```dockerfile
FROM node:22-bookworm-slim AS styles
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY web ./web
RUN npm run build:css

FROM python:3.12-slim-bookworm AS runtime
# ติดตั้ง Python dependencies และคัดลอก source ตามไฟล์จริง
COPY --from=styles /build/web/assets/styles.css ./web/assets/styles.css
USER chat
```

เลือกอธิบายบรรทัด `COPY --from=styles`: เอาเฉพาะ CSS ที่ build เสร็จมาใส่ Python image
จึงไม่ต้องมี Node/npm ใน runtime ส่วน `npm ci` ใช้ dependency ตาม lockfile
ทั้ง web/server ใช้ image เดียวกันแต่รันคนละ command และรันด้วย user ธรรมดา UID 10001
`.dockerignore` กัน `.env*`, node_modules และประวัติบนเครื่องไม่ให้เข้า build context

**2. Compose: ปลายทางเครือข่ายและข้อมูลถาวร**

```yaml
# excerpt จาก compose.yaml; ทั้งสอง services อยู่ network chat
server:
  environment:
    CHAT_STATE_PATH: /data/chat_state.json
    GROQ_API_KEY: ${GROQ_API_KEY:-}
  volumes:
    - chat-data:/data
web:
  command: ["python", "-u", "web_bridge.py", "--host", "0.0.0.0", "--tcp-host", "server"]
  ports:
    - "127.0.0.1:${CHAT_WEB_PORT:-3000}:3000"
```

`server` คือชื่อ service ที่ Docker DNS หาให้ ไม่ใช่ IP ของผู้ใช้หรือ Ubuntu
พอร์ต 5000 ไม่ publish ออก host; web ต้อง bind `0.0.0.0` ภายใน container เพื่อรับการเชื่อมต่อ
แต่พอร์ต host เปิดเฉพาะ loopback ส่วน volume อยู่แยกจาก container จึง recreate แล้วประวัติยังอยู่
API key เข้าผ่าน environment ของ server ตอนรัน ไม่มี key อยู่ใน Dockerfile หรือ frontend

ถาม: “ทำไมไม่ใช้ localhost:5000 ใน bridge?” ตอบ: “localhost ภายใน web container
คือตัว web เอง ต้องใช้ server:5000 เพื่อไป container อีกตัว”

## หน้า 2 — ผู้ใช้กรอกชื่อ และ HTTPS ใช้ WebSocket ได้

**3. Bridge กำหนด TCP server จริง ไม่อาศัยการซ่อนช่องบนหน้าเว็บ**

```python
# BrowserSession.handle_command ใน web_bridge.py
host, port = self.tcp_target or (command.get("host"), command.get("port"))
name = command.get("name")
```

เมื่อ Docker ส่ง `--tcp-host server` ค่า `tcp_target` จะเป็น `("server", 5000)`
แม้ผู้ใช้แก้ JSON ใส่ host/port อื่น bridge ก็ใช้ค่าของผู้ดูแล
ถ้ารัน local แบบเดิมโดยไม่กำหนด tcp host จะใช้ค่าจากหน้าเว็บเหมือนเดิม
`GET /config` บอกเพียง `{"fixed_server": true}` ให้ JavaScript ซ่อน/disable host และ port
แล้วส่ง `{type: "connect", name}` โดยไม่ส่ง host ภายในหรือ secret ให้ Browser

**4. Origin ต้องเป็นโดเมนที่ Browser เปิดจริง**

```python
# websocket_handler ใน web_bridge.py (ย่อเฉพาะส่วนตรวจ Origin)
origin = request.headers.get("Origin")
public_origin = request.app.get(PUBLIC_ORIGIN)
allowed_origin = public_origin or f"{request.scheme}://{request.host}"
if (public_origin is not None or origin is not None) and origin != allowed_origin:
    raise web.HTTPForbidden(text="Open the client from this bridge's own URL.")
```

Cloudflare รับ HTTPS/WSS จาก Browser แล้วส่ง HTTP เข้า web ใน network ของ Ubuntu
จึงเทียบกับ scheme ภายในอย่างเดียวไม่ได้ ตั้ง `CHAT_PUBLIC_ORIGIN=https://chat.example.com`
เพื่อยอมรับ origin ภายนอกตรงตัว ในโหมด public จะปฏิเสธทั้ง origin หายและโดเมนอื่น
โดยไม่เชื่อ forwarded headers ที่ผู้เรียกอาจปลอม ส่วน frontend เลือก `wss` เมื่อหน้าเว็บเป็น HTTPS อยู่แล้ว

Cloudflared ที่รันบน host ชี้ `http://localhost:3000`; ถ้ารันใน bridge container
ให้ใช้ external network ร่วมกับ web และชี้ `http://socket-chat-web:3000`
Tunnel เดิมยังใช้ token/config เดิม เพิ่มเพียง route ของโดเมนและการต่อ network ตามกรณี

**คำถามที่ควรตอบได้**

| คำถาม | คำตอบสั้น |
| --- | --- |
| WebSocket แทน TCP server หรือไม่? | ไม่แทน: Browser ใช้ WS กับ bridge; bridge ใช้ TCP กับ server |
| Origin คือการล็อกอินหรือไม่? | ไม่ใช่ ตรวจแหล่งหน้าเว็บ; แอปยังใช้ชื่อเป็นตัวตนตามเดิม |
| ลบ container แล้วประวัติหายไหม? | recreate/down เก็บ named volume; `down -v` ลบข้อมูลด้วย |
| Tunnel เข้าถึง server:5000 โดยตรงไหม? | ใน config นี้ Tunnel ติดต่อ web; server อยู่เฉพาะ network chat |
| จะรัน server หลายตัวได้ไหม? | รุ่นนี้หนึ่งตัว เพราะ state JSON และ online users อยู่ใน process เดียว |
| ยืนยันว่าของเดิมยังใช้ได้อย่างไร? | regression tests และโหมด local ที่ไม่กำหนด tcp host; smoke แชต/กลุ่มและตรวจประวัติหลัง recreate |

ลำดับเดโม: `docker compose up -d --build --wait` → เปิด localhost:3000 สองแท็บ
→ กรอกชื่อและส่งข้อความ → recreate services → Connect ใหม่แล้วเปิดประวัติ
รายละเอียดผลที่ทดสอบจริงและส่วนที่ยังต้องตรวจบน Ubuntu อยู่ใน [สรุป PR](deployment-pr.md)

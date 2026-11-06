# Docker deployment

Node build Tailwind ครั้งเดียวใน build stage; runtime ใช้ Python ทั้งสอง services:
`Browser → web:3000 (HTTP/WebSocket) → server:5000 (TCP) → chat-data volume`.
มี TCP server หนึ่ง instance ตามรูปแบบ state JSON และรายชื่อออนไลน์เดิม

## ทดลอง localhost

ต้องมี Docker Engine/Desktop ที่เปิดอยู่ และ Docker Compose v2+ รันจาก root:

```bash
docker compose up -d --build --wait
docker compose ps
```

เปิด **http://localhost:3000** สองแท็บ กรอกเพียงชื่อคนละชื่อ ลองแชตส่วนตัว,
Secret Chat ด้วย PIN เดียวกัน, สร้างกลุ่ม/Join/Leave และ Summarize หากตั้ง key แล้ว
ไม่ตั้ง `CHAT_PUBLIC_ORIGIN` ในการทดลอง HTTP บนเครื่อง
ถ้าพอร์ตชน ให้ตั้ง `CHAT_WEB_PORT=3001` แล้วเปิดพอร์ตนั้น

Compose อ่าน `.env` เดิมได้ แต่ส่ง `GROQ_API_KEY`/`GROQ_MODEL` ให้เฉพาะ `server`.
ไม่ตั้ง key ยังแชตได้ ส่วน Summarize จะแจ้งว่ายังไม่ได้ตั้งค่า AI
`.dockerignore` กัน `.env*` และประวัติออกจาก build context; ไม่ส่ง secret ผ่าน build argument

```bash
docker compose logs --tail=100
docker compose restart server
docker compose down              # เก็บประวัติไว้; อย่าเติม -v
```

ประวัติอยู่ใน `socket-chat_chat-data` ที่ `/data/chat_state.json` ไม่ปนกับ
`output/chat_state.json` เดิม เปลี่ยน project name จะได้ volume อีกชุด
build/recreate container ไม่ลบประวัติ ผู้ใช้กด Connect ใหม่หลัง server restart

## Ubuntu + Cloudflare Tunnel เดิม

ติดตั้ง [Docker Engine และ Compose plugin บน Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
แล้วนำ source branch/commit นี้ขึ้นเครื่อง ไม่ต้องลง Node/Python บน host

```bash
cp feature/deployment/.env.example .env.deploy
chmod 600 .env.deploy
nano .env.deploy
```

เปลี่ยน `CHAT_PUBLIC_ORIGIN=https://chat.example.com` ให้เป็นโดเมน HTTPS จริง
ไม่มี path หรือ `/` ท้าย และใส่ Groq key ถ้าต้องการ ห้าม commit ไฟล์จริง
หากมี `.env.deploy` แล้ว ให้แก้ไฟล์เดิม ไม่คัดลอกตัวอย่างทับ

เลือกตามตำแหน่งที่ Tunnel เดิมรัน:

| Tunnel เดิม | ปลายทาง route แบบ HTTP | วิธีเปิดแอป |
| --- | --- | --- |
| รันบน Ubuntu host หรือ container แบบ host network | `localhost:3000` | ใช้ `compose.yaml` |
| รันเป็น container แบบ bridge network | `socket-chat-web:3000` | เพิ่ม `compose.tunnel.yaml` |

กรณีรันบน host:

```bash
docker compose --env-file .env.deploy up -d --build --wait
```

กรณี container แบบ bridge: ใช้ external network ร่วมกันระหว่าง web กับ Tunnel
สร้างครั้งแรกด้วย `docker network create socket-chat-tunnel` หรือกำหนด `TUNNEL_NETWORK`
เป็นชื่อ network ที่มีอยู่แล้ว รวม networks ตาม
[ตัวอย่าง](tunnel-network.example.yaml) เข้า Stack เดิมของ Tunnel และ redeploy Stack นั้น
เก็บ token/config/volume เดิมไว้ จากนั้นเปิดแอป:

```bash
docker compose --env-file .env.deploy -f compose.yaml -f compose.tunnel.yaml up -d --build --wait
```

ใน Cloudflare Dashboard ของ Tunnel เดิม เพิ่ม Published application route
สำหรับโดเมนเดียวกับ `CHAT_PUBLIC_ORIGIN`, เลือก HTTP และปลายทางตามตาราง
เว้น Path เพื่อให้ route ครอบคลุม `/ws`, `/config`, assets และ E2EE
ถ้าเป็น locally managed Tunnel ให้เพิ่ม ingress hostname/service คู่เดียวกันก่อน catch-all เดิม
container แบบ bridge ใช้ `localhost` ถึง web ไม่ได้ เพราะหมายถึงตัว container Tunnel เอง

web ผูก host port เฉพาะ `127.0.0.1:3000`; server ไม่มี published port
จึงไม่ต้องเปิดพอร์ต 5000 หรือ router port forwarding ส่วน server ยังออก Internet เรียก Groq ได้
ตั้ง WebSockets ของ zone ให้เปิด และ bypass cache ถ้ามีกฎ Cache Everything ครอบคลุมแอป
เมื่อกำหนด public origin แล้ว การเชื่อม WebSocket ผ่าน localhost จะถูกปฏิเสธตามตั้งใจ
ให้ใช้งานผ่านโดเมน HTTPS; ไม่ตั้งค่าเชื่อ `X-Forwarded-*` จากผู้เรียก

ตรวจรับ: เปิด HTTPS จากสองเครื่อง (อีกเครื่องลอง hotspot), แชต/Secret Chat/กลุ่ม/Summarize,
recreate containers และ reconnect ตรวจประวัติ จากนั้นตรวจอีกครั้งหลัง reboot Ubuntu
ระบบเดิมใช้ชื่อเป็นตัวตน ไม่มีรหัสผ่าน จึงควรจำกัดผู้ใช้ด้วย Cloudflare Access หากใช้ข้อมูลจริง

อ้างอิง: [Compose networks](https://docs.docker.com/compose/how-tos/networking/),
[Tunnel routes](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/),
[WebSockets](https://developers.cloudflare.com/network/websockets/)

## ดูแลข้อมูลและแก้ปัญหา

ใช้คำสั่ง Compose ชุดเดิมรวม `--env-file` และ `-f` ทุกครั้งที่ติดตั้งแบบ Tunnel
อัปเดต/rollback source แล้วรัน `up -d --build --wait`; เก็บ volume เดิมและใช้รุ่นที่อ่าน schema เดิมได้
ก่อนสำรอง ให้ `stop web server` แล้วอ่านไฟล์ผ่าน service server ที่ mount volume:

```bash
umask 077
docker compose --env-file .env.deploy run --rm --no-deps -T server \
  python -c 'from pathlib import Path; print(Path("/data/chat_state.json").read_text(), end="")' \
  > "chat_state.backup.$(date +%Y%m%d-%H%M%S).json"
```

ตรวจ exit status และ JSON ก่อนนำไปใช้ แล้ว `up -d --wait` ด้วยชุดคำสั่งเดิม
หากย้ายข้อมูล local เดิม ให้หยุด server ทั้งต้นทาง/ปลายทาง สำรองก่อนนำเข้า
และให้ UID/GID `10001:10001` อ่านเขียนไฟล์ได้ ไม่มีการย้ายข้อมูลอัตโนมัติ

| อาการ | ตรวจ |
| --- | --- |
| 502 | web healthy, network Tunnel และปลายทาง route |
| `/ws` ได้ 403 | origin ต้องตรงโดเมน HTTPS รวม port; แก้ env แล้ว `up -d` |
| Connection error | server healthy และ bridge ใช้ `server:5000` |
| Summarize ใช้ไม่ได้ | key/model ใน server; ตรวจ logs โดยไม่เผยค่า key |

โหมด local/LAN ยังรัน Python/Tailwind ตาม README หลักและกรอก host/port ได้เหมือนเดิม
bridge ยัง bind `127.0.0.1` โดย default; ใช้ `--host 0.0.0.0` เฉพาะเมื่อต้องการเปิด bridge ให้ LAN

## ทดสอบซ้ำ

```bash
.venv/bin/python -m unittest discover -s tests -v
npm run check:js
npm run build:css
```

สำหรับ smoke test ใช้ Compose project ทดสอบที่พอร์ต 3000 ว่างอยู่ (สร้างข้อมูลทดลอง):

```bash
docker compose -p socket-chat-deployment-test --env-file /dev/null up -d --build --wait
.venv/bin/python tests/smoke_deployment.py --write /tmp/chat-smoke.json
docker compose -p socket-chat-deployment-test --env-file /dev/null up -d --force-recreate --wait
.venv/bin/python tests/smoke_deployment.py --verify /tmp/chat-smoke.json
docker compose -p socket-chat-deployment-test --env-file /dev/null down
```

`--env-file /dev/null` ไม่อ่าน `.env` แต่ environment ใน shell ยังมีผล
smoke test ตรวจ HTTP/WebSocket, Unsend ส่วนตัว/กลุ่ม และ persistence หลัง recreate;
ยังต้องลอง UI/Secret Chat บน Browser จริง

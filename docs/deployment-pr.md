# สรุป deployment สำหรับเปิด PR

Branch: `feature/deployment` สร้างจาก `origin/main` ที่ `9f71189` หลัง fetch
รวม `origin/main` ที่ `64b8aa8` ซึ่ง merge PR #9 (Unsend) แล้ว และทดสอบร่วมกับ deployment ก่อน merge PR #10

ชื่อ PR ที่แนะนำ: `feat: add Docker deployment for chat through existing Cloudflare Tunnel`

## พฤติกรรมที่ได้

เปิดเว็บด้วย `docker compose up -d --build --wait` แล้วเข้า `http://localhost:3000`
ผู้ใช้กรอกเพียงชื่อ bridge เลือก TCP server จากค่าฝั่งผู้ดูแล
ติดตั้งบน Ubuntu ผ่าน Tunnel เดิมได้ทั้งแบบรัน cloudflared บน host และแบบ container
กำหนด HTTPS origin ชัดเจนเพื่อให้ WebSocket ผ่าน Tunnel ได้

Node ใช้ build Tailwind ส่วน runtime เป็น Python สอง services
server เก็บประวัติใน named volume และได้รับ Groq key ผ่าน environment เท่านั้น
โหมดรัน local/LAN เดิมยังใช้ host/port จากหน้าเว็บ ไม่มีการเปลี่ยน TCP protocol หรือ schema ประวัติ

## Diff: เพิ่มหรือแก้ไฟล์อะไร เพราะอะไร

| ไฟล์ | การเปลี่ยนและเหตุผล |
| --- | --- |
| `Dockerfile` | เพิ่ม multi-stage Node → Python; build CSS, คัดลอก source ที่ต้องใช้, user ธรรมดา และเตรียม `/data` ให้เขียน volume ได้ |
| `.dockerignore` | เพิ่มการตัด `.env*`, ประวัติ, Git, dependencies local และไฟล์ที่ runtime ไม่ใช้ ออกจาก build context |
| `compose.yaml` | เพิ่ม web:3000 กับ server:5000, network, volume, environment เฉพาะ service, healthchecks และ restart policy; ไม่ publish TCP port |
| `compose.tunnel.yaml` | เพิ่ม overlay ต่อ web เข้า external network ของ Tunnel และ alias `socket-chat-web`; บังคับตั้ง public origin |
| `web_bridge.py` | เพิ่ม fixed TCP target, `/config`, CLI bind/target/origin และตรวจ HTTPS Origin โดยไม่เชื่อ forwarded headers; defaults เดิมยังใช้ได้ |
| `web/app.js` | อ่าน config ก่อน Connect, ซ่อน/disable host/port ใน fixed mode และส่งเพียงชื่อ; ใช้ข้อความสถานะที่เหมาะกับเว็บผ่าน Tunnel |
| `web/index.html` | เพิ่ม ID ให้ wrapper ของ host/port เพื่อสลับฟอร์มตามโหมด |
| `tests/test_hosted_bridge.py` | เพิ่ม 8 tests ครอบคลุม fixed target ที่ปลอมไม่ได้, private/group chat, Unsend/สิทธิ์เจ้าของข้อความ, history, HTTPS Origin, config validation, E2EE assets และโหมด local |
| `tests/test_web_bridge.py` | เผื่อเวลารอเฉพาะกรณี connect ไม่สำเร็จให้มากกว่า TCP timeout 5 วินาที ป้องกันเทสต์แข่งกับ timeout จริง |
| `tests/smoke_deployment.py` | เพิ่ม smoke test สำหรับ stack ที่รันจริง ตรวจ assets/Origin, สองผู้ใช้, private/group chat, Unsend และตรวจประวัติ/สถานะ Unsend หลัง recreate |
| `feature/deployment/.env.example` | เพิ่มตัวอย่างค่าติดตั้ง ไม่มี key จริง |
| `feature/deployment/tunnel-network.example.yaml` | เพิ่มตัวอย่างเฉพาะส่วน network ที่ต้องรวมใน Stack Tunnel เดิม |
| `feature/deployment/README.md` | เพิ่มคู่มือ localhost/Ubuntu/Tunnel, volume, backup, troubleshooting และคำสั่งทดสอบ |
| `docs/deployment-presentation.md` | เลือกโค้ดสำคัญประมาณ 2 หน้า พร้อมคำอธิบาย flow และคำถาม/คำตอบ |
| `docs/deployment-pr.md` | สรุป scope, diff, ผลทดสอบ และขั้นตอนรับงาน unsent สำหรับ reviewer |
| `README.md` | เพิ่มทางเข้าคู่มือ deployment และเอกสารพรีเซนต์ |

## ผลทดสอบจริง

ตรวจบน macOS ด้วย Docker Desktop/Engine `29.9.2`, Compose `v5.6.1`:

- `.venv/bin/python -m unittest discover -s tests -v`: ผ่าน 126 tests หลังรวม Unsend จาก main
- `npm run check:js`, `npm run build:css`, `git diff --check`: ผ่าน
- Docker build สำเร็จ; web/server healthy; มี host binding เฉพาะ `127.0.0.1:3000` ไม่มี TCP port ของ server ออก host
- smoke ที่ `http://localhost:3000`: assets รวม CSS/E2EE โหลดได้, Origin ต่างเว็บถูกปฏิเสธ, host/port ปลอมเปลี่ยน TCP target ไม่ได้, สองผู้ใช้ส่งและ Unsend private/group chat ได้
- `up -d --force-recreate --wait` แล้วตรวจซ้ำ: ห้องส่วนตัว สมาชิกกลุ่ม ประวัติทั้งสองแบบ และสถานะ Unsend ยังอยู่
- ตรวจ runtime: UID 10001, ไม่มี Node, ไม่มีไฟล์ `.env*`/ประวัติ local ใน `/app`; web ไม่มี Groq environment; server เขียน `/data/chat_state.json` ได้
- ทดลอง overlay กับ external network ชั่วคราวและ client container แทนตำแหน่ง cloudflared: alias `socket-chat-web:3000` ใช้ HTTP และ WebSocket ที่ส่ง HTTPS Origin ได้; server ไม่อยู่ใน DNS ของ network Tunnel
- public mode ปฏิเสธ Origin หาย/localhost; เปลี่ยนกลับ local mode แล้ว services healthy และเก็บ volume เดิม

ขอบเขตที่ยังต้องตรวจ: Browser automation ถูกปิดใน Work settings จึงยังไม่ได้กด UI/Secret Chat
ผ่าน Browser จริง; เทสต์ยืนยัน E2EE asset และการส่งต่อข้อความ แต่ไม่ได้พิสูจน์การเข้ารหัสใน Browser
ยังไม่ได้ติดตั้งบน Ubuntu จริงหรือแก้ route ใน Cloudflare บัญชีจริง และไม่ได้เรียก Groq ด้วย key จริง
ให้ตรวจรับตามคู่มือบนเครื่องปลายทางก่อนใช้งานจริง

## การรวม Unsend จาก PR #9

รับ `origin/main` หลัง PR #9 merge แล้ว พบ conflict 1 จุดใน `tests/test_web_bridge.py`
แก้ helper เป็น `event(..., timeout=5)` ที่ใช้ `async_timeout(timeout)` เพื่อเก็บทั้ง compatibility ของปั้นและเวลารอ connection error ของ deployment
`web/app.js`, `web/index.html` และ `web_bridge.py` รวมได้อัตโนมัติ

เพิ่ม integration test ยืนยัน Unsend ทั้ง private/group ผ่าน fixed-target HTTPS-Origin bridge,
ปฏิเสธการปลอมผู้ส่งเพื่อยกเลิกข้อความคนอื่น และอ่านประวัติที่มีสถานะ Unsend ได้
ขยาย Docker smoke test ให้ตรวจสถานะ Unsend หลัง recreate ด้วย
ส่วน UI บน Browser จริงและการติดตั้ง Ubuntu ยังตรวจรับตามคู่มือก่อนใช้งานจริง

# Protocol and Data Contracts

เอกสารนี้อธิบายข้อมูลที่ใช้ใน Part 2 ขั้นที่ 1–2 และโครงสร้างสำหรับต่อยอด โดยแยกส่วนที่เขียนแล้วออกจากแผนสำหรับขั้นถัดไป

## รูปแบบบนเครือข่าย

- ใช้ TCP Socket และ UTF-8
- แต่ละข้อความเป็น JSON object จบด้วยไบต์ขึ้นบรรทัดใหม่หนึ่งตัว
- `protocol.py` แยกข้อความโดยใช้ buffer ก่อนแปลง UTF-8 และ JSON

## คำสั่งที่ใช้แล้ว

Client ส่งชื่อหลังเชื่อมต่อ:

```json
{"type": "register", "name": "alice"}
```

Server ตอบ `registered` เป็นคำตอบแรกของการลงชื่อสำเร็จ ก่อนเหตุการณ์รายชื่อหรือข้อความเข้า:

```json
{"type": "registered", "name": "alice"}
```

หากชื่อซ้ำ ชื่อว่าง หรือชื่อสงวน จะตอบ `error` เช่น:

```json
{"type": "error", "text": "Name is already in use. Choose another name."}
```

Terminal client ลองชื่อใหม่ผ่าน Socket เดิมได้ ส่วนเว็บและ Tkinter ปิดการเชื่อมต่อที่ลงชื่อไม่สำเร็จ แล้วให้แก้ชื่อและกด Connect ใหม่ งานเครือข่ายแต่ละครั้งมีคิวและ thread ของตัวเองเพื่อไม่ให้เหตุการณ์จากรอบเก่าปนกับรอบใหม่

เมื่อรายชื่อเปลี่ยน Server ส่งภาพรวมรายชื่อทั้งหมดให้ผู้ใช้ที่ลงชื่อแล้วทุกคน รวมคนที่เพิ่งเข้า:

```json
{"type": "users_updated", "version": 2, "users": ["alice", "bob"]}
```

- `users` คือรายชื่อที่เชื่อมต่อและลงทะเบียนสำเร็จอยู่จริง เรียงตามชื่อและรวมชื่อผู้รับข้อมูลเอง
- ชื่อที่อยู่ในประวัติหรือสมาชิกกลุ่มแต่ออฟไลน์จะไม่อยู่ในรายการนี้
- `version` เพิ่มเมื่อเพิ่มหรือลบชื่อออนไลน์ เป็นเลขของ Server รอบปัจจุบัน ไม่ใช่เวลาหรือรหัสข้อความ
- Server จับภาพรายชื่อกับ version ภายใต้ Lock เดียวกัน แล้วปล่อย Lock ก่อนส่งผ่านเครือข่าย
- แต่ละ Socket ไม่ส่ง version เก่าย้อนหลัง version ใหม่ และ Client กรอง version ที่เก่าหรือเท่ากับที่แสดงแล้วอีกชั้น
- การเชื่อมต่อใหม่เริ่มตัวนับที่รับล่าสุดใหม่ จึงใช้ต่อได้แม้ Server เปิดใหม่และเริ่ม version จากต้น
- Client ที่ยังไม่ลงทะเบียนจะไม่ได้รับรายชื่อออนไลน์

การส่งข้อความส่วนตัวใน Terminal จาก Part 1 ยังใช้ต่อได้:

```json
{"type": "message", "to": "bob", "text": "Hello Bob!"}
```

## Browser และ Python bridge

หน้าเว็บโหลด HTML/JavaScript/CSS ผ่าน HTTP จาก bridge ภายในเครื่อง (เริ่มต้น `127.0.0.1:8765`) จากนั้นเปิด WebSocket ที่ `/ws` เพื่อส่งคำสั่งและรับเหตุการณ์ ส่วน bridge ติดต่อ TCP Server เดิม (เริ่มต้น `127.0.0.1:5000`) ผ่าน `NetworkClient`

WebSocket ส่งหนึ่ง JSON object ต่อ text message จึงไม่ต้องเติม `\n` ส่วน TCP ระหว่าง NetworkClient กับ Server ยังใช้ JSON จบด้วย `\n` ตามเดิม

คำสั่งเริ่ม session จาก Browser ไป bridge:

```json
{"type": "connect", "host": "127.0.0.1", "port": 5000, "name": "alice"}
```

bridge ตรวจชนิดข้อมูลและพอร์ต สร้าง NetworkClient หนึ่งตัวต่อ WebSocket แล้วเรียก `connect()` ซึ่งส่งคำสั่ง `register` เดิมให้ TCP Server คำสั่ง `connect` จึงไม่ได้ส่งไปที่ Server โดยตรง

คำสั่งอื่นจาก Browser:

```json
{"type": "disconnect"}
```

```json
{"type": "message", "to": "bob", "text": "Hello Bob!"}
```

- `disconnect` ปิด TCP Socket ของ session นั้น รอเหตุการณ์ `disconnected` แล้วปิด WebSocket
- `message` รองรับใน bridge เพื่อใช้กติกาส่งต่อ Part 1 เดิม โดยส่งได้หลังได้รับ `registered` เท่านั้น ส่วน UI ห้องแชตจะเชื่อมในขั้นถัดไป
- เหตุการณ์ `connected`, `registered`, `users_updated`, `error`, `message`, `sent`, `disconnected` ส่งต่อให้ Browser ผ่าน WebSocket โดย bridge ไม่สร้างรายชื่อหรือสมาชิกจำลอง
- แต่ละแท็บมี session แยกกัน ไม่ใช้ global current user หรือ NetworkClient ร่วมกัน
- เมื่อชื่อซ้ำ bridge ส่ง `error` ก่อนปิด TCP และส่ง `disconnected` เพื่อให้หน้าเว็บกลับมาแก้ชื่อได้
- ปิดแท็บหรือ WebSocket หลุด จะปิด TCP Socket และหยุด workers เฉพาะ session นั้น
- เมื่อ bridge ปิด จะปิดทุก session ที่ตัวเองดูแล ส่วน TCP Server ยังทำงาน
- bridge bind ที่ loopback และตรวจ Origin ของ WebSocket ให้ตรงกับหน้าเว็บของตัวเอง
- สำหรับเดโมสองเครื่องให้รัน bridge บนแต่ละเครื่อง Client แล้วเชื่อมไปยัง IP ของ TCP Server

## เหตุการณ์ภายใน NetworkClient และ Tkinter เดิม

`client_network.py` ใช้คิวสองทิศทาง:

```text
Main thread -> outgoing queue -> sender thread -> socket
Socket -> receiver thread -> events queue -> main thread -> widgets
```

- `connected` และ `disconnected` เป็นเหตุการณ์ที่ Client สร้างเอง ไม่ใช่คำสั่ง JSON ที่ Server ส่งมา
- `registered`, `users_updated`, `error` และข้อความอื่นเป็นข้อมูลจาก Server ที่ receiver ใส่คิวให้ GUI
- main thread ใช้ `after()` ตรวจคิวโดยไม่รอ และประมวลผลจำนวนจำกัดต่อรอบ เพื่อให้รับการคลิกและการพิมพ์ได้ต่อ
- การ connect อยู่ใน receiver thread ส่วนการ send อยู่ใน sender thread จึงไม่ให้ GUI รอเครือข่าย
- ช่วงเชื่อมต่อหนึ่งครั้งมี main thread ของ GUI และ thread เบื้องหลังสำหรับรับและส่ง รวมสาม thread ที่แอปใช้งาน
- เมื่อตัดการเชื่อมต่อ ใช้ Event แจ้งหยุด ปลุกคิวงานส่ง และ shutdown Socket เพื่อปลุกงานรับ โดยไม่ join รอใน callback ของ GUI

สำหรับหน้าเว็บ เปลี่ยนผู้ตรวจคิว `events` จาก `after()` เป็น async task ของ bridge ซึ่งใช้ `get_nowait()` รอบละไม่เกิน 100 เหตุการณ์และ `asyncio.sleep(0.02)` เพื่อคืนเวลาให้แท็บอื่น แล้วส่ง JSON ผ่าน WebSocket ให้ JavaScript อัปเดต DOM งาน async ไม่ได้สร้าง thread ใหม่ต่อแท็บ ส่วน `NetworkClient` ยังมี worker รับ/ส่งสอง thread ตามเดิม

## ขอบเขตข้อมูลที่เตรียมไว้สำหรับขั้นถัดไป

ขั้นที่ 1–2 ยังไม่มีระบบห้อง กลุ่ม หรือการบันทึกข้อมูลจริง รูปแบบตั้งต้นที่เสนอสำหรับ `output/chat_state.json` คือ:

```json
{
  "schema_version": 1,
  "groups": {},
  "private_rooms": {},
  "messages": []
}
```

- `groups` จะผูก group_id กับชื่อและสมาชิก โดยสมาชิกไม่หายเมื่อออฟไลน์
- `private_rooms` จะผูกรหัสห้องกับคู่สนทนา
- `messages` จะเก็บข้อความพร้อมห้องและข้อมูลผู้มีสิทธิ์เห็นในขณะส่ง เพื่อไม่คืนประวัติก่อน Join หรือหลัง Leave ผิดคน
- กลุ่ม ห้อง และสมาชิกจะโหลดกลับเมื่อเปิด Server ใหม่ ส่วน Socket, Lock, thread, queue และสถานะออนไลน์ไม่บันทึกเป็นข้อมูลถาวร
- ใช้ไฟล์ภายใต้ `output/` ซึ่งถูกละเว้นจาก Git ส่วน schema ของแต่ละ record จะขยายเมื่อทำขั้นที่เกี่ยวข้องตามแผน

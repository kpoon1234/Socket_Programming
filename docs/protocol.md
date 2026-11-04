# Protocol and Data Contracts

เอกสารนี้อธิบายข้อมูลที่ใช้ใน Part 2 ขั้นที่ 1–4 รวมห้องส่วนตัว ประวัติ และการสร้าง/แสดงกลุ่ม ส่วน Join/Leave และข้อความกลุ่มยังเป็นขั้นถัดไป

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

หน้าเว็บปิดการเชื่อมต่อที่ลงชื่อไม่สำเร็จ แล้วให้แก้ชื่อและกด Connect ใหม่ งานเครือข่ายแต่ละครั้งมีคิวและ thread ของตัวเองเพื่อไม่ให้เหตุการณ์จากรอบเก่าปนกับรอบใหม่

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

Server ยังรองรับคำสั่งข้อความพื้นฐานจาก Part 1 สำหรับการทดสอบระดับ protocol:

```json
{"type": "message", "to": "bob", "text": "Hello Bob!"}
```

## Browser และ Python bridge

หน้าเว็บโหลด HTML/JavaScript/CSS ผ่าน HTTP จาก bridge ภายในเครื่อง (เริ่มต้น `127.0.0.1:3000`) จากนั้นเปิด WebSocket ที่ `/ws` เพื่อส่งคำสั่งและรับเหตุการณ์ ส่วน bridge ติดต่อ TCP Server เดิม (เริ่มต้น `127.0.0.1:5000`) ผ่าน `NetworkClient`

WebSocket ส่งหนึ่ง JSON object ต่อ text message จึงไม่ต้องเติม `\n` ส่วน TCP ระหว่าง NetworkClient กับ Server ยังใช้ JSON จบด้วย `\n` ตามเดิม

คำสั่งเริ่ม session จาก Browser ไป bridge:

```json
{"type": "connect", "host": "127.0.0.1", "port": 5000, "name": "alice"}
```

bridge ตรวจชนิดข้อมูลและพอร์ต สร้าง NetworkClient หนึ่งตัวต่อ WebSocket แล้วเรียก `connect()` ซึ่งส่ง `register` พร้อม `capabilities: ["private_rooms", "groups"]` ให้ TCP Server คำสั่ง `connect` จึงไม่ได้ส่งไปที่ Server โดยตรง Client เดิมที่ไม่ประกาศ capability เหล่านี้จะยังได้รับรูปแบบข้อความเดิม และไม่ถูกแทรกเหตุการณ์กลุ่ม

คำสั่งอื่นจาก Browser:

```json
{"type": "disconnect"}
```

```json
{"type": "message", "to": "bob", "text": "Hello Bob!"}
```

- `disconnect` ปิด TCP Socket ของ session นั้น รอเหตุการณ์ `disconnected` แล้วปิด WebSocket
- `message` รองรับใน bridge เพื่อใช้กติกาส่งต่อ Part 1 เดิม ส่วน UI ห้องแชตใช้ `open_private` และ `private_message` ซึ่งส่งได้หลัง `registered` เท่านั้น
- เหตุการณ์ `connected`, `registered`, `users_updated`, `private_rooms`, `room_opened`, `private_message`, `groups_updated`, `group_created`, `error`, `message`, `sent`, `disconnected` ส่งต่อให้ Browser ผ่าน WebSocket โดย bridge ไม่สร้างรายชื่อหรือสมาชิกจำลอง
- แต่ละแท็บมี session แยกกัน ไม่ใช้ global current user หรือ NetworkClient ร่วมกัน
- เมื่อชื่อซ้ำ bridge ส่ง `error` ก่อนปิด TCP และส่ง `disconnected` เพื่อให้หน้าเว็บกลับมาแก้ชื่อได้
- ปิดแท็บหรือ WebSocket หลุด จะปิด TCP Socket และหยุด workers เฉพาะ session นั้น
- เมื่อ bridge ปิด จะปิดทุก session ที่ตัวเองดูแล ส่วน TCP Server ยังทำงาน
- bridge bind ที่ loopback และตรวจ Origin ของ WebSocket ให้ตรงกับหน้าเว็บของตัวเอง
- สำหรับเดโมสองเครื่องให้รัน bridge บนแต่ละเครื่อง Client แล้วเชื่อมไปยัง IP ของ TCP Server

## ห้องส่วนตัวและประวัติ

หลัง `registered` Server ส่ง `private_rooms` เฉพาะห้องของชื่อนั้น โดยมี metadata แต่ยังไม่มีเนื้อหาประวัติ ไม่ส่งเหตุการณ์นี้ให้ Client เดิมที่ไม่ประกาศ capability:

```json
{"type": "private_rooms", "rooms": [{"room_id": "private_example", "kind": "private", "members": ["alice", "bob"]}]}
```

เปิดห้องตามคู่สนทนา หรือเปิดห้องเดิมตามรหัส (เลือกอย่างใดอย่างหนึ่ง):

```json
{"type": "open_private", "to": "bob", "request_id": "open-1"}
```

```json
{"type": "open_private", "room_id": "private_example", "request_id": "open-2"}
```

Server ตอบพร้อมประวัติที่ผู้ขอมีสิทธิ์อ่าน:

```json
{"type": "room_opened", "room_id": "private_example", "kind": "private", "members": ["alice", "bob"], "messages": [], "request_id": "open-1"}
```

- ห้องหนึ่งมีสมาชิกสองชื่อ และคู่ชื่อเดิมใช้ห้องเดียวกันไม่ว่าฝ่ายใดเปิดก่อน
- สร้างห้องใหม่ได้เมื่ออีกฝ่ายออนไลน์ ส่วนห้องเดิมเปิดอ่านได้แม้อีกฝ่ายออฟไลน์
- Server ตรวจสมาชิกทุกครั้ง ทั้งขอห้องและส่งข้อความ ไม่เชื่อฟิลด์ `from` หรือสมาชิกจาก Client
- คำสั่งห้องต้องมี `request_id` เป็น string ที่ไม่ว่าง หน้าเว็บสร้าง UUID ต่อคำขอ ส่วนเหตุการณ์ที่ Server ส่งให้ผู้รับเองไม่จำเป็นต้องมี `request_id`

ส่งข้อความเข้าห้อง:

```json
{"type": "private_message", "room_id": "private_example", "text": "Hello Bob!", "request_id": "send-1"}
```

Server ตรวจสมาชิก ผู้รับออนไลน์ และข้อความไม่ว่าง ก่อนบันทึกแล้วส่งให้ทั้งสองฝ่าย:

```json
{"type": "private_message", "room_id": "private_example", "message_id": "message_example", "sequence": 1, "from": "alice", "to": "bob", "text": "Hello Bob!", "timestamp": "2026-11-01T10:00:00+00:00"}
```

เหตุการณ์ของผู้ส่งแนบ `request_id` เดิมด้วย ส่วนของผู้รับไม่มี หากผู้รับยังไม่เคยได้ข้อมูลห้องในการเชื่อมต่อรอบนั้น Server ส่ง `room_opened` พร้อมประวัติก่อนข้อความล่าสุด แล้วจึงส่งข้อความสด เพื่อให้สร้างแท็บได้โดยไม่ต้องคลิกคู่สนทนาก่อน

เมื่อส่งผ่าน Socket ผู้รับสำเร็จ Server ตอบผู้ส่ง:

```json
{"type": "sent", "to": "bob", "room_id": "private_example", "message_id": "message_example", "request_id": "send-1"}
```

- `message_id` กำหนดโดย Server และใช้ป้องกันการแสดงข้อความเดิมซ้ำ ระหว่างประวัติกับข้อความสด
- `sequence` เพิ่มตามลำดับภายในห้อง และใช้จัดเรียงข้อความแม้มีประวัติ/ข้อมูลสดเข้ามาใกล้กัน
- `request_id` ใช้จับคู่ผลลัพธ์กับคำขอใน session ไม่บันทึกเป็นประวัติ และไม่ได้ทำให้คำขอที่ส่งซ้ำมีผลเพียงครั้งเดียวโดยอัตโนมัติ
- หน้าเว็บเพิ่มกล่องข้อความจากประวัติหรือ `private_message` เท่านั้น `sent` เปลี่ยนสถานะ ไม่เพิ่มกล่องซ้ำ
- `sent` ยืนยันว่าเขียนผ่าน Socket แล้ว ไม่ใช่สถานะอ่านแล้ว และไม่มีการยืนยันจาก Browser ผู้รับ
- บันทึกลงไฟล์ก่อนส่งสด หากเขียนไฟล์ล้มเหลว ตอบ `error` พร้อม `request_id` โดยไม่สร้างข้อความสำเร็จในหน่วยความจำ
- ถ้าผู้รับหลุดหลังบันทึกแต่ระหว่างส่งสด ผู้ส่งยังได้ข้อความที่บันทึกแล้ว พร้อม `error` ที่มี `persisted: true` และ `message_id` ประวัติจะคืนให้คู่สนทนาเมื่อกลับมา
- ถ้าผู้ส่งหลุดก่อนรับผลตอบกลับ อาจมีข้อความที่บันทึกสำเร็จแล้ว ให้เปิดห้องตรวจประวัติก่อนส่งซ้ำ หน้าเว็บไม่ resend อัตโนมัติ
- ปิดการเชื่อมต่อทำให้หน้าเว็บล้างข้อมูล session รวมข้อความร่าง ส่วนประวัติถาวรอยู่กับ Server การเก็บข้อความร่างแยกห้องครอบคลุมการสลับแท็บระหว่างเชื่อมต่อ
- Server ยังรองรับ `message` กับ `sent` แบบพื้นฐานสำหรับ Client ที่ไม่ประกาศ capability ข้อความระหว่างคนละชื่อเก็บลงห้องเดียวกับเว็บ และแปลงรูปแบบตาม capability ของผู้รับ ส่วนการส่งหาตัวเองแบบเดิมไม่ได้สร้างห้องส่วนตัวสองสมาชิก

Server ใช้ Lock แยกตามห้องเพื่อเรียงการเปิดประวัติและการส่งข้อความของห้องนั้น ใช้ Lock ของ state store เพื่อป้องกันการเขียนไฟล์ชนกัน และปล่อย `clients_lock` ก่อนทำ I/O ไฟล์หรือเครือข่าย

## เหตุการณ์ภายใน NetworkClient และ bridge

`client_network.py` ใช้คิวสองทิศทาง:

```text
Browser -> WebSocket -> bridge handler -> outgoing queue -> sender thread -> TCP socket
TCP socket -> receiver thread -> events queue -> bridge task -> WebSocket -> Browser DOM
```

- `connected` และ `disconnected` เป็นเหตุการณ์ที่ NetworkClient สร้างเอง ไม่ใช่คำสั่ง JSON ที่ Server ส่งมา
- `registered`, `users_updated`, `groups_updated` และเหตุการณ์อื่นจาก Server ถูก receiver ใส่คิว `events`
- งาน async ของ bridge ใช้ `get_nowait()` ตรวจคิวรอบละไม่เกิน 100 เหตุการณ์ แล้ว `asyncio.sleep(0.02)` เพื่อคืนเวลาให้แท็บอื่น
- การ connect อยู่ใน receiver thread ส่วนการ send อยู่ใน sender thread จึงไม่ให้ event loop รอเครือข่าย
- แต่ละ session มี sender และ receiver สอง thread ส่วนงาน async ของทุกแท็บใช้ event loop ของ bridge ร่วมกัน
- เมื่อตัดการเชื่อมต่อ ใช้ Event แจ้งหยุด ปลุกคิวงานส่ง และ shutdown Socket เพื่อปลุกงานรับ การรอ thread จบใช้ `asyncio.to_thread()` เพื่อไม่ขวาง event loop

## การสร้างและแสดงกลุ่ม

Client ที่ประกาศ capability `groups` จะได้รับ `groups_updated` หลัง `registered` โดยมีทุกกลุ่ม รวมกลุ่มที่ตัวเองไม่ได้เป็นสมาชิก เมื่อไม่มีรายการจะเป็น `groups: []` คำสั่งสร้างใช้ได้หลังลงทะเบียนเท่านั้น:

```json
{"type": "create_group", "name": "Study group", "request_id": "create-1"}
```

Server ตัดช่องว่างหัวท้ายของชื่อและปฏิเสธชื่อว่าง กำหนดผู้สร้างจากการเชื่อมต่อและสมาชิกตั้งต้นเพียงผู้สร้าง ไม่ใช้ `creator` หรือ `members` จาก Client แต่ละคำสั่งที่สำเร็จสร้างรหัสใหม่แม้ใช้ชื่อกลุ่มซ้ำ การใช้ `request_id` เป็นการจับคู่คำตอบ ไม่ใช่กลไก deduplicate การส่งคำสั่งซ้ำ:

```json
{"type": "group_created", "request_id": "create-1", "group_id": "group_example"}
```

คำตอบนี้ส่งหลังบันทึกไฟล์สำเร็จ แล้ว Server กระจาย snapshot ล่าสุดให้ผู้ที่ประกาศ `groups` ทุกคน โดยไม่ส่งเนื้อหาห้องแชตไปด้วย:

```json
{"type": "groups_updated", "version": 1, "groups": [{"group_id": "group_example", "name": "Study group", "creator": "alice", "members": ["alice"]}]}
```

- เลขรุ่นและกลุ่มอ่านภายใต้ Lock เดียวกัน เพิ่มรุ่นเมื่อสร้างและบันทึกสำเร็จเท่านั้น แล้วปล่อย Lock ก่อนส่งเครือข่าย
- Server, NetworkClient และ Browser กรอง snapshot ที่ version เก่าหรือเท่ากับที่ส่ง/รับแล้ว เพื่อไม่ให้รายการย้อนเมื่อสร้างพร้อมกัน
- `version` เริ่ม 0 เมื่อโหลด Server ใหม่ แม้มีข้อมูลเดิม การเชื่อมต่อใหม่รีเซ็ตเลขรุ่นที่รับล่าสุดเป็น -1
- Browser เพิ่ม/แทนการ์ดจาก `groups_updated` เท่านั้น ส่วน `group_created` ใช้จบสถานะรอและปิดฟอร์ม
- หากบันทึกล้มเหลว ตอบ `error` พร้อม request_id ไม่ตอบสำเร็จ ไม่กระจายกลุ่มที่บันทึกไม่สำเร็จ และไม่เปลี่ยนข้อมูลในหน่วยความจำ
- กลุ่มและสมาชิกคงอยู่แม้ทุกคนออฟไลน์หรือเปิด Server ใหม่ รายชื่อออนไลน์ยังมาจาก Socket จริงแยกต่างหาก
- ขั้นนี้ยังไม่มีคำสั่ง Join/Leave หรือส่งข้อความกลุ่ม และยังไม่เปิดแท็บห้องกลุ่ม

## ข้อมูลถาวร

ใช้ `state_store.py` เก็บห้อง ประวัติส่วนตัว และกลุ่มจริงใน `output/chat_state.json` รูปแบบตั้งต้นคือ:

```json
{
  "schema_version": 1,
  "groups": {},
  "private_rooms": {},
  "messages": []
}
```

- `groups` ผูก group_id กับข้อมูล group_id, name, creator และ members รายการเดิมที่ groups ว่างยังโหลดได้ ส่วนสิทธิ์ข้อความตามช่วง Join/Leave จะเพิ่มในขั้นถัดไป
- `private_rooms` ผูกรหัสห้องกับสมาชิกสองชื่อคงที่
- `messages` เก็บข้อความที่มี room_id, message_id, sequence, from, to, text และ timestamp โดยไม่เก็บ request_id
- ห้องและประวัติโหลดกลับเมื่อเปิด Server ใหม่ ส่วน Socket, Lock, thread, queue และสถานะออนไลน์ไม่บันทึกเป็นข้อมูลถาวร
- เขียนไฟล์ชั่วคราวให้ครบและ flush/fsync ก่อน `os.replace()` ไฟล์เดิม หากบันทึกล้มเหลวจะไม่เปลี่ยน state ในหน่วยความจำ หากไฟล์เดิมเสียจะรายงาน error ไม่เขียนทับด้วยข้อมูลว่าง
- `CHAT_STATE_PATH` เปลี่ยนตำแหน่งไฟล์ได้ ชุดทดสอบใช้โฟลเดอร์ชั่วคราวแยกจากข้อมูลจริง

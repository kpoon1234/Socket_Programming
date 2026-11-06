# ฟีเจอร์ Unsend Message (ยกเลิกข้อความ)

ฟีเจอร์นี้อนุญาตให้ผู้ใช้ยกเลิกข้อความ (Unsend / Retract) ที่ตนเองเคยส่งได้ ทั้งในห้องแชตส่วนตัว (Private Room) และห้องแชตกลุ่ม (Group Chat) โดยข้อความต้นฉบับจะถูกนำออกจากหน่วยความจำและไฟล์ประวัติ `chat_state.json` บน Server และแจ้งให้ Client ทุกฝ่ายอัปเดตหน้าจอแบบ Real-time ทันที

## ความสามารถหลัก

1. **สิทธิ์ในการยกเลิกเฉพาะข้อความตนเอง (Ownership Enforcement)**:
   - ตรวจสอบชื่อผู้ส่งจริงที่ Server โดยใช้ชื่อที่ผูกกับ TCP Socket (`from == sender.name`)
   - ผู้ใช้ไม่สามารถยกเลิกข้อความของผู้อื่นได้ หากพยายามส่งคำสั่งยกเลิกข้อความคนอื่น Server จะปฏิเสธและตอบ `error`

2. **กระจายแบบ Real-time (Live Notification)**:
   - เมื่อผู้ส่งกดยกเลิกข้อความ Server จะส่งอีเวนต์ `message_unsent` ไปยังผู้ส่งและคู่สนทนา (ในแชตส่วนตัว) หรือสมาชิกกลุ่มทุกคนที่กำลังออนไลน์ (ในแชตกลุ่ม)
   - หน้าเว็บของผู้รับจะอัปเดตข้อความนั้นเป็นสถานะยกเลิกแล้วทันทีโดยไม่ต้อง Refresh

3. **บันทึกลงประวัติถาวร (Durable State Persistence)**:
   - บันทึกการยกเลิกลงในไฟล์ `chat_state.json` ทันทีด้วยกลไก Atomic file replacement
   - ข้อความที่ถูกยกเลิกแล้วจะถูกล้างเนื้อหาต้นฉบับเพื่อความปลอดภัยและความเป็นส่วนตัว
   - สมาชิกที่ออฟไลน์อยู่ เมื่อเชื่อมต่อกลับมาจะเห็นเฉพาะสถานะยกเลิกแล้ว ไม่เห็นเนื้อหาเดิม

4. **ทำงานร่วมกับ AI Summarization**:
   - ข้อความที่ถูกยกเลิกแล้วจะไม่ถูกนำไปประมวลผลใน AI Summarization ป้องกันข้อมูลที่ยกเลิกไปแล้วหลุดเข้าไปในบทสรุป

5. **UI / UX ที่ใช้งานง่าย**:
   - ข้อความของตนเองจะมีปุ่ม **Unsend** ปรากฏข้างเวลาส่ง
   - มีกล่องข้อความยืนยัน (Confirmation Dialog) ป้องกันการกดผิด
   - ข้อความที่ถูกยกเลิกแล้วจะแสดงเป็นกล่องข้อความสไตล์ Muted/Dashed พร้อมข้อความระบุว่า "You unsent a message" หรือ "[Name] unsent a message"

## โปรโตคอล JSON

### 1. Client ส่งคำขอยกเลิกข้อความ (Browser -> Bridge -> TCP Server)

สำหรับห้องส่วนตัว:
```json
{
  "type": "unsend_message",
  "room_type": "private",
  "room_id": "private_example",
  "message_id": "message_example",
  "request_id": "unsend-1"
}
```

สำหรับห้องกลุ่ม:
```json
{
  "type": "unsend_message",
  "room_type": "group",
  "group_id": "group_example",
  "message_id": "message_example",
  "request_id": "unsend-2"
}
```

### 2. Server แจ้งเหตุการณ์ข้อความถูกยกเลิก (Server -> Bridge -> Browser)

ส่งให้ผู้ส่ง (มี `request_id`):
```json
{
  "type": "message_unsent",
  "room_type": "private",
  "room_id": "private_example",
  "message_id": "message_example",
  "from": "alice",
  "request_id": "unsend-1"
}
```

ส่งให้ผู้รับ/สมาชิกอื่น:
```json
{
  "type": "message_unsent",
  "room_type": "private",
  "room_id": "private_example",
  "message_id": "message_example",
  "from": "alice"
}
```

Server ตอบยืนยันคำขอแก่ผู้ส่ง:
```json
{
  "type": "sent",
  "action": "unsend",
  "room_id": "private_example",
  "message_id": "message_example",
  "request_id": "unsend-1"
}
```

### 3. กรณีเกิดข้อผิดพลาด
หากข้อความไม่มีอยู่, พยายามยกเลิกข้อความของคนอื่น หรือข้อความถูกยกเลิกไปแล้ว:
```json
{
  "type": "error",
  "request_id": "unsend-1",
  "code": "unsend_failed",
  "text": "You can only unsend your own messages."
}
```

## ไฟล์ที่เกี่ยวข้อง

| ไฟล์ | หน้าที่ |
| --- | --- |
| `state_store.py` | เพิ่ม `unsend_private_message()` และ `unsend_group_message()` ตรวจสิทธิ์ ล้างเนื้อหา และบันทึกลง JSON |
| `server.py` | เพิ่มฟังก์ชัน `unsend_private()`, `unsend_group()`, `handle_unsend()` ตรวจสิทธิ์และกระจายอีเวนต์ `message_unsent` |
| `web_bridge.py` | รองรับคำสั่ง `unsend_message` จาก WebSocket ส่งต่อไปยัง TCP Socket ผ่าน `NetworkClient` |
| `web/app.js` | เพิ่มปุ่ม Unsend ใน Message Bubble, หน้าต่างยืนยัน, ส่งคำสั่ง `unsend_message`, และรับอีเวนต์ `message_unsent` |
| `web/index.html` | เพิ่มโมดอลยืนยัน `#unsend-dialog` |
| `feature/summarize/service.py` | กรองข้อความที่ถูก unsent ออกจากการส่งไปประมวลผล AI |
| `tests/test_unsend.py` | ชุดทดสอบครอบคลุมการยกเลิกข้อความส่วนตัว กลุ่ม สิทธิ์ ความคงอยู่ข้าม restart และการกรองใน AI |

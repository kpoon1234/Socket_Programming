# Socket Programming

โปรเจกต์แอปแชตด้วย Python 3 และ TCP Socket ใช้โมดูลมาตรฐานของ Python โดยไม่ต้องติดตั้งแพ็กเกจเพิ่ม

## สถานะปัจจุบัน: Part 1 ขั้นที่ 4

Server รองรับ Client หลายคนพร้อมกันที่ `127.0.0.1:5000` แต่ละคนลงทะเบียนชื่อไม่ซ้ำ และส่งข้อความส่วนตัวหากันผ่าน Server ได้ ใช้ช่อง `Recipient:` และ `Message:` แยกกันตามที่เลือก

โค้ด ชื่อตัวแปร และข้อความที่โปรแกรมแสดงเป็นภาษาอังกฤษ ส่วนคอมเมนต์และคำอธิบายเป็นภาษาไทย ข้อความแชตที่ผู้ใช้ส่งยังรองรับ UTF-8 รวมถึงภาษาไทย

| ไฟล์ | หน้าที่ |
| --- | --- |
| `server.py` | รับหลาย Client เก็บชื่อ ส่งต่อข้อความ และจัดการเมื่อ Client ออก |
| `client.py` | ลงชื่อ รับผู้รับและข้อความจากผู้ใช้ พร้อมแสดงข้อความเข้า |
| `protocol.py` | ส่งและรับ JSON แบบหนึ่งข้อความต่อหนึ่งบรรทัด |
| `tests/test_chat.py` | ทดสอบกติกาข้อความ การส่งต่อ และการทำงานพร้อมกัน |

## วิธีทดลองบนเครื่องเดียว

เปิด Terminal สามหน้าต่างในโฟลเดอร์โปรเจกต์

**Terminal 1 — เริ่ม Server**

```bash
python3 server.py
```

```text
Server listening on 127.0.0.1:5000
```

**Terminal 2 — เริ่ม Client คนแรก**

```bash
python3 client.py
```

ลงชื่อ `alice` แล้วรอที่ช่องผู้รับ

```text
Connected to 127.0.0.1:5000.
Name: alice
Registered as alice.
Enter a recipient and a message. Type /quit at Recipient to exit.
Recipient (/quit to exit):
```

**Terminal 3 — เริ่ม Client อีกคน**

```bash
python3 client.py
```

ลงชื่อ `bob` แล้วกลับไปที่ Terminal ของ alice และพิมพ์:

```text
Recipient (/quit to exit): bob
Message: Hello Bob!
```

bob จะได้รับข้อความได้แม้ยังรออยู่ที่ช่องผู้รับ:

```text
[alice -> bob] Hello Bob!
```

ส่วน alice จะเห็น `[Sent to bob]` ซึ่งหมายถึง Server ส่งต่อผ่าน Socket แล้ว ไม่ใช่การยืนยันว่า bob อ่านแล้ว จากนั้นให้ bob เลือกผู้รับเป็น `alice` เพื่อตอบกลับ

- พิมพ์ `/quit` ที่ช่อง `Recipient` เพื่อออก ชื่อ `/quit` จึงสงวนไว้และใช้ลงทะเบียนไม่ได้ ส่วน `/quit` ที่ช่อง `Message` จะถูกส่งเป็นข้อความตามปกติ
- ชื่อตัดช่องว่างหัวท้ายออก และเทียบตัวพิมพ์ใหญ่เล็กตามจริง เช่น `alice` กับ `Alice` เป็นคนละชื่อ ชื่อที่มีช่องว่างภายในยังใช้ได้
- ถ้าชื่อซ้ำ Client จะให้กรอกชื่อใหม่บนการเชื่อมต่อเดิม
- ถ้าผู้รับไม่มีอยู่ Server จะตอบ `Error` และผู้ส่งยังส่งข้อความต่อได้
- เมื่อ Client ออก Server ยังทำงานและรับคนใหม่ได้ รวมถึงการใช้ชื่อที่คนเดิมเลิกใช้แล้ว
- หยุด Server ด้วย `Ctrl+C` เพื่อปิดการเชื่อมต่อทั้งหมด
- ถ้า Server ปิดขณะ Client รอ `input()` จะแสดง `Server disconnected. Press Enter to exit.` ให้กด Enter เพื่อออกจากช่องที่กำลังพิมพ์
- ข้อความที่เข้าระหว่างพิมพ์อาจแสดงแทรกกับ prompt ใน Terminal ได้ ข้อความที่กำลังพิมพ์ยังส่งได้ตามปกติ หน้าต่าง GUI จะทำใน Part 2

ถ้า Client แจ้ง `Connection refused` ให้เปิด Server ก่อน หาก Server แจ้ง `Address already in use` ให้ตรวจว่า Server รอบก่อนหรือโปรแกรมอื่นยังใช้พอร์ต `5000` อยู่หรือไม่

## Socket และ thread ต่างกันอย่างไร

**Socket คือช่องทางรับและส่งข้อมูล** ส่วน **thread คืองานที่แยกมาทำพร้อมกับงานอื่นภายในโปรแกรมเดียวกัน**

ฝั่ง Server มี Socket สองหน้าที่:

1. **Listening socket:** สร้างด้วย `socket()` แล้ว `bind()` และ `listen()` ไว้รอคนใหม่
2. **Connected socket:** `accept()` คืน Socket ใหม่สำหรับคุยกับ Client ที่เพิ่งเข้ามา แต่ละครั้งได้คนละ Socket

เมื่อมี alice และ bob จะมี listening socket หนึ่งตัว และ connected socket สองตัวบน Server ส่วน Client แต่ละโปรแกรมมี Socket ของตัวเองอีกหนึ่งตัว

```text
Server process
  Main thread: accept() waits for new clients
  Worker A: recv() reads from Alice's connected socket
  Worker B: recv() reads from Bob's connected socket

Alice client process
  Main thread: input() -> send()
  Receiver thread: recv() -> display incoming messages
```

Thread A สามารถรอข้อมูลจาก alice โดยไม่ขวาง Thread B หรือการรับคนใหม่ ถ้า alice ส่งหา bob Thread A จะอ่านคำสั่งจาก Socket ของ alice แล้วเขียนข้อมูลไปที่ Socket ของ bob ขณะเดียวกัน Thread B ยังรออ่านข้อความที่ bob ส่งมาได้

ฝั่ง Client งานหลักรอผู้ใช้พิมพ์ ส่วน receiver thread รอข้อมูลจาก Server จึงรับข้อความได้โดยไม่ต้องกดส่งก่อน การส่งและรับบน Socket เดียวกันทำได้พร้อมกัน แต่ให้มีตัวอ่านเพียงตัวเดียวต่อ Socket เพื่อไม่แย่งข้อมูลกัน

## รายชื่อและ Lock

Server ใช้ dictionary กลาง แนวคิดเป็น:

```python
clients = {
    "alice": alice_connection,
    "bob": bob_connection,
}
```

ค่าของ dictionary ในโค้ดจริงเป็น `ClientConnection` ซึ่งรวม Socket ชื่อที่ลงทะเบียน และกุญแจการส่งของคนนั้นไว้ด้วยกัน

| กุญแจ | ป้องกันอะไร |
| --- | --- |
| `clients_lock` | การตรวจชื่อซ้ำ เพิ่ม ลบ และค้นหาการเชื่อมต่อพร้อมกัน |
| `client.send_lock` | หลาย thread ส่งเข้า Socket ของผู้รับเดียวกันจนข้อมูล JSON แทรกกัน |

`Lock` เปรียบเหมือนกุญแจที่ให้เข้าทำงานส่วนหนึ่งได้ทีละงาน ใช้ `with lock:` เพื่อให้ปล่อยกุญแจเมื่อทำเสร็จหรือเกิดข้อผิดพลาด เราปล่อย `clients_lock` ก่อนส่งข้อมูลผ่านเครือข่าย เพื่อไม่ให้ผู้รับที่ช้าขวางการจัดการรายชื่อทั้งหมด

ตอนลงชื่อ Server ล็อกฝั่งส่งก่อนเพิ่มชื่อเข้ารายการ เพื่อให้คำตอบ `registered` มาก่อนข้อความจากคนอื่นที่อาจส่งมาทันที และตอนลบชื่อจะตรวจว่าเป็นการเชื่อมต่อเดิม เพื่อไม่เผลอลบคนใหม่ที่กลับมาใช้ชื่อเดียวกัน

## ข้อความ JSON และ flow

Client ลงทะเบียนชื่อ:

```json
{"type": "register", "name": "alice"}
```

Server ตอบรับ:

```json
{"type": "registered", "name": "alice"}
```

alice ส่งหา bob:

```json
{"type": "message", "to": "bob", "text": "Hello Bob!"}
```

Server ใช้ชื่อที่ผูกกับ Socket ของผู้ส่งเติม `from` เอง แล้วส่งเฉพาะให้ bob:

```json
{"type": "message", "from": "alice", "to": "bob", "text": "Hello Bob!"}
```

Server แจ้งสถานะกลับให้ alice:

```json
{"type": "sent", "to": "bob"}
```

การแจ้งชื่อยังไม่ใช่ระบบยืนยันตัวตนด้วยรหัสผ่าน ส่วนคำสั่งหรือข้อมูลผิดจะตอบด้วย `error` หาก JSON เสียหรือการเชื่อมต่อจบกลางบรรทัด จะพยายามแจ้งข้อผิดพลาดแล้วปิดเฉพาะ Client คนนั้น

```text
Client -> register -> Server -> registered -> Client
Alice -> message(to=bob) -> Server -> message(from=alice) -> Bob
                                  -> sent -> Alice
Client -> /quit -> close socket -> Server removes that connection
Server continues accepting other clients
```

## กติกาข้อความจากขั้นที่ 3 ที่ยังใช้ต่อ

- `send_message()` ใช้ `json.dumps()` → เติม `\n` → เข้ารหัส UTF-8 → `sendall()`
- `receive_messages()` ใช้ `recv()` → เก็บ buffer → แยกบรรทัด → ถอดรหัส UTF-8 → `json.loads()`
- JSON หนึ่งข้อความต่อหนึ่งบรรทัดช่วยแยกข้อมูลเมื่อ TCP แบ่งข้อความมาหลายส่วน หรือรวมหลายข้อความมาในครั้งเดียว
- ขึ้นบรรทัดใหม่ภายในข้อความจะถูก JSON escape จึงไม่สับสนกับตัวจบข้อความ
- `yield` คืนข้อความทีละรายการและจำ buffer ไว้ Client ใช้ generator เดิมตั้งแต่ลงชื่อจนส่งต่อให้ receiver thread
- `threading.Event` ใช้แจ้งให้งานรับและงานหลักรู้ว่าต้องหยุด และ `shutdown(SHUT_RDWR)` ปลุกงานที่กำลังรอ Socket ก่อนปิดโปรแกรม

## การทดสอบ

```bash
python3 -B -m unittest discover -s tests -v
```

ทดสอบการแบ่งและรวมข้อความ UTF-8 ชื่อซ้ำ การส่งส่วนตัว การรับระหว่างรอพิมพ์ การส่งพร้อมกัน การนำชื่อกลับมาใช้ และการปิด Server โดยใช้พอร์ตว่างอัตโนมัติสำหรับการทดสอบ ไม่รบกวน Server ที่พอร์ต `5000`

การทดสอบต้องเปิด Socket ภายในเครื่อง หากรันผ่านเครื่องมือที่จำกัดสิทธิ์เปิด Socket อาจต้องอนุญาตการทดสอบก่อน

แผนหลักอยู่ใน [flow/part1.md](flow/part1.md) ลำดับการทำงานถัดไปคือพัฒนา Part 2 ให้ครบโดยทดสอบในเครื่องก่อน แล้วจึงนำ Server ขึ้น Cloud ภายหลัง ส่วนการเดโมตามโจทย์ยังต้องใช้ Client บนคอมพิวเตอร์จริงคนละเครื่อง

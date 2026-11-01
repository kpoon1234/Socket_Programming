# Socket Programming

โปรเจกต์แอปแชตด้วย Python 3 และ TCP Socket ใช้โมดูลมาตรฐานของ Python และ Tkinter สำหรับหน้าต่าง GUI ซึ่งบางระบบต้องติดตั้งส่วนรองรับเพิ่ม

## สถานะปัจจุบัน: Part 2 ขั้นที่ 1–2

GUI เชื่อมต่อ Server ด้วยชื่อไม่ซ้ำ และแสดงรายชื่อออนไลน์ที่อัปเดตตามการเข้า ออก และหลุด รวมชื่อตัวเองด้วย โดยแก้ widget ใน main thread ผ่านคิวเหตุการณ์

รอบนี้ GUI ใช้เชื่อมต่อและดูรายชื่อ ส่วนการเปิดห้องส่วนตัวและระบบกลุ่มจะทำในขั้นถัดไป พื้นที่ห้องและปุ่มกลุ่มจึงเป็นโครงหน้าต่างที่ยังไม่ได้เปิดใช้งาน ส่วน Terminal client ยังส่งข้อความส่วนตัวผ่าน Server ได้ตามเดิม

หน้าต่างใช้โทนเขียวกับพื้นสว่าง แบ่งแถบรายชื่อและข้อมูลผู้ใช้ไว้ด้านซ้าย ส่วนฟอร์มเชื่อมต่อและพื้นที่สนทนาอยู่ด้านขวา ป้ายสถานะแสดง Offline, Connecting, Online หรือ Error พร้อมข้อความอธิบายด้านล่าง ขนาดเริ่มต้น 1100 × 740 และย่อได้ถึง 900 × 640 ใช้ Tkinter/ttk และ Canvas โดยไม่เพิ่ม dependency สำหรับตัวแอป

โค้ด ชื่อตัวแปร และข้อความที่โปรแกรมแสดงเป็นภาษาอังกฤษ ส่วนคอมเมนต์และคำอธิบายเป็นภาษาไทย ข้อความแชตที่ผู้ใช้ส่งยังรองรับ UTF-8 รวมถึงภาษาไทย

| ไฟล์ | หน้าที่ |
| --- | --- |
| `server.py` | รับหลาย Client เก็บชื่อ ส่งต่อข้อความ และจัดการเมื่อ Client ออก |
| `client.py` | ลงชื่อ รับผู้รับและข้อความจากผู้ใช้ พร้อมแสดงข้อความเข้า |
| `gui_client.py` | หน้าต่างเชื่อมต่อ แสดงรายชื่อ และตรวจคิวด้วย after() |
| `client_network.py` | งาน connect, receive และ send เบื้องหลัง โดยไม่เรียก widget |
| `protocol.py` | ส่งและรับ JSON แบบหนึ่งข้อความต่อหนึ่งบรรทัด |
| `tests/test_chat.py` | ทดสอบกติกาข้อความ การส่งต่อ และการทำงานพร้อมกัน |
| `tests/test_presence.py` | ทดสอบรายชื่อออนไลน์ ลำดับข้อมูล และการหยุดงานเครือข่าย |
| `tests/test_gui.py` | ทดสอบ Tkinter จริง รวมการตอบสนองของหน้าต่างระหว่างรอเครือข่าย |
| `docs/protocol.md` | กติกา JSON คิวเหตุการณ์ และขอบเขตข้อมูลถาวรสำหรับขั้นต่อไป |

## เปิด GUI บนเครื่องเดียว

ตรวจว่า Tkinter พร้อมด้วย `python3 -m tkinter` สำหรับ Ubuntu หากยังไม่มี ให้ติดตั้งจาก Terminal:

```bash
sudo apt-get install python3-tk
```

เปิด Server ก่อน:

```bash
python3 server.py
```

เปิดอีกสอง Terminal แล้วรันคำสั่งนี้ในแต่ละหน้าต่าง:

```bash
python3 gui_client.py
```

1. ใช้ Server `127.0.0.1` และ Port `5000`
2. ตั้งชื่อหน้าต่างแรกเป็น `alice` แล้วกด Connect จะเห็น `alice (you)`
3. ตั้งชื่ออีกหน้าต่างเป็น `bob` แล้วกด Connect ทั้งสองจะเห็นรายชื่อ alice และ bob
4. ถ้าชื่อซ้ำ GUI จะแสดง Error และให้แก้ชื่อแล้วกด Connect ใหม่
5. กด Disconnect หรือปิดหน้าต่างหนึ่ง รายชื่อของหน้าต่างที่เหลือจะเปลี่ยนตามจริง
6. กด Connect อีกครั้งเพื่อเชื่อมต่อใหม่ หาก Server ปิด GUI จะแจ้งสาเหตุ ล้างรายชื่อ และกลับมาให้เชื่อมต่อได้โดยไม่ต้องกด Enter

การมีชื่ออยู่ในประวัติหรือสมาชิกกลุ่มในอนาคตไม่ทำให้ชื่อนั้นแสดงเป็นออนไลน์ รายชื่อรอบนี้มาจากการเชื่อมต่อที่ลงทะเบียนสำเร็จอยู่จริงเท่านั้น

## ทดลอง Terminal client เดิม

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
- ข้อความและเหตุการณ์รายชื่อที่เข้าระหว่างพิมพ์อาจแสดงแทรกกับ prompt ใน Terminal ได้ ข้อความที่กำลังพิมพ์ยังส่งได้ตามปกติ สำหรับหน้าต่างใช้ `gui_client.py`

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

สำหรับ GUI เพิ่ม sender thread อีกหนึ่งงานเพื่อไม่ให้ `connect()` หรือ `sendall()` ที่รอเครือข่ายขวางการวาดหน้าต่าง จึงมีสามงานหลักต่อ Client ที่เชื่อมต่อ:

```text
GUI main thread -> outgoing queue -> sender thread -> socket
Socket -> receiver thread -> events queue -> GUI main thread -> widgets
```

`after()` และ Queue ไม่ได้สร้าง thread เพิ่ม GUI ตรวจคิวด้วย `get_nowait()` รอบละไม่เกิน 100 เหตุการณ์ แล้วนัดตรวจครั้งถัดไปในประมาณ 100 มิลลิวินาที ไม่มีการเรียก widget จากงานเครือข่าย

Server ส่ง `users_updated` พร้อม `version` ที่เพิ่มเมื่อคนเข้าออก ทั้งฝั่งส่งและฝั่งรับป้องกันการใช้รายการเก่าย้อนทับรายการใหม่ ส่วน `registered` ต้องมาก่อนรายชื่อหรือข้อความอื่นบนการเชื่อมต่อนั้นเสมอ รายละเอียดอยู่ใน `docs/protocol.md`

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

การทดสอบ GUI ต้องมี Tkinter และ display หากทดสอบบน Linux โดยไม่มีหน้าจอจริง ให้ใช้ Xvfb:

```bash
xvfb-run -a python3 -B -m unittest discover -s tests -v
```

เมื่อไม่มี display ชุดทดสอบ GUI จะข้ามตัวเอง ส่วนการทดสอบ protocol, Server และงานเครือข่ายยังรันได้ตามปกติ

การทดสอบต้องเปิด Socket ภายในเครื่อง หากรันผ่านเครื่องมือที่จำกัดสิทธิ์เปิด Socket อาจต้องอนุญาตการทดสอบก่อน

แผนหลักอยู่ใน [flow/part1.md](flow/part1.md) และ [flow/part2.md](flow/part2.md) ขั้นถัดไปคือห้องส่วนตัวและหน้าต่างแชต เก็บงาน Cloud ไว้หลังพัฒนา Part 2 การเดโมตามโจทย์ยังต้องใช้ Client บนคอมพิวเตอร์จริงคนละเครื่อง

โฟลเดอร์ `output/` ถูกละเว้นจาก Git และเตรียมไว้สำหรับกลุ่ม สมาชิก และประวัติในขั้นต่อไป ขั้นที่ 1–2 กำหนดขอบเขตข้อมูลไว้ในเอกสาร แต่ยังไม่บันทึกประวัติหรือสร้างกลุ่มจริง

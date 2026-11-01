# Socket Programming

โปรเจกต์แอปแชตด้วย Python 3 และ TCP Socket หน้าหลักเป็นเว็บ HTML + Tailwind CSS + JavaScript เชื่อมผ่าน Python bridge (`aiohttp`) ไปยัง TCP Server เดิม

## สถานะปัจจุบัน: Part 2 ขั้นที่ 1–3

หน้าเว็บเชื่อมต่อ Server ด้วยชื่อไม่ซ้ำ และแสดงรายชื่อออนไลน์ที่อัปเดตตามการเข้า ออก และหลุด รวมชื่อตัวเองด้วย แต่ละแท็บมี WebSocket, `NetworkClient`, คิว และ TCP Socket แยกกัน

หน้าเว็บเลือกคนจากรายชื่อเพื่อเปิดห้องส่วนตัว ส่งข้อความ และแสดงข้อความของทั้งสองฝ่ายได้ แต่ละคู่มี `room_id` เดียวกัน แต่ละห้องมีแท็บ ช่องพิมพ์ ข้อความร่าง และตัวนับข้อความใหม่แยกกัน รับข้อความในห้องอื่นได้โดยไม่บังคับสลับแท็บ ส่วนระบบกลุ่มเป็นขั้นถัดไป ปุ่ม Create group จึงยังปิดใช้งาน

Server เก็บห้องและประวัติส่วนตัวใน `output/chat_state.json` และคืนแท็บห้องเดิมเมื่อลงชื่อกลับมา เมื่อเลือกแท็บจึงขอประวัติของห้องนั้น การปิด Client หรือ Server ไม่ลบประวัติ คู่สนทนาออฟไลน์ยังเปิดห้องเก่าอ่านได้ แต่ส่งข้อความใหม่ไม่ได้ ชื่อที่ว่างแล้วถือเป็นตัวตนเดิมตามนโยบายที่ตกลง ระบบนี้ยังไม่มีรหัสผ่าน

หน้าเว็บใช้โทนมืดตามภาพตัวอย่าง แถบรายชื่อและกลุ่มอยู่ด้านซ้าย พื้นที่ห้องอยู่ด้านขวา พร้อมฟอร์มเชื่อมต่อและสถานะ Offline, Connecting, Online หรือ Error ปรับการเรียงเมื่อหน้าจอเล็ก ใช้ Tailwind CLI สร้าง CSS ภายในโปรเจกต์ โดยไม่พึ่ง CDN ระหว่างเปิดแอป ส่วน GUI Tkinter เดิมยังเก็บไว้เป็นตัวอย่าง

โค้ด ชื่อตัวแปร และข้อความที่โปรแกรมแสดงเป็นภาษาอังกฤษ ส่วนคอมเมนต์และคำอธิบายเป็นภาษาไทย ข้อความแชตที่ผู้ใช้ส่งยังรองรับ UTF-8 รวมถึงภาษาไทย

| ไฟล์ | หน้าที่ |
| --- | --- |
| `server.py` | รับหลาย Client เก็บชื่อ จัดการห้องส่วนตัว ตรวจสมาชิก และส่งต่อข้อความ |
| `state_store.py` | เก็บห้องและประวัติใน JSON ด้วย Lock และแทนไฟล์แบบ atomic |
| `client.py` | ลงชื่อ รับผู้รับและข้อความจากผู้ใช้ พร้อมแสดงข้อความเข้า |
| `web_bridge.py` | เสิร์ฟหน้าเว็บและเชื่อมแต่ละ WebSocket เข้ากับ NetworkClient ของแท็บนั้น |
| `web/index.html` | โครงหน้าเว็บและ Tailwind utility classes |
| `web/app.js` | ฟอร์ม WebSocket รายชื่อ แท็บห้อง ข้อความร่าง ประวัติ และสถานะบน Browser |
| `web/input.css` | นำเข้า Tailwind และกำหนดสีหลัก |
| `web/assets/styles.css` | CSS ที่สร้างด้วย build และถูกละเว้นจาก Git |
| `requirements.txt` | dependency Python สำหรับ bridge |
| `package.json`, `package-lock.json` | dependency และคำสั่ง Tailwind ที่ติดตั้งซ้ำได้ |
| `gui_client.py` | GUI Tkinter เดิม สำหรับดูตัวอย่าง main thread และ after() |
| `client_network.py` | งาน connect, receive และ send เบื้องหลัง โดยไม่เรียก widget |
| `protocol.py` | ส่งและรับ JSON แบบหนึ่งข้อความต่อหนึ่งบรรทัด |
| `tests/test_chat.py` | ทดสอบกติกาข้อความ การส่งต่อ และการทำงานพร้อมกัน |
| `tests/test_presence.py` | ทดสอบรายชื่อออนไลน์ ลำดับข้อมูล และการหยุดงานเครือข่าย |
| `tests/test_gui.py` | ทดสอบ Tkinter จริง รวมการตอบสนองของหน้าต่างระหว่างรอเครือข่าย |
| `tests/test_web_bridge.py` | ทดสอบหลาย session, WebSocket → TCP, ชื่อซ้ำ และการปิด Server/bridge |
| `tests/test_private_rooms.py` | ทดสอบสิทธิ์ห้อง การเปิดห้องพร้อมกัน ลำดับข้อความ และประวัติหลังเปิด Server ใหม่ |
| `tests/test_state_store.py` | ทดสอบไฟล์ประวัติ Unicode การเขียนพร้อมกัน และความล้มเหลวระหว่างบันทึก |
| `docs/protocol.md` | กติกา JSON คิวเหตุการณ์ และขอบเขตข้อมูลถาวรสำหรับขั้นต่อไป |

## เปิดหน้าเว็บบนเครื่องเดียว

เตรียม dependency ครั้งแรก (ต้องมี Python 3 และ Node.js/npm):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci
npm run build:css
```

Terminal แรกเปิด TCP Server:

```bash
python3 server.py
```

Terminal ที่สองเปิด Python bridge:

```bash
.venv/bin/python web_bridge.py
```

เปิด [http://127.0.0.1:3000](http://127.0.0.1:3000) ใน Browser สองแท็บ:

1. ใช้ Server address `127.0.0.1` และ Port `5000` ทั้งสองแท็บ
2. แท็บแรกตั้งชื่อ `alice` แท็บที่สองตั้งชื่อ `bob` แล้วกด Connect แต่ละแท็บเห็นรายชื่อครบ รวมตัวเองที่มี `(you)`
3. ลองชื่อซ้ำ จะเห็น Error และแก้ชื่อเพื่อกด Connect ใหม่ได้
4. กด Disconnect หรือปิดแท็บหนึ่ง รายชื่ออีกแท็บเปลี่ยนตามจริง
5. หยุด TCP Server ด้วย `Ctrl+C` เว็บล้างรายชื่อ แสดงเหตุผล และให้เชื่อมต่อใหม่ได้เมื่อ Server กลับมา
6. หยุด bridge ด้วย `Ctrl+C` จะปิดการเชื่อมต่อของแท็บที่ bridge นั้นดูแล ส่วน TCP Server ยังทำงาน

พอร์ต `3000` คือ HTTP/WebSocket ภายในเครื่อง ส่วนช่อง Port `5000` บนหน้าเว็บคือพอร์ต TCP Server เป็นคนละหน้าที่ หากพอร์ตเว็บถูกใช้แล้ว ให้รัน `.venv/bin/python web_bridge.py --port 3001` แล้วเปิด URL ของพอร์ตใหม่

### ทดลองห้องส่วนตัว (Step 3)

1. ลงชื่อ `alice`, `bob`, `carol` ในสามแท็บ
2. ที่ Alice คลิก Bob ใน Online users จะเปิดแท็บ Bob พร้อมช่องพิมพ์และปุ่ม Send
3. พิมพ์ข้อความแล้วกด Send หรือ Enter; Shift+Enter ใช้ขึ้นบรรทัดใหม่ ข้อความตัวเองอยู่ขวา ของอีกฝ่ายอยู่ซ้าย
4. ที่ Bob จะได้แท็บ Alice โดยอัตโนมัติและตอบกลับได้ ข้อความขึ้นจากเหตุการณ์ของ Server เพียงครั้งเดียว ไม่เพิ่มซ้ำเมื่อได้รับ `sent`
5. ที่ Alice เปิด Carol แล้วลองสลับห้อง ข้อความและข้อความร่างไม่ปนกัน ถ้า Bob ส่งระหว่างอ่าน Carol แท็บ Bob จะแสดงจำนวนข้อความใหม่ โดยไม่เปลี่ยนห้องที่กำลังอ่าน
6. ปิดแท็บ Bob: ห้อง Bob ที่ Alice ยังอ่านประวัติได้ แต่ช่องส่งปิด เมื่อ Bob กลับมาใช้ชื่อเดิมจะส่งต่อในห้องเดิมได้
7. ปิดและเปิด TCP Server ใหม่ แล้วเชื่อมต่อชื่อเดิม เลือกแท็บห้องเก่าเพื่อโหลดประวัติและคุยต่อ
8. Carol ต้องไม่ได้ห้องหรือเนื้อหาของ Alice–Bob แม้ส่ง JSON ขอเปิดหรือส่งเข้า `room_id` ของคู่นั้นเอง

Server บันทึกข้อความก่อนกระจายแบบสด ถ้าบันทึกล้มเหลวจะไม่แสดงว่าเป็นข้อความสำเร็จ และหน้าเว็บเก็บข้อความที่ส่งไม่สำเร็จให้กด Use unsent text กลับมาใช้ได้ หากบันทึกแล้วแต่ผู้รับหลุดระหว่างส่ง จะแจ้งว่า saved แต่ live delivery ไม่สำเร็จ โดยประวัติยังอยู่ ถ้าการเชื่อมต่อของผู้ส่งขาดกลางทาง ให้เปิดห้องตรวจประวัติก่อนส่งซ้ำ ระบบไม่ resend อัตโนมัติ

ข้อมูลจริงอยู่ที่ `output/chat_state.json` ซึ่งถูก ignore ส่วนชุดทดสอบใช้ไฟล์ชั่วคราวคนละชุดเพื่อไม่ปนกับประวัติของผู้ใช้ สามารถกำหนด `CHAT_STATE_PATH` เพื่อเลือกไฟล์ประวัติอื่นได้ หากไฟล์เดิมเสีย Server จะแจ้งข้อผิดพลาดและไม่เขียนทับด้วยประวัติว่าง

เมื่อแก้ utility classes ใน `web/index.html` หรือ `web/app.js` ให้รัน `npm run build:css` ใหม่ หรือเปิด `npm run watch:css` ใน Terminal แยกเพื่อสร้าง CSS ทุกครั้งที่แก้ แล้ว refresh หน้าเว็บ Node.js ใช้ตอน build สไตล์เท่านั้น การรันแอปใช้ Browser และ Python

### แผนการเปิดข้ามเครื่อง

แต่ละเครื่อง Client รัน bridge ของตัวเองและเปิด `http://127.0.0.1:3000` ภายในเครื่อง จากนั้นกรอก IP จริงของเครื่อง TCP Server ในช่อง Server address ตัว bridge รับเฉพาะ loopback ส่วน TCP Server ต้องเปิดรับจากเครือข่ายตามแผน Part 1 (ปัจจุบัน `server.py` ยัง bind ที่ `127.0.0.1` สำหรับการทดสอบเครื่องเดียว)

```text
Browser A <-> local bridge A <-> TCP socket A <-> TCP Server
Browser B <-> local bridge B <-> TCP socket B <-> TCP Server
```

## เปิด GUI Tkinter เดิม (ทางเลือก)

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

สำหรับ `NetworkClient` ที่ทั้งเว็บและ Tkinter ใช้ มี sender thread และ receiver thread แยกกัน เพื่อไม่ให้ `connect()` หรือ `sendall()` ขวางงานหน้าจอ เส้นทางเว็บคือ:

```text
Browser -> WebSocket -> bridge async handler -> outgoing queue -> sender thread -> TCP
TCP -> receiver thread -> events queue -> bridge async task -> WebSocket -> Browser DOM
```

งาน async ของ bridge แชร์ event loop เดียวกัน ไม่ได้เป็น Python thread ใหม่ต่อแท็บ แต่ละ session มี worker รับและส่งสอง thread ของตัวเอง และแต่ละ TCP Socket ใช้ส่งและรับได้พร้อมกัน เมื่อปิด session จะมีการรอ worker จบผ่าน executor เพื่อไม่ขวาง event loop ส่วน JavaScript ทำงานใน Browser คนละ process

สำหรับ Tkinter เดิมมีสามงานหลักต่อ Client ที่เชื่อมต่อ:

```text
GUI main thread -> outgoing queue -> sender thread -> socket
Socket -> receiver thread -> events queue -> GUI main thread -> widgets
```

`after()` และ Queue ไม่ได้สร้าง thread เพิ่ม Tkinter ตรวจคิวด้วย `get_nowait()` รอบละไม่เกิน 100 เหตุการณ์แล้วนัดตรวจครั้งถัดไปในประมาณ 100 มิลลิวินาที ส่วน bridge ตรวจคิวแบบไม่รอรอบละไม่เกิน 100 เหตุการณ์แล้วคืนเวลาให้ event loop ประมาณ 20 มิลลิวินาที

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
.venv/bin/python -B -m unittest discover -s tests -v
```

ทดสอบการแบ่งและรวมข้อความ UTF-8 ชื่อซ้ำ การส่งส่วนตัว การรับระหว่างรอพิมพ์ การส่งพร้อมกัน การนำชื่อกลับมาใช้ และการปิด Server รวมถึง WebSocket bridge หลาย session และการปิดแท็บ/bridge โดยใช้พอร์ตว่างอัตโนมัติสำหรับการทดสอบ ไม่รบกวน Server ที่พอร์ต `5000` หากไม่ได้ติดตั้ง aiohttp ชุดทดสอบ bridge จะข้ามตัวเอง

การทดสอบ GUI ต้องมี Tkinter และ display หากทดสอบบน Linux โดยไม่มีหน้าจอจริง ให้ใช้ Xvfb:

```bash
xvfb-run -a .venv/bin/python -B -m unittest discover -s tests -v
```

เมื่อไม่มี display ชุดทดสอบ GUI จะข้ามตัวเอง ส่วนการทดสอบ protocol, Server และงานเครือข่ายยังรันได้ตามปกติ

การทดสอบต้องเปิด Socket ภายในเครื่อง หากรันผ่านเครื่องมือที่จำกัดสิทธิ์เปิด Socket อาจต้องอนุญาตการทดสอบก่อน

ผลตรวจ Step 3: ผ่านการทดสอบรวม 45 กรณี (รวม Tkinter เดิมเมื่อใช้ Xvfb) ครอบคลุมห้องเดียวต่อคู่ การปฏิเสธคนนอกห้อง การส่งพร้อมกัน การบันทึกแบบ atomic ประวัติข้ามการเปิด Server ใหม่ และผู้รับหลุดหลังบันทึกข้อความ รวมถึง build Tailwind/ตรวจ syntax JavaScript ผ่าน ทดลอง Browser จริงสามแท็บส่งตอบกลับ แยกข้อความและข้อความร่าง แจ้งข้อความใหม่โดยไม่สลับห้อง คู่สนทนาออฟไลน์ และคืนประวัติเมื่อกลับมาใช้ชื่อเดิม ตรวจภาษาไทย/หลายบรรทัดและ layout เดสก์ท็อป 1280 × 900 กับมือถือ 390 × 844 แล้ว

แผนหลักอยู่ใน [flow/part1.md](flow/part1.md) และ [flow/part2.md](flow/part2.md) ขั้นถัดไปคือสร้างและแสดงรายการกลุ่ม เก็บงาน Cloud ไว้หลังพัฒนา Part 2 การเดโมตามโจทย์ยังต้องใช้ Client บนคอมพิวเตอร์จริงคนละเครื่อง

โฟลเดอร์ `output/` ถูกละเว้นจาก Git ปัจจุบันบันทึกห้องและประวัติส่วนตัวแล้ว ส่วนกลุ่มและนโยบายสมาชิกกลุ่มจะเพิ่มในขั้นถัดไป

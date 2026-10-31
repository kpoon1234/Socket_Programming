"""กติกาข้อความร่วมกัน: JSON หนึ่งข้อความต่อหนึ่งบรรทัด เข้ารหัส UTF-8."""

import json

BUFFER_SIZE = 4096


def send_message(connection, message):
    """แปลง dictionary เป็น JSON และส่งพร้อมตัวจบบรรทัด."""
    text = json.dumps(message, ensure_ascii=False)
    connection.sendall((text + "\n").encode("utf-8"))


def receive_messages(connection):
    """ทยอยคืน dictionary เมื่อรับข้อความครบ โดยเก็บส่วนที่เหลือไว้ใน buffer."""
    buffer = b""

    while True:
        data = connection.recv(BUFFER_SIZE)
        if not data:
            if buffer:
                raise ValueError("การเชื่อมต่อจบก่อนรับข้อความครบหนึ่งบรรทัด")
            return

        buffer += data
        while b"\n" in buffer:
            # แยกเพียงบรรทัดแรก ส่วนที่เหลือเก็บไว้รอรอบถัดไป
            line, _, buffer = buffer.partition(b"\n")
            try:
                # decode เมื่อครบข้อความแล้ว เพื่อไม่ตัดกลางตัวอักษร UTF-8
                message = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("ข้อความต้องเป็น JSON ที่เข้ารหัส UTF-8 ถูกต้อง") from error

            if not isinstance(message, dict):
                raise ValueError("ข้อความ JSON ต้องเป็น object เช่น {\"type\": \"message\"}")

            # yield คืนข้อความทีละรายการ และจำ buffer ไว้สำหรับการเรียกครั้งถัดไป
            yield message

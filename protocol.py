"""Exchange newline-delimited JSON objects encoded as UTF-8."""

import json

BUFFER_SIZE = 4096


def send_message(connection, message):
    """Send one dictionary as a complete JSON line."""
    text = json.dumps(message, ensure_ascii=False)
    connection.sendall((text + "\n").encode("utf-8"))


def receive_messages(connection):
    """Yield complete dictionaries while keeping incomplete bytes in a buffer."""
    buffer = b""

    while True:
        data = connection.recv(BUFFER_SIZE)
        if not data:
            if buffer:
                raise ValueError("Connection ended before a complete JSON line was received.")
            return

        buffer += data
        while b"\n" in buffer:
            # แยกเพียงบรรทัดแรก ส่วนที่เหลือเก็บไว้รอรอบถัดไป
            line, _, buffer = buffer.partition(b"\n")
            try:
                # decode เมื่อครบข้อความแล้ว เพื่อไม่ตัดกลางตัวอักษร UTF-8
                message = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("Messages must be valid JSON encoded as UTF-8.") from error

            if not isinstance(message, dict):
                raise ValueError("Each JSON message must be an object.")

            # yield คืนข้อความทีละรายการ และจำ buffer ไว้สำหรับการเรียกครั้งถัดไป
            yield message

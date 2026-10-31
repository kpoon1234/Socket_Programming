"""ขั้นที่ 3: ลงทะเบียนชื่อ แล้วส่งข้อความ JSON ได้หลายครั้งบน Socket เดิม."""

import socket

from protocol import receive_messages, send_message

HOST = "127.0.0.1"  # เชื่อมต่อ Server ที่อยู่บนเครื่องเดียวกัน
PORT = 5000


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.connect((HOST, PORT))
        print(f"เชื่อมต่อ Server ที่ {HOST}:{PORT} แล้ว")

        name = input("ชื่อของคุณ: ").strip()
        while not name:
            name = input("ชื่อต้องไม่ว่าง กรุณาพิมพ์ใหม่: ").strip()

        send_message(client, {"type": "register", "name": name})
        # สร้างตัวรับเพียงครั้งเดียว เพื่อเก็บ buffer เดิมตลอดการเชื่อมต่อ
        messages = receive_messages(client)
        response = next(messages, None)
        if response is None:
            raise ConnectionError("Server ปิดการเชื่อมต่อก่อนตอบรับชื่อ")
        if response.get("type") != "registered":
            raise ValueError(response.get("text", "Server ไม่ตอบรับการลงทะเบียนชื่อ"))

        print(f"ลงทะเบียนเป็น {response['name']} แล้ว พิมพ์ /quit เพื่อออก")
        while True:
            text = input("พิมพ์ข้อความถึง Server: ")
            if text == "/quit":
                break

            send_message(client, {"type": "message", "text": text})
            response = next(messages, None)
            if response is None:
                raise ConnectionError("Server ปิดการเชื่อมต่อก่อนตอบข้อความ")

            if response.get("type") == "message":
                print(f"คำตอบจาก Server: {response['text']}")
            elif response.get("type") == "error":
                print(f"Server แจ้งข้อผิดพลาด: {response['text']}")
            else:
                raise ValueError("ได้รับชนิดคำตอบที่ไม่รู้จักจาก Server")

    print("ปิดการเชื่อมต่อแล้ว")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nหยุด Client แล้ว")
    except OSError as error:
        print(f"Client ทำงานไม่สำเร็จ: {error}")
        raise SystemExit(1)
    except ValueError as error:
        print(f"ข้อมูลจาก Server ไม่ถูกต้อง: {error}")
        raise SystemExit(1)

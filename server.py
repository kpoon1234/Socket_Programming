"""ขั้นที่ 3: รับลงทะเบียนชื่อและตอบข้อความ JSON บนการเชื่อมต่อเดิม."""

import socket

from protocol import receive_messages, send_message

HOST = "127.0.0.1"  # รับเฉพาะการเชื่อมต่อภายในเครื่องนี้
PORT = 5000


def handle_client(connection):
    # ชื่อนี้ผูกกับ Socket ที่กำลังคุยอยู่ ไม่เชื่อชื่อผู้ส่งในข้อความแต่ละรอบ
    client_name = None

    try:
        for message in receive_messages(connection):
            message_type = message.get("type")

            if client_name is None:
                if message_type != "register":
                    send_message(connection, {"type": "error", "text": "ต้อง register ชื่อก่อนส่งข้อความ"})
                    continue

                name = message.get("name")
                if not isinstance(name, str) or not name.strip():
                    send_message(connection, {"type": "error", "text": "ชื่อต้องเป็นข้อความที่ไม่ว่าง"})
                    continue

                client_name = name.strip()
                print(f"ลงทะเบียนชื่อแล้ว: {client_name}")
                send_message(connection, {"type": "registered", "name": client_name})

            elif message_type == "message":
                text = message.get("text")
                if not isinstance(text, str):
                    send_message(connection, {"type": "error", "text": "text ต้องเป็นข้อความ"})
                    continue

                print(f"{client_name} ส่งมา: {text}")
                send_message(connection, {
                    "type": "message",
                    "from": "server",
                    "to": client_name,
                    "text": f"Server ได้รับข้อความจาก {client_name}: {text}",
                })

            else:
                send_message(connection, {"type": "error", "text": "คำสั่งนี้ใช้ไม่ได้หลังลงทะเบียนชื่อแล้ว"})

    except ValueError as error:
        # JSON ผิดหรือข้อความไม่ครบ: แจ้งสาเหตุ แล้วจบการเชื่อมต่อนี้
        send_message(connection, {"type": "error", "text": str(error)})
        print(f"ข้อมูลจาก Client ไม่ถูกต้อง: {error}")

def main():
    # AF_INET คือ IPv4 และ SOCK_STREAM คือ TCP
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        # ช่วยให้เปิด Server ใหม่ได้หลังจบการทดสอบรอบก่อน
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen()
        print(f"Server รอ Client ที่ {HOST}:{PORT}")

        # accept() จะรอจนมี Client เชื่อมต่อ แล้วคืน Socket สำหรับคุยกับคนนั้น
        connection, address = server.accept()
        with connection:
            print(f"Client เชื่อมต่อแล้ว: {address}")

            handle_client(connection)

    print("Client ออกจากการเชื่อมต่อแล้ว จบการทดสอบ Server")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nหยุด Server แล้ว")
    except OSError as error:
        print(f"Server ทำงานไม่สำเร็จ: {error}")
        raise SystemExit(1)

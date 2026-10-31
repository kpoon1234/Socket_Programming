"""ขั้นที่ 2: รับหนึ่งข้อความจาก Client แล้วตอบกลับผ่าน TCP Socket."""

import socket

HOST = "127.0.0.1"  # รับเฉพาะการเชื่อมต่อภายในเครื่องนี้
PORT = 5000
BUFFER_SIZE = 4096

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

            chunks = []
            while True:
                data = connection.recv(BUFFER_SIZE)
                if not data:
                    # Client ปิดเฉพาะฝั่งส่ง เป็นสัญญาณว่าส่งข้อความครบแล้ว
                    break
                chunks.append(data)

            # รวมไบต์ให้ครบก่อน decode เพราะตัวอักษรไทยอาจถูกแบ่งระหว่าง recv()
            message = b"".join(chunks).decode("utf-8")
            print(f"Client ส่งมา: {message}")

            reply = f"Server ได้รับข้อความแล้ว: {message}"
            connection.sendall(reply.encode("utf-8"))
            print("Server ส่งคำตอบกลับแล้ว")

        # ออกจาก with จะปิด Socket ทำให้ Client รู้ว่าได้รับคำตอบครบแล้ว
    print("Server จบการทดสอบหนึ่งข้อความแล้ว")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nหยุด Server แล้ว")
    except OSError as error:
        print(f"Server ทำงานไม่สำเร็จ: {error}")
        raise SystemExit(1)

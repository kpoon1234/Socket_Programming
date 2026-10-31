"""ขั้นที่ 2: ส่งหนึ่งข้อความให้ Server แล้วแสดงคำตอบที่ได้รับ."""

import socket

HOST = "127.0.0.1"  # เชื่อมต่อ Server ที่อยู่บนเครื่องเดียวกัน
PORT = 5000
BUFFER_SIZE = 4096

def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.connect((HOST, PORT))
        print(f"เชื่อมต่อ Server ที่ {HOST}:{PORT} แล้ว")

        message = input("พิมพ์ข้อความถึง Server: ")
        client.sendall(message.encode("utf-8"))

        # บอก Server ว่าส่งครบแล้ว โดยยังเปิดฝั่งรับไว้รอคำตอบ
        client.shutdown(socket.SHUT_WR)

        chunks = []
        while True:
            data = client.recv(BUFFER_SIZE)
            if not data:
                # Server ปิดการเชื่อมต่อเมื่อส่งคำตอบครบแล้ว
                break
            chunks.append(data)

        reply = b"".join(chunks).decode("utf-8")
        print(f"คำตอบจาก Server: {reply}")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nหยุด Client แล้ว")
    except OSError as error:
        print(f"Client ทำงานไม่สำเร็จ: {error}")
        raise SystemExit(1)

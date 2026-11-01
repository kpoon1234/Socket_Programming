"""Send and receive private messages through the TCP server."""

import socket
import threading

from protocol import receive_messages, send_message

HOST = "127.0.0.1"
PORT = 5000


def register(client, messages):
    while True:
        name = input("Name: ").strip()
        if not name:
            print("Name must not be empty.")
            continue

        send_message(client, {"type": "register", "name": name})
        response = next(messages, None)
        if response is None:
            raise ConnectionError("Server disconnected before registration completed.")
        if response.get("type") == "registered":
            print(f"Registered as {response['name']}.")
            return
        if response.get("type") == "error":
            print(f"Error: {response['text']}")
        else:
            raise ValueError("Unexpected registration response.")


def receive_from_server(messages, stopped):
    last_users_version = -1
    try:
        # หลังลงทะเบียนแล้ว มี thread นี้เพียงตัวเดียวที่อ่าน Socket
        for message in messages:
            if stopped.is_set():
                return
            message_type = message.get("type")
            if message_type == "message":
                print(f"\n[{message['from']} -> {message['to']}] {message['text']}", flush=True)
            elif message_type == "sent":
                print(f"\n[Sent to {message['to']}]", flush=True)
            elif message_type == "error":
                print(f"\nError: {message['text']}", flush=True)
            elif message_type == "users_updated":
                if message["version"] > last_users_version:
                    last_users_version = message["version"]
                    print(f"\nOnline users: {', '.join(message['users'])}", flush=True)
            else:
                raise ValueError("Unexpected message type from server.")
    except (OSError, ValueError) as error:
        if not stopped.is_set():
            print(f"\nReceive error: {error}", flush=True)
    finally:
        if not stopped.is_set():
            print("\nServer disconnected. Press Enter to exit.", flush=True)
        stopped.set()


def main():
    stopped = threading.Event()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.connect((HOST, PORT))
        print(f"Connected to {HOST}:{PORT}.")
        # ใช้ generator เดิมทั้งตอนลงชื่อและใน thread เพื่อไม่ทิ้งข้อมูลใน buffer
        messages = receive_messages(client)
        register(client, messages)

        receiver = threading.Thread(
            target=receive_from_server, args=(messages, stopped), daemon=True
        )
        receiver.start()
        print("Enter a recipient and a message. Type /quit at Recipient to exit.")
        try:
            while not stopped.is_set():
                recipient = input("Recipient (/quit to exit): ").strip()
                if stopped.is_set() or recipient == "/quit":
                    break
                if not recipient:
                    print("Recipient must not be empty.")
                    continue

                text = input("Message: ")
                if stopped.is_set():
                    break
                send_message(client, {"type": "message", "to": recipient, "text": text})
        finally:
            stopped.set()
            try:
                # ปลุก thread ที่รอ recv ให้หยุด ก่อนออกจากโปรแกรม
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            receiver.join()
    print("Disconnected.")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nClient stopped.")
    except (OSError, ValueError) as error:
        print(f"Client error: {error}")
        raise SystemExit(1)

"""Connect to the chat server and display its live online users list."""

import queue
import tkinter as tk
from tkinter import ttk

from client_network import NetworkClient


class ChatApp:
    def __init__(self, root):
        self.root = root
        self.network = None
        self.closing = False
        self.registered = False
        self.current_name = None
        self.online_users = []
        self.last_users_version = -1
        self.poll_id = None

        root.title("Socket Chat")
        root.geometry("900x560")
        root.minsize(680, 440)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.host_var = tk.StringVar(value="127.0.0.1")
        self.port_var = tk.StringVar(value="5000")
        self.name_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Disconnected.")
        self.users_title = tk.StringVar(value="Online users (0)")
        self.build_widgets()
        self.poll_id = root.after(100, self.poll_events)

    def build_widgets(self):
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill="both", expand=True)

        connection_form = ttk.LabelFrame(container, text="Connection", padding=10)
        connection_form.pack(fill="x", pady=(0, 12))
        connection_form.columnconfigure(0, weight=2)
        connection_form.columnconfigure(2, weight=2)
        for column, text in enumerate(("Server", "Port", "Name")):
            ttk.Label(connection_form, text=text).grid(row=0, column=column, sticky="w")

        self.host_entry = ttk.Entry(connection_form, textvariable=self.host_var, width=24)
        self.port_entry = ttk.Entry(connection_form, textvariable=self.port_var, width=8)
        self.name_entry = ttk.Entry(connection_form, textvariable=self.name_var, width=20)
        for column, entry in enumerate((self.host_entry, self.port_entry, self.name_entry)):
            entry.grid(row=1, column=column, sticky="ew", padx=(0, 10), pady=(4, 10))
        self.name_entry.bind("<Return>", lambda event: self.connect())

        actions = ttk.Frame(connection_form)
        actions.grid(row=2, column=0, columnspan=3, sticky="w")
        self.connect_button = ttk.Button(actions, text="Connect", command=self.connect)
        self.connect_button.pack(side="left")
        self.disconnect_button = ttk.Button(
            actions, text="Disconnect", command=self.disconnect, state="disabled"
        )
        self.disconnect_button.pack(side="left", padx=(8, 0))

        body = ttk.Frame(container)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(body, width=230)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        users_frame = ttk.LabelFrame(sidebar, text="Online users", padding=8)
        users_frame.pack(fill="both", expand=True)
        ttk.Label(users_frame, textvariable=self.users_title).pack(anchor="w", pady=(0, 6))
        users_row = ttk.Frame(users_frame)
        users_row.pack(fill="both", expand=True)
        self.users_list = tk.Listbox(users_row, exportselection=False, height=8)
        self.users_list.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(users_row, orient="vertical", command=self.users_list.yview)
        scrollbar.pack(side="right", fill="y")
        self.users_list.configure(yscrollcommand=scrollbar.set)

        groups_frame = ttk.LabelFrame(sidebar, text="Groups", padding=8)
        groups_frame.pack(fill="x", pady=(10, 0))
        ttk.Label(groups_frame, text="No groups available.").pack(anchor="w")
        group_actions = ttk.Frame(groups_frame)
        group_actions.pack(anchor="w", pady=(8, 0))
        ttk.Button(group_actions, text="Create", state="disabled").pack(side="left")
        ttk.Button(group_actions, text="Join", state="disabled").pack(side="left", padx=(6, 0))

        self.rooms_notebook = ttk.Notebook(body)
        self.rooms_notebook.grid(row=0, column=1, sticky="nsew")
        empty_room = ttk.Frame(self.rooms_notebook, padding=20)
        self.rooms_notebook.add(empty_room, text="Rooms")
        ttk.Label(empty_room, text="No chat room open.").pack(anchor="center", pady=30)

        ttk.Label(container, textvariable=self.status_var, wraplength=630).pack(
            anchor="w", fill="x", pady=(12, 0)
        )
        self.name_entry.focus_set()

    def set_controls(self, busy):
        state = "disabled" if busy else "normal"
        for widget in (self.host_entry, self.port_entry, self.name_entry, self.connect_button):
            widget.configure(state=state)
        self.disconnect_button.configure(state="normal" if busy else "disabled")

    def clear_users(self):
        self.online_users = []
        self.users_list.delete(0, tk.END)
        self.users_title.set("Online users (0)")
        self.last_users_version = -1

    def connect(self):
        if self.closing or (self.network is not None and not self.network.stopped.is_set()):
            return
        host = self.host_var.get().strip()
        name = self.name_var.get().strip()
        if not host or not name:
            self.status_var.set("Enter a server address and a name.")
            return
        try:
            port = int(self.port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.status_var.set("Port must be a number between 1 and 65535.")
            return

        self.registered = False
        self.current_name = None
        self.clear_users()
        self.set_controls(busy=True)
        self.status_var.set(f"Connecting to {host}:{port}...")
        self.network = NetworkClient()
        # connect สร้างงานเบื้องหลังและคืนทันที ไม่รอเครือข่ายในงาน GUI
        self.network.connect(host, port, name)

    def disconnect(self):
        if self.network is not None:
            self.network.close()
        self.registered = False
        self.current_name = None
        self.clear_users()
        self.set_controls(busy=False)
        self.status_var.set("Disconnected.")

    def poll_events(self):
        if self.closing:
            return
        if self.network is not None:
            # จำกัดงานต่อรอบ เพื่อคืนเวลาให้การคลิก การพิมพ์ และวาดหน้าต่าง
            for _ in range(100):
                try:
                    event = self.network.events.get_nowait()
                except queue.Empty:
                    break
                if self.network.stopped.is_set() and event.get("type") != "disconnected":
                    continue
                self.handle_event(event)
        self.poll_id = self.root.after(100, self.poll_events)

    def handle_event(self, event):
        # ฟังก์ชันนี้ถูกเรียกจาก poll_events ใน main thread เท่านั้น
        event_type = event.get("type")
        if event_type == "connected":
            self.status_var.set("Connected. Registering name...")
        elif event_type == "registered":
            self.registered = True
            self.current_name = event["name"]
            self.status_var.set(f"Connected as {self.current_name}.")
        elif event_type == "users_updated":
            if event["version"] <= self.last_users_version:
                return
            self.last_users_version = event["version"]
            self.online_users = list(event["users"])
            self.users_list.delete(0, tk.END)
            for name in self.online_users:
                label = f"{name} (you)" if name == self.current_name else name
                self.users_list.insert(tk.END, label)
            self.users_title.set(f"Online users ({len(self.online_users)})")
        elif event_type == "error":
            self.status_var.set(f"Error: {event['text']}")
            if not self.registered:
                self.network.close(reason=f"Error: {event['text']}")
                self.set_controls(busy=False)
        elif event_type == "disconnected":
            self.registered = False
            self.current_name = None
            self.clear_users()
            self.set_controls(busy=False)
            self.status_var.set(event["text"])

    def close(self):
        self.closing = True
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
        if self.network is not None:
            self.network.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    ChatApp(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except tk.TclError as error:
        print(f"GUI error: {error}")
        raise SystemExit(1)

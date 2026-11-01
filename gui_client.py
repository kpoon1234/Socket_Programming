"""Connect to the chat server and display its live online users list."""

import queue
import tkinter as tk
from tkinter import ttk

from client_network import NetworkClient


COLORS = {
    "background": "#F3F6F4", "surface": "#FFFFFF", "ink": "#203B34",
    "muted": "#718079", "border": "#DDE5DF", "accent": "#216C53",
    "sidebar": "#17392F", "sidebar_text": "#ECF4EF", "sidebar_muted": "#A7C1B4",
}
FONT = "DejaVu Sans"


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
        root.geometry("1100x740")
        root.minsize(900, 640)
        root.configure(background=COLORS["background"])
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.host_var = tk.StringVar(value="127.0.0.1")
        self.port_var = tk.StringVar(value="5000")
        self.name_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Disconnected.")
        self.connection_state = tk.StringVar(value="Offline")
        self.identity_var = tk.StringVar(value="Not connected")
        self.empty_hint = tk.StringVar(value="Connect to see who is online.")
        self.users_title = tk.StringVar(value="Online users (0)")
        self.configure_styles()
        self.build_widgets()
        self.poll_id = root.after(100, self.poll_events)

    def configure_styles(self):
        # ใช้ theme เดียวกันทุกระบบ แล้วกำหนดสีและระยะห่างส่วนกลาง
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=COLORS["background"])
        style.configure("Card.TFrame", background=COLORS["surface"])
        style.configure("TLabel", background=COLORS["background"], foreground=COLORS["ink"], font=(FONT, 10))
        style.configure("Card.TLabel", background=COLORS["surface"])
        style.configure("Field.TLabel", background=COLORS["surface"], foreground=COLORS["muted"], font=(FONT, 9))
        style.configure("Title.TLabel", font=(FONT, 23, "bold"))
        style.configure("Muted.TLabel", foreground=COLORS["muted"])
        style.configure("TEntry", padding=(10, 9), font=(FONT, 10),
                        fieldbackground=COLORS["background"], foreground=COLORS["ink"],
                        bordercolor=COLORS["border"], lightcolor=COLORS["border"], darkcolor=COLORS["border"])
        style.map("TEntry", bordercolor=[("focus", COLORS["accent"])],
                  foreground=[("disabled", COLORS["muted"])],
                  lightcolor=[("focus", COLORS["accent"])], darkcolor=[("focus", COLORS["accent"])])
        style.configure("TButton", font=(FONT, 10), padding=(14, 9), borderwidth=0,
                        background="#E6ECE7", foreground=COLORS["ink"], focusthickness=0)
        style.map("TButton", background=[("disabled", "#EDF0ED"), ("active", "#D8E3DB")],
                  foreground=[("disabled", "#9BA99F")])
        style.configure("Accent.TButton", background=COLORS["accent"], foreground="white")
        style.map("Accent.TButton", background=[("disabled", "#DDE5DF"), ("active", "#19563F")],
                  foreground=[("disabled", "#8B9E91")])
        style.configure("Sidebar.TButton", background="#284C3E", foreground=COLORS["sidebar_text"], padding=(10, 8))
        style.map("Sidebar.TButton", background=[("disabled", "#234437")],
                  foreground=[("disabled", "#829F8C")])
        style.configure("Rooms.TNotebook", background=COLORS["surface"], borderwidth=0, tabmargins=(18, 14, 0, 0),
                        bordercolor=COLORS["surface"], lightcolor=COLORS["surface"], darkcolor=COLORS["surface"])
        style.configure("Rooms.TNotebook.Tab", padding=(18, 9), font=(FONT, 10), borderwidth=0)
        style.map("Rooms.TNotebook.Tab", background=[("selected", "#EAF2EC"), ("!selected", COLORS["surface"])],
                  foreground=[("selected", COLORS["accent"])], bordercolor=[("selected", "#EAF2EC")],
                  lightcolor=[("selected", "#EAF2EC")], darkcolor=[("selected", "#EAF2EC")])
        style.configure("Sidebar.Vertical.TScrollbar", background="#426252", troughcolor=COLORS["sidebar"],
                        borderwidth=0, arrowsize=11)

    def build_widgets(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.build_sidebar()
        workspace = ttk.Frame(self.root, padding=(28, 28, 28, 18))
        workspace.grid(row=0, column=1, sticky="nsew")
        header = ttk.Frame(workspace)
        header.pack(fill="x", pady=(0, 24))
        ttk.Label(header, text="YOUR WORKSPACE", style="Muted.TLabel", font=(FONT, 9, "bold")).pack(anchor="w")
        title_row = ttk.Frame(header)
        title_row.pack(fill="x", pady=(6, 6))
        ttk.Label(title_row, text="A space to connect.", style="Title.TLabel").pack(side="left")
        self.state_badge = tk.Label(title_row, textvariable=self.connection_state, font=(FONT, 9, "bold"),
                                    background="#E4EAE5", foreground=COLORS["muted"], padx=12, pady=6)
        self.state_badge.pack(side="right", padx=(12, 0))
        ttk.Label(header, text="Your people, your groups, one place to connect.", style="Muted.TLabel").pack(anchor="w")
        self.build_connection_form(workspace)

        rooms_card = tk.Frame(workspace, background=COLORS["surface"], highlightbackground=COLORS["border"],
                              highlightcolor=COLORS["border"], highlightthickness=1)
        rooms_card.pack(fill="both", expand=True, pady=(20, 16))
        room_header = ttk.Frame(rooms_card, style="Card.TFrame", padding=(22, 18))
        room_header.pack(fill="x")
        ttk.Label(room_header, text="Conversations", style="Card.TLabel", font=(FONT, 12, "bold")).pack(side="left")
        ttk.Label(room_header, text="PRIVATE / GROUP", style="Field.TLabel", font=(FONT, 8, "bold")).pack(side="right")
        tk.Frame(rooms_card, background=COLORS["border"], height=1).pack(fill="x")
        self.rooms_notebook = ttk.Notebook(rooms_card, style="Rooms.TNotebook")
        self.rooms_notebook.pack(fill="both", expand=True)
        empty_room = ttk.Frame(self.rooms_notebook, style="Card.TFrame")
        self.rooms_notebook.add(empty_room, text="Overview")
        empty_content = ttk.Frame(empty_room, style="Card.TFrame")
        empty_content.place(relx=0.5, rely=0.5, anchor="center")
        self.build_chat_icon(empty_content)
        empty_text = ttk.Frame(empty_content, style="Card.TFrame")
        empty_text.pack(side="left")
        ttk.Label(empty_text, text="No conversations yet", style="Card.TLabel", font=(FONT, 17, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(empty_text, textvariable=self.empty_hint, style="Field.TLabel", font=(FONT, 10),
                  wraplength=300, justify="left").pack(anchor="w")
        ttk.Label(workspace, textvariable=self.status_var, style="Muted.TLabel", wraplength=560).pack(anchor="w")
        self.name_entry.focus_set()

    def build_sidebar(self):
        sidebar = tk.Frame(self.root, background=COLORS["sidebar"], width=246)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(2, weight=1)
        brand = tk.Frame(sidebar, background=COLORS["sidebar"])
        brand.grid(row=0, column=0, sticky="ew", padx=24, pady=(30, 26))
        tk.Label(brand, text="S", font=(FONT, 18, "bold"), background="#D8EDB9", foreground=COLORS["sidebar"],
                 padx=11, pady=3).pack(side="left", padx=(0, 12))
        tk.Label(brand, text="Socket", font=(FONT, 22, "bold"), background=COLORS["sidebar"],
                 foreground=COLORS["sidebar_text"]).pack(side="left")
        tk.Frame(sidebar, background="#345347", height=1).grid(row=1, column=0, sticky="ew", padx=24)

        people = tk.Frame(sidebar, background=COLORS["sidebar"])
        people.grid(row=2, column=0, sticky="nsew", padx=18, pady=(24, 12))
        tk.Label(people, textvariable=self.users_title, font=(FONT, 10, "bold"), background=COLORS["sidebar"],
                 foreground=COLORS["sidebar_text"]).pack(anchor="w", padx=6, pady=(0, 12))
        users_row = tk.Frame(people, background=COLORS["sidebar"])
        users_row.pack(fill="both", expand=True)
        self.users_list = tk.Listbox(users_row, exportselection=False, height=4, width=16, font=(FONT, 12),
                                     background=COLORS["sidebar"], foreground=COLORS["sidebar_text"],
                                     selectbackground="#345D48", selectforeground="white", activestyle="none",
                                     borderwidth=0, highlightthickness=0, relief="flat")
        self.users_list.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(users_row, orient="vertical", command=self.users_list.yview, style="Sidebar.Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y")
        self.users_list.configure(yscrollcommand=scrollbar.set)
        self.users_empty = tk.Label(users_row, text="Nobody online yet.\nConnect to get started.", justify="left",
                                    background=COLORS["sidebar"], foreground=COLORS["sidebar_muted"], font=(FONT, 9))
        self.users_empty.place(x=6, y=4)

        groups = tk.Frame(sidebar, background=COLORS["sidebar"])
        groups.grid(row=3, column=0, sticky="ew", padx=24, pady=(12, 24))
        tk.Frame(groups, background="#345347", height=1).pack(fill="x", pady=(0, 22))
        tk.Label(groups, text="Groups", font=(FONT, 10, "bold"), background=COLORS["sidebar"],
                 foreground=COLORS["sidebar_text"]).pack(anchor="w")
        tk.Label(groups, text="No groups yet", font=(FONT, 9), background=COLORS["sidebar"],
                 foreground=COLORS["sidebar_muted"]).pack(anchor="w", pady=(10, 14))
        actions = tk.Frame(groups, background=COLORS["sidebar"])
        actions.pack(fill="x")
        ttk.Button(actions, text="+ Create", state="disabled", style="Sidebar.TButton", width=8).pack(side="left")
        ttk.Button(actions, text="Join", state="disabled", style="Sidebar.TButton", width=5).pack(side="right")
        profile = tk.Frame(sidebar, background="#102E24", padx=24, pady=18)
        profile.grid(row=4, column=0, sticky="ew")
        tk.Label(profile, text="YOUR SESSION", font=(FONT, 8, "bold"), background="#102E24",
                 foreground=COLORS["sidebar_muted"]).pack(anchor="w")
        tk.Label(profile, textvariable=self.identity_var, font=(FONT, 10), background="#102E24",
                 foreground=COLORS["sidebar_text"], wraplength=190, justify="left").pack(anchor="w", pady=(6, 0))

    def build_connection_form(self, parent):
        border = tk.Frame(parent, background=COLORS["surface"], highlightbackground=COLORS["border"],
                          highlightcolor=COLORS["border"], highlightthickness=1)
        border.pack(fill="x")
        form = ttk.Frame(border, style="Card.TFrame", padding=20)
        form.pack(fill="x")
        ttk.Label(form, text="Connect to your server", style="Card.TLabel", font=(FONT, 11, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 16))
        for column, title in enumerate(("Server address", "Port", "Your name")):
            ttk.Label(form, text=title, style="Field.TLabel").grid(row=1, column=column, sticky="w")
        form.columnconfigure(0, weight=2)
        form.columnconfigure(2, weight=2)
        self.host_entry = ttk.Entry(form, textvariable=self.host_var, width=16, font=(FONT, 10))
        self.port_entry = ttk.Entry(form, textvariable=self.port_var, width=6, font=(FONT, 10))
        self.name_entry = ttk.Entry(form, textvariable=self.name_var, width=14, font=(FONT, 10))
        for column, entry in enumerate((self.host_entry, self.port_entry, self.name_entry)):
            entry.grid(row=2, column=column, sticky="ew", padx=(0, 12 if column < 2 else 0), pady=(6, 16))
        self.name_entry.bind("<Return>", lambda event: self.connect())
        actions = ttk.Frame(form, style="Card.TFrame")
        actions.grid(row=3, column=0, columnspan=3, sticky="w")
        self.connect_button = ttk.Button(actions, text="Connect", command=self.connect, style="Accent.TButton")
        self.connect_button.pack(side="left")
        self.disconnect_button = ttk.Button(actions, text="Disconnect", command=self.disconnect, state="disabled")
        self.disconnect_button.pack(side="left", padx=(10, 0))

    def build_chat_icon(self, parent):
        # วาดไอคอนด้วย Canvas จึงไม่ต้องติดตั้งแพ็กเกจรูปภาพเพิ่ม
        icon = tk.Canvas(parent, width=100, height=86, background=COLORS["surface"], highlightthickness=0)
        icon.pack(side="left", padx=(0, 18))
        icon.create_oval(9, 2, 91, 84, fill="#EFF5EC", outline="")
        icon.create_rectangle(39, 31, 80, 61, fill="#D7E7C4", outline="")
        icon.create_polygon(68, 59, 78, 69, 78, 58, fill="#D7E7C4", outline="")
        icon.create_rectangle(20, 18, 65, 49, fill=COLORS["accent"], outline="")
        icon.create_polygon(22, 45, 22, 58, 35, 46, fill=COLORS["accent"], outline="")
        for x in (31, 42, 53):
            icon.create_oval(x, 31, x + 4, 35, fill="white", outline="")

    def set_status(self, text, state):
        self.status_var.set(text)
        self.connection_state.set(state)
        background, foreground = {
            "Offline": ("#E4EAE5", COLORS["muted"]),
            "Connecting": ("#FFF0CF", "#80641F"),
            "Online": ("#DCEEDB", "#286039"),
            "Error": ("#FBE5DE", "#A04A35"),
        }[state]
        self.state_badge.configure(background=background, foreground=foreground)

    def set_controls(self, busy):
        state = "disabled" if busy else "normal"
        for widget in (self.host_entry, self.port_entry, self.name_entry, self.connect_button):
            widget.configure(state=state)
        self.disconnect_button.configure(state="normal" if busy else "disabled")

    def clear_users(self):
        self.online_users = []
        self.users_list.delete(0, tk.END)
        self.users_title.set("Online users (0)")
        self.users_empty.place(x=6, y=4)
        self.identity_var.set("Not connected")
        self.empty_hint.set("Connect to see who is online.")
        self.last_users_version = -1

    def connect(self):
        if self.closing or (self.network is not None and not self.network.stopped.is_set()):
            return
        host = self.host_var.get().strip()
        name = self.name_var.get().strip()
        if not host or not name:
            self.set_status("Enter a server address and a name.", "Error")
            return
        try:
            port = int(self.port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.set_status("Port must be a number between 1 and 65535.", "Error")
            return

        self.registered = False
        self.current_name = None
        self.clear_users()
        self.set_controls(busy=True)
        self.set_status(f"Connecting to {host}:{port}...", "Connecting")
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
        self.set_status("Disconnected.", "Offline")

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
            self.set_status("Connected. Registering name...", "Connecting")
        elif event_type == "registered":
            self.registered = True
            self.current_name = event["name"]
            self.set_status(f"Connected as {self.current_name}.", "Online")
            self.identity_var.set(self.current_name)
            self.empty_hint.set("Your online contacts appear in the sidebar.")
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
            if self.online_users:
                self.users_empty.place_forget()
            else:
                self.users_empty.place(x=6, y=4)
        elif event_type == "error":
            self.set_status(f"Error: {event['text']}", "Error")
            if not self.registered:
                self.network.close(reason=f"Error: {event['text']}")
                self.set_controls(busy=False)
        elif event_type == "disconnected":
            self.registered = False
            self.current_name = None
            self.clear_users()
            self.set_controls(busy=False)
            self.set_status(event["text"], "Offline" if event.get("intentional") else "Error")

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

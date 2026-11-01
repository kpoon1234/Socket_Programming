"use strict";

const form = document.querySelector("#connection-form");
const hostInput = document.querySelector("#server-host");
const portInput = document.querySelector("#server-port");
const nameInput = document.querySelector("#display-name");
const connectButton = document.querySelector("#connect-button");
const disconnectButton = document.querySelector("#disconnect-button");
const statusText = document.querySelector("#status");
const connectionLabel = document.querySelector("#connection-label");
const connectionDot = document.querySelector("#connection-dot");
const usersList = document.querySelector("#users-list");
const rooms = new Map();
const requests = new Map();
const roomTabs = document.querySelector("#room-tabs");
const roomPanels = document.querySelector("#room-panels");
const overviewTab = document.querySelector("#overview-tab");

let socket = null;
let currentName = null;
let lastUsersVersion = -1;
let intentionalDisconnect = false;
let lastError = "";
let onlineUsers = [];
let activeRoomId = null;
let lastOpenRequestId = null;

function setStatus(text, state) {
  statusText.textContent = text;
  connectionLabel.textContent = state;
  statusText.classList.toggle("text-rose-300", state === "Error");
  const dotColors = {
    Offline: "bg-slate-500",
    Connecting: "bg-amber-300",
    Online: "bg-emerald-400",
    Error: "bg-rose-400",
  };
  connectionDot.className = `size-1.5 rounded-full ${dotColors[state]}`;
}

function setBusy(busy) {
  for (const control of [hostInput, portInput, nameInput, connectButton]) {
    control.disabled = busy;
  }
  disconnectButton.disabled = !busy;
  connectButton.textContent = busy ? "Connected" : "Connect";
}

function clearSession() {
  currentName = null;
  lastUsersVersion = -1;
  onlineUsers = [];
  requests.clear();
  for (const room of rooms.values()) {
    room.tab.remove();
    room.panel.remove();
  }
  rooms.clear();
  lastOpenRequestId = null;
  selectRoom(null);
  usersList.replaceChildren();
  document.querySelector("#user-count").textContent = "0";
  document.querySelector("#users-empty").hidden = false;
  document.querySelector("#identity").textContent = "Not connected";
  document.querySelector("#session-label").textContent = "No active session";
  document.querySelector("#room-hint").textContent = "Connect to your server to see who is online.";
}

function renderUsers(users) {
  onlineUsers = users;
  usersList.replaceChildren();
  for (const name of users) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "flex w-full items-center gap-3 rounded-lg px-2 py-2.5 text-left transition hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-slate-300 disabled:cursor-default disabled:hover:bg-transparent";
    button.disabled = name === currentName;
    if (name !== currentName) {
      button.setAttribute("aria-label", `Chat with ${name}`);
      button.addEventListener("click", () => openPrivate({ to: name }));
    }
    const avatar = document.createElement("span");
    avatar.className = "flex size-9 shrink-0 items-center justify-center rounded-lg border border-line bg-accent/30 text-sm font-medium text-slate-200";
    avatar.textContent = Array.from(name)[0].toLocaleUpperCase();
    const label = document.createElement("span");
    label.className = "min-w-0 flex-1 break-words text-sm";
    // ใช้ textContent เพื่อให้ชื่อผู้ใช้เป็นข้อความ ไม่กลายเป็น HTML
    label.textContent = name === currentName ? `${name} (you)` : name;
    const dot = document.createElement("span");
    dot.className = "size-1.5 shrink-0 rounded-full bg-emerald-400/80";
    dot.setAttribute("aria-hidden", "true");
    button.append(avatar, label, dot);
    item.append(button);
    usersList.append(item);
  }
  document.querySelector("#user-count").textContent = String(users.length);
  document.querySelector("#users-empty").hidden = users.length > 0;
  for (const room of rooms.values()) updateRoomControls(room);
}

function sendCommand(command, context) {
  if (socket?.readyState !== WebSocket.OPEN || currentName === null) {
    setStatus("Connect before opening a room or sending a message.", "Error");
    return null;
  }
  const requestId = crypto.randomUUID();
  requests.set(requestId, context);
  socket.send(JSON.stringify({ ...command, request_id: requestId }));
  return requestId;
}

function openPrivate(target) {
  lastOpenRequestId = null;
  const known = target.room_id ? rooms.get(target.room_id) : [...rooms.values()].find((room) => room.peer === target.to);
  if (known) {
    selectRoom(known.room_id);
    if (known.loaded) return;
  }
  lastOpenRequestId = sendCommand({ type: "open_private", ...target }, { kind: "open", roomId: known?.room_id });
  if (known) {
    known.empty.textContent = "Loading conversation…";
    known.error.hidden = true;
  }
}

function updateRoomControls(room) {
  const available = currentName !== null && onlineUsers.includes(room.peer);
  room.presence.textContent = available ? "Online" : "Offline";
  room.presence.classList.toggle("text-emerald-300", available);
  room.input.disabled = !available || !room.loaded;
  room.input.placeholder = available ? "Write a message…" : `${room.peer} is offline`;
  room.send.disabled = room.input.disabled || room.pending !== null || !room.input.value.trim();
}

function selectRoom(roomId) {
  activeRoomId = roomId;
  const overview = roomId === null;
  document.querySelector("#overview-panel").hidden = !overview;
  overviewTab.setAttribute("aria-selected", String(overview));
  overviewTab.classList.toggle("bg-accent/80", overview);
  for (const room of rooms.values()) {
    const selected = room.room_id === roomId;
    room.panel.hidden = !selected;
    room.tab.setAttribute("aria-selected", String(selected));
    room.tab.classList.toggle("bg-accent/80", selected);
    if (selected) {
      room.unread = 0;
      room.badge.hidden = true;
      room.history.scrollTop = room.history.scrollHeight;
    }
  }
}

function ensureRoom(metadata) {
  if (rooms.has(metadata.room_id)) return rooms.get(metadata.room_id);
  const peer = metadata.members.find((name) => name !== currentName);
  const panel = document.querySelector("#private-room-template").content.firstElementChild.cloneNode(true);
  panel.id = `panel-${metadata.room_id}`;
  const tab = document.createElement("button");
  tab.id = `tab-${metadata.room_id}`;
  tab.type = "button";
  tab.setAttribute("role", "tab");
  tab.setAttribute("aria-selected", "false");
  tab.setAttribute("aria-controls", panel.id);
  tab.className = "flex max-w-64 shrink-0 items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-slate-300";
  const title = document.createElement("span");
  title.className = "truncate";
  title.textContent = peer;
  const badge = document.createElement("span");
  badge.hidden = true;
  badge.className = "rounded-full bg-slate-200 px-1.5 text-xs text-slate-800";
  tab.append(title, badge);
  panel.setAttribute("aria-labelledby", tab.id);
  panel.querySelector("[data-peer]").textContent = peer;
  const room = {
    ...metadata, peer, tab, panel, badge, loaded: false, unread: 0, messages: new Map(), pending: null,
    input: panel.querySelector("[data-input]"), send: panel.querySelector("[data-send]"),
    history: panel.querySelector("[data-history]"), list: panel.querySelector("[data-messages]"),
    empty: panel.querySelector("[data-empty]"), error: panel.querySelector("[data-error]"),
    presence: panel.querySelector("[data-presence]"), status: panel.querySelector("[data-send-status]"),
    failed: panel.querySelector("[data-failed]"), failedText: null,
  };
  room.input.id = `message-${metadata.room_id}`;
  panel.querySelector("[data-message-label]").htmlFor = room.input.id;
  panel.querySelector("[data-composer]").addEventListener("submit", (event) => {
    event.preventDefault();
    submitMessage(room);
  });
  room.input.addEventListener("input", () => updateRoomControls(room));
  room.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      submitMessage(room);
    }
  });
  panel.querySelector("[data-restore]").addEventListener("click", () => {
    if (room.failedText !== null) {
      room.input.value += `${room.input.value ? "\n" : ""}${room.failedText}`;
      room.failedText = null;
      room.failed.hidden = true;
      updateRoomControls(room);
      room.input.focus();
    }
  });
  tab.addEventListener("click", () => openPrivate({ room_id: room.room_id }));
  rooms.set(room.room_id, room);
  roomTabs.append(tab);
  roomPanels.append(panel);
  updateRoomControls(room);
  return room;
}

function mergeMessages(room, messages) {
  let added = false;
  for (const message of messages) {
    if (!room.messages.has(message.message_id)) {
      room.messages.set(message.message_id, message);
      added = true;
    }
  }
  if (!added) return false;
  const nearBottom = room.history.scrollHeight - room.history.scrollTop - room.history.clientHeight < 80;
  const fragment = document.createDocumentFragment();
  for (const message of [...room.messages.values()].sort((a, b) => a.sequence - b.sequence)) {
    const own = message.from === currentName;
    const bubble = document.createElement("article");
    bubble.dataset.messageId = message.message_id;
    bubble.className = own
      ? "max-w-[88%] self-end rounded-2xl rounded-br-sm bg-accent px-4 py-3 sm:max-w-[75%]"
      : "max-w-[88%] self-start rounded-2xl rounded-bl-sm bg-sidebar px-4 py-3 sm:max-w-[75%]";
    const caption = document.createElement("div");
    caption.className = "mb-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-soft";
    const author = document.createElement("span");
    author.textContent = own ? `${message.from} (you)` : message.from;
    const time = document.createElement("time");
    time.dateTime = message.timestamp;
    time.textContent = new Date(message.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    time.title = new Date(message.timestamp).toLocaleString();
    caption.append(author, time);
    const content = document.createElement("p");
    content.className = "whitespace-pre-wrap break-words text-sm leading-6";
    content.textContent = message.text;
    bubble.append(caption, content);
    fragment.append(bubble);
  }
  room.list.replaceChildren(fragment);
  room.empty.hidden = room.messages.size > 0;
  if (nearBottom) room.history.scrollTop = room.history.scrollHeight;
  return true;
}

function submitMessage(room) {
  updateRoomControls(room);
  if (room.send.disabled) return;
  const text = room.input.value;
  const requestId = sendCommand({ type: "private_message", room_id: room.room_id, text }, {
    kind: "send", roomId: room.room_id, text,
  });
  if (requestId === null) return;
  room.pending = requestId;
  room.input.value = "";
  room.error.hidden = true;
  room.status.textContent = "Sending…";
  updateRoomControls(room);
}

function handleRoomOpened(event) {
  const room = ensureRoom(event);
  room.loaded = true;
  room.empty.textContent = "No messages yet. Say hello!";
  mergeMessages(room, event.messages);
  room.error.hidden = true;
  const requested = requests.get(event.request_id);
  if ((requested?.kind === "open" && event.request_id === lastOpenRequestId) || activeRoomId === null) {
    selectRoom(room.room_id);
  }
  requests.delete(event.request_id);
  updateRoomControls(room);
}

function handlePrivateMessage(event) {
  const room = ensureRoom({ room_id: event.room_id, members: [event.from, event.to] });
  const added = mergeMessages(room, [event]);
  if (added && event.from !== currentName && activeRoomId !== room.room_id) {
    room.unread += 1;
    room.badge.textContent = String(room.unread);
    room.badge.hidden = false;
  }
}

function handleRequestError(event) {
  const request = requests.get(event.request_id);
  const room = rooms.get(request?.roomId);
  if (room) {
    room.error.textContent = event.text;
    room.error.hidden = false;
    if (request.kind === "send") {
      room.pending = null;
      room.status.textContent = event.persisted ? "Saved; live delivery failed." : "Message was not sent.";
      if (!event.persisted) {
        room.failedText = request.text;
        room.panel.querySelector("[data-failed-text]").textContent = request.text;
        room.failed.hidden = false;
      }
    } else {
      room.empty.textContent = "Could not load this conversation. Select the tab to retry.";
    }
    updateRoomControls(room);
  }
  requests.delete(event.request_id);
  setStatus(event.text, currentName === null ? "Error" : "Online");
}

function handleEvent(event) {
  switch (event.type) {
    case "connected":
      setStatus("Connected to the server. Registering your name…", "Connecting");
      break;
    case "registered":
      currentName = event.name;
      connectButton.textContent = "Connected";
      document.querySelector("#identity").textContent = `${currentName} · You`;
      document.querySelector("#session-label").textContent = `Signed in as ${currentName}`;
      document.querySelector("#room-hint").textContent = "Choose an online user or a saved conversation to start chatting.";
      setStatus(`Connected as ${currentName}.`, "Online");
      break;
    case "users_updated":
      if (event.version > lastUsersVersion) {
        lastUsersVersion = event.version;
        renderUsers(event.users);
      }
      break;
    case "private_rooms":
      for (const room of event.rooms) ensureRoom(room);
      break;
    case "room_opened":
      handleRoomOpened(event);
      break;
    case "private_message":
      handlePrivateMessage(event);
      break;
    case "sent": {
      const request = requests.get(event.request_id);
      const room = rooms.get(request?.roomId);
      if (room) {
        room.pending = null;
        room.status.textContent = `Sent to ${room.peer}`;
        updateRoomControls(room);
      }
      requests.delete(event.request_id);
      break;
    }
    case "error":
      if (currentName === null) lastError = event.text;
      handleRequestError(event);
      break;
    case "disconnected":
      if (!intentionalDisconnect) {
        lastError = lastError || (requests.size > 0
          ? `${event.text} Reopen your conversation after reconnecting to check saved messages before resending.`
          : event.text);
      }
      socket.close();
      break;
  }
}

overviewTab.addEventListener("click", () => {
  lastOpenRequestId = null;
  selectRoom(null);
});

roomTabs.addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const tabs = [...roomTabs.querySelectorAll('[role="tab"]')];
  const index = tabs.indexOf(document.activeElement);
  if (index < 0) return;
  event.preventDefault();
  const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
    : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
  tabs[next].focus();
  tabs[next].click();
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (socket !== null) return;
  const host = hostInput.value.trim();
  const name = nameInput.value.trim();
  const port = Number(portInput.value);
  if (!host || !name || !Number.isInteger(port) || port < 1 || port > 65535) {
    setStatus("Enter a server address, a valid port, and a name.", "Error");
    return;
  }
  clearSession();
  intentionalDisconnect = false;
  lastError = "";
  setBusy(true);
  connectButton.textContent = "Connecting…";
  setStatus(`Connecting to ${host}:${port}…`, "Connecting");
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const connection = new WebSocket(`${scheme}://${location.host}/ws`);
  socket = connection;
  connection.addEventListener("open", () => {
    connection.send(JSON.stringify({ type: "connect", host, port, name }));
  });
  connection.addEventListener("message", (message) => {
    if (socket !== connection) return;
    handleEvent(JSON.parse(message.data));
  });
  connection.addEventListener("error", () => {
    if (!intentionalDisconnect) lastError = "Cannot reach the local bridge. Check that it is running.";
  });
  connection.addEventListener("close", () => {
    if (socket !== connection) return;
    socket = null;
    clearSession();
    setBusy(false);
    const failed = !intentionalDisconnect;
    setStatus(failed ? lastError || "Connection lost. You can reconnect." : "Disconnected.", failed ? "Error" : "Offline");
  });
});

disconnectButton.addEventListener("click", () => {
  if (socket === null) return;
  intentionalDisconnect = true;
  if (socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "disconnect" }));
  } else {
    socket.close();
  }
});

window.addEventListener("pagehide", () => socket?.close());

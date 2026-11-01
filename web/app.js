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

let socket = null;
let currentName = null;
let lastUsersVersion = -1;
let intentionalDisconnect = false;
let lastError = "";

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
  usersList.replaceChildren();
  document.querySelector("#user-count").textContent = "0";
  document.querySelector("#users-empty").hidden = false;
  document.querySelector("#identity").textContent = "Not connected";
  document.querySelector("#session-label").textContent = "No active session";
  document.querySelector("#room-hint").textContent = "Connect to your server to see who is online.";
}

function renderUsers(users) {
  usersList.replaceChildren();
  for (const name of users) {
    const item = document.createElement("li");
    item.className = "flex items-center gap-3 rounded-lg px-2 py-2.5";
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
    item.append(avatar, label, dot);
    usersList.append(item);
  }
  document.querySelector("#user-count").textContent = String(users.length);
  document.querySelector("#users-empty").hidden = users.length > 0;
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
      document.querySelector("#room-hint").textContent = "You're connected. Your online contacts appear in the sidebar.";
      setStatus(`Connected as ${currentName}.`, "Online");
      break;
    case "users_updated":
      if (event.version > lastUsersVersion) {
        lastUsersVersion = event.version;
        renderUsers(event.users);
      }
      break;
    case "error":
      lastError = event.text;
      setStatus(event.text, "Error");
      break;
    case "disconnected":
      if (!intentionalDisconnect) {
        lastError = lastError || event.text;
      }
      socket.close();
      break;
  }
}

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

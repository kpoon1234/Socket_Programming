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
const groupRooms = new Map();
const pendingJoins = new Map();
const pendingLeaves = new Map();
const departedGroups = new Set();
const joinErrors = new Map();
const requests = new Map();
const roomTabs = document.querySelector("#room-tabs");
const roomPanels = document.querySelector("#room-panels");
const overviewTab = document.querySelector("#overview-tab");
const groupsList = document.querySelector("#groups-list");
const createGroupButton = document.querySelector("#create-group-button");
const groupForm = document.querySelector("#group-form");
const groupNameInput = document.querySelector("#group-name");
const groupSubmit = document.querySelector("#group-submit");
const groupCancel = document.querySelector("#group-cancel");
const groupError = document.querySelector("#group-error");
const leaveDialog = document.querySelector("#leave-dialog");

let socket = null;
let currentName = null;
let lastUsersVersion = -1;
let intentionalDisconnect = false;
let lastError = "";
let onlineUsers = [];
let activeRoomId = null;
let lastOpenRequestId = null;
let lastGroupsVersion = -1;
let pendingGroupRequest = null;
let currentGroups = [];
let lastJoinRequestId = null;
let leaveTargetId = null;

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
  leaveDialog.close();
  leaveTargetId = null;
  currentName = null;
  lastUsersVersion = -1;
  lastGroupsVersion = -1;
  pendingGroupRequest = null;
  currentGroups = [];
  lastJoinRequestId = null;
  pendingJoins.clear();
  pendingLeaves.clear();
  departedGroups.clear();
  joinErrors.clear();
  groupsList.replaceChildren();
  document.querySelector("#group-count").textContent = "0";
  document.querySelector("#groups-empty").textContent = "Connect to see groups.";
  document.querySelector("#groups-empty").hidden = false;
  groupForm.reset();
  groupError.hidden = true;
  showGroupForm(false);
  updateGroupControls();
  onlineUsers = [];
  requests.clear();
  for (const room of rooms.values()) {
    room.tab.remove();
    room.panel.remove();
  }
  rooms.clear();
  for (const room of groupRooms.values()) {
    room.tab.remove();
    room.panel.remove();
  }
  groupRooms.clear();
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
  updateGroupPresence();
}

function formatGroupMember(name) {
  return `${name}${name === currentName ? " (you)" : ""} · ${onlineUsers.includes(name) ? "Online" : "Offline"}`;
}

function updateGroupMemberLabels(room) {
  const members = room.members.map(formatGroupMember).join(", ");
  const label = room.panel.querySelector("[data-group-members]");
  label.textContent = `Members: ${members}`;
  label.title = members;
}

function updateGroupPresence() {
  for (const group of currentGroups) {
    const label = groupsList.querySelector(`[data-group-card-members="${CSS.escape(group.group_id)}"]`);
    if (label) label.textContent = `Members: ${group.members.map(formatGroupMember).join(", ")}`;
  }
  for (const room of groupRooms.values()) updateGroupMemberLabels(room);
}

function updateGroupControls() {
  const disabled = currentName === null || pendingGroupRequest !== null;
  for (const control of [createGroupButton, groupNameInput, groupSubmit, groupCancel]) {
    control.disabled = disabled;
  }
  groupSubmit.textContent = pendingGroupRequest === null ? "Create" : "Creating…";
}

function showGroupForm(visible) {
  groupForm.hidden = !visible;
  createGroupButton.setAttribute("aria-expanded", String(visible));
  if (visible) groupNameInput.focus();
}

function renderGroups() {
  const scrollTop = groupsList.scrollTop;
  const fragment = document.createDocumentFragment();
  for (const group of currentGroups) {
    const card = document.createElement("li");
    card.dataset.groupId = group.group_id;
    card.className = "rounded-lg border border-line/70 bg-panel/60 p-3";
    const title = document.createElement("h3");
    title.className = "break-words text-sm font-medium";
    title.textContent = group.name;
    const members = document.createElement("p");
    members.className = "mt-1 break-words text-xs leading-5 text-soft";
    members.dataset.groupCardMembers = group.group_id;
    members.textContent = `Members: ${group.members.map(formatGroupMember).join(", ")}`;
    const membership = document.createElement("p");
    const isMember = group.members.includes(currentName);
    membership.className = isMember ? "mt-1 text-xs text-emerald-300" : "mt-1 text-xs text-soft";
    membership.textContent = isMember ? "You are a member" : "Not joined";
    card.append(title, members, membership);
    const action = document.createElement("button");
    action.type = "button";
    action.className = "mt-3 h-9 w-full rounded-lg border border-line bg-accent/30 px-3 text-xs font-medium transition hover:bg-accent focus-visible:outline-2 focus-visible:outline-slate-300 disabled:cursor-not-allowed disabled:opacity-50";
    action.disabled = currentName === null || pendingJoins.has(group.group_id) || pendingLeaves.has(group.group_id);
    action.textContent = pendingLeaves.has(group.group_id) ? "Leaving…" : pendingJoins.has(group.group_id) ? "Joining…" : isMember ? "Open group" : "Join";
    action.setAttribute("aria-label", `${isMember ? "Open group" : "Join"} ${group.name}`);
    action.addEventListener("click", () => {
      lastOpenRequestId = null;
      lastJoinRequestId = null;
      if (isMember) {
        openGroup(group.group_id);
      } else {
        const requestId = sendCommand({ type: "join_group", group_id: group.group_id }, {
          kind: "join_group", groupId: group.group_id, confirmed: false,
        });
        if (requestId === null) return;
        lastJoinRequestId = requestId;
        pendingJoins.set(group.group_id, requestId);
        joinErrors.delete(group.group_id);
        renderGroups();
      }
    });
    card.append(action);
    if (joinErrors.has(group.group_id)) {
      const error = document.createElement("p");
      error.className = "mt-2 break-words text-xs leading-5 text-rose-300";
      error.setAttribute("role", "alert");
      error.textContent = joinErrors.get(group.group_id);
      card.append(error);
    }
    fragment.append(card);
  }
  groupsList.replaceChildren(fragment);
  groupsList.scrollTop = scrollTop;
  document.querySelector("#group-count").textContent = String(currentGroups.length);
  document.querySelector("#groups-empty").textContent = "No groups yet. Create the first one.";
  document.querySelector("#groups-empty").hidden = currentGroups.length > 0;
}

function ensureGroupRoom(group) {
  let room = groupRooms.get(group.group_id);
  if (!room) {
    const panel = document.querySelector("#group-room-template").content.firstElementChild.cloneNode(true);
    panel.id = `panel-${group.group_id}`;
    const tab = document.createElement("button");
    tab.type = "button";
    tab.id = `tab-${group.group_id}`;
    tab.className = "flex max-w-64 shrink-0 items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-slate-300";
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", "false");
    tab.setAttribute("aria-controls", panel.id);
    panel.setAttribute("aria-labelledby", tab.id);
    const title = document.createElement("span");
    title.className = "truncate";
    const badge = document.createElement("span");
    badge.hidden = true;
    badge.className = "rounded-full bg-slate-200 px-1.5 text-xs text-slate-800";
    tab.append(title, badge);
    tab.addEventListener("click", () => openGroup(group.group_id));
    room = { kind: "group", group_id: group.group_id, tab, panel, title, badge };
    initializeComposer(room);
    groupRooms.set(group.group_id, room);
    roomTabs.append(tab);
    roomPanels.append(panel);
  }
  room.name = group.name;
  room.members = group.members;
  room.title.textContent = `# ${group.name}`;
  room.tab.title = group.name;
  room.tab.setAttribute("aria-label", `Group ${group.name}`);
  room.panel.querySelector("[data-group-name]").textContent = group.name;
  updateGroupMemberLabels(room);
  room.leave.setAttribute("aria-label", `Leave group ${group.name}`);
  updateRoomControls(room);
  return room;
}

function openGroup(groupId) {
  lastOpenRequestId = null;
  lastJoinRequestId = null;
  const room = groupRooms.get(groupId);
  if (!room || pendingLeaves.has(groupId)) return;
  selectRoom(groupId);
  if (room.loaded) return;
  lastOpenRequestId = sendCommand({ type: "open_group", group_id: groupId }, { kind: "open_group", roomId: groupId });
  room.empty.textContent = "Loading conversation…";
  room.error.hidden = true;
}

function completeGroupJoins() {
  for (const [groupId, requestId] of pendingJoins) {
    const request = requests.get(requestId);
    const group = currentGroups.find((item) => item.group_id === groupId);
    // รอทั้งคำตอบรับและ snapshot ที่ยืนยันสมาชิก ก่อนเปิดแท็บและปลดสถานะรอ
    if (!request?.confirmed || !group?.members.includes(currentName)) continue;
    pendingJoins.delete(groupId);
    requests.delete(requestId);
    joinErrors.delete(groupId);
    updateRoomControls(groupRooms.get(groupId));
    if (requestId === lastJoinRequestId) {
      openGroup(groupId);
      groupRooms.get(groupId).tab.focus();
      lastJoinRequestId = null;
    }
    setStatus(`Joined ${group.name}.`, "Online");
  }
}

function requestLeave(room) {
  updateRoomControls(room);
  if (room.leave.disabled) return;
  leaveTargetId = room.group_id;
  document.querySelector("#leave-target").textContent = room.name;
  leaveDialog.showModal();
}

function confirmGroupLeave() {
  const room = groupRooms.get(leaveTargetId);
  leaveDialog.close();
  leaveTargetId = null;
  if (!room) return;
  updateRoomControls(room);
  if (room.leave.disabled) return;
  const requestId = sendCommand({ type: "leave_group", group_id: room.group_id }, {
    kind: "leave_group", roomId: room.group_id, confirmed: false, version: null,
  });
  if (requestId === null) return;
  lastOpenRequestId = null;
  lastJoinRequestId = null;
  pendingLeaves.set(room.group_id, requestId);
  room.error.hidden = true;
  updateRoomControls(room);
  renderGroups();
}

function removeGroupRoom(groupId) {
  departedGroups.add(groupId);
  if (leaveTargetId === groupId) {
    leaveDialog.close();
    leaveTargetId = null;
  }
  const room = groupRooms.get(groupId);
  if (!room) return;
  const selected = activeRoomId === groupId;
  room.messages.clear();
  room.input.value = "";
  room.failedText = null;
  room.tab.remove();
  room.panel.remove();
  groupRooms.delete(groupId);
  for (const [requestId, request] of requests) {
    if (request.roomId === groupId && request.kind !== "leave_group") requests.delete(requestId);
  }
  if (selected) {
    selectRoom(null);
    overviewTab.focus();
  }
}

function completeGroupLeaves() {
  for (const [groupId, requestId] of pendingLeaves) {
    const request = requests.get(requestId);
    const group = currentGroups.find((item) => item.group_id === groupId);
    // คำตอบ Leave อาจมาถึงก่อน snapshot เก่า ต้องรอ version ที่ยืนยันการออกจริง
    if (!request?.confirmed || lastGroupsVersion < request.version || group?.members.includes(currentName)) continue;
    pendingLeaves.delete(groupId);
    requests.delete(requestId);
    setStatus(request.deleted ? "Group and its history deleted." : "Left the group.", "Online");
  }
}

function syncGroupRooms() {
  for (const groupId of groupRooms.keys()) {
    const group = currentGroups.find((item) => item.group_id === groupId);
    if (!group?.members.includes(currentName)) removeGroupRoom(groupId);
  }
  for (const group of currentGroups) {
    if (!group.members.includes(currentName)) continue;
    const leave = requests.get(pendingLeaves.get(group.group_id));
    if (leave?.confirmed && lastGroupsVersion < leave.version) continue;
    departedGroups.delete(group.group_id);
    ensureGroupRoom(group);
  }
  completeGroupJoins();
  completeGroupLeaves();
}

function sendCommand(command, context) {
  if (socket?.readyState !== WebSocket.OPEN || currentName === null) {
    setStatus("Connect before using chat features.", "Error");
    return null;
  }
  const requestId = crypto.randomUUID();
  requests.set(requestId, context);
  socket.send(JSON.stringify({ ...command, request_id: requestId }));
  return requestId;
}

function openPrivate(target) {
  lastOpenRequestId = null;
  lastJoinRequestId = null;
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
  const isGroup = room.kind === "group";
  const available = currentName !== null && (isGroup ? room.members.includes(currentName) : onlineUsers.includes(room.peer));
  const leaving = isGroup && pendingLeaves.has(room.group_id);
  room.presence.textContent = isGroup ? `${room.members.length} ${room.members.length === 1 ? "member" : "members"}` : available ? "Online" : "Offline";
  room.presence.classList.toggle("text-emerald-300", available);
  room.input.disabled = !available || !room.loaded || leaving;
  room.input.placeholder = !room.loaded ? "Loading conversation…" : available ? "Write a message…" : isGroup ? "You are not a member" : `${room.peer} is offline`;
  room.send.disabled = room.input.disabled || room.pending !== null || !room.input.value.trim();
  if (isGroup) {
    room.leave.disabled = !available || leaving || pendingJoins.has(room.group_id) || room.pending !== null;
    room.leave.textContent = leaving ? "Leaving…" : "Leave group";
  }
}

function roomKey(room) {
  return room.kind === "group" ? room.group_id : room.room_id;
}

function findRoom(roomId) {
  return rooms.get(roomId) || groupRooms.get(roomId);
}

function selectRoom(roomId) {
  activeRoomId = roomId;
  const overview = roomId === null;
  document.querySelector("#overview-panel").hidden = !overview;
  overviewTab.setAttribute("aria-selected", String(overview));
  overviewTab.classList.toggle("bg-accent/80", overview);
  for (const room of [...rooms.values(), ...groupRooms.values()]) {
    const selected = roomKey(room) === roomId;
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
  const room = { ...metadata, kind: "private", peer, tab, panel, badge };
  initializeComposer(room);
  tab.addEventListener("click", () => openPrivate({ room_id: room.room_id }));
  rooms.set(room.room_id, room);
  roomTabs.append(tab);
  roomPanels.append(panel);
  updateRoomControls(room);
  return room;
}

function initializeComposer(room) {
  const panel = room.panel;
  Object.assign(room, {
    loaded: false, unread: 0, messages: new Map(), pending: null,
    input: panel.querySelector("[data-input]"), send: panel.querySelector("[data-send]"),
    history: panel.querySelector("[data-history]"), list: panel.querySelector("[data-messages]"),
    empty: panel.querySelector("[data-empty]"), error: panel.querySelector("[data-error]"),
    presence: panel.querySelector("[data-presence]"), status: panel.querySelector("[data-send-status]"),
    failed: panel.querySelector("[data-failed]"), failedText: null,
    leave: panel.querySelector("[data-leave]"),
  });
  room.leave?.addEventListener("click", () => requestLeave(room));
  room.input.id = `message-${roomKey(room)}`;
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
  const command = room.kind === "group"
    ? { type: "group_message", group_id: room.group_id, text }
    : { type: "private_message", room_id: room.room_id, text };
  const requestId = sendCommand(command, { kind: "send", roomId: roomKey(room), text });
  if (requestId === null) return;
  room.pending = requestId;
  room.input.value = "";
  room.error.hidden = true;
  room.status.textContent = "Sending…";
  updateRoomControls(room);
  room.input.focus();
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

function handleGroupOpened(event) {
  if (departedGroups.has(event.group_id) && !pendingJoins.has(event.group_id)) {
    requests.delete(event.request_id);
    return;
  }
  const room = ensureGroupRoom(event);
  room.loaded = true;
  room.empty.textContent = "No messages since you joined. Say hello!";
  mergeMessages(room, event.messages);
  room.error.hidden = true;
  const request = requests.get(event.request_id);
  if (request?.kind === "open_group" && event.request_id === lastOpenRequestId) selectRoom(event.group_id);
  requests.delete(event.request_id);
  updateRoomControls(room);
}

function handleGroupMessage(event) {
  if (departedGroups.has(event.group_id) && !pendingJoins.has(event.group_id)) return;
  const room = groupRooms.get(event.group_id);
  if (!room) return;
  const added = mergeMessages(room, [event]);
  if (added && event.from !== currentName && activeRoomId !== event.group_id) {
    room.unread += 1;
    room.badge.textContent = String(room.unread);
    room.badge.hidden = false;
  }
}

function handleRequestError(event) {
  const request = requests.get(event.request_id);
  if (request?.kind === "leave_group") {
    pendingLeaves.delete(request.roomId);
    renderGroups();
  }
  if (request?.kind === "join_group" && pendingJoins.get(request.groupId) === event.request_id) {
    pendingJoins.delete(request.groupId);
    joinErrors.set(request.groupId, event.text);
    renderGroups();
    groupsList.querySelector(`[data-group-id="${CSS.escape(request.groupId)}"] button`)?.focus();
  }
  if (request?.kind === "create_group" && event.request_id === pendingGroupRequest) {
    pendingGroupRequest = null;
    groupError.textContent = event.text;
    groupError.hidden = false;
    updateGroupControls();
    groupNameInput.focus();
  }
  const room = findRoom(request?.roomId);
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
    } else if (request.kind === "open" || request.kind === "open_group") {
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
      updateGroupControls();
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
    case "groups_updated":
      if (event.version > lastGroupsVersion) {
        lastGroupsVersion = event.version;
        currentGroups = event.groups;
        syncGroupRooms();
        renderGroups();
      }
      break;
    case "group_left": {
      const request = requests.get(event.request_id);
      if (request?.kind === "leave_group" && request.roomId === event.group_id) {
        Object.assign(request, { confirmed: true, version: event.version, deleted: event.deleted });
        removeGroupRoom(event.group_id);
        completeGroupLeaves();
        renderGroups();
      }
      break;
    }
    case "group_joined": {
      const request = requests.get(event.request_id);
      if (request?.kind === "join_group" && request.groupId === event.group_id) {
        request.confirmed = true;
        completeGroupJoins();
        renderGroups();
      }
      break;
    }
    case "group_created":
      if (requests.get(event.request_id)?.kind === "create_group" && event.request_id === pendingGroupRequest) {
        requests.delete(event.request_id);
        pendingGroupRequest = null;
        groupForm.reset();
        groupError.hidden = true;
        showGroupForm(false);
        updateGroupControls();
        createGroupButton.focus();
        setStatus("Group created.", "Online");
      }
      // ไม่เพิ่มการ์ดจากคำตอบนี้ รอรายการจริงใน groups_updated เพื่อไม่ให้กลุ่มซ้ำ
      break;
    case "room_opened":
      handleRoomOpened(event);
      break;
    case "private_message":
      handlePrivateMessage(event);
      break;
    case "group_opened":
      handleGroupOpened(event);
      break;
    case "group_message":
      handleGroupMessage(event);
      break;
    case "sent": {
      const request = requests.get(event.request_id);
      const room = findRoom(request?.roomId);
      if (room) {
        room.pending = null;
        room.status.textContent = room.kind === "group" ? "Saved and sent to online members." : `Sent to ${room.peer}`;
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
          ? `${event.text} Check saved conversations and groups after reconnecting before retrying.`
          : event.text);
      }
      socket.close();
      break;
  }
}

createGroupButton.addEventListener("click", () => showGroupForm(groupForm.hidden));
document.querySelector("#leave-confirm").addEventListener("click", confirmGroupLeave);
leaveDialog.addEventListener("close", () => { leaveTargetId = null; });
groupCancel.addEventListener("click", () => {
  groupForm.reset();
  groupError.hidden = true;
  showGroupForm(false);
  createGroupButton.focus();
});
groupForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (currentName === null || pendingGroupRequest !== null) return;
  groupError.hidden = true;
  pendingGroupRequest = sendCommand({ type: "create_group", name: groupNameInput.value }, { kind: "create_group" });
  updateGroupControls();
});

overviewTab.addEventListener("click", () => {
  lastOpenRequestId = null;
  lastJoinRequestId = null;
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

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
  window.E2EE?.clearAll?.();
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
  const foundGroup = currentGroups.find((g) => g.group_id === group.group_id);
  const creator = group.creator || foundGroup?.creator;
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
    room = { kind: "group", group_id: group.group_id, tab, panel, title, badge, creator };
    initializeComposer(room);
    groupRooms.set(group.group_id, room);
    roomTabs.append(tab);
    roomPanels.append(panel);
  }
  room.name = group.name;
  room.members = group.members;
  if (creator) {
    room.creator = creator;
  }
  room.title.textContent = `# ${group.name}`;
  room.tab.title = group.name;
  room.tab.setAttribute("aria-label", `Group ${group.name}`);
  room.panel.querySelector("[data-group-name]").textContent = group.name;
  updateGroupMemberLabels(room);
  room.leave.setAttribute("aria-label", `Leave group ${group.name}`);
  if (group.is_secret === true) {
    setRoomSecretMode(room, true);
  } else if (group.is_secret === false) {
    setRoomSecretMode(room, false);
  }
  updateRoomControls(room);
  updateSecretChatUI(room);
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
  refreshSummaryControls();
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
  const summaryRunning = [...requests.values()].some((request) => request.kind === "summarize");
  const canRead = currentName !== null && (!isGroup || room.members.includes(currentName));
  room.summarize.disabled = !canRead || !room.loaded || leaving || summaryRunning;
  room.summarize.textContent = room.summaryPending ? "Summarizing…" : "Summarize";
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

function formatLockedCipher(rawText) {
  if (!rawText) return "••••••••••••••••••••••••••••";
  const raw = rawText.replace(/^🔒\s*enc:v1:/, "");
  const parts = raw.split(":").filter(Boolean);
  if (parts.length >= 3) {
    const cipher = parts[2].replace(/=/g, "");
    if (cipher.length < 24) {
      const tag = parts[1].replace(/=/g, "");
      return (tag + cipher).slice(0, 36);
    }
    return cipher.slice(0, 48);
  }
  return raw.slice(0, 48);
}

function selectRoom(roomId) {
  const previousRoomId = activeRoomId;
  activeRoomId = roomId;

  // When leaving a chat room, lock it only if there are encrypted messages
  if (previousRoomId && previousRoomId !== roomId) {
    const prevRoom = findRoom(previousRoomId);
    const hasEncrypted = prevRoom?.messages && [...prevRoom.messages.values()].some((m) => window.E2EE?.isEncrypted(m.text));
    if (hasEncrypted) {
      window.E2EE?.lockRoom(previousRoomId);
      if (prevRoom) {
        prevRoom.unlockedPin = null;
        prevRoom.pinPrompted = false;
        renderMessages(prevRoom);
      }
    }
  }

  const overview = roomId === null;
  if (overview) {
    closePinDialog();
  }
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
      updateE2EEButton(room);
      room.pinPrompted = false; // Always allow PIN prompt on entering room!
      if (window.E2EE?.isRoomUnlocked(roomKey(room))) {
        closePinDialog();
      }
      renderMessages(room);
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
  if (metadata.is_secret === true) {
    setRoomSecretMode(room, true);
  } else if (metadata.is_secret === false) {
    setRoomSecretMode(room, false);
  }
  updateRoomControls(room);
  return room;
}

function initializeComposer(room) {
  const panel = room.panel;
  const summaryPanel = document.querySelector("#summary-template").content.firstElementChild.cloneNode(true);
  Object.assign(room, {
    loaded: false, unread: 0, messages: new Map(), pending: null,
    input: panel.querySelector("[data-input]"), send: panel.querySelector("[data-send]"),
    history: panel.querySelector("[data-history]"), list: panel.querySelector("[data-messages]"),
    empty: panel.querySelector("[data-empty]"), error: panel.querySelector("[data-error]"),
    presence: panel.querySelector("[data-presence]"), status: panel.querySelector("[data-send-status]"),
    failed: panel.querySelector("[data-failed]"), failedText: null,
    leave: panel.querySelector("[data-leave]"),
    summarize: panel.querySelector("[data-summarize]"), summaryPending: null, summaryAfterSequence: 0,
    summaryPanel, summaryText: summaryPanel.querySelector("[data-summary-text]"),
    summaryStatus: summaryPanel.querySelector("[data-summary-status]"),
    summaryError: summaryPanel.querySelector("[data-summary-error]"),
    secretBadge: panel.querySelector("[data-secret-badge]"),
    secretPrompt: panel.querySelector("[data-secret-prompt]"),
    secretYes: panel.querySelector("[data-secret-yes]"),
    secretNo: panel.querySelector("[data-secret-no]"),
    isSecretChat: null,
    pendingSendText: null,
  });
  if (room.secretPrompt) {
    room.secretPrompt.hidden = true;
  }
  room.summarize.addEventListener("click", () => requestSummary(room));
  room.leave?.addEventListener("click", () => requestLeave(room));
  room.secretYes?.addEventListener("click", () => activateSecretChat(room));
  room.secretNo?.addEventListener("click", () => {
    setRoomSecretMode(room, false);
    if (window.E2EE?.createNormalSyncMessage) {
      sendSyncPayload(room, window.E2EE.createNormalSyncMessage());
    }
  });
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
  updateSecretChatUI(room);
}

function getStoredSecretMode(rKey) {
  if (!currentName) return null;
  const val = localStorage.getItem(`secret_chat_${currentName}_${rKey}`);
  if (val === "true") return true;
  if (val === "false") return false;
  return null;
}

function setRoomSecretMode(room, isSecret) {
  const rKey = roomKey(room);
  room.isSecretChat = isSecret;
  if (currentName) {
    localStorage.setItem(`secret_chat_${currentName}_${rKey}`, isSecret ? "true" : "false");
  }
  updateSecretChatUI(room);
}

function isRoomSecret(room) {
  if (!room) return false;
  const rKey = roomKey(room);

  // If set on room instance
  if (room.isSecretChat === true) return true;
  if (room.isSecretChat === false) return false;

  // Check stored preference first
  const stored = getStoredSecretMode(rKey);
  if (stored !== null) {
    room.isSecretChat = stored;
    return stored;
  }

  // Check messages
  if (room.messages && room.messages.size > 0) {
    const hasEncrypted = [...room.messages.values()].some((m) => window.E2EE?.isEncrypted(m.text));
    if (hasEncrypted) {
      room.isSecretChat = true;
      if (currentName) localStorage.setItem(`secret_chat_${currentName}_${rKey}`, "true");
      return true;
    }
    // Has messages, and none are encrypted -> definitely normal chat
    room.isSecretChat = false;
    if (currentName) localStorage.setItem(`secret_chat_${currentName}_${rKey}`, "false");
    return false;
  }

  return null; // Not chosen yet
}

function updateSecretChatUI(room) {
  if (!room) return;
  const status = isRoomSecret(room);

  if (room.secretBadge) {
    room.secretBadge.hidden = status !== true;
  }

  if (room.secretPrompt) {
    const hasMessages = room.messages && room.messages.size > 0;
    if (room.kind === "group") {
      // In group chats: ONLY the verified creator of a brand new group with 0 messages can see the prompt.
      // Anyone else who enters, joins, or connects must NEVER see this prompt!
      const isCreator = Boolean(room.creator && currentName && room.creator === currentName);
      if (isCreator && status === null && !hasMessages) {
        room.secretPrompt.hidden = false;
      } else {
        room.secretPrompt.hidden = true;
      }
    } else {
      // Private 1-on-1 chats:
      room.secretPrompt.hidden = status !== null || hasMessages;
    }
  }
}

function refreshSummaryControls() {
  for (const room of [...rooms.values(), ...groupRooms.values()]) updateRoomControls(room);
}

function positionSummary(room) {
  // วางสรุปหลังช่วงที่ใช้สรุป เพื่อให้ข้อความใหม่เรียงต่อด้านล่าง
  const nextMessage = [...room.list.children].find((node) => {
    const message = room.messages.get(node.dataset.messageId);
    return message && message.sequence > room.summaryAfterSequence;
  });
  room.list.insertBefore(room.summaryPanel, nextMessage || null);
}

function requestSummary(room) {
  updateRoomControls(room);
  if (room.summarize.disabled) return;
  const requestId = sendCommand({
    type: "summarize_room", room_type: room.kind, room_id: roomKey(room),
  }, { kind: "summarize", roomId: roomKey(room), roomType: room.kind });
  if (requestId === null) return;
  room.summaryPending = requestId;
  room.summaryAfterSequence = 0;
  for (const message of room.messages.values()) {
    room.summaryAfterSequence = Math.max(room.summaryAfterSequence, message.sequence);
  }
  room.summaryPanel.hidden = false;
  positionSummary(room);
  room.summaryPanel.setAttribute("aria-busy", "true");
  room.summaryText.textContent = "";
  room.summaryStatus.textContent = "Summarizing recent messages… You can keep chatting.";
  room.summaryError.hidden = true;
  refreshSummaryControls();
  room.history.scrollTop = room.history.scrollHeight;
}

function handleSummary(event) {
  const request = requests.get(event.request_id);
  const room = findRoom(request?.roomId);
  if (request?.kind !== "summarize" || !room || room.summaryPending !== event.request_id
      || event.room_id !== roomKey(room) || event.room_type !== room.kind) return;
  requests.delete(event.request_id);
  room.summaryPending = null;
  room.summaryPanel.setAttribute("aria-busy", "false");
  room.summaryText.textContent = event.summary;
  const first = room.messages.get(event.first_message_id);
  const last = room.messages.get(event.last_message_id);
  if (last) room.summaryAfterSequence = last.sequence;
  positionSummary(room);
  const range = first && last
    ? ` · ${new Date(first.timestamp).toLocaleString()} – ${new Date(last.timestamp).toLocaleString()}` : "";
  room.summaryStatus.textContent = `${event.message_count} messages${range}.`
    + (event.truncated ? " Earlier messages were not included." : "")
    + " Messages sent after this request are not included.";
  room.summaryError.hidden = true;
  refreshSummaryControls();
  if (activeRoomId === roomKey(room)) room.history.scrollTop = room.history.scrollHeight;
}

let pendingChoiceRoom = null;
const secretChoiceModal = document.querySelector("#secret-choice-modal");
const choiceSecretYes = document.querySelector("#choice-secret-yes");
const choiceSecretNo = document.querySelector("#choice-secret-no");

function openSecretChoiceModal(room, rawText) {
  pendingChoiceRoom = room;
  if (rawText) {
    room.pendingSendText = rawText;
  }
  if (secretChoiceModal) {
    secretChoiceModal.hidden = false;
  }
}

function closeSecretChoiceModal() {
  if (secretChoiceModal) {
    secretChoiceModal.hidden = true;
  }
}

choiceSecretYes?.addEventListener("click", () => {
  const room = pendingChoiceRoom || findRoom(activeRoomId);
  closeSecretChoiceModal();
  if (room) {
    activateSecretChat(room);
  }
});

choiceSecretNo?.addEventListener("click", () => {
  const room = pendingChoiceRoom || findRoom(activeRoomId);
  closeSecretChoiceModal();
  if (room) {
    setRoomSecretMode(room, false);
    if (window.E2EE?.createNormalSyncMessage) {
      sendSyncPayload(room, window.E2EE.createNormalSyncMessage());
    }
    if (room.pendingSendText) {
      const text = room.pendingSendText;
      room.pendingSendText = null;
      sendMessagePayload(room, text);
    }
  }
});

secretChoiceModal?.addEventListener("click", (e) => {
  if (e.target === secretChoiceModal) {
    closeSecretChoiceModal();
  }
});

function activateSecretChat(room) {
  const targetRoom = room || findRoom(activeRoomId);
  if (!targetRoom) return;
  currentPinRoom = targetRoom;
  const rKey = roomKey(targetRoom);
  if (window.E2EE?.isRoomUnlocked(rKey)) {
    setRoomSecretMode(targetRoom, true);
    if (targetRoom.pendingSendText) {
      const text = targetRoom.pendingSendText;
      targetRoom.pendingSendText = null;
      window.E2EE.encrypt(rKey, text).then((enc) => sendMessagePayload(targetRoom, enc));
    }
    return;
  }
  openPinDialog(targetRoom);
}

async function renderMessages(room) {
  const nearBottom = room.history.scrollHeight - room.history.scrollTop - room.history.clientHeight < 80;
  const fragment = document.createDocumentFragment();
  const rKey = roomKey(room);
  const isUnlocked = window.E2EE?.isRoomUnlocked(rKey);

  let hasLockedMessages = false;

  for (const message of [...room.messages.values()].sort((a, b) => a.sequence - b.sequence)) {
    const own = message.from === currentName;
    const isEnc = window.E2EE?.isEncrypted(message.text);
    let displayText = message.text;
    let isLocked = false;

    if (isEnc) {
      if (window.E2EE) {
        const decResult = await window.E2EE.decrypt(rKey, message.text);
        if (decResult.success) {
          displayText = decResult.text;
        } else {
          hasLockedMessages = true;
          isLocked = true;
          // Display the scrambled cipher text without length-leaking short cuts
          displayText = formatLockedCipher(message.text);
        }
      }
    }

    const bubble = document.createElement("article");
    bubble.dataset.messageId = message.message_id;
    bubble.className = own
      ? "max-w-[88%] self-end rounded-2xl rounded-br-sm bg-accent px-4 py-3 sm:max-w-[75%]"
      : "max-w-[88%] self-start rounded-2xl rounded-bl-sm bg-sidebar px-4 py-3 sm:max-w-[75%]";

    const caption = document.createElement("div");
    caption.className = "mb-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-soft";
    const author = document.createElement("span");
    author.textContent = own ? `${message.from} (you)` : message.from;
    const time = document.createElement("time");
    time.dateTime = message.timestamp;
    time.textContent = new Date(message.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    time.title = new Date(message.timestamp).toLocaleString();
    caption.append(author, time);

    const content = document.createElement("p");
    content.className = "whitespace-pre-wrap break-words text-sm leading-6";
    if (isLocked) {
      content.className += " font-mono text-xs opacity-75 cursor-pointer select-none";
      content.title = "Tap to enter Passcode";
      content.onclick = () => openPinDialog(room);
    }
    content.textContent = displayText;
    bubble.append(caption, content);
    fragment.append(bubble);
  }

  room.list.replaceChildren(fragment);
  if (!room.summaryPanel.hidden) positionSummary(room);
  room.empty.hidden = room.messages.size > 0;
  if (nearBottom) room.history.scrollTop = room.history.scrollHeight;

  updateSecretChatUI(room);

  // Auto-prompt Passcode dialog if room has locked messages and hasn't been prompted yet
  if (hasLockedMessages && !isUnlocked && !room.pinPrompted && activeRoomId === rKey) {
    room.pinPrompted = true;
    openPinDialog(room);
  }
}

function mergeMessages(room, messages) {
  let added = false;
  for (const message of messages) {
    if (
      window.E2EE?.isSyncMessage(message.text) ||
      window.E2EE?.isNormalSyncMessage?.(message.text) ||
      (typeof message.text === "string" && message.text.includes("mode:normal"))
    ) {
      continue;
    }
    if (!room.messages.has(message.message_id)) {
      room.messages.set(message.message_id, message);
      added = true;
    }
  }
  if (!added) return false;
  renderMessages(room);
  return true;
}

function sendSyncPayload(room, text) {
  const rKey = roomKey(room);
  const command = room.kind === "group"
    ? { type: "group_message", group_id: room.group_id, text }
    : { type: "private_message", room_id: room.room_id, text };
  sendCommand(command, { kind: "sync", roomId: rKey, text });
}

function sendMessagePayload(room, text) {
  const rKey = roomKey(room);
  const command = room.kind === "group"
    ? { type: "group_message", group_id: room.group_id, text }
    : { type: "private_message", room_id: room.room_id, text };
  const requestId = sendCommand(command, { kind: "send", roomId: rKey, text });
  if (requestId === null) return;
  room.pending = requestId;
  room.input.value = "";
  room.error.hidden = true;
  room.status.textContent = "Sending…";
  updateRoomControls(room);
  room.input.focus();
}

async function submitMessage(room) {
  updateRoomControls(room);
  if (room.send.disabled) return;
  const rawText = room.input.value;
  if (!rawText.trim()) return;
  const rKey = roomKey(room);

  let secretStatus = isRoomSecret(room);
  if (room.kind === "group") {
    const isCreator = Boolean(room.creator && currentName && room.creator === currentName);
    if (!isCreator && secretStatus === null) {
      secretStatus = false;
    }
  }
  if (secretStatus === null) {
    openSecretChoiceModal(room, rawText);
    return;
  }

  if (secretStatus === true) {
    if (!window.E2EE?.isRoomUnlocked(rKey)) {
      if (room.unlockedPin) {
        await window.E2EE.unlockRoom(rKey, room.unlockedPin);
      } else {
        room.pendingSendText = rawText;
        openPinDialog(room);
        return;
      }
    }
    const text = await window.E2EE.encrypt(rKey, rawText);
    sendMessagePayload(room, text);
  } else {
    sendMessagePayload(room, rawText);
  }
}

let currentPinRoom = null;
const pinModal = document.querySelector("#pin-modal") || document.querySelector("#pin-dialog");
const pinDotsContainer = document.querySelector("#pin-dots");
const pinError = document.querySelector("#pin-error");
const pinCancelBtn = document.querySelector("#pin-cancel-btn");
const pinCloseBtn = document.querySelector("#pin-close-btn");
const pinDeleteBtn = document.querySelector("#pin-delete-btn");
const pinTitle = document.querySelector("#pin-title");
const pinDesc = document.querySelector("#pin-description");

function isPinDialogOpen() {
  return Boolean(pinModal && !pinModal.hidden);
}

// Backward-compatibility alias
const pinDialog = pinModal;
if (pinDialog) {
  pinDialog.showModal = () => openPinDialog();
  pinDialog.close = () => closePinDialog();
  Object.defineProperty(pinDialog, "open", {
    get: () => isPinDialogOpen(),
    set: (v) => { if (pinModal) pinModal.hidden = !v; }
  });
}

let enteredDigits = [];

function updatePasscodeDots() {
  if (!pinDotsContainer) return;
  const dots = pinDotsContainer.querySelectorAll(".pin-dot");
  dots.forEach((dot, idx) => {
    if (idx < enteredDigits.length) {
      dot.classList.add("pin-dot-filled");
    } else {
      dot.classList.remove("pin-dot-filled");
    }
  });
}

function clearPasscode(shake = false) {
  enteredDigits = [];
  updatePasscodeDots();
  if (shake && pinDotsContainer) {
    pinDotsContainer.classList.add("shake-anim");
    setTimeout(() => {
      pinDotsContainer?.classList.remove("shake-anim");
    }, 400);
  }
}

function pressKeypadDigit(digit) {
  if (enteredDigits.length >= 4) return;
  enteredDigits.push(digit);
  updatePasscodeDots();
  if (enteredDigits.length === 4) {
    setTimeout(() => {
      verifyAndSubmitPasscode(enteredDigits.join(""));
    }, 80);
  }
}

function deleteKeypadDigit() {
  if (enteredDigits.length > 0) {
    enteredDigits.pop();
    updatePasscodeDots();
  }
}

// Bind 0-9 keypad buttons
document.querySelectorAll(".pin-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const val = btn.dataset.val;
    if (val !== undefined) pressKeypadDigit(val);
  });
});

function cancelPinDialog() {
  if (currentPinRoom) {
    currentPinRoom.pendingSendText = null;
  }
  closePinDialog();
}

pinDeleteBtn?.addEventListener("click", deleteKeypadDigit);
pinCancelBtn?.addEventListener("click", cancelPinDialog);
pinCloseBtn?.addEventListener("click", cancelPinDialog);

// Click on dimmed backdrop (outside card) closes modal
pinModal?.addEventListener("click", (e) => {
  if (e.target === pinModal) {
    cancelPinDialog();
  }
});

// Physical keyboard listener
window.addEventListener("keydown", (e) => {
  if (!isPinDialogOpen()) return;
  if (e.key >= "0" && e.key <= "9") {
    e.preventDefault();
    pressKeypadDigit(e.key);
  } else if (e.key === "Backspace") {
    e.preventDefault();
    deleteKeypadDigit();
  } else if (e.key === "Escape") {
    cancelPinDialog();
  }
});

function updateE2EEButton(room) {
  // Presence and header UI are kept completely normal and clean
}

function openPinDialog(room) {
  const targetRoom = room || findRoom(activeRoomId);
  if (!targetRoom) return;
  const rKey = roomKey(targetRoom);
  if (activeRoomId !== rKey) return;

  currentPinRoom = targetRoom;
  clearPasscode(false);
  if (pinError) {
    pinError.hidden = true;
    pinError.textContent = "";
  }

  const encryptedSamples = [...targetRoom.messages.values()]
    .map((m) => m.text)
    .filter((t) => window.E2EE?.isEncrypted(t));

  if (encryptedSamples.length > 0) {
    if (pinTitle) pinTitle.textContent = "Enter Passcode";
    if (pinDesc) pinDesc.textContent = "Enter 4-digit PIN to decrypt chat";
  } else {
    if (pinTitle) pinTitle.textContent = "Set 4-Digit Passcode";
    if (pinDesc) pinDesc.textContent = "Choose a 4-digit PIN to secure this chat";
  }

  if (pinModal) {
    pinModal.hidden = false;
  }
}

function closePinDialog() {
  if (pinModal) {
    pinModal.hidden = true;
  }
  clearPasscode(false);
}

async function verifyAndSubmitPasscode(pin) {
  const room = currentPinRoom || findRoom(activeRoomId);
  if (!room) {
    if (pinError) {
      pinError.textContent = "No conversation selected.";
      pinError.hidden = false;
    }
    clearPasscode(true);
    return;
  }
  if (!window.E2EE) {
    if (pinError) {
      pinError.textContent = "E2EE security module error.";
      pinError.hidden = false;
    }
    clearPasscode(true);
    return;
  }

  const rKey = roomKey(room);
  try {
    const encryptedSamples = [...room.messages.values()]
      .map((m) => m.text)
      .filter((t) => window.E2EE.isEncrypted(t));

    const isInitialSetup = encryptedSamples.length === 0;

    if (!isInitialSetup) {
      const isValid = await window.E2EE.testPin(rKey, pin, encryptedSamples);
      if (!isValid) {
        if (pinError) {
          pinError.textContent = "Incorrect Passcode";
          pinError.hidden = false;
        }
        clearPasscode(true);
        return;
      }
    }

    await window.E2EE.unlockRoom(rKey, pin);
    room.unlockedPin = pin;
    setRoomSecretMode(room, true);

    // Sync secret chat activation & PIN to all participants in the room
    if (isInitialSetup && window.E2EE?.createSyncMessage) {
      sendSyncPayload(room, window.E2EE.createSyncMessage(pin));
    }

    const textToSend = room.pendingSendText;
    room.pendingSendText = null;
    closePinDialog();
    clearPasscode(false);
    updateE2EEButton(room);
    await renderMessages(room);
    updateRoomControls(room);

    if (textToSend) {
      const encText = await window.E2EE.encrypt(rKey, textToSend);
      sendMessagePayload(room, encText);
    } else {
      room.input?.focus();
    }
  } catch (err) {
    if (pinError) {
      pinError.textContent = err.message || "Failed to unlock";
      pinError.hidden = false;
    }
    clearPasscode(true);
  }
}

function handleRoomOpened(event) {
  const room = ensureRoom(event);
  room.loaded = true;
  room.empty.textContent = "No messages yet. Say hello!";
  room.error.hidden = true;

  // Detect if history has secret chat or normal chat signals
  let foundSecret = event.is_secret === true;
  let foundNormal = event.is_secret === false;
  for (const m of event.messages) {
    if (window.E2EE?.isSyncMessage(m.text) || window.E2EE?.isEncrypted(m.text)) {
      foundSecret = true;
      break;
    }
    if (window.E2EE?.isNormalSyncMessage?.(m.text) || (typeof m.text === "string" && m.text.includes("mode:normal"))) {
      foundNormal = true;
    }
  }

  if (foundSecret) {
    setRoomSecretMode(room, true);
  } else if (foundNormal) {
    setRoomSecretMode(room, false);
  }

  const requested = requests.get(event.request_id);
  const shouldSelect = requested?.kind === "open" && event.request_id === lastOpenRequestId;
  if (shouldSelect) {
    selectRoom(room.room_id);
  }

  mergeMessages(room, event.messages);
  updateSecretChatUI(room);
  requests.delete(event.request_id);
  updateRoomControls(room);
}

function handlePrivateMessage(event) {
  const room = ensureRoom({ room_id: event.room_id, members: [event.from, event.to] });
  if (window.E2EE?.isSyncMessage(event.text)) {
    const pin = window.E2EE.extractSyncPin(event.text);
    if (pin) {
      setRoomSecretMode(room, true);
      room.unlockedPin = pin;
      updateSecretChatUI(room);
      window.E2EE.unlockRoom(roomKey(room), pin).then(() => {
        updateSecretChatUI(room);
        renderMessages(room);
        updateRoomControls(room);
      });
    }
    return;
  }
  if (window.E2EE?.isNormalSyncMessage?.(event.text)) {
    setRoomSecretMode(room, false);
    updateSecretChatUI(room);
    return;
  }
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
  room.error.hidden = true;

  // Detect if history has secret chat or normal chat signals
  let foundSecret = event.is_secret === true;
  let foundNormal = event.is_secret === false;
  for (const m of event.messages) {
    if (window.E2EE?.isSyncMessage(m.text) || window.E2EE?.isEncrypted(m.text)) {
      foundSecret = true;
      break;
    }
    if (window.E2EE?.isNormalSyncMessage?.(m.text) || (typeof m.text === "string" && m.text.includes("mode:normal"))) {
      foundNormal = true;
    }
  }

  if (foundSecret) {
    setRoomSecretMode(room, true);
  } else if (foundNormal) {
    setRoomSecretMode(room, false);
  }

  const request = requests.get(event.request_id);
  const shouldSelect = request?.kind === "open_group" && event.request_id === lastOpenRequestId;
  if (shouldSelect) {
    selectRoom(event.group_id);
  }

  mergeMessages(room, event.messages);
  updateSecretChatUI(room);
  requests.delete(event.request_id);
  updateRoomControls(room);
}

function handleGroupMessage(event) {
  if (departedGroups.has(event.group_id) && !pendingJoins.has(event.group_id)) return;
  const room = groupRooms.get(event.group_id);
  if (!room) return;
  if (window.E2EE?.isSyncMessage(event.text)) {
    const pin = window.E2EE.extractSyncPin(event.text);
    if (pin) {
      setRoomSecretMode(room, true);
      room.unlockedPin = pin;
      updateSecretChatUI(room);
      window.E2EE.unlockRoom(roomKey(room), pin).then(() => {
        updateSecretChatUI(room);
        renderMessages(room);
        updateRoomControls(room);
      });
    }
    return;
  }
  if (window.E2EE?.isNormalSyncMessage?.(event.text)) {
    setRoomSecretMode(room, false);
    updateSecretChatUI(room);
    return;
  }
  const added = mergeMessages(room, [event]);
  if (added && event.from !== currentName && activeRoomId !== event.group_id) {
    room.unread += 1;
    room.badge.textContent = String(room.unread);
    room.badge.hidden = false;
  }
}

function handleRequestError(event) {
  const request = requests.get(event.request_id);
  if (request?.kind === "summarize") {
    const room = findRoom(request.roomId);
    requests.delete(event.request_id);
    if (room && room.summaryPending === event.request_id) {
      room.summaryPending = null;
      room.summaryPanel.setAttribute("aria-busy", "false");
      room.summaryStatus.textContent = "Summary unavailable. You can keep chatting or try again.";
      room.summaryError.textContent = event.text;
      room.summaryError.hidden = false;
    }
    refreshSummaryControls();
    return;
  }
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
    case "room_summary":
      handleSummary(event);
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

"use strict";

const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

// Minimal DOM surface for exercising the real app's group event handlers.
class Element {
  constructor() {
    this.children = [];
    this.nodes = new Map();
    this.dataset = {};
    this.value = "";
    this.hidden = true;
    this.scrollTop = this.scrollHeight = 0;
    this.classList = { toggle() {} };
  }
  querySelector(selector) {
    if (!this.nodes.has(selector)) this.nodes.set(selector, new Element());
    return this.nodes.get(selector);
  }
  querySelectorAll() { return []; }
  addEventListener() {}
  setAttribute(name, value) { this[name] = value; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  insertBefore(node) { this.children.push(node); }
  cloneNode() { return new Element(); }
  focus() {}
  reset() {}
  close() {}
}

function browser(name) {
  const document = new Element();
  document.createElement = document.createDocumentFragment = () => new Element();
  for (const id of ["#group-room-template", "#private-room-template", "#summary-template"]) {
    document.querySelector(id).content = { firstElementChild: new Element() };
  }
  const sent = [];
  const storage = new Map();
  const context = vm.createContext({
    document, window: { addEventListener() {} },
    localStorage: { getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value) },
    // Configuration loading is unrelated to group events.
    fetch: () => new Promise(() => {}),
    WebSocket: { OPEN: 1 }, crypto: require("node:crypto").webcrypto,
    CSS: { escape: (value) => value },
  });
  vm.runInContext(readFileSync(join(__dirname, "../web/app.js"), "utf8"), context);
  context.connection = { readyState: 1, send: (raw) => sent.push(JSON.parse(raw)) };
  vm.runInContext("socket = connection", context);
  const event = (value) => {
    context.event = value;
    vm.runInContext("handleEvent(event)", context);
  };
  event({ type: "registered", name });
  return { document, sent, event, run: (code) => vm.runInContext(code, context) };
}

const group = { group_id: "group_test", name: "กลุ่มเรียน", creator: "alice", members: ["alice"] };
const snapshot = (members, version = 1) => ({
  type: "groups_updated", version, groups: [{ ...group, members }],
});

test("creator sees the created group and can open it", () => {
  const ui = browser("alice");
  ui.run('pendingGroupRequest = sendCommand({ type: "create_group", name: "กลุ่มเรียน" }, { kind: "create_group" })');
  ui.event({ type: "group_created", group_id: group.group_id, request_id: ui.sent[0].request_id });
  ui.event(snapshot(["alice"]));
  assert.equal(ui.document.querySelector("#group-count").textContent, "1");
  assert.equal(ui.run("groupRooms.size"), 1);
  assert.equal(ui.run('groupRooms.get("group_test").secretPrompt.hidden'), false);
  ui.run('openGroup("group_test")');
  assert.equal(ui.sent.at(-1).type, "open_group");
  ui.event({ type: "group_opened", ...group, messages: [], request_id: ui.sent.at(-1).request_id });
  assert.equal(ui.run('groupRooms.get("group_test").input.disabled'), false);
});

for (const ackFirst of [true, false]) {
  test(`join completes and opens the group (${ackFirst ? "ack" : "snapshot"} first)`, () => {
    const ui = browser("bob");
    ui.event(snapshot(["alice"]));
    assert.equal(ui.run("groupRooms.size"), 0);
    ui.run(`lastJoinRequestId = sendCommand({ type: "join_group", group_id: "group_test" },
      { kind: "join_group", groupId: "group_test", confirmed: false });
      pendingJoins.set("group_test", lastJoinRequestId)`);
    const ack = { type: "group_joined", group_id: group.group_id, request_id: ui.sent[0].request_id };
    const joined = snapshot(["alice", "bob"], 2);
    for (const event of ackFirst ? [ack, joined] : [joined, ack]) ui.event(event);
    assert.equal(ui.run("pendingJoins.size"), 0);
    assert.equal(ui.run("activeRoomId"), group.group_id);
    assert.equal(ui.run('groupRooms.get("group_test").secretPrompt.hidden'), true);
    assert.equal(ui.sent.at(-1).type, "open_group");
    ui.event({ type: "group_opened", ...group, members: ["alice", "bob"], messages: [],
      request_id: ui.sent.at(-1).request_id });
    assert.equal(ui.run('groupRooms.get("group_test").input.disabled'), false);
  });
}

test("reconnecting member restores a saved group without joining again", () => {
  const ui = browser("bob");
  ui.event(snapshot(["alice", "bob"]));
  assert.equal(ui.run("groupRooms.size"), 1);
  assert.equal(ui.document.querySelector("#group-count").textContent, "1");
  assert.equal(ui.sent.length, 0);
});

for (const kind of ["group", "private"]) {
  test(`saved ${kind} history renders after a fresh connection`, () => {
    const ui = browser("bob");
    const id = `${kind}_test`;
    const metadata = kind === "group"
      ? { ...group, members: ["alice", "bob"] }
      : { kind, room_id: id, members: ["alice", "bob"] };
    ui.event(kind === "group" ? snapshot(metadata.members)
      : { type: "private_rooms", rooms: [metadata] });
    ui.run(kind === "group" ? `openGroup("${id}")` : `openPrivate({ room_id: "${id}" })`);
    const message = { type: `${kind}_message`, message_id: "saved_message", sequence: 1,
      from: "alice", to: "bob", text: "ข้อความเก่าก่อน reconnect",
      timestamp: "2026-11-07T06:00:00+00:00", [`${kind === "group" ? "group" : "room"}_id`]: id };
    ui.event({ type: kind === "group" ? "group_opened" : "room_opened", ...metadata,
      messages: [message], request_id: ui.sent.at(-1).request_id });
    const room = ui.run(`findRoom("${id}")`);
    assert.equal(room.messages.get(message.message_id).text, message.text);
    assert.equal(room.list.children[0].children[0].children[1].textContent, message.text);
    assert.equal(room.empty.hidden, true);
  });
}

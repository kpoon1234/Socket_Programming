"""Exercise summary requests over TCP with a controlled offline AI provider."""

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

from test_chat import PROJECT_ROOT, ProcessOutput, ServerTestCase


class SummarySocketTests(ServerTestCase):
    def start_server(self):
        self.release_path = Path(self.state_directory.name) / "release-ai"
        # เปลี่ยนผู้ให้บริการใน process ทดสอบเท่านั้น ไม่มี test hook ในโค้ดจริง
        script = textwrap.dedent('''
            import os
            from pathlib import Path
            import time
            from feature.summarize import service
            from feature.summarize.ai_summarize import SummaryError
            import server

            def complete(prompt, conversation):
                print("Summary provider started", flush=True)
                if "hold-ai" in conversation:
                    deadline = time.monotonic() + 10
                    while not Path(os.environ["SUMMARY_TEST_RELEASE"]).exists():
                        if time.monotonic() >= deadline:
                            raise SummaryError("timeout", "Test AI timed out.")
                        time.sleep(0.01)
                if "rate-limit-ai" in conversation:
                    raise SummaryError("rate_limited", "The AI quota is full.")
                return conversation

            service.summarize_text = complete
            server.PORT = 0
            server.main()
        ''')
        self.server = subprocess.Popen(
            [sys.executable, "-B", "-u", "-c", script], cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            env={**os.environ, "CHAT_STATE_PATH": str(self.state_path),
                 "SUMMARY_TEST_RELEASE": str(self.release_path)},
        )
        self.output = ProcessOutput(self.server)
        ready = self.output.wait_for("Server listening on ")
        self.port = int(ready.rsplit(":", 1)[1])

    def event(self, peer, kind):
        while True:
            event = peer.receive()
            if event["type"] == kind:
                return event

    def group(self, alice, *members):
        alice.send({"type": "create_group", "name": "Summary test", "request_id": "create"})
        group_id = self.event(alice, "group_created")["group_id"]
        for member in members:
            member.send({"type": "join_group", "group_id": group_id, "request_id": "join"})
            self.event(member, "group_joined")
        return group_id

    def send_group(self, peer, group_id, text):
        peer.send({"type": "group_message", "group_id": group_id, "text": text, "request_id": "send"})
        self.event(peer, "sent")

    def summarize(self, peer, room_id, request_id="summary", room_type="group", **extra):
        peer.send({"type": "summarize_room", "room_type": room_type, "room_id": room_id,
                   "request_id": request_id, **extra})

    def probe_no_summary(self, peer):
        peer.send({"type": "message", "to": "bob", "text": "probe"})
        self.assertEqual(peer.receive()["type"], "message")
        self.assertEqual(peer.receive()["type"], "sent")

    def test_private_summary_is_requester_only_does_not_persist_and_ignores_forged_history(self):
        alice, bob, carol = self.peer("alice"), self.peer("bob"), self.peer("carol")
        alice.send({"type": "open_private", "to": "bob", "request_id": "open"})
        room_id = self.event(alice, "room_opened")["room_id"]
        alice.send({"type": "private_message", "room_id": room_id, "text": "งานวันศุกร์", "request_id": "send"})
        self.event(alice, "sent")
        self.event(bob, "message")
        before = self.state_path.read_bytes()
        self.summarize(carol, room_id, room_type="private", request_id="outsider")
        self.assertEqual(self.event(carol, "error")["request_id"], "outsider")
        self.summarize(alice, room_id, room_type="private", messages=[{"text": "forged-history"}], **{"from": "bob"})
        result = self.event(alice, "room_summary")
        self.assertEqual(result["request_id"], "summary")
        self.assertEqual(result["room_type"], "private")
        self.assertEqual(result["message_count"], 1)
        self.assertIn("งานวันศุกร์", result["summary"])
        self.assertNotIn("forged-history", result["summary"])
        self.assertEqual(self.state_path.read_bytes(), before)
        self.probe_no_summary(bob)

    def test_private_history_can_be_summarized_with_peer_offline(self):
        alice, bob = self.peer("alice"), self.peer("bob")
        alice.send({"type": "open_private", "to": "bob", "request_id": "open"})
        room_id = self.event(alice, "room_opened")["room_id"]
        alice.send({"type": "private_message", "room_id": room_id, "text": "Saved history", "request_id": "send"})
        self.event(alice, "sent")
        bob.close()
        self.output.wait_for("Client disconnected: bob")
        self.summarize(alice, room_id, room_type="private")
        self.assertEqual(self.event(alice, "room_summary")["message_count"], 1)

    def test_group_snapshot_excludes_before_join_and_leave_interval(self):
        alice, bob = self.peer("alice"), self.peer("bob")
        group_id = self.group(alice)
        self.send_group(alice, group_id, "hidden-before-join")
        bob.send({"type": "join_group", "group_id": group_id, "request_id": "join"})
        self.event(bob, "group_joined")
        self.send_group(alice, group_id, "visible-one")
        bob.send({"type": "leave_group", "group_id": group_id, "request_id": "leave"})
        self.event(bob, "group_left")
        self.send_group(alice, group_id, "hidden-while-away")
        bob.send({"type": "join_group", "group_id": group_id, "request_id": "rejoin"})
        self.event(bob, "group_joined")
        self.send_group(alice, group_id, "visible-two")
        self.summarize(bob, group_id)
        result = self.event(bob, "room_summary")
        self.assertEqual(result["message_count"], 2)
        self.assertEqual([item["text"] for item in json.loads(result["summary"])], ["visible-one", "visible-two"])

    def test_secret_private_and_group_chats_reject_summary_without_calling_provider(self):
        alice, bob = self.peer("alice"), self.peer("bob")
        alice.send({"type": "open_private", "to": "bob", "request_id": "open"})
        private_id = self.event(alice, "room_opened")["room_id"]
        group_id = self.group(alice, bob)
        for room_type, room_id in (("private", private_id), ("group", group_id)):
            for text in ("🔒 pin:sync:123456", "🔒 enc:v1:salt:tag:ciphertext"):
                with self.subTest(room_type=room_type, text=text):
                    command = {"type": f"{room_type}_message", "text": text, "request_id": "secret"}
                    command["group_id" if room_type == "group" else "room_id"] = room_id
                    alice.send(command)
                    self.event(alice, "sent")
                    # ข้อมูลจาก Client ต้องไม่เปิดสรุปให้ห้องลับได้
                    self.summarize(alice, room_id, room_type=room_type, is_secret=False)
                    error = self.event(alice, "error")
                    self.assertEqual(error["code"], "secret_chat_unsupported")
                    self.assertEqual(error["request_id"], "summary")
                    self.assertEqual(error["room_type"], room_type)
                    self.assertEqual(error["room_id"], room_id)
        self.assertNotIn("Summary provider started", "".join(self.output.history))
        self.send_group(alice, group_id, "🔒 enc:v1:still:chatting:encrypted")

    def test_switching_to_secret_chat_during_summary_discards_result(self):
        alice, bob = self.peer("alice"), self.peer("bob")
        alice.send({"type": "open_private", "to": "bob", "request_id": "open"})
        private_id = self.event(alice, "room_opened")["room_id"]
        group_id = self.group(alice, bob)
        for room_type, room_id in (("private", private_id), ("group", group_id)):
            with self.subTest(room_type=room_type):
                self.release_path.unlink(missing_ok=True)
                command = {"type": f"{room_type}_message", "text": "hold-ai", "request_id": "send"}
                command["group_id" if room_type == "group" else "room_id"] = room_id
                alice.send(command)
                self.event(alice, "sent")
                self.summarize(alice, room_id, room_type=room_type)
                self.output.wait_for("Summary provider started")
                alice.send({**command, "text": "🔒 pin:sync:123456"})
                self.event(alice, "sent")
                self.release_path.touch()
                error = self.event(alice, "error")
                self.assertEqual(error["code"], "secret_chat_unsupported")
                self.assertEqual(error["request_id"], "summary")
                self.assertEqual(error["room_id"], room_id)

    def test_validation_outsider_and_empty_room_do_not_call_provider(self):
        alice, bob, anonymous = self.peer("alice"), self.peer("bob"), self.peer()
        group_id = self.group(alice)
        self.summarize(anonymous, group_id)
        self.assertIn("Register", self.event(anonymous, "error")["text"])
        for peer, room_type, identifier, request_id in (
            (bob, "group", group_id, "outsider"),
            (alice, "invalid", group_id, "invalid-kind"),
            (alice, "group", [], "invalid-id"),
            (alice, "group", group_id, ""),
            (alice, "private", "missing", "missing-room"),
        ):
            self.summarize(peer, identifier, request_id=request_id, room_type=room_type)
            self.assertEqual(self.event(peer, "error")["request_id"], request_id)
        self.summarize(alice, group_id, request_id="empty")
        error = self.event(alice, "error")
        self.assertEqual(error["code"], "no_messages")
        self.assertNotIn("Summary provider started", "".join(self.output.history))

    def test_chat_continues_and_capacity_is_bounded_without_a_queue(self):
        alice, bob, carol = self.peer("alice"), self.peer("bob"), self.peer("carol")
        group_id = self.group(alice, bob, carol)
        self.send_group(alice, group_id, "hold-ai")
        self.summarize(alice, group_id, "first")
        self.output.wait_for("Summary provider started")
        self.summarize(bob, group_id, "second")
        self.output.wait_for("Summary provider started")
        self.summarize(alice, group_id, "duplicate")
        self.assertEqual(self.event(alice, "error")["code"], "summary_pending")
        self.summarize(carol, group_id, "busy")
        self.assertEqual(self.event(carol, "error")["code"], "summary_busy")
        self.send_group(carol, group_id, "Chat works while AI is waiting")
        self.release_path.touch()
        for peer in (alice, bob):
            result = self.event(peer, "room_summary")
            self.assertEqual(result["message_count"], 1)
            self.assertNotIn("Chat works", result["summary"])
        self.summarize(carol, group_id, "after")
        self.assertEqual(self.event(carol, "room_summary")["request_id"], "after")

    def test_leave_and_rejoin_during_ai_invalidates_old_result(self):
        alice, bob = self.peer("alice"), self.peer("bob")
        group_id = self.group(alice, bob)
        self.send_group(alice, group_id, "hold-ai")
        self.summarize(bob, group_id)
        self.output.wait_for("Summary provider started")
        bob.send({"type": "leave_group", "group_id": group_id, "request_id": "leave"})
        self.event(bob, "group_left")
        bob.send({"type": "join_group", "group_id": group_id, "request_id": "rejoin"})
        self.event(bob, "group_joined")
        self.release_path.touch()
        self.assertEqual(self.event(bob, "error")["code"], "access_changed")
        self.summarize(bob, group_id, "new")
        self.assertEqual(self.event(bob, "room_summary")["request_id"], "new")

    def test_disconnect_does_not_send_old_result_to_same_name_new_connection(self):
        alice, bob = self.peer("alice"), self.peer("bob")
        group_id = self.group(alice, bob)
        self.send_group(alice, group_id, "hold-ai")
        self.summarize(bob, group_id, "old")
        self.output.wait_for("Summary provider started")
        bob.close()
        self.output.wait_for("Client disconnected: bob")
        returning = self.peer("bob")
        self.release_path.touch()
        self.summarize(returning, group_id, "new")
        self.assertEqual(self.event(returning, "room_summary")["request_id"], "new")
        self.probe_no_summary(returning)

    def test_ai_failure_is_correlated_and_does_not_disconnect_chat(self):
        alice = self.peer("alice")
        group_id = self.group(alice)
        self.send_group(alice, group_id, "rate-limit-ai")
        self.summarize(alice, group_id, "limited")
        error = self.event(alice, "error")
        self.assertEqual(error["code"], "rate_limited")
        self.assertEqual(error["request_id"], "limited")
        self.send_group(alice, group_id, "Still connected")

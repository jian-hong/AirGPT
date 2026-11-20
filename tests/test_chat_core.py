"""Send, stop, edit, regenerate and history must be correct.

Each test below failed on the code before this lane's changes (see the commit
messages for what was seen failing). They drive the real HTTP handler with a
stand-in for the model call, so the route, the saving and the history building are
the real ones.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import socket
import sys
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import ai_engine  # noqa: E402
import clipdrop  # noqa: E402
import db  # noqa: E402


def _events(raw: bytes) -> list[dict]:
    out = []
    for m in re.finditer(rb"data: (\{.*?\})\n\n", raw, re.S):
        try:
            out.append(json.loads(m.group(1).decode("utf-8")))
        except ValueError:
            pass
    return out


class ChatCoreBase(unittest.TestCase):
    def setUp(self):
        self.calls: list[dict] = []
        self._orig = (
            clipdrop._chat_stream_events, clipdrop._check_ai_rate,
            clipdrop._is_online, clipdrop._ai_allowed,
        )
        clipdrop._check_ai_rate = lambda: None
        clipdrop._is_online = lambda: True
        clipdrop._ai_allowed = lambda: True
        clipdrop._chat_stream_events = self._fake_events
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addr = self.srv.server_address
        self.sids: list[int] = []

    def tearDown(self):
        (clipdrop._chat_stream_events, clipdrop._check_ai_rate,
         clipdrop._is_online, clipdrop._ai_allowed) = self._orig
        for sid in self.sids:
            db.delete_session(sid)
        self.srv.shutdown()
        self.srv.server_close()

    def new_chat(self, capture_type="ai") -> int:
        sid = int(db.create_session("t", capture_type=capture_type)["id"])
        self.sids.append(sid)
        return sid

    # What the model call is replaced with: records what it was given, then answers.
    def _fake_events(self, question, mode, history, abort, **kw):
        self.calls.append({"question": question, "history": [dict(m) for m in (history or [])], **kw})
        yield {"type": "token", "text": "Answer "}
        yield {"type": "token", "text": "to: " + question[:30]}
        yield {"type": "done", "analysis": "Answer to: " + question[:30], "model": "stand-in"}

    def post(self, path, body) -> tuple[int, list[dict], dict]:
        c = http.client.HTTPConnection(*self.addr, timeout=20)
        c.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
        r = c.getresponse()
        raw = r.read()
        c.close()
        if r.getheader("Content-Type", "").startswith("text/event-stream"):
            return r.status, _events(raw), {}
        try:
            return r.status, [], json.loads(raw or b"{}")
        except ValueError:
            return r.status, [], {}

    def rows(self, sid):
        return db.get_messages(session_id=sid, limit=500)


class HistoryTest(ChatCoreBase):
    def test_first_message_sends_no_history(self):
        sid = self.new_chat()
        self.post("/api/chat/stream", {"session_id": sid, "text": "start a plan"})
        self.assertEqual(self.calls[0]["history"], [], "the question was handed over as history of itself")

    def test_second_message_history_is_the_first_turn_only(self):
        sid = self.new_chat()
        self.post("/api/chat/stream", {"session_id": sid, "text": "first"})
        self.post("/api/chat/stream", {"session_id": sid, "text": "second"})
        got = [(m["role"], m["content"]) for m in self.calls[1]["history"]]
        self.assertEqual(got, [("user", "first"), ("assistant", "Answer to: first")])

    def test_scratch_chat_sends_no_history(self):
        sid = self.new_chat("scratch")
        self.post("/api/chat/stream", {"session_id": sid, "text": "hi"})
        self.post("/api/chat/stream", {"session_id": sid, "text": "thanks"})
        self.assertEqual(self.calls[1]["history"], [])

    def test_long_chat_is_cut_by_budget_not_by_a_12_message_cap(self):
        sid = self.new_chat()
        for i in range(30):
            db.add_message(device_ip="x", device_name="me", text=f"q{i}", source="ai-chat", session_id=sid)
            db.add_message(device_ip="x", device_name="AirGPT", text=f"a{i}", source="ai", session_id=sid)
        self.post("/api/chat/stream", {"session_id": sid, "text": "now"})
        self.assertEqual(len(self.calls[0]["history"]), 60)
        self.assertEqual(self.calls[0]["history"][0]["content"], "q0")
        self.assertEqual(self.calls[0]["history_older"], 0)

    def test_messages_older_than_the_read_window_are_counted(self):
        sid = self.new_chat()
        for i in range(70):
            db.add_message(device_ip="x", device_name="me", text=f"q{i}", source="ai-chat", session_id=sid)
            db.add_message(device_ip="x", device_name="AirGPT", text=f"a{i}", source="ai", session_id=sid)
        self.post("/api/chat/stream", {"session_id": sid, "text": "now"})
        self.assertEqual(len(self.calls[0]["history"]), 60)
        self.assertEqual(self.calls[0]["history_older"], 80)


class PromptBuildTest(unittest.TestCase):
    def setUp(self):
        self._orig = ai_engine.retrieve_vault_snippets
        ai_engine.retrieve_vault_snippets = lambda *a, **k: ""
        self.sids: list[int] = []

    def tearDown(self):
        ai_engine.retrieve_vault_snippets = self._orig
        for sid in self.sids:
            db.delete_session(sid)

    def _chat(self, kind="ai"):
        sid = int(db.create_session("t", capture_type=kind)["id"])
        self.sids.append(sid)
        return sid

    def test_empty_history_stays_empty(self):
        sid = self._chat()
        db.add_message(device_ip="x", device_name="me", text="start a plan", source="ai-chat", session_id=sid)
        prompt, *_ = ai_engine._prepare_text_chat("start a plan", "general", session_id=sid, history=[])
        self.assertEqual(prompt.count("start a plan"), 1)
        self.assertNotIn("Conversation history", prompt)

    def test_panel_counts_include_older_messages_not_read(self):
        from prompt_trace import finalize, new
        trace = new("direct")
        hist = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        ai_engine._prepare_text_chat("q", "general", history=hist, history_older=40, trace=trace)
        h = finalize(trace)["history"]
        self.assertEqual((h["available"], h["sent"], h["dropped"]), (42, 2, 40))
        note = [s for s in finalize(trace)["sections"] if s["key"] == "history"][0]["note"]
        self.assertIn("2 of 42", note)
        self.assertIn("40", note)

    def test_fallback_skips_only_the_question_being_asked(self):
        sid = self._chat()
        for t, src in (("same", "ai-chat"), ("an answer", "ai"), ("same", "ai-chat")):
            db.add_message(device_ip="x", device_name="AirGPT" if src == "ai" else "me", text=t, source=src, session_id=sid)
        got = ai_engine._session_history_messages(sid, "[skill]\n\nsame")
        self.assertEqual([m["content"] for m in got], ["same", "an answer"])

    def test_fallback_respects_scratch(self):
        sid = self._chat("scratch")
        db.add_message(device_ip="x", device_name="me", text="old", source="ai-chat", session_id=sid)
        self.assertEqual(ai_engine._session_history_messages(sid, "new"), [])


class StopTest(ChatCoreBase):
    def setUp(self):
        super().setUp()
        self.produced = 0
        self.closed = threading.Event()
        self.first_token = threading.Event()

    def _fake_events(self, question, mode, history, abort, **kw):
        self.calls.append({"question": question})
        try:
            yield {"type": "thinking", "text": "Preparing"}
            for i in range(60):
                self.produced += 1
                yield {"type": "token", "text": f"w{i} "}
                if i == 2:
                    self.first_token.set()
                time.sleep(0.05)
            yield {"type": "done", "analysis": "FULL ANSWER", "model": "stand-in"}
        finally:
            self.closed.set()

    def _open(self, sid, text="long one"):
        body = json.dumps({"session_id": sid, "text": text}).encode()
        s = socket.create_connection(self.addr, timeout=20)
        s.sendall(b"POST /api/chat/stream HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                  b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
        return s

    def _read_until_closed(self, s) -> bytes:
        raw = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                return raw
            raw += chunk
            if raw.endswith(b"0\r\n\r\n"):
                return raw

    def test_stop_ends_the_model_call_and_keeps_the_partial_answer(self):
        sid = self.new_chat()
        s = self._open(sid)
        self.assertTrue(self.first_token.wait(5))
        raw = b""
        while b"stream_id" not in raw:
            raw += s.recv(4096)
        stream_id = _events(raw)[0]["stream_id"]
        code, _, out = self.post("/api/chat/cancel", {"stream_id": stream_id})
        self.assertEqual((code, out.get("stopped")), (200, True))
        raw += self._read_until_closed(s)
        s.close()
        evs = _events(raw)
        self.assertEqual(evs[-1]["type"], "stopped")
        self.assertTrue(evs[-1]["saved"])
        self.assertTrue(self.closed.wait(2), "the model call was left running after Stop")
        made = self.produced
        time.sleep(0.6)
        self.assertEqual(self.produced, made, "tokens were still being made after Stop")
        replies = [m for m in self.rows(sid) if m["source"] == "ai"]
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["ai_status"], "stopped")
        self.assertTrue(replies[0]["text"].startswith("w0 w1"))
        self.assertNotIn("FULL ANSWER", replies[0]["text"])

    def test_stop_before_any_text_saves_no_reply(self):
        sid = self.new_chat()
        started = threading.Event()

        def silent(question, mode, history, abort, **kw):
            started.set()
            yield {"type": "thinking", "text": "Preparing"}
            time.sleep(5)
            yield {"type": "done", "analysis": "LATE", "model": "stand-in"}

        clipdrop._chat_stream_events = silent
        s = self._open(sid)
        self.assertTrue(started.wait(5))
        raw = b""
        while b"stream_id" not in raw:
            raw += s.recv(4096)
        self.post("/api/chat/cancel", {"stream_id": _events(raw)[0]["stream_id"]})
        raw += self._read_until_closed(s)
        s.close()
        self.assertEqual(_events(raw)[-1], {"type": "stopped", "saved": False, "session_id": sid})
        time.sleep(0.3)
        self.assertEqual([m for m in self.rows(sid) if m["source"] == "ai"], [])

    def test_cancel_of_an_unknown_stream_says_so(self):
        code, _, out = self.post("/api/chat/cancel", {"stream_id": "nope"})
        self.assertEqual((code, out.get("stopped")), (200, False))

    def test_a_finished_stream_cannot_be_cancelled(self):
        sid = self.new_chat()
        clipdrop._chat_stream_events = ChatCoreBase._fake_events.__get__(self)
        _, evs, _ = self.post("/api/chat/stream", {"session_id": sid, "text": "quick"})
        stream_id = evs[0]["stream_id"]
        self.assertFalse(self.post("/api/chat/cancel", {"stream_id": stream_id})[2]["stopped"])
        self.assertEqual(len([m for m in self.rows(sid) if m["source"] == "ai"]), 1)
        self.assertNotIn("stopped", [m["ai_status"] for m in self.rows(sid)])


class ChangeLastTurnTest(ChatCoreBase):
    def _turn(self, sid, q="old question", a="old answer"):
        u = db.add_message(device_ip="x", device_name="me", text=q, source="ai-chat", session_id=sid)
        r = db.add_message(device_ip="x", device_name="AirGPT", text=a, source="ai", session_id=sid)
        return u, r

    def test_edit_replaces_the_question_and_its_answer(self):
        sid = self.new_chat()
        u0, r0 = self._turn(sid, "first", "first answer")
        u1, r1 = self._turn(sid)
        code, evs, _ = self.post("/api/chat/stream", {"session_id": sid, "text": "better question", "replace_msg_id": u1["id"]})
        self.assertEqual(code, 200)
        texts = [(m["source"], m["text"]) for m in self.rows(sid)]
        self.assertEqual(texts, [("ai-chat", "first"), ("ai", "first answer"),
                                 ("ai-chat", "better question"), ("ai", "Answer to: better question")])
        self.assertEqual([m["content"] for m in self.calls[0]["history"]], ["first", "first answer"])

    def test_regenerate_asks_the_same_question_without_a_second_copy(self):
        sid = self.new_chat()
        u, r = self._turn(sid)
        code, evs, _ = self.post("/api/chat/stream", {"session_id": sid, "text": "ignored", "regenerate_msg_id": u["id"]})
        self.assertEqual(code, 200)
        rows = self.rows(sid)
        self.assertEqual([(m["source"], m["text"]) for m in rows],
                         [("ai-chat", "old question"), ("ai", "Answer to: old question")])
        self.assertEqual(rows[0]["id"], u["id"], "the question must stay the same row")
        self.assertEqual(self.calls[0]["history"], [], "the old answer must not be history for its own redo")

    def _remember(self, sid, q, a):
        import memory_index as mi

        return mi.add_memory(kind="memory", title=q[:56], body=f"Q: {q}\nA: {a}", session_id=sid,
                             folder="session", source="chat_turn")

    def _memory_bodies(self, sid):
        import memory_index as mi

        return [m["body"] for m in mi.list_memories(session_id=sid, kind="memory", limit=200)
                if int(m.get("session_id") or 0) == sid]

    def test_edit_and_regenerate_forget_the_old_turn_in_memory(self):
        for key in ("replace_msg_id", "regenerate_msg_id"):
            sid = self.new_chat()
            u, _ = self._turn(sid, f"unique question {key}", "the answer I threw away")
            self._remember(sid, f"unique question {key}", "the answer I threw away")
            keep = self._remember(sid, "an older unrelated thing", "stays")
            self.assertEqual(len(self._memory_bodies(sid)), 2)
            self.post("/api/chat/stream", {"session_id": sid, "text": "better", key: u["id"]})
            bodies = self._memory_bodies(sid)
            self.assertFalse([b for b in bodies if "the answer I threw away" in b], (key, bodies))
            self.assertTrue([b for b in bodies if "stays" in b], "other notes must stay")

    def test_failed_regenerate_keeps_the_old_reply(self):
        sid = self.new_chat()
        u, r = self._turn(sid)

        def broken(question, mode, history, abort, **kw):
            yield {"type": "error", "text": "model down"}

        clipdrop._chat_stream_events = broken
        self.post("/api/chat/stream", {"session_id": sid, "text": "x", "regenerate_msg_id": u["id"]})
        self.assertEqual([m["text"] for m in self.rows(sid)], ["old question", "old answer"])

    def test_only_the_last_turn_can_change(self):
        sid = self.new_chat()
        u0, _ = self._turn(sid, "first", "a1")
        self._turn(sid, "second", "a2")
        for key in ("regenerate_msg_id", "replace_msg_id"):
            code, _, out = self.post("/api/chat/stream", {"session_id": sid, "text": "t", key: u0["id"]})
            self.assertEqual(code, 409, key)
            self.assertIn("last question", out["error"])
        self.assertEqual(len(self.rows(sid)), 4)

    def test_a_message_from_another_chat_cannot_be_changed_through_this_one(self):
        a, b = self.new_chat(), self.new_chat()
        u, _ = self._turn(a)
        code, _, _ = self.post("/api/chat/stream", {"session_id": b, "text": "t", "replace_msg_id": u["id"]})
        self.assertEqual(code, 409)
        self.assertEqual(len(self.rows(a)), 2)


class RateLimitTest(ChatCoreBase):
    def test_refusal_carries_the_wait_in_seconds(self):
        clipdrop._check_ai_rate = lambda: "Free tier: 1 AI request/min. Wait 42s or add your API key in Settings."
        code, _, out = self.post("/api/chat/stream", {"text": "hello"})
        self.assertEqual((code, out.get("retry_after")), (429, 42))


class CortexDownWordingTest(unittest.TestCase):
    def test_no_developer_error_reaches_the_person(self):
        import cortex_client
        orig = (cortex_client.engine_agent_loop, ai_engine.chat_text_stream, clipdrop._ai_lockdown_block)
        cortex_client.engine_agent_loop = lambda *a, **k: {
            "ok": False, "reason": "wrong_surface",
            "error": "http://127.0.0.1:8010 has no /api/engine/specs. Point CORTEX_API_URL at CortexOS.api.main, not constructor_app.",
        }
        ai_engine.chat_text_stream = lambda *a, **k: iter(())
        clipdrop._ai_lockdown_block = lambda: None
        try:
            evs = list(clipdrop._chat_stream_events("hi", "general", [], threading.Event()))
        finally:
            cortex_client.engine_agent_loop, ai_engine.chat_text_stream, clipdrop._ai_lockdown_block = orig
        said = " ".join(e.get("text", "") for e in evs if e.get("type") == "thinking")
        self.assertNotIn("CORTEX_API_URL", said)
        self.assertNotIn("constructor_app", said)
        self.assertNotIn("Quality loop", said)
        self.assertIn("Cortex is not running", said)


if __name__ == "__main__":
    unittest.main()

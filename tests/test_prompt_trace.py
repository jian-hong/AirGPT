"""The prompt lens must show the prompt that was sent, not a description of one.

A viewer that rebuilds the prompt from its own idea of the pipeline drifts the first
time someone adds a block to the real request. So the trace is filled at the lines
that build the request, and these tests pin the property that matters: the recorded
sections add up to the exact string handed to the provider.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import ai_engine  # noqa: E402
import clipdrop  # noqa: E402
import db  # noqa: E402
import prompt_trace  # noqa: E402

NOTE = "- Founder prefers answers in bullet form."
HISTORY = [
    {"role": "user", "content": "We are planning the Q3 launch."},
    {"role": "assistant", "content": "Understood. What is the date?"},
]


class AssembledPromptTest(unittest.TestCase):
    def setUp(self):
        self._orig = ai_engine.retrieve_vault_snippets
        ai_engine.retrieve_vault_snippets = lambda *a, **k: NOTE

    def tearDown(self):
        ai_engine.retrieve_vault_snippets = self._orig

    def _prep(self, question="Summarise the plan so far"):
        trace = prompt_trace.new("direct")
        prompt, mode, has_vault, gate = ai_engine._prepare_text_chat(
            question, "general", history=[dict(m) for m in HISTORY], trace=trace,
        )
        return prompt, prompt_trace.finalize(trace)

    def test_sections_add_up_to_the_prompt_that_was_built(self):
        prompt, trace = self._prep()
        self.assertEqual(
            trace["total_chars"], len(prompt),
            "a block reached the prompt without reaching the trace (or the reverse)",
        )

    def test_each_block_is_the_text_that_was_sent(self):
        prompt, trace = self._prep()
        by_key = {s["key"]: s for s in trace["sections"]}
        self.assertEqual(sorted(by_key), ["history", "instructions", "memory", "question"])
        # Not assertEqual: the injection guard wraps the question in markers, and the
        # trace shows the wrapped form because that is what the model receives.
        self.assertIn("Summarise the plan so far", by_key["question"]["text"])
        for key in ("question", "history", "memory"):
            self.assertIn(by_key[key]["text"], prompt)
        self.assertIn(NOTE, by_key["memory"]["text"])
        self.assertIn("Q3 launch", by_key["history"]["text"])
        self.assertTrue(by_key["memory"].get("private"))

    def test_history_counts_are_reported(self):
        _, trace = self._prep()
        self.assertEqual(trace["history"], {
            "available": 2, "sent": 2, "dropped": 0, "compressed": 0,
            "budget_chars": ai_engine.HISTORY_BUDGET_CHARS,
        })

    def test_a_block_that_was_not_sent_is_not_listed(self):
        ai_engine.retrieve_vault_snippets = lambda *a, **k: ""
        prompt, trace = self._prep()
        self.assertNotIn("memory", [s["key"] for s in trace["sections"]])
        self.assertEqual(trace["total_chars"], len(prompt))

    def test_no_trace_argument_changes_nothing(self):
        with_trace, _ = self._prep()
        plain, *_ = ai_engine._prepare_text_chat(
            "Summarise the plan so far", "general", history=[dict(m) for m in HISTORY],
        )
        self.assertEqual(plain, with_trace)

    def test_stream_emits_the_trace_for_the_request_it_made(self):
        calls = []
        orig = (ai_engine._standard_llm_stream, ai_engine.route_request, ai_engine._finish_chat_side_effects)

        def fake_stream(prompt, system="", **kw):
            calls.append((prompt, system))
            return iter(["ok"]), ["test-model"]

        ai_engine._standard_llm_stream = fake_stream
        ai_engine.route_request = lambda *a, **k: {"complexity": "low"}
        ai_engine._finish_chat_side_effects = lambda **k: None
        try:
            events = list(ai_engine.chat_text_stream(
                "Summarise the plan so far", history=[dict(m) for m in HISTORY], thinking=False,
            ))
        finally:
            (ai_engine._standard_llm_stream, ai_engine.route_request,
             ai_engine._finish_chat_side_effects) = orig
        kinds = [e["type"] for e in events]
        self.assertLess(kinds.index("prompt_trace"), kinds.index("done"))
        trace = next(e["trace"] for e in events if e["type"] == "prompt_trace")
        prompt, system = calls[0]
        by_key = {s["key"]: s for s in trace["sections"]}
        # The system block shown is the one the provider call ends up sending.
        self.assertEqual(by_key["system"]["text"], ai_engine._effective_system(system))
        user_side = sum(s["chars"] for s in trace["sections"] if s["key"] not in ("system", "tools"))
        self.assertEqual(user_side, len(prompt))
        # This fake provider attached no tools, so none may be counted.
        self.assertNotIn("tools", by_key)
        self.assertEqual(trace["model"], "test-model")

    def test_tools_are_listed_only_when_a_provider_call_attached_them(self):
        orig = (ai_engine._standard_llm_stream, ai_engine.route_request, ai_engine._finish_chat_side_effects)

        def fake_stream(prompt, system="", **kw):
            ai_engine._turn.tools_sent = True   # what _standard_llm does when it attaches them
            return iter(["ok"]), ["cloud-model"]

        ai_engine._standard_llm_stream = fake_stream
        ai_engine.route_request = lambda *a, **k: {"complexity": "low"}
        ai_engine._finish_chat_side_effects = lambda **k: None
        try:
            events = list(ai_engine.chat_text_stream("Summarise the plan so far", thinking=False))
        finally:
            (ai_engine._standard_llm_stream, ai_engine.route_request,
             ai_engine._finish_chat_side_effects) = orig
        trace = next(e["trace"] for e in events if e["type"] == "prompt_trace")
        keys = [s["key"] for s in trace["sections"]]
        self.assertEqual("tools" in keys, bool(ai_engine._chat_tool_defs("chat")))


class RecordingFailureTest(unittest.TestCase):
    def test_a_broken_record_never_costs_the_answer(self):
        orig = (ai_engine._standard_llm_stream, ai_engine.route_request,
                ai_engine._finish_chat_side_effects, prompt_trace.finalize)

        def boom(trace):
            raise RuntimeError("disk full")

        ai_engine._standard_llm_stream = lambda prompt, system="", **kw: (iter(["the answer"]), ["m"])
        ai_engine.route_request = lambda *a, **k: {"complexity": "low"}
        ai_engine._finish_chat_side_effects = lambda **k: None
        prompt_trace.finalize = boom
        try:
            events = list(ai_engine.chat_text_stream("hello there", thinking=False))
        finally:
            (ai_engine._standard_llm_stream, ai_engine.route_request,
             ai_engine._finish_chat_side_effects, prompt_trace.finalize) = orig
        done = [e for e in events if e["type"] == "done"]
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["analysis"], "the answer")
        # No record is claimed: nothing gets stored, so the panel says "no record".
        self.assertIsNone(next(e for e in events if e["type"] == "prompt_trace")["trace"])


class CortexRouteTest(unittest.TestCase):
    """On the Cortex route AirGPT can only vouch for what it handed over."""

    def _loop_prompt(self, question, history):
        # Mirrors the assembly in clipdrop._chat_stream_events.
        prior = []
        for m in history[-8:]:
            content = str(m.get("content") or "").strip()[:500]
            if content:
                prior.append(f"{m.get('role') or 'user'}: {content}")
        return ("Prior turns:\n" + "\n".join(prior) + "\n\nUser:\n" + question) if prior else question

    def test_sections_add_up_to_what_was_handed_to_cortex(self):
        history = [{"role": "user", "content": "x" * 900}] + [dict(m) for m in HISTORY] * 5
        question = "What did we decide?"
        loop_prompt = self._loop_prompt(question, history)
        trace = clipdrop._cortex_prompt_trace(
            question, history, loop_prompt, mode="general", tier="high", web_search=True,
        )
        self.assertEqual(trace["total_chars"], len(loop_prompt))
        self.assertEqual(trace["history"]["sent"], 8)
        self.assertEqual(trace["history"]["available"], 11)
        self.assertEqual(trace["history"]["dropped"], 3)
        self.assertTrue(trace["opaque"], "the part Cortex adds must be flagged as not visible")
        self.assertTrue(any("web_search" in n for n in trace["notes"]))

    def test_first_turn_has_no_history_block(self):
        trace = clipdrop._cortex_prompt_trace("hello", [], "hello", mode="general", tier="high", web_search=False)
        self.assertEqual([s["key"] for s in trace["sections"]], ["question"])
        self.assertEqual(trace["total_chars"], len("hello"))


class EffectiveSystemTest(unittest.TestCase):
    def test_security_block_is_appended_once(self):
        once = ai_engine._effective_system("Be brief.")
        self.assertEqual(ai_engine._effective_system(once), once)
        if ai_engine._security:
            self.assertEqual(once.count(ai_engine._security.SECURITY_SYSTEM), 1)


class RedactionTest(unittest.TestCase):
    def test_private_text_is_removed_and_size_kept(self):
        trace = prompt_trace.new("direct")
        prompt_trace.add(trace, "memory", "Memory notes", "secret note", private=True)
        prompt_trace.add(trace, "question", "Your message", "hello")
        red = prompt_trace.redact_private(prompt_trace.finalize(trace))
        mem = next(s for s in red["sections"] if s["key"] == "memory")
        self.assertNotIn("text", mem)
        self.assertTrue(mem["redacted"])
        self.assertEqual(mem["chars"], len("secret note"))
        self.assertEqual(next(s for s in red["sections"] if s["key"] == "question")["text"], "hello")
        # the stored trace is untouched
        self.assertEqual(trace["sections"][0]["text"], "secret note")


class PromptTraceHttpTest(unittest.TestCase):
    def setUp(self):
        def stream(question, mode, history, abort, **kw):
            trace = prompt_trace.new("direct", mode=mode)
            prompt_trace.add(trace, "question", "Your message", question)
            prompt_trace.add(trace, "memory", "Memory notes", NOTE, private=True)
            yield {"type": "prompt_trace", "trace": prompt_trace.finalize(trace)}
            yield {"type": "token", "text": "Done."}
            yield {"type": "done", "analysis": "Done.", "model": "test-model"}

        self._orig = (
            clipdrop._chat_stream_events, clipdrop._check_ai_rate,
            clipdrop._is_online, clipdrop._ai_allowed,
        )
        clipdrop._chat_stream_events = stream
        clipdrop._check_ai_rate = lambda: None
        clipdrop._is_online = lambda: True
        clipdrop._ai_allowed = lambda: True
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]
        self.sid = int(db.create_session("Prompt lens", capture_type="ai")["id"])

    def tearDown(self):
        (clipdrop._chat_stream_events, clipdrop._check_ai_rate,
         clipdrop._is_online, clipdrop._ai_allowed) = self._orig
        db.delete_session(self.sid)
        self.srv.shutdown()
        self.srv.server_close()

    def _ask(self):
        req = urllib.request.Request(
            self.base + "/api/chat/stream",
            data=json.dumps({"session_id": self.sid, "text": "what was sent?", "mode": "general"}).encode(),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode()
        deadline = time.time() + 10
        while time.time() < deadline:
            replies = [m for m in db.get_messages(session_id=self.sid, limit=50) if m.get("source") == "ai"]
            if replies:
                return body, int(replies[-1]["id"])
            time.sleep(0.1)
        self.fail("reply was never saved")

    def _get(self, query, headers=None):
        req = urllib.request.Request(self.base + "/api/chat/prompt-trace?" + query, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def test_trace_is_stored_with_the_reply_and_read_back(self):
        body, mid = self._ask()
        self.assertNotIn("prompt_trace", body, "the trace belongs to the reply row, not the token stream")
        code, got = self._get(f"message_id={mid}")
        self.assertEqual(code, 200)
        self.assertEqual(got["session_id"], self.sid)
        self.assertTrue(got["host_view"])
        self.assertEqual(got["trace"]["model"], "test-model")
        self.assertEqual(got["trace"]["reply_chars"], len("Done."))
        self.assertGreaterEqual(got["trace"]["elapsed_ms"], 0)
        texts = {s["key"]: s.get("text") for s in got["trace"]["sections"]}
        self.assertEqual(texts["question"], "what was sent?")
        self.assertEqual(texts["memory"], NOTE)

    def test_latest_for_a_chat(self):
        _, mid = self._ask()
        code, got = self._get(f"session_id={self.sid}")
        self.assertEqual((code, got["message_id"]), (200, mid))

    def test_reply_without_a_record_says_so(self):
        code, got = self._get("message_id=999999999")
        self.assertEqual(code, 404)
        self.assertEqual(got["error"], "not_recorded")

    def test_a_device_that_is_not_the_host_never_gets_memory_text(self):
        _, mid = self._ask()
        # The S1 and auth gates sit in front of this handler and have their own tests.
        # This pins the handler's own branch: when the host check says "not the host",
        # the memory text must not leave.
        orig = (clipdrop._is_host_request, clipdrop._s1_remote_open)
        clipdrop._is_host_request = lambda headers, ip: False
        clipdrop._s1_remote_open = lambda: True   # as if the host passcode is set
        try:
            code, got = self._get(f"message_id={mid}")
        finally:
            clipdrop._is_host_request, clipdrop._s1_remote_open = orig
        self.assertEqual(code, 200)
        self.assertFalse(got["host_view"])
        mem = next(s for s in got["trace"]["sections"] if s["key"] == "memory")
        self.assertNotIn("text", mem)
        self.assertEqual(mem["chars"], len(NOTE))
        self.assertNotIn(NOTE, json.dumps(got))

    def test_a_tunnel_device_without_a_passcode_gets_nothing_at_all(self):
        _, mid = self._ask()
        code, got = self._get(f"message_id={mid}", headers={"Host": "demo.trycloudflare.com"})
        self.assertIn(code, (401, 403))
        self.assertNotIn("trace", got)

if __name__ == "__main__":
    unittest.main()

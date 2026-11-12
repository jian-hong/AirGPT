"""Custom instructions for one chat: storage, API, trust boundary, and the real prompt."""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import ai_engine  # noqa: E402
import chat_prefs  # noqa: E402
import clipdrop  # noqa: E402
import db  # noqa: E402
import prompt_trace  # noqa: E402

TEXT = "Answer in Malay."


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.sid = int(db.create_session("Prefs store", capture_type="ai")["id"])

    def tearDown(self):
        chat_prefs.set(self.sid, "")
        db.delete_session(self.sid)

    def test_round_trip_and_clear(self):
        self.assertEqual(chat_prefs.get(self.sid), "")
        chat_prefs.set(self.sid, "  " + TEXT + " ")
        self.assertEqual(chat_prefs.get(self.sid), TEXT)
        chat_prefs.set(self.sid, "")
        self.assertEqual(chat_prefs.get(self.sid), "")

    def test_deleting_a_chat_removes_its_instructions(self):
        chat_prefs.set(self.sid, TEXT)
        db.delete_session(self.sid)
        with db._lock, db._connect() as conn:
            n = conn.execute("SELECT COUNT(*) FROM session_prefs WHERE session_id=?", (self.sid,)).fetchone()[0]
        self.assertEqual(n, 0)

    def test_too_long_is_refused_not_cut(self):
        chat_prefs.set(self.sid, TEXT)
        with self.assertRaises(ValueError) as cm:
            chat_prefs.set(self.sid, "x" * (chat_prefs.MAX_CHARS + 1))
        self.assertIn("4,000", str(cm.exception))
        self.assertEqual(chat_prefs.get(self.sid), TEXT)
        chat_prefs.set(self.sid, "x" * chat_prefs.MAX_CHARS)
        self.assertEqual(len(chat_prefs.get(self.sid)), chat_prefs.MAX_CHARS)

    def test_no_session_is_refused(self):
        with self.assertRaises(ValueError):
            chat_prefs.set(0, TEXT)
        self.assertEqual(chat_prefs.get(0), "")


class PromptTest(unittest.TestCase):
    def setUp(self):
        self._orig = ai_engine.retrieve_vault_snippets
        ai_engine.retrieve_vault_snippets = lambda *a, **k: ""
        self.sid = int(db.create_session("Prefs prompt", capture_type="ai")["id"])
        self.other = int(db.create_session("Prefs other", capture_type="ai")["id"])
        chat_prefs.set(self.sid, TEXT)

    def tearDown(self):
        ai_engine.retrieve_vault_snippets = self._orig
        for s in (self.sid, self.other):
            chat_prefs.set(s, "")
            db.delete_session(s)

    def _prep(self, sid):
        trace = prompt_trace.new("direct")
        prompt, *_ = ai_engine._prepare_text_chat(
            "hello there", "general", session_id=sid, history=[], trace=trace)
        return prompt, prompt_trace.finalize(trace)

    def test_direct_route_sends_and_records_it(self):
        prompt, trace = self._prep(self.sid)
        self.assertIn(TEXT, prompt)
        self.assertEqual(trace["total_chars"], len(prompt))
        sec = next(s for s in trace["sections"] if s["key"] == "chat_instructions")
        self.assertEqual(sec["label"], "Chat instructions")
        self.assertIn(TEXT, sec["text"])
        self.assertIn(sec["text"], prompt)

    def test_other_chat_and_no_chat_do_not_get_it(self):
        for sid in (self.other, 0):
            prompt, trace = self._prep(sid)
            self.assertNotIn(TEXT, prompt)
            self.assertNotIn("chat_instructions", [s["key"] for s in trace["sections"]])
            self.assertEqual(trace["total_chars"], len(prompt))

    def test_cortex_route_sends_it_and_sections_add_up(self):
        import cortex_client

        captured = {}
        orig = cortex_client.engine_agent_loop

        def fake(prompt, **kw):
            captured["prompt"] = prompt
            return {"ok": True, "content": "ok"}

        cortex_client.engine_agent_loop = fake
        try:
            hist = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}]
            for sid, has in ((self.sid, True), (self.other, False)):
                events = list(clipdrop._chat_stream_events(
                    "What now?", "general", hist, threading.Event(), session_id=sid))
                trace = next(e["trace"] for e in events if e["type"] == "prompt_trace")
                self.assertEqual(TEXT in captured["prompt"], has)
                self.assertEqual(trace["total_chars"], len(captured["prompt"]))
                self.assertEqual("chat_instructions" in [s["key"] for s in trace["sections"]], has)
        finally:
            cortex_client.engine_agent_loop = orig


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]
        self.sid = int(db.create_session("Prefs api", capture_type="ai")["id"])
        self.other = int(db.create_session("Prefs api other", capture_type="ai")["id"])
        self._orig = (clipdrop._is_host_request, clipdrop._s1_remote_open,
                      clipdrop.app_auth.token_session_acl, clipdrop._needs_establish)

    def tearDown(self):
        clipdrop._is_host_request, clipdrop._s1_remote_open = self._orig[:2]
        clipdrop.app_auth.token_session_acl = self._orig[2]
        clipdrop._needs_establish = self._orig[3]
        for s in (self.sid, self.other):
            chat_prefs.set(s, "")
            db.delete_session(s)
        self.srv.shutdown()
        self.srv.server_close()

    def _call(self, method, path, body=None):
        req = urllib.request.Request(
            self.base + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def _guest(self, scoped):
        clipdrop._is_host_request = lambda h, ip: False
        clipdrop._s1_remote_open = lambda: True
        clipdrop._needs_establish = lambda method, path: False   # the establish gate has its own tests
        clipdrop.app_auth.token_session_acl = lambda tok: scoped

    def test_host_set_get_clear(self):
        code, got = self._call("POST", "/api/chat/prefs", {"session_id": self.sid, "instructions": TEXT})
        self.assertEqual((code, got["instructions"]), (200, TEXT))
        code, got = self._call("GET", f"/api/chat/prefs?session_id={self.sid}")
        self.assertEqual((code, got["instructions"], got["limit"]), (200, TEXT, 4000))
        self.assertEqual(self._call("POST", "/api/chat/prefs", {"session_id": self.sid, "instructions": ""})[0], 200)
        self.assertEqual(self._call("GET", f"/api/chat/prefs?session_id={self.sid}")[1]["instructions"], "")

    def test_refusals_are_plain(self):
        code, got = self._call("POST", "/api/chat/prefs", {"session_id": self.sid, "instructions": "x" * 4001})
        self.assertEqual(code, 400)
        self.assertIn("Too long", got["error"])
        self.assertEqual(chat_prefs.get(self.sid), "")
        code, got = self._call("POST", "/api/chat/prefs", {"session_id": 0, "instructions": "a"})
        self.assertEqual(code, 404)
        self.assertIn("not been created", got["error"])
        self.assertEqual(self._call("POST", "/api/chat/prefs", {"session_id": "abc"})[0], 400)
        self.assertEqual(self._call("GET", "/api/chat/prefs?session_id=abc")[0], 400)

    def test_view_only_guest_can_read_own_chat_but_not_write(self):
        chat_prefs.set(self.sid, TEXT)
        self._guest({"session_id": self.sid, "acl": "view"})
        code, got = self._call("GET", f"/api/chat/prefs?session_id={self.sid}")
        self.assertEqual((code, got["instructions"]), (200, TEXT))
        code, got = self._call("POST", "/api/chat/prefs", {"session_id": self.sid, "instructions": "changed"})
        self.assertEqual(code, 403)
        self.assertIn("view-only", got["error"])
        self.assertEqual(chat_prefs.get(self.sid), TEXT)

    def test_scoped_guest_cannot_touch_another_chat(self):
        chat_prefs.set(self.other, "secret")
        self._guest({"session_id": self.sid, "acl": "post"})
        code, got = self._call("GET", f"/api/chat/prefs?session_id={self.other}")
        self.assertEqual(code, 403)
        self.assertIn("own chat", got["error"])
        code, got = self._call("POST", "/api/chat/prefs", {"session_id": self.other, "instructions": "x"})
        self.assertEqual(code, 403)
        self.assertIn("own chat", got["error"])
        self.assertEqual(chat_prefs.get(self.other), "secret")
        code, _ = self._call("POST", "/api/chat/prefs", {"session_id": self.sid, "instructions": "mine"})
        self.assertEqual(code, 200)
        self.assertEqual(chat_prefs.get(self.sid), "mine")


if __name__ == "__main__":
    unittest.main()

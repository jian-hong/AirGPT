"""GET /api/skills and the snippet-card `Use` contract.

Two things must stay true or the cards go back to being decoration:
  * the registry serves real packs from data/skills with usable titles, and
  * arming a skill changes what the *model* sees without polluting the transcript
    the user reads back later.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402
import db  # noqa: E402
import invoke_registry  # noqa: E402


def _serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class SkillsEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.base = _serve()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=15) as r:
            return json.loads(r.read().decode())

    def test_returns_real_packs(self):
        data = self._get("/api/skills")
        self.assertTrue(data.get("ok"))
        self.assertGreater(len(data["skills"]), 0, "data/skills has packs but none served")

    def test_every_entry_has_the_card_contract(self):
        for s in self._get("/api/skills")["skills"]:
            for key in ("id", "title", "summary", "tools"):
                self.assertIn(key, s)
            self.assertTrue(s["title"].strip(), s)
            self.assertIsInstance(s["tools"], list)

    def test_content_free_packs_are_not_served(self):
        """A 10-byte scratch file must not render as an empty card."""
        ids = [s["id"] for s in self._get("/api/skills")["skills"]]
        self.assertNotIn("hi", ids)

    def test_bom_packs_keep_their_heading_as_the_title(self):
        """Several packs are UTF-8 with BOM; the BOM used to break the '# ' test.

        Symptom was `ml` titled "Ml" with its own heading served as the description.
        """
        by_id = {s["id"]: s for s in self._get("/api/skills")["skills"]}
        if "ml" in by_id:
            self.assertNotEqual(by_id["ml"]["title"], "Ml")
            self.assertNotIn("﻿", by_id["ml"]["title"] + by_id["ml"]["summary"])
        for s in by_id.values():
            self.assertFalse(s["summary"].lstrip().startswith("#"), f"{s['id']} serves a heading")

    def test_no_pack_text_leaks_a_bom(self):
        for sid in ("engineering", "ml", "finance", "general"):
            self.assertNotIn("﻿", invoke_registry.load_skill(sid), sid)


class SkillArmingTest(unittest.TestCase):
    """`Use` arms the next send — it must not send, and must not rewrite history."""

    USER_TEXT = "draw me the pipeline"

    def setUp(self):
        self.seen = {}

        def fake_stream(question, mode, history, abort, **kw):
            self.seen["question"] = question
            yield {"type": "done", "analysis": "ok", "model": "test"}

        self._orig = (
            clipdrop._chat_stream_events,
            clipdrop._check_ai_rate,
            clipdrop._is_online,
            clipdrop._ai_allowed,
        )
        clipdrop._chat_stream_events = fake_stream
        clipdrop._check_ai_rate = lambda: None
        clipdrop._is_online = lambda: True
        clipdrop._ai_allowed = lambda: True
        self.srv, self.base = _serve()
        self.sid = int(db.create_session("Skill test", capture_type="ai")["id"])

    def tearDown(self):
        (
            clipdrop._chat_stream_events,
            clipdrop._check_ai_rate,
            clipdrop._is_online,
            clipdrop._ai_allowed,
        ) = self._orig
        db.delete_session(self.sid)
        self.srv.shutdown()
        self.srv.server_close()

    def _send(self, **extra):
        payload = {"session_id": self.sid, "text": self.USER_TEXT, "mode": "general", **extra}
        req = urllib.request.Request(
            self.base + "/api/chat/stream",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
        return self.seen.get("question", "")

    def test_armed_skill_reaches_the_model(self):
        q = self._send(skill="visual-diagrams")
        self.assertIn("[Skill: visual-diagrams]", q)
        self.assertTrue(q.strip().endswith(self.USER_TEXT), "user text must come last")

    def test_transcript_stores_the_raw_user_text(self):
        self._send(skill="visual-diagrams")
        rows = [m for m in db.get_messages(session_id=self.sid) if m.get("source") == "ai-chat"]
        self.assertEqual(rows[-1]["text"], self.USER_TEXT)

    def test_no_skill_means_no_preamble(self):
        self.assertEqual(self._send(), self.USER_TEXT)

    def test_unknown_skill_falls_through_quietly(self):
        self.assertEqual(self._send(skill="does-not-exist"), self.USER_TEXT)

    def test_path_traversal_id_is_refused(self):
        for evil in ("../../etc/passwd", "..\\..\\secrets", "a/b"):
            self.assertEqual(self._send(skill=evil), self.USER_TEXT, evil)


if __name__ == "__main__":
    unittest.main()

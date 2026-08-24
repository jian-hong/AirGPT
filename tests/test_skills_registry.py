"""GET /api/skills and the snippet-card `Use` contract.

Two things must stay true or the cards go back to being decoration:
  * the registry serves real packs with usable titles (committed fixtures when
    gitignored data/skills is empty), and
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
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402
import db  # noqa: E402
import invoke_registry  # noqa: E402

_FIXTURE_SKILLS = Path(__file__).resolve().parent / "fixtures" / "skills"


def _serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class SkillsEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._skills_dir = mock.patch.object(invoke_registry, "SKILLS_DIR", _FIXTURE_SKILLS)
        cls._skills_dir.start()
        cls.srv, cls.base = _serve()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls._skills_dir.stop()

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=15) as r:
            return json.loads(r.read().decode())

    def test_returns_real_packs(self):
        data = self._get("/api/skills")
        self.assertTrue(data.get("ok"))
        self.assertGreater(len(data["skills"]), 0, "fixture packs exist but none served")

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
        self._skills_dir = mock.patch.object(invoke_registry, "SKILLS_DIR", _FIXTURE_SKILLS)
        self._skills_dir.start()
        self.addCleanup(self._skills_dir.stop)
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


class MultipleArmedSkillsTest(SkillArmingTest):
    """More than one pack may ride a single send.

    The composer used to hold exactly one armed skill because the wire field was a
    single string, so arming a second silently replaced the first.
    """

    PACKS = ("visual-diagrams", "web-research")

    def test_every_armed_pack_reaches_the_model(self):
        q = self._send(skills=list(self.PACKS))
        for sid in self.PACKS:
            self.assertIn(f"[Skill: {sid}]", q, sid)
        self.assertTrue(q.strip().endswith(self.USER_TEXT), "user text must come last")

    def test_packs_keep_the_order_they_were_armed_in(self):
        q = self._send(skills=list(reversed(self.PACKS)))
        seen = [q.index(f"[Skill: {sid}]") for sid in reversed(self.PACKS)]
        self.assertEqual(seen, sorted(seen))

    def test_legacy_single_field_merges_without_duplicating(self):
        q = self._send(skill=self.PACKS[0], skills=[self.PACKS[0], self.PACKS[1]])
        self.assertEqual(q.count(f"[Skill: {self.PACKS[0]}]"), 1)
        self.assertIn(f"[Skill: {self.PACKS[1]}]", q)

    def test_list_is_capped_so_preamble_cannot_run_away(self):
        every = [s["id"] for s in invoke_registry.list_skills()]
        self.assertGreater(len(every), clipdrop.MAX_ARMED_SKILLS, "need more packs than the cap to test it")
        q = self._send(skills=every)
        self.assertLessEqual(q.count("[Skill: "), clipdrop.MAX_ARMED_SKILLS)

    def test_one_unknown_id_does_not_drop_the_valid_ones(self):
        q = self._send(skills=["does-not-exist", self.PACKS[0]])
        self.assertIn(f"[Skill: {self.PACKS[0]}]", q)
        self.assertNotIn("does-not-exist", q)

    def test_empty_list_means_no_preamble(self):
        self.assertEqual(self._send(skills=[]), self.USER_TEXT)


if __name__ == "__main__":
    unittest.main()

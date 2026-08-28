"""SHELL-02 HTTP: the customer seat gets a Cortex routine or an honest refusal.

Cortex :8010 has no /api/routines this session. Issue #60 puts an AirGPT-owned cron
out of scope, so POST /api/cortex/routines must refuse by name instead of quietly
creating a host-clock chip that looks scheduled. This hits clipdrop.Handler, not
only cortex_client.py.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402
import cortex_client  # noqa: E402
import host_routines  # noqa: E402


def _serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class Shell02RoutinesHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        store = Path(cls._td.name) / "host_routines.json"
        cls._patches = [
            mock.patch.object(host_routines, "STORE", store),
            mock.patch.object(host_routines, "DATA_DIR", Path(cls._td.name)),
            mock.patch.object(cortex_client, "ensure_engine", lambda **_k: {"ok": False}),
            # Pinned so the suite does not depend on what is really on :8010.
            mock.patch.object(
                cortex_client,
                "health",
                lambda: {
                    "ok": True,
                    "status": "live",
                    "raw": {"status": "ok", "pack": "dms", "surface": "constructor"},
                    "url": "http://127.0.0.1:8010",
                },
            ),
            mock.patch.object(
                cortex_client,
                "_json_call",
                lambda *_a, **_k: {"ok": False, "error": "no /api/routines", "_http": 404},
            ),
            mock.patch.object(
                cortex_client,
                "_get",
                lambda *_a, **_k: {"ok": False, "error": "no /api/routines", "_http": 404},
            ),
        ]
        for p in cls._patches:
            p.start()
        cls.srv, cls.base = _serve()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        for p in cls._patches:
            p.stop()
        cls._td.cleanup()

    def _json(self, method, path, body=None):
        """Return (status, payload). A refusal is a 4xx/5xx with a body, not a raise."""
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def test_create_refuses_and_writes_nothing_when_cortex_cannot_schedule(self):
        code, created = self._json(
            "POST", "/api/cortex/routines", {"goal": "Morning news brief daily"}
        )
        self.assertGreaterEqual(code, 400, created)
        self.assertFalse(created.get("ok"), created)
        self.assertEqual(created.get("reason"), "wrong_surface", created)
        self.assertIn("/api/routines", str(created.get("error") or ""), created)
        self.assertNotEqual(created.get("scheduler"), "airgpt_host", created)
        self.assertIsNone(created.get("routine_id"), created)
        # No chip on disk: a refusal that still wrote a host row is the old defect.
        self.assertEqual(host_routines.list_routines()["routines"], [], "refusal must not create")

    def test_draft_refuses_rather_than_previewing_a_blank_card(self):
        code, draft = self._json(
            "POST", "/api/cortex/routines/draft", {"goal": "Morning news brief daily"}
        )
        self.assertGreaterEqual(code, 400, draft)
        self.assertFalse(draft.get("ok"), draft)
        self.assertNotIn("name", draft, draft)
        self.assertNotIn("schedule_text", draft, draft)

    def test_list_reports_offline_and_marks_legacy_host_rows(self):
        legacy = host_routines.create("legacy host row", agent_id=0)
        self.addCleanup(host_routines.delete, legacy["routine_id"])
        code, listed = self._json("GET", "/api/cortex/routines")
        self.assertEqual(code, 503, listed)
        self.assertFalse(listed.get("ok"), listed)
        self.assertEqual(listed.get("reason"), "wrong_surface", listed)
        self.assertEqual(listed.get("routines"), [], listed)
        rows = listed.get("host_routines") or []
        self.assertEqual([r.get("id") for r in rows], [legacy["routine_id"]], listed)
        self.assertEqual(rows[0].get("scheduler"), "airgpt_host", listed)

    def test_legacy_host_row_run_reports_what_actually_happened(self):
        legacy = host_routines.create("legacy host row", agent_id=0)
        self.addCleanup(host_routines.delete, legacy["routine_id"])
        rid = legacy["routine_id"]
        first = float(legacy["next_run_at"])
        code, ran = self._json("POST", f"/api/cortex/routines/{rid}/run", {})
        self.assertFalse(ran.get("ok"), ran)
        self.assertIn("no agent", str(ran.get("error") or "").lower(), ran)
        row = ran.get("routine") or {}
        self.assertGreater(float(row.get("last_run_at") or 0), 0, ran)
        self.assertNotEqual(float(row.get("next_run_at") or 0), first, ran)
        self.assertEqual(row.get("scheduler"), "airgpt_host", ran)

    def test_index_is_not_a_use_shop(self):
        req = urllib.request.Request(self.base + "/")
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="replace")
        self.assertIn("Force a skill", html)
        self.assertIn("function peelSkillSlash", html)
        self.assertIn("Armed':'Force'", html)
        self.assertNotIn("Armed':'Use'", html)
        # SHELL-01: consecutive tool SSE events collapse into one summary row.
        # The old `tools?:` pin was dropped: #59 replaced the regex round-trip with a
        # per-kind Map, so the token now survives only inside the comment that records
        # its removal - an assertion on prose, which is not a gate.
        # tests/test_shell_d09_readout.py holds the behavioural checks.
        self.assertIn("⚙", html)
        self.assertIn("tools:", html)


class Shell01LineDeltaTests(unittest.TestCase):
    def test_write_returns_added_removed(self):
        from OpenIDE import workspace_api

        d = workspace_api.line_delta("a\nb\n", "a\nb\nc\n")
        self.assertEqual(d["added"], 1)
        self.assertEqual(d["removed"], 0)
        d2 = workspace_api.line_delta("a\nb\nc\n", "a\n")
        self.assertEqual(d2["removed"], 2)


if __name__ == "__main__":
    unittest.main()

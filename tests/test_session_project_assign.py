"""A chat can be assigned to a project, and projects can be read back.

POST /api/projects wrote rows nothing could list, and PATCH /api/sessions/<id>
dropped project_id on the floor - so every session kept the default project of
its category. These gates go over HTTP, the layer the client actually calls
(R-0001), and check the DB row after, not just the 200.
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402
import db  # noqa: E402


class SessionProjectAssignTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self._orig_db = db.DB_PATH
        db.DB_PATH = Path(self._tmp.name) / "clipdrop.db"
        db.init_db()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        db.DB_PATH = self._orig_db

    def _call(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def _session_project_id(self, sid):
        """Straight from the DB - no handler in the way."""
        with db._connect() as conn:
            row = conn.execute(
                "SELECT project_id FROM chat_sessions WHERE id=?", (sid,)
            ).fetchone()
        return None if row is None else row["project_id"]

    def _new_session(self, title="Q3 numbers", mode="general"):
        # A titled session survives prune_empty_orphan_sessions, which eats
        # empty rows still called "New chat".
        code, out = self._call("POST", "/api/sessions", {"title": title, "mode": mode})
        self.assertEqual(code, 200, out)
        return out["session"]["id"]

    # -- read-back ---------------------------------------------------------

    def test_posted_project_is_listed_by_get_projects(self):
        code, made = self._call(
            "POST", "/api/projects", {"name": "Ledger 2026", "category": "finance"}
        )
        self.assertEqual(code, 200, made)
        pid = made["project"]["id"]

        code, listed = self._call("GET", "/api/projects")
        self.assertEqual(code, 200, listed)
        rows = listed["projects"]
        by_id = {int(p["id"]): p for p in rows}
        self.assertIn(pid, by_id, "POST wrote a row GET cannot see")
        self.assertEqual(by_id[pid]["name"], "Ledger 2026")
        self.assertEqual(by_id[pid]["category"], "finance")
        # The four fixed-category defaults are rows too.
        self.assertGreaterEqual(len(rows), 5, rows)

    # -- assignment --------------------------------------------------------

    def test_patch_assigns_the_session_to_the_project(self):
        sid = self._new_session()
        _, made = self._call(
            "POST", "/api/projects", {"name": "Ledger 2026", "category": "finance"}
        )
        pid = made["project"]["id"]
        self.assertNotEqual(self._session_project_id(sid), pid)

        code, out = self._call("PATCH", f"/api/sessions/{sid}", {"project_id": pid})
        self.assertEqual(code, 200, out)
        self.assertEqual(self._session_project_id(sid), pid)

        code, listed = self._call("GET", "/api/projects")
        self.assertEqual(code, 200, listed)
        row = next(p for p in listed["projects"] if int(p["id"]) == pid)
        self.assertEqual(row["session_count"], 1)

    def test_patch_project_id_zero_clears_the_assignment(self):
        sid = self._new_session()
        _, made = self._call(
            "POST", "/api/projects", {"name": "Ledger 2026", "category": "finance"}
        )
        pid = made["project"]["id"]
        self._call("PATCH", f"/api/sessions/{sid}", {"project_id": pid})
        # Pin the assignment first, or a handler that ignores project_id
        # entirely would pass this by never having set anything.
        self.assertEqual(self._session_project_id(sid), pid)
        code, out = self._call("PATCH", f"/api/sessions/{sid}", {"project_id": 0})
        self.assertEqual(code, 200, out)
        self.assertEqual(self._session_project_id(sid), 0)

    def test_patch_still_updates_title_without_touching_project(self):
        sid = self._new_session()
        _, made = self._call(
            "POST", "/api/projects", {"name": "Ledger 2026", "category": "finance"}
        )
        pid = made["project"]["id"]
        self._call("PATCH", f"/api/sessions/{sid}", {"project_id": pid})
        code, out = self._call("PATCH", f"/api/sessions/{sid}", {"title": "Renamed"})
        self.assertEqual(code, 200, out)
        self.assertEqual(self._session_project_id(sid), pid, "title edit dropped the project")

    # -- the failure this prevents ----------------------------------------

    def test_unknown_project_id_is_refused_and_leaves_the_session_alone(self):
        """An id nothing owns would park the chat where no listing can show it."""
        sid = self._new_session()
        before = self._session_project_id(sid)
        ghost = 999_999
        self.assertIsNone(db.get_project(ghost))

        code, out = self._call("PATCH", f"/api/sessions/{sid}", {"project_id": ghost})
        self.assertEqual(code, 404, out)
        self.assertIn("project", str(out.get("error", "")).lower())
        self.assertEqual(self._session_project_id(sid), before)

    def test_non_numeric_project_id_is_refused(self):
        sid = self._new_session()
        before = self._session_project_id(sid)
        for bad in ("hoy", None, {"id": 1}):
            code, out = self._call("PATCH", f"/api/sessions/{sid}", {"project_id": bad})
            self.assertEqual(code, 400, (bad, out))
            self.assertEqual(self._session_project_id(sid), before, bad)

    def test_refused_patch_does_not_apply_the_rest_of_the_body(self):
        """A rejected project_id must not half-apply a title change with it."""
        sid = self._new_session(title="Keep me")
        code, out = self._call(
            "PATCH", f"/api/sessions/{sid}", {"title": "Renamed", "project_id": 999_999}
        )
        self.assertEqual(code, 404, out)
        with db._connect() as conn:
            title = conn.execute(
                "SELECT title FROM chat_sessions WHERE id=?", (sid,)
            ).fetchone()["title"]
        self.assertEqual(title, "Keep me")

    # -- grouping guard ----------------------------------------------------

    def test_assigning_a_cross_category_project_does_not_move_the_chat(self):
        """list_vault_tree groups on the session's own category first.

        A general chat filed under a finance project stays under General - it
        must not vanish from its category, nor show up in two.
        """
        sid = self._new_session(title="General thoughts", mode="general")
        _, made = self._call(
            "POST", "/api/projects", {"name": "Ledger 2026", "category": "finance"}
        )
        pid = made["project"]["id"]

        code, tree = self._call("GET", "/api/vault")
        self.assertEqual(code, 200, tree)
        before = {c["key"]: [s["id"] for s in c["sessions"]] for c in tree["categories"]}
        self.assertIn(sid, before["general"])

        code, out = self._call("PATCH", f"/api/sessions/{sid}", {"project_id": pid})
        self.assertEqual(code, 200, out)

        code, tree = self._call("GET", "/api/vault")
        self.assertEqual(code, 200, tree)
        after = {c["key"]: [s["id"] for s in c["sessions"]] for c in tree["categories"]}
        self.assertEqual(after, before, "project assignment reshuffled the vault tree")
        appears_in = [k for k, ids in after.items() if sid in ids]
        self.assertEqual(appears_in, ["general"])
        self.assertEqual(self._session_project_id(sid), pid)


if __name__ == "__main__":
    unittest.main()

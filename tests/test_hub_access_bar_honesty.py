"""HOST-DEMO-04 / #28: the Hub access bar must not claim a grant the gate ignores.

set_peer_acl persists a chosen level. Request gates are IP-only
(_is_host_only_path + _is_host_request) and never read access_level.
read_write and read_only get the same 403 on /api/rag. A persist-only
round-trip hid that: the bar looked like a control.

This test sets a level, then hits a host-only path from that peer, and
checks the operator HTML does not contradict the 403.
"""
from __future__ import annotations

import inspect
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import auth  # noqa: E402
import clipdrop  # noqa: E402
import db  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TUNNEL_HOST = "abc.trycloudflare.com"
PEER_IP = "203.0.113.9"
HONESTY = "not yet enforced"
OLD_LIES = (
    "can watch, cannot type",
    "can type",
    "spends your tokens",
    "brings their own key",
    "paused — no AI, no writes",
    "what they can do, and how they use AI",
)


class HubAccessBarHonestyStaticTest(unittest.TestCase):
    """No HTTP server: Windows SQLite locks a temp DB on teardown."""

    def test_host_only_gate_does_not_read_access_level(self):
        """F22a / DR-0003 is still proposed. Do not make the level load-bearing."""
        self.assertNotIn("access_level", inspect.getsource(clipdrop._is_host_only_path))
        self.assertNotIn("access_level", inspect.getsource(clipdrop._is_host_request))
        for meth in (clipdrop.Handler.do_GET, clipdrop.Handler.do_POST):
            src = inspect.getsource(meth)
            gate_lines = [
                line
                for line in src.splitlines()
                if "_is_host_only_path(path)" in line and "_is_host_request" in line
            ]
            self.assertTrue(gate_lines, f"host-only gate missing on {meth.__name__}")
            for line in gate_lines:
                self.assertNotIn("access_level", line)

    def test_host_only_prefixes_stay_closed(self):
        self.assertIn("/api/rag", clipdrop._HOST_ONLY_PREFIXES)
        self.assertEqual(len(clipdrop._HOST_ONLY_PREFIXES), 17)

    def test_min_tests_stays_380(self):
        wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
        self.assertIn('MIN_TESTS: "380"', wf)


class HubAccessBarHonestyHttpTest(unittest.TestCase):
    def setUp(self):
        # ignore_cleanup_errors: Windows keeps sqlite's clipdrop.db open after
        # the handler returns (WinError 32). Auth files here are JSON only.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self._orig_ws = auth.WORKSPACE_FILE
        self._orig_toks = auth.TOKENS_FILE
        self._orig_tokens = dict(auth._tokens)
        auth.WORKSPACE_FILE = root / "workspace.json"
        auth.TOKENS_FILE = root / "auth_tokens.json"
        auth._tokens.clear()
        clipdrop._establish.clear()
        clipdrop._establish_token.clear()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        auth.WORKSPACE_FILE = self._orig_ws
        auth.TOKENS_FILE = self._orig_toks
        auth._tokens.clear()
        auth._tokens.update(self._orig_tokens)
        clipdrop._establish.clear()
        clipdrop._establish_token.clear()
        self._tmp.cleanup()

    def _peer_headers(self, extra=None):
        h = {
            "Host": TUNNEL_HOST,
            "CF-Connecting-IP": PEER_IP,
            "Content-Type": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def _call(self, method, path, headers=None, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path,
            data=data,
            headers=headers or {},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
                payload = json.loads(raw.decode() or "{}") if raw else {}
                return r.status, dict(r.headers), payload
        except urllib.error.HTTPError as e:
            raw = e.read()
            payload = json.loads(raw.decode() or "{}") if raw else {}
            return e.code, dict(e.headers), payload

    def _set_acl(self, level):
        code, _, body = self._call(
            "POST",
            f"/api/hub/peers/{PEER_IP}/acl",
            {"Content-Type": "application/json"},
            {"access_level": level},
        )
        self.assertEqual(code, 200, body)
        self.assertTrue(body.get("ok"), body)
        self.assertEqual((body.get("peer") or {}).get("access_level"), level)
        stored = db.get_hub_peer(PEER_IP) or {}
        self.assertEqual(stored.get("access_level"), level)
        return body

    def test_set_level_then_peer_host_only_path_is_403(self):
        """Persist is not a grant. /api/rag from the peer must stay host-only."""
        for level in ("read_write", "read_only"):
            self._set_acl(level)
            code, _, body = self._call("GET", "/api/rag", self._peer_headers())
            self.assertEqual(code, 403, (level, body))
            self.assertEqual(body.get("error"), "host only", (level, body))
            code, _, body = self._call("GET", "/api/rag/spaces", self._peer_headers())
            self.assertEqual(code, 403, (level, body))
            self.assertEqual(body.get("error"), "host only", (level, body))

    def test_operator_html_does_not_contradict_the_403(self):
        """R-0001: the Hub page the host receives must say the bar is decorative."""
        self._set_acl("read_write")
        code, _, rag = self._call("GET", "/api/rag", self._peer_headers())
        self.assertEqual(code, 403, rag)
        self.assertEqual(rag.get("error"), "host only", rag)

        with urllib.request.urlopen(self.base + "/", timeout=15) as r:
            self.assertEqual(r.status, 200)
            html = r.read().decode("utf-8", errors="replace")
        self.assertIn(HONESTY, html)
        self.assertIn("Levels are saved, not yet enforced", html)
        self.assertIn("saved, not yet enforced", html)
        self.assertIn("Share level (not enforced)", html)
        for lie in OLD_LIES:
            self.assertNotIn(lie, html, f"operator HTML still claims {lie!r}")

        with urllib.request.urlopen(self.base + "/ui/multiplayer_demo.js", timeout=15) as r:
            self.assertEqual(r.status, 200)
            js = r.read().decode("utf-8", errors="replace")
        self.assertIn(HONESTY, js)
        self.assertNotIn("what they can do, and how they use AI", js)

    def test_host_still_reaches_rag(self):
        """Honesty must not lock the host out of its own host-only path."""
        code, _, body = self._call("GET", "/api/rag/spaces")
        self.assertNotEqual(code, 403, body)
        self.assertNotEqual(body.get("error"), "host only", body)


if __name__ == "__main__":
    unittest.main()

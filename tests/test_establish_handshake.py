"""HOST-DEMO-02: non-local clients must establish before AI and chat POSTs.

Assert the HTTP the phone receives: status, headers, and body. Local host
keeps today's path. A leftover token without a bound nonce is refused.
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import auth  # noqa: E402
import clipdrop  # noqa: E402

TUNNEL_HOST = "abc.trycloudflare.com"
PHONE_IP = "203.0.113.9"
SEC_HDR = clipdrop.SECURITY_VERSION_HEADER
NONCE_HDR = clipdrop.SESSION_NONCE_HEADER


class EstablishHandshakeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
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

    def _phone(self, extra=None):
        h = {
            "Host": TUNNEL_HOST,
            "CF-Connecting-IP": PHONE_IP,
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

    def _hdr(self, headers, name):
        for k, v in headers.items():
            if k.lower() == name.lower():
                return v
        return None

    def test_phone_ai_config_refused_before_establish(self):
        code, headers, body = self._call("GET", "/api/ai/config", self._phone())
        self.assertEqual(code, 403, body)
        self.assertTrue(body.get("establish"), body)
        self.assertEqual(body.get("code"), "establish_required")
        self.assertIn("establish", (body.get("error") or "").lower())
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

    def test_phone_chat_stream_refused_before_establish(self):
        code, headers, body = self._call(
            "POST", "/api/chat/stream", self._phone(), {"text": "hi"},
        )
        self.assertEqual(code, 403, body)
        self.assertEqual(body.get("code"), "establish_required")
        self.assertTrue(body.get("establish"), body)
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

    def test_phone_messages_and_project_suggest_refused_before_establish(self):
        for path in ("/api/messages", "/api/chat/project-suggest"):
            code, headers, body = self._call("POST", path, self._phone(), {})
            self.assertEqual(code, 403, (path, body))
            self.assertEqual(body.get("code"), "establish_required", path)
            self.assertTrue(body.get("establish"), (path, body))
            self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

    def test_phone_ai_post_siblings_refused_before_establish(self):
        for path in ("/api/ai/config", "/api/ai/mode"):
            code, headers, body = self._call("POST", path, self._phone(), {})
            self.assertEqual(code, 403, (path, body))
            self.assertEqual(body.get("code"), "establish_required", path)
            self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

    def test_establish_returns_nonce_and_security_version(self):
        code, headers, body = self._call("POST", "/api/establish", self._phone())
        self.assertEqual(code, 200, body)
        self.assertTrue(body.get("ok"), body)
        self.assertTrue(body.get("session_nonce"), body)
        self.assertEqual(body.get("security_version"), clipdrop.AIRGPT_SECURITY_VERSION)
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)
        self.assertGreaterEqual(len(body["session_nonce"]), 16)

    def test_after_establish_ai_config_is_accepted(self):
        _, _, est = self._call("POST", "/api/establish", self._phone())
        nonce = est["session_nonce"]
        code, headers, body = self._call(
            "GET", "/api/ai/config", self._phone({NONCE_HDR: nonce}),
        )
        self.assertEqual(code, 200, body)
        self.assertIn("auto", body)
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

    def test_after_establish_chat_stream_fails_for_a_later_reason(self):
        """Handshake passed: refusal must not be establish_*."""
        _, _, est = self._call("POST", "/api/establish", self._phone())
        nonce = est["session_nonce"]
        code, headers, body = self._call(
            "POST", "/api/chat/stream", self._phone({NONCE_HDR: nonce}), {},
        )
        self.assertNotEqual(body.get("code"), "establish_required", body)
        self.assertFalse(body.get("establish"), body)
        self.assertIn(code, (400, 429, 503), body)
        self.assertTrue(body.get("error"), body)
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

    def test_after_establish_ai_mode_is_accepted(self):
        _, _, est = self._call("POST", "/api/establish", self._phone())
        nonce = est["session_nonce"]
        code, headers, body = self._call(
            "POST", "/api/ai/mode", self._phone({NONCE_HDR: nonce}), {"enabled": True},
        )
        self.assertEqual(code, 200, body)
        self.assertIn("enabled", body)
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

    def test_leftover_token_without_nonce_is_refused(self):
        auth.init_workspace("host@example.com", "secret123")
        guest = auth.join_workspace("secret123")
        token = guest["token"]
        code, headers, body = self._call(
            "POST",
            "/api/chat/stream",
            self._phone({"X-AirGPT-Token": token}),
            {"text": "hi"},
        )
        self.assertEqual(code, 403, body)
        self.assertEqual(body.get("code"), "establish_unbound")
        self.assertTrue(body.get("establish"), body)
        self.assertIn("token", (body.get("error") or "").lower())
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

    def test_leftover_token_then_establish_then_accepted(self):
        auth.init_workspace("host@example.com", "secret123")
        guest = auth.join_workspace("secret123")
        token = guest["token"]
        phone = self._phone({"X-AirGPT-Token": token})
        code, _, body = self._call("GET", "/api/ai/config", phone)
        self.assertEqual(code, 403, body)
        self.assertEqual(body.get("code"), "establish_unbound")

        code, headers, est = self._call("POST", "/api/establish", phone)
        self.assertEqual(code, 200, est)
        nonce = est["session_nonce"]
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

        code, headers, body = self._call(
            "GET", "/api/ai/config", self._phone({
                "X-AirGPT-Token": token,
                NONCE_HDR: nonce,
            }),
        )
        self.assertEqual(code, 200, body)
        self.assertIn("auto", body)

    def test_wrong_nonce_is_mismatch(self):
        auth.init_workspace("host@example.com", "secret123")
        token = auth.join_workspace("secret123")["token"]
        phone = self._phone({"X-AirGPT-Token": token})
        _, _, est = self._call("POST", "/api/establish", phone)
        code, headers, body = self._call(
            "POST",
            "/api/chat/stream",
            self._phone({"X-AirGPT-Token": token, NONCE_HDR: "not-the-nonce"}),
            {"text": "hi"},
        )
        self.assertEqual(code, 403, body)
        self.assertEqual(body.get("code"), "establish_mismatch")
        self.assertTrue(body.get("establish"), body)
        self.assertIn("nonce", (body.get("error") or "").lower())
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)
        self.assertTrue(est.get("session_nonce"))

    def test_nonce_cannot_be_stolen_by_another_token(self):
        auth.init_workspace("host@example.com", "secret123")
        a = auth.join_workspace("secret123")["token"]
        b = auth.join_workspace("secret123")["token"]
        _, _, est = self._call("POST", "/api/establish", self._phone({"X-AirGPT-Token": a}))
        nonce = est["session_nonce"]
        code, headers, body = self._call(
            "GET",
            "/api/ai/config",
            self._phone({"X-AirGPT-Token": b, NONCE_HDR: nonce}),
        )
        self.assertEqual(code, 403, body)
        self.assertIn(body.get("code"), ("establish_unbound", "establish_mismatch"))
        self.assertTrue(body.get("establish"), body)
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

    def test_local_host_keeps_today_path_without_establish(self):
        code, headers, body = self._call("GET", "/api/ai/config")
        self.assertEqual(code, 200, body)
        self.assertIn("auto", body)
        self.assertNotIn("establish", body)
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

    def test_local_host_chat_stream_is_not_an_establish_refusal(self):
        code, headers, body = self._call(
            "POST", "/api/chat/stream", {"Content-Type": "application/json"}, {},
        )
        self.assertNotEqual(code, 403, body)
        self.assertFalse(body.get("establish"), body)
        self.assertIn(code, (400, 429, 503), body)
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

    def test_probe_stays_open_without_establish(self):
        code, headers, body = self._call("GET", "/api/probe", self._phone())
        self.assertEqual(code, 200, body)
        self.assertFalse(body.get("establish"), body)
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

    def test_get_establish_also_issues_a_nonce(self):
        code, headers, body = self._call("GET", "/api/establish", self._phone())
        self.assertEqual(code, 200, body)
        self.assertTrue(body.get("session_nonce"), body)
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)


if __name__ == "__main__":
    unittest.main()

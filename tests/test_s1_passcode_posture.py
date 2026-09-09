"""EPIC-D10 / S1: no LAN or tunnel chat until the host has set a passcode.

Assert the HTTP the phone receives. Local host keeps today's first-run path.
Probe/health/auth-status stay open so the phone can name the lock.
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


class S1PasscodePostureTest(unittest.TestCase):
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

    def _assert_s1(self, code, headers, body):
        self.assertEqual(code, 403, body)
        self.assertEqual(body.get("code"), "s1_passcode_required", body)
        self.assertTrue(body.get("s1"), body)
        self.assertIn("passcode", (body.get("error") or "").lower())
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

    def test_status_names_s1_closed_when_no_passcode(self):
        st = auth.status()
        self.assertFalse(st["passcode_set"])
        self.assertFalse(st["s1_remote_open"])
        self.assertFalse(clipdrop._s1_remote_open())

    def test_phone_without_passcode_cannot_establish(self):
        code, headers, body = self._call("POST", "/api/establish", self._phone())
        self._assert_s1(code, headers, body)

    def test_phone_without_passcode_cannot_open_chat(self):
        for method, path, payload in (
            ("GET", "/api/ai/config", None),
            ("POST", "/api/chat/stream", {"text": "hi"}),
            ("POST", "/api/messages", {}),
            ("GET", "/", None),
            ("GET", "/index.html", None),
        ):
            code, headers, body = self._call(method, path, self._phone(), payload)
            self._assert_s1(code, headers, body)

    def test_phone_head_app_shell_is_403(self):
        code, _headers, body = self._call("HEAD", "/", self._phone())
        self.assertEqual(code, 403, body)
        if body.get("code"):
            self.assertEqual(body.get("code"), "s1_passcode_required")

    def test_phone_probe_and_auth_status_stay_open(self):
        code, headers, body = self._call("GET", "/api/probe", self._phone())
        self.assertEqual(code, 200, body)
        self.assertNotEqual(body.get("code"), "s1_passcode_required")
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

        code, headers, body = self._call("GET", "/api/health", self._phone())
        self.assertEqual(code, 200, body)
        self.assertTrue(body.get("ok"), body)

        code, headers, body = self._call("GET", "/api/auth/status", self._phone())
        self.assertEqual(code, 200, body)
        self.assertFalse(body.get("s1_remote_open"), body)
        self.assertFalse(body.get("passcode_set"), body)

    def test_local_host_without_passcode_still_reaches_ai_config(self):
        code, headers, body = self._call("GET", "/api/ai/config")
        self.assertEqual(code, 200, body)
        self.assertNotEqual(body.get("code"), "s1_passcode_required")
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

    def test_after_passcode_phone_without_token_is_auth_required_not_s1(self):
        auth.init_workspace("host@example.com", "secret123")
        code, headers, body = self._call("GET", "/api/ai/config", self._phone())
        self.assertEqual(code, 401, body)
        self.assertTrue(body.get("auth"), body)
        self.assertNotEqual(body.get("code"), "s1_passcode_required")
        self.assertFalse(body.get("s1"))
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)
        code, headers, body = self._call("GET", "/api/probe", self._phone())
        self.assertEqual(code, 200, body)

    def test_after_passcode_phone_hits_establish_not_s1(self):
        auth.init_workspace("host@example.com", "secret123")
        self.assertTrue(auth.status()["s1_remote_open"])
        guest = auth.join_workspace("secret123")
        phone = self._phone({"X-AirGPT-Token": guest["token"]})
        code, headers, body = self._call("GET", "/api/ai/config", phone)
        self.assertEqual(code, 403, body)
        self.assertIn(body.get("code"), ("establish_required", "establish_unbound"), body)
        self.assertTrue(body.get("establish"), body)
        self.assertFalse(body.get("s1"), body)
        self.assertEqual(self._hdr(headers, SEC_HDR), clipdrop.AIRGPT_SECURITY_VERSION)

        code, headers, est = self._call("POST", "/api/establish", phone)
        self.assertEqual(code, 200, est)
        nonce = est["session_nonce"]
        code, headers, body = self._call(
            "GET", "/api/ai/config",
            self._phone({
                "X-AirGPT-Token": guest["token"],
                clipdrop.SESSION_NONCE_HEADER: nonce,
            }),
        )
        self.assertEqual(code, 200, body)
        self.assertIn("auto", body)

    def test_phone_without_passcode_cannot_touch_fs_or_openide(self):
        for method, path, payload in (
            ("POST", "/api/fs/write", {"path": "x.py", "content": "print(1)"}),
            ("GET", "/OpenIDE/ui/openide.js", None),
            ("GET", "/api/git/status", None),
            ("POST", "/api/agents/1/run", {}),
        ):
            code, headers, body = self._call(method, path, self._phone(), payload)
            self._assert_s1(code, headers, body)

    def test_phone_without_passcode_cannot_delete(self):
        code, headers, body = self._call("DELETE", "/api/messages/1", self._phone())
        self._assert_s1(code, headers, body)

    def test_tunnel_stays_locked_until_passcode(self):
        self.assertFalse(clipdrop._tunnel_allowed())
        auth.init_workspace("host@example.com", "secret123")
        # License may still refuse tunnel; S1 itself must no longer be the block.
        self.assertTrue(clipdrop._s1_remote_open())


if __name__ == "__main__":
    unittest.main()

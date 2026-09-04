"""HOST-DEMO-02 / F8a: a phone must establish before it can spend AI or write chat.

The gate is the HTTP the client receives (status + headers + body), not a log line
(R-0001). Loopback stays as today. A leftover token without a session nonce is
refused. Host-only and ordinary auth still sit in front.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
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
LEFTOVER_TOKEN = "leftover-guest-token"


class _Quiet(clipdrop.Handler):
    def log_message(self, *args, **kwargs):
        pass


def _header(headers, name):
    for key, val in headers.items():
        if key.lower() == name.lower():
            return val
    return None


class EstablishHandshakeTest(unittest.TestCase):
    def setUp(self):
        clipdrop.reset_establish_sessions()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Quiet)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        clipdrop.reset_establish_sessions()

    def _call(self, method, path, body=None, headers=None, remote=False):
        h = {"Content-Type": "application/json"}
        if remote:
            h["Host"] = TUNNEL_HOST
        if headers:
            h.update(headers)
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
                hdrs = dict(r.headers)
                try:
                    parsed = json.loads(raw.decode() or "{}")
                except json.JSONDecodeError:
                    parsed = {"_raw": raw.decode(errors="replace")[:240]}
                return r.status, parsed, hdrs
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                parsed = json.loads(raw.decode() or "{}")
            except json.JSONDecodeError:
                parsed = {"_raw": raw.decode(errors="replace")[:240]}
            return e.code, parsed, dict(e.headers)

    def _establish(self, token=""):
        headers = {}
        if token:
            headers["X-AirGPT-Token"] = token
        code, body, hdrs = self._call("POST", "/api/establish", {}, headers=headers, remote=True)
        self.assertEqual(code, 200, body)
        return body, hdrs

    def test_remote_chat_stream_without_establish_is_refused(self):
        code, body, hdrs = self._call(
            "POST", "/api/chat/stream", {"text": "hi"}, remote=True,
        )
        self.assertEqual(code, 403, body)
        self.assertEqual(body.get("code"), "establish_required")
        self.assertEqual(body.get("error"), "establish required")
        self.assertFalse(body.get("ok", True))
        self.assertEqual(_header(hdrs, "X-AirGPT-Security-Version"), clipdrop.SECURITY_VERSION)

    def test_leftover_token_without_nonce_is_refused(self):
        code, body, hdrs = self._call(
            "POST",
            "/api/chat/stream",
            {"text": "hi"},
            headers={"X-AirGPT-Token": LEFTOVER_TOKEN},
            remote=True,
        )
        self.assertEqual(code, 403, body)
        self.assertEqual(body.get("code"), "establish_required")
        self.assertEqual(body.get("error"), "establish required")
        self.assertEqual(_header(hdrs, "X-AirGPT-Security-Version"), clipdrop.SECURITY_VERSION)

    def test_remote_ai_and_chat_posts_are_gated(self):
        paths = (
            ("GET", "/api/ai/config", None),
            ("POST", "/api/ai/config", {"auto": True}),
            ("POST", "/api/ai/mode", {"enabled": True}),
            ("POST", "/api/messages", {"text": "hi"}),
            ("POST", "/api/chat/project-suggest", {"text": "hi", "session_id": 1}),
        )
        for method, path, body in paths:
            code, payload, hdrs = self._call(method, path, body, remote=True)
            self.assertEqual(code, 403, (path, payload))
            self.assertEqual(payload.get("code"), "establish_required", path)
            self.assertEqual(payload.get("error"), "establish required", path)
            self.assertEqual(_header(hdrs, "X-AirGPT-Security-Version"), clipdrop.SECURITY_VERSION, path)

    def test_establish_returns_nonce_and_security_version(self):
        body, hdrs = self._establish()
        self.assertTrue(body.get("ok"))
        self.assertTrue(body.get("nonce"))
        self.assertGreaterEqual(len(body["nonce"]), 16)
        self.assertEqual(body.get("security_version"), clipdrop.SECURITY_VERSION)
        self.assertEqual(_header(hdrs, "X-AirGPT-Security-Version"), clipdrop.SECURITY_VERSION)
        self.assertEqual(_header(hdrs, "X-AirGPT-Session-Nonce"), body["nonce"])

    def test_after_establish_ai_config_is_accepted(self):
        established, _ = self._establish()
        code, body, hdrs = self._call(
            "GET",
            "/api/ai/config",
            headers={clipdrop.SESSION_NONCE_HEADER: established["nonce"]},
            remote=True,
        )
        self.assertEqual(code, 200, body)
        self.assertIn("auto", body)
        self.assertIn("client_ai", body)
        self.assertNotEqual(body.get("code"), "establish_required")
        self.assertNotEqual(body.get("error"), "establish required")

    def test_after_establish_chat_stream_fails_for_a_later_reason(self):
        """Empty text never starts the model; 400/503/429/lockdown are past the handshake."""
        established, _ = self._establish()
        code, body, hdrs = self._call(
            "POST",
            "/api/chat/stream",
            {"text": ""},
            headers={clipdrop.SESSION_NONCE_HEADER: established["nonce"]},
            remote=True,
        )
        self.assertNotEqual(body.get("code"), "establish_required", body)
        self.assertNotEqual(body.get("error"), "establish required", body)
        self.assertNotEqual(body.get("code"), "establish_mismatch", body)
        self.assertNotEqual(code, 401, body)

    def test_after_establish_messages_post_is_past_the_handshake(self):
        established, _ = self._establish()
        code, body, hdrs = self._call(
            "POST",
            "/api/messages",
            {"text": "hello from phone"},
            headers={clipdrop.SESSION_NONCE_HEADER: established["nonce"]},
            remote=True,
        )
        self.assertNotEqual(body.get("code"), "establish_required", body)
        self.assertNotEqual(body.get("error"), "establish required", body)
        self.assertNotEqual(body.get("code"), "establish_mismatch", body)
        self.assertNotEqual(code, 401, body)
        self.assertNotEqual(code, 403, body)

    def test_matching_token_after_establish_is_accepted(self):
        established, _ = self._establish(token=LEFTOVER_TOKEN)
        code, body, hdrs = self._call(
            "GET",
            "/api/ai/config",
            headers={
                clipdrop.SESSION_NONCE_HEADER: established["nonce"],
                "X-AirGPT-Token": LEFTOVER_TOKEN,
            },
            remote=True,
        )
        self.assertEqual(code, 200, body)
        self.assertIn("auto", body)

    def test_nonce_bound_to_the_token_used_at_handshake(self):
        established, _ = self._establish(token=LEFTOVER_TOKEN)
        code, body, hdrs = self._call(
            "POST",
            "/api/messages",
            {"text": "hi"},
            headers={
                clipdrop.SESSION_NONCE_HEADER: established["nonce"],
                "X-AirGPT-Token": "some-other-token",
            },
            remote=True,
        )
        self.assertEqual(code, 403, body)
        self.assertEqual(body.get("code"), "establish_mismatch")
        self.assertEqual(body.get("error"), "establish mismatch")
        self.assertFalse(body.get("ok", True))
        self.assertEqual(_header(hdrs, "X-AirGPT-Security-Version"), clipdrop.SECURITY_VERSION)

    def test_security_version_mismatch_is_refused(self):
        established, _ = self._establish()
        code, body, hdrs = self._call(
            "GET",
            "/api/ai/config",
            headers={
                clipdrop.SESSION_NONCE_HEADER: established["nonce"],
                clipdrop.SECURITY_VERSION_HEADER: "0",
            },
            remote=True,
        )
        self.assertEqual(code, 403, body)
        self.assertEqual(body.get("code"), "establish_mismatch")
        self.assertEqual(body.get("error"), "establish mismatch")
        self.assertEqual(_header(hdrs, "X-AirGPT-Security-Version"), clipdrop.SECURITY_VERSION)

    def test_unknown_nonce_is_refused(self):
        code, body, hdrs = self._call(
            "POST",
            "/api/chat/stream",
            {"text": "hi"},
            headers={clipdrop.SESSION_NONCE_HEADER: "not-a-real-nonce"},
            remote=True,
        )
        self.assertEqual(code, 403, body)
        self.assertEqual(body.get("code"), "establish_required")
        self.assertEqual(body.get("error"), "establish required")

    def test_expired_nonce_is_refused(self):
        nonce = "expired-nonce"
        clipdrop._establish_sessions[nonce] = {
            "token": "",
            "ip": "tunnel-peer",
            "ts": 0,
            "exp": time.time() - 1,
            "ver": clipdrop.SECURITY_VERSION,
        }
        code, body, hdrs = self._call(
            "GET",
            "/api/ai/config",
            headers={clipdrop.SESSION_NONCE_HEADER: nonce},
            remote=True,
        )
        self.assertEqual(code, 403, body)
        self.assertEqual(body.get("code"), "establish_required")
        self.assertEqual(body.get("error"), "establish required")

    def test_loopback_chat_without_establish_is_not_the_handshake_refusal(self):
        code, body, hdrs = self._call("POST", "/api/chat/stream", {"text": "hi"})
        self.assertNotEqual(body.get("code"), "establish_required", body)
        self.assertNotEqual(body.get("error"), "establish required", body)
        self.assertNotEqual(body.get("code"), "establish_mismatch", body)

    def test_host_only_still_wins_after_establish(self):
        established, _ = self._establish()
        code, body, hdrs = self._call(
            "GET",
            "/api/audit",
            headers={clipdrop.SESSION_NONCE_HEADER: established["nonce"]},
            remote=True,
        )
        self.assertEqual(code, 403, body)
        self.assertEqual(body.get("error"), "host only")
        self.assertNotEqual(body.get("code"), "establish_required")

    def test_probe_stays_open_without_establish(self):
        code, body, hdrs = self._call("GET", "/api/probe", remote=True)
        self.assertEqual(code, 200, body)
        self.assertTrue(body.get("ok"))

    def test_get_messages_is_not_an_ai_spend_path(self):
        """Read-back of chat history is not the F8a spend gate; POST is."""
        code, body, hdrs = self._call("GET", "/api/messages?since=0", remote=True)
        self.assertNotEqual(body.get("code"), "establish_required", body)
        self.assertNotEqual(code, 403, body)


class EstablishAuthStillWinsTest(unittest.TestCase):
    def setUp(self):
        clipdrop.reset_establish_sessions()
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = auth.WORKSPACE_FILE
        auth.WORKSPACE_FILE = Path(self._tmp.name) / "workspace.json"
        auth.init_workspace("host@example.com", "secret123")
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Quiet)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        auth.WORKSPACE_FILE = self._orig
        self.srv.shutdown()
        self.srv.server_close()
        self._tmp.cleanup()
        clipdrop.reset_establish_sessions()

    def test_establish_does_not_bypass_passcode_auth(self):
        req = urllib.request.Request(
            self.base + "/api/establish",
            data=b"{}",
            headers={"Content-Type": "application/json", "Host": TUNNEL_HOST},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                code = r.status
                body = json.loads(r.read().decode() or "{}")
                hdrs = dict(r.headers)
        except urllib.error.HTTPError as e:
            code = e.code
            body = json.loads(e.read().decode() or "{}")
            hdrs = dict(e.headers)
        self.assertEqual(code, 401, body)
        self.assertTrue(body.get("auth"))
        self.assertEqual(body.get("error"), "auth required")
        self.assertNotEqual(body.get("code"), "establish_required")
        self.assertIsNone(_header(hdrs, "X-AirGPT-Session-Nonce"))


if __name__ == "__main__":
    unittest.main()

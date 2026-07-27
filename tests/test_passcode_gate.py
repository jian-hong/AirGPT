"""The phone-passcode off-switch is a security control, so test it like one.

The switch exists for someone locked out of their own laptop. That makes exactly one
property non-negotiable: a phone must never be able to disarm the gate that is keeping
it out. Everything else here guards the ways that could quietly stop being true —
notably that `_auth_ok` waves through every `/api/auth/*` path unauthenticated, which is
why this endpoint deliberately lives under `/api/access/`.
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

ENDPOINT = "/api/access/passcode-required"


class PasscodeGateUnitTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = auth.WORKSPACE_FILE
        auth.WORKSPACE_FILE = Path(self._tmp.name) / "workspace.json"

    def tearDown(self):
        auth.WORKSPACE_FILE = self._orig
        self._tmp.cleanup()

    def test_no_passcode_means_nothing_to_require(self):
        self.assertFalse(auth.passcode_required())
        self.assertFalse(auth.status()["passcode_set"])
        self.assertFalse(auth.set_passcode_required(False)["ok"])

    def test_default_is_armed_once_a_passcode_exists(self):
        auth.init_workspace("host@example.com", "secret123")
        self.assertTrue(auth.passcode_required())
        self.assertTrue(auth.status()["needs_auth"])

    def test_disarming_keeps_the_passcode_so_rearming_is_one_tap(self):
        auth.init_workspace("host@example.com", "secret123")
        auth.set_passcode_required(False)
        self.assertFalse(auth.status()["needs_auth"])
        self.assertTrue(auth.status()["passcode_set"], "passcode must survive disarming")
        # And the original passcode still works when re-armed
        auth.set_passcode_required(True)
        self.assertTrue(auth.status()["needs_auth"])
        self.assertTrue(auth.verify_passcode("secret123"))

    def test_disarmed_state_survives_a_reload(self):
        auth.init_workspace("host@example.com", "secret123")
        auth.set_passcode_required(False)
        self.assertFalse(auth.passcode_required(), "flag must be on disk, not in memory")


class PasscodeGateEndpointTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_ws = auth.WORKSPACE_FILE
        auth.WORKSPACE_FILE = Path(self._tmp.name) / "workspace.json"
        auth.init_workspace("host@example.com", "secret123")
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        auth.WORKSPACE_FILE = self._orig_ws
        self.srv.shutdown()
        self.srv.server_close()
        self._tmp.cleanup()

    def _post(self, payload, headers=None):
        req = urllib.request.Request(
            self.base + ENDPOINT,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def test_host_can_disarm_and_rearm(self):
        code, out = self._post({"required": False})
        self.assertEqual(code, 200, out)
        self.assertFalse(out["passcode_required"])
        self.assertFalse(auth.status()["needs_auth"])

        code, out = self._post({"required": True})
        self.assertEqual(code, 200, out)
        self.assertTrue(out["passcode_required"])
        self.assertTrue(auth.status()["needs_auth"])

    def test_a_proxied_request_cannot_disarm_the_gate(self):
        """A phone arriving over the tunnel carries a forwarding header — refuse it.

        This is the whole point of the control: the device the passcode is protecting
        against must not be able to switch the passcode off.
        """
        for header in ("X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP"):
            auth.set_passcode_required(True)
            code, out = self._post({"required": False}, headers={header: "203.0.113.9"})
            self.assertEqual(code, 403, f"{header} was accepted: {out}")
            self.assertTrue(auth.status()["needs_auth"], f"{header} disarmed the gate")

    def test_refusal_does_not_change_state(self):
        auth.set_passcode_required(True)
        self._post({"required": False}, headers={"X-Forwarded-For": "203.0.113.9"})
        self.assertTrue(auth.passcode_required())

    def test_endpoint_is_not_under_the_open_auth_prefix(self):
        """_auth_ok lets every /api/auth/* path through without a token."""
        self.assertFalse(ENDPOINT.startswith("/api/auth/"))
        self.assertTrue(clipdrop.Handler._auth_ok(_Fake(), "/api/auth/anything"))

    def test_bad_json_is_rejected(self):
        req = urllib.request.Request(
            self.base + ENDPOINT,
            data=b"{not json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        self.assertEqual(code, 400)
        self.assertTrue(auth.passcode_required(), "a malformed body must not disarm")


class _Fake:
    """Minimal stand-in for the handler in the prefix check above."""

    client_address = ("127.0.0.1", 0)
    headers: dict = {}
    path = "/api/auth/anything"


if __name__ == "__main__":
    unittest.main()

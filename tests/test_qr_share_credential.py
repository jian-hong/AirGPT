"""HOST-DEMO-05 / #27: a share QR without a passcode is still a credential.

The default no-passcode state used to make issue_qr_token return None and
status().needs_auth false, so clipdrop._join_url handed out the bare LAN/tunnel
URL. Scanning that QR was an unauthenticated open door. The host-only prefixes
are not this ticket; this only asserts the QR itself carries a token.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import auth  # noqa: E402
import clipdrop  # noqa: E402


class _JoinHandler:
    def _request_token(self, allow_query=False):
        return ""


class QrShareCredentialTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_ws = auth.WORKSPACE_FILE
        self._orig_tok = auth.TOKENS_FILE
        auth.WORKSPACE_FILE = Path(self._tmp.name) / "workspace.json"
        auth.TOKENS_FILE = Path(self._tmp.name) / "auth_tokens.json"
        auth._tokens.clear()
        auth._qr_tokens.clear()
        clipdrop._qr_join_cache.clear()

    def tearDown(self):
        auth.WORKSPACE_FILE = self._orig_ws
        auth.TOKENS_FILE = self._orig_tok
        auth._tokens.clear()
        auth._qr_tokens.clear()
        clipdrop._qr_join_cache.clear()
        self._tmp.cleanup()

    def test_no_passcode_still_requires_a_credential_on_the_qr(self):
        self.assertFalse(auth.status()["passcode_set"])
        self.assertTrue(
            auth.status()["needs_auth"],
            "unset passcode must not look like an open LAN to _join_url",
        )

    def test_host_can_mint_a_qr_token_without_a_passcode(self):
        tok = auth.issue_qr_token(host_verified=True)
        self.assertTrue(tok)
        redeemed = auth.redeem_qr_token(tok)
        self.assertTrue(redeemed.get("ok"), redeemed)
        self.assertTrue(redeemed.get("token"))

    def test_remote_cannot_mint_a_qr_token_just_because_no_passcode(self):
        """verify_token is True for any token when pass_hash is missing."""
        self.assertIsNone(auth.issue_qr_token("any-token", host_verified=False))
        self.assertIsNone(auth.issue_qr_token(host_verified=False))

    def test_join_url_carries_qr_token_when_no_passcode(self):
        url, tok = clipdrop.Handler._join_url(
            _JoinHandler(), "http://192.0.2.10:8765", "127.0.0.1"
        )
        self.assertTrue(tok)
        self.assertIn("?qr=", url)
        self.assertIn(tok, url)
        self.assertNotEqual(url, "http://192.0.2.10:8765")

    def test_passcode_disarm_still_opens_the_door_on_purpose(self):
        auth.init_workspace("host@example.com", "secret123")
        auth.set_passcode_required(False)
        self.assertFalse(auth.status()["needs_auth"])
        self.assertTrue(auth.status()["passcode_set"])

    def test_host_only_prefixes_stay_closed(self):
        """This ticket must not open the operator surfaces DR-0003 fences."""
        closed = (
            "/api/fs/",
            "/api/terminal/",
            "/api/workspace",
            "/api/git/",
            "/api/agents/",
            "/api/cortex/",
            "/api/workflows",
            "/api/invoke/",
            "/api/openide/",
            "/api/openvault/",
            "/api/openforge/",
            "/api/rag",
            "/api/github",
            "/api/engine",
            "/api/desktop",
            "/api/admin",
            "/api/audit",
        )
        for prefix in closed:
            self.assertTrue(
                any(
                    prefix == p or prefix.startswith(p)
                    for p in clipdrop._HOST_ONLY_PREFIXES
                ),
                f"{prefix} left the host-only list",
            )


if __name__ == "__main__":
    unittest.main()

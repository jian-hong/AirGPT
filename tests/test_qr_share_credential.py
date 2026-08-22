"""HOST-DEMO-05 / #27: a share QR without a passcode is still a credential.

The default no-passcode state used to make issue_qr_token return None and
status().needs_auth false, so clipdrop._join_url handed out the bare LAN/tunnel
URL. Scanning that QR was an unauthenticated open door.

clipdrop.py is not imported here: PR #39 owns a syntax error on that file.
These tests hit the auth signals _join_url reads, then read clipdrop.py as
text so a later edit cannot quietly drop the host-only list or the QR hook.
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

ROOT = Path(__file__).resolve().parents[1]
CLIPDROP = (ROOT / "clipdrop.py").read_text(encoding="utf-8")

HOST_ONLY_PREFIXES = (
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


def _join_url_from_auth(base_url: str, *, host_verified: bool) -> tuple[str, str]:
    """The clipdrop._join_url contract, using only the auth signals it reads."""
    if not auth.status().get("needs_auth"):
        return base_url, ""
    qt = auth.issue_qr_token(None, host_verified=host_verified)
    if not qt:
        return base_url, ""
    return base_url.rstrip("/") + "/?qr=" + qt, qt


class QrShareCredentialTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_ws = auth.WORKSPACE_FILE
        self._orig_tok = auth.TOKENS_FILE
        auth.WORKSPACE_FILE = Path(self._tmp.name) / "workspace.json"
        auth.TOKENS_FILE = Path(self._tmp.name) / "auth_tokens.json"
        auth._tokens.clear()
        auth._qr_tokens.clear()

    def tearDown(self):
        auth.WORKSPACE_FILE = self._orig_ws
        auth.TOKENS_FILE = self._orig_tok
        auth._tokens.clear()
        auth._qr_tokens.clear()
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
        url, tok = _join_url_from_auth("http://192.0.2.10:8765", host_verified=True)
        self.assertTrue(tok)
        self.assertIn("?qr=", url)
        self.assertIn(tok, url)
        self.assertNotEqual(url, "http://192.0.2.10:8765")

    def test_join_url_stays_bare_for_a_remote_minter(self):
        url, tok = _join_url_from_auth("http://192.0.2.10:8765", host_verified=False)
        self.assertEqual(tok, "")
        self.assertEqual(url, "http://192.0.2.10:8765")

    def test_passcode_disarm_still_opens_the_door_on_purpose(self):
        auth.init_workspace("host@example.com", "secret123")
        auth.set_passcode_required(False)
        self.assertFalse(auth.status()["needs_auth"])
        self.assertTrue(auth.status()["passcode_set"])
        url, tok = _join_url_from_auth("http://192.0.2.10:8765", host_verified=True)
        self.assertEqual(tok, "")
        self.assertEqual(url, "http://192.0.2.10:8765")

    def test_clipdrop_join_url_still_reads_the_auth_signals(self):
        """PR #39 owns clipdrop.py; this ticket must keep using those two calls."""
        self.assertIn("if not app_auth.status().get(\"needs_auth\"):", CLIPDROP)
        self.assertIn("qt = app_auth.issue_qr_token(", CLIPDROP)
        self.assertIn("join_url = key + \"/?qr=\" + qt", CLIPDROP)

    def test_host_only_prefixes_stay_closed(self):
        """This ticket must not open the operator surfaces DR-0003 fences."""
        for prefix in HOST_ONLY_PREFIXES:
            self.assertIn(f'"{prefix}"', CLIPDROP, f"{prefix} left the host-only list")


if __name__ == "__main__":
    unittest.main()

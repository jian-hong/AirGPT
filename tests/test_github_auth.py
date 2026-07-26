"""github_auth device-flow helpers (no network in happy unit paths)."""
from __future__ import annotations

import unittest
from unittest import mock

import github_auth


class GitHubAuthTests(unittest.TestCase):
    def test_minimal_vs_broad_scopes(self) -> None:
        self.assertIn("read:user", github_auth.GITHUB_SCOPES_MINIMAL)
        self.assertNotIn("repo ", github_auth.GITHUB_SCOPES_MINIMAL + " ")
        self.assertIn("repo", github_auth.scopes_for(broad=True))
        self.assertIn("read:org", github_auth.scopes_for(broad=True))

    def test_start_without_client_id(self) -> None:
        with mock.patch.dict("os.environ", {"GITHUB_CLIENT_ID": ""}, clear=False):
            out = github_auth.start_device_flow()
        self.assertFalse(out.get("ok"))
        self.assertIn("GITHUB_CLIENT_ID", out.get("error") or "")

    def test_poll_pending(self) -> None:
        with mock.patch.dict("os.environ", {"GITHUB_CLIENT_ID": "abc"}, clear=False):
            with mock.patch.object(
                github_auth,
                "_post_form",
                return_value={"error": "authorization_pending"},
            ):
                out = github_auth.poll_device_flow("device")
        self.assertTrue(out.get("pending"))
        self.assertNotIn("access_token", out)

    def test_status_disconnected(self) -> None:
        with mock.patch.object(github_auth, "stored_token", return_value=""):
            out = github_auth.status()
        self.assertTrue(out.get("ok"))
        self.assertFalse(out.get("connected"))


if __name__ == "__main__":
    unittest.main()

"""Unit tests for shared Netie identity + license linkage."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class NetieIdTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.account = Path(self._tmpdir.name) / "account.json"
        import netie_id

        self.netie_id = netie_id
        self._orig = netie_id.ACCOUNT_FILE
        netie_id.ACCOUNT_FILE = self.account

    def tearDown(self) -> None:
        self.netie_id.ACCOUNT_FILE = self._orig

    def test_link_airgpt_also_marks_space(self):
        out = self.netie_id.link_local(email="user@netie.ai", product="airgpt", sku="personal")
        self.assertTrue(out["ok"])
        st = self.netie_id.status()
        self.assertEqual(st["email"], "user@netie.ai")
        self.assertTrue(st["products"]["airgpt"]["linked"])
        self.assertTrue(st["products"]["space"]["linked"])
        self.assertEqual(st["products"]["space"].get("via"), "airgpt_bundle")

    def test_account_file_written(self):
        self.netie_id.link_local(email="a@b.co", product="space", sku="personal")
        raw = json.loads(self.account.read_text(encoding="utf-8"))
        self.assertEqual(raw["email"], "a@b.co")
        self.assertTrue(raw["products"]["space"]["linked"])

    def test_login_offline_falls_back_to_local_link(self):
        with mock.patch.object(self.netie_id, "_api_base", return_value=""):
            out = self.netie_id.login_online("offline@netie.ai", "secret")
        self.assertTrue(out["ok"])
        self.assertEqual(self.netie_id.status()["email"], "offline@netie.ai")


class LicenseNetieBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        import license as app_license
        import netie_id

        self.license = app_license
        self.netie_id = netie_id
        self._lic = app_license.LICENSE_FILE if hasattr(app_license, "LICENSE_FILE") else None
        # Point LICENSE_FILE via config monkeypatch
        from config import LICENSE_FILE

        self._orig_lic = LICENSE_FILE
        self.lic_path = Path(self._tmpdir.name) / "license.json"
        self._patcher = mock.patch("license.LICENSE_FILE", self.lic_path)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self._orig_acc = netie_id.ACCOUNT_FILE
        netie_id.ACCOUNT_FILE = Path(self._tmpdir.name) / "account.json"
        self.addCleanup(lambda: setattr(netie_id, "ACCOUNT_FILE", self._orig_acc))

    def test_activate_links_netie_account(self):
        r = self.license.activate_license("TEST-KEY-ABCDEFGH", "biz@netie.ai")
        self.assertTrue(r.get("ok"))
        st = self.netie_id.status()
        self.assertEqual(st["email"], "biz@netie.ai")
        self.assertTrue(st["products"]["airgpt"]["linked"])
        status = self.license.get_status()
        self.assertTrue(status.get("netie_account", {}).get("signed_in") or status.get("email"))


if __name__ == "__main__":
    unittest.main()

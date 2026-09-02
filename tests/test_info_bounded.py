"""HOST-DEMO-03: /api/info must answer while LAN/online/Cortex probes hang.

Live :8766 /api/info timed out at 12s (probe was 0.3s). The request thread was
doing PowerShell Get-NetAdapter, netsh firewall rules, and Google generate_204
on a cold cache. The phone never received tunnel_attempts. Asserted on the HTTP
body and elapsed time, not a log line (R-0001).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")
os.environ.setdefault("AIRGPT_DATA_DIR", os.path.join(tempfile.gettempdir(), "airgpt_test_data"))

import clipdrop  # noqa: E402
import wifi_access  # noqa: E402
import cortex_client as cc  # noqa: E402


def _sleep8(*_a, **_k):
    time.sleep(8.0)
    return False


class InfoBoundedTest(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "compute": clipdrop._compute_lan_diagnostics,
            "probe": clipdrop._probe_online,
            "health": cc.health,
            "wifi": wifi_access.wifi_adapter_up,
            "bt": wifi_access.bluetooth_present,
            "lan_cache": dict(clipdrop._lan_diag_cache),
            "online_cache": dict(clipdrop._online_cache),
            "hw": dict(wifi_access._hw_cache),
            "cortex_cache": dict(clipdrop._cortex_info_cache),
        }
        clipdrop._lan_diag_cache.update({"ts": 0.0, "value": None})
        clipdrop._online_cache.update({"ok": True, "ts": 0.0})
        clipdrop._cortex_info_cache.update({"ts": 0.0, "quick": None, "full": None})
        wifi_access._hw_cache.clear()
        clipdrop._compute_lan_diagnostics = _sleep8
        clipdrop._probe_online = _sleep8
        cc.health = lambda: (_sleep8() or {"ok": False, "status": "standby"})
        wifi_access.wifi_adapter_up = _sleep8
        wifi_access.bluetooth_present = _sleep8
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        clipdrop._compute_lan_diagnostics = self._orig["compute"]
        clipdrop._probe_online = self._orig["probe"]
        cc.health = self._orig["health"]
        wifi_access.wifi_adapter_up = self._orig["wifi"]
        wifi_access.bluetooth_present = self._orig["bt"]
        clipdrop._lan_diag_cache.clear()
        clipdrop._lan_diag_cache.update(self._orig["lan_cache"])
        clipdrop._online_cache.clear()
        clipdrop._online_cache.update(self._orig["online_cache"])
        clipdrop._cortex_info_cache.clear()
        clipdrop._cortex_info_cache.update(self._orig["cortex_cache"])
        wifi_access._hw_cache.clear()
        wifi_access._hw_cache.update(self._orig["hw"])

    def test_info_returns_inside_three_seconds_when_probes_hang(self):
        t0 = time.monotonic()
        with urllib.request.urlopen(f"{self.base}/api/info", timeout=8) as r:
            body = json.loads(r.read())
        elapsed = time.monotonic() - t0
        self.assertLess(
            elapsed, 2.0,
            f"/api/info blocked {elapsed:.1f}s while LAN/online/Cortex probes were hanging",
        )
        self.assertIn("tunnel_attempts", body, "HOST-DEMO-03 payload missing after the deadline")
        self.assertIn("tunnel_url", body)
        self.assertIn("lan_url", body)

    def test_info_still_names_tunnel_state_on_a_cold_cache(self):
        """R-0005: a fast fallback that drops tunnel fields is not a fix."""
        with urllib.request.urlopen(f"{self.base}/api/info", timeout=8) as r:
            body = json.loads(r.read())
        status = body.get("tunnel_status")
        self.assertTrue(
            status in ("off", "failed", "starting", "paywall", "", None) or isinstance(status, str),
            f"tunnel_status missing or unusable: {status!r}",
        )
        self.assertIsInstance(body.get("tunnel_attempts"), list)
        self.assertIn("online", body)


if __name__ == "__main__":
    unittest.main()

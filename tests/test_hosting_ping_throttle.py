"""HOST-DEMO-01: backend health pings are polled, so they must be throttled.

`hosting.status()` fired up to four live `_ping_openai()` requests every time it was
called - Ollama, vLLM, SGLang, Colibri, 2.5s timeout each, serially. `/api/hosting`
called it uncached and undeadlined, and the Hosting page re-fetches that route every
8s while it is open. With two offline backends an 8s poll was servicing a 5-10s
blocking handler.

Two gates: the fan-out is cached behind a TTL, and the route never holds the request
thread on a slow backend. Both assert the HTTP response body, not a log line (R-0001).
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
import hosting  # noqa: E402

FOUR_BACKENDS = {
    "OLLAMA_BASE_URL": "http://127.0.0.1:59001",
    "VLLM_BASE_URL": "http://127.0.0.1:59002",
    "SGLANG_BASE_URL": "http://127.0.0.1:59003",
    "COLIBRI_BASE_URL": "http://127.0.0.1:59004",
}


class _PingSpy:
    """Stands in for _ping_openai: counts calls, optionally burns wall clock."""

    def __init__(self, cost: float = 0.0):
        self.calls: list[str] = []
        self.cost = cost

    def __call__(self, base, key="EMPTY", timeout=2.5):
        self.calls.append(base)
        if self.cost:
            time.sleep(self.cost)
        return {"ok": False, "status": "offline", "error": "refused", "url": base}


class _HostingCacheBase(unittest.TestCase):
    def setUp(self):
        self._orig_ping = hosting._ping_openai
        self._orig_env = hosting._env
        self._orig_cache = dict(hosting._ping_cache)
        self.env = dict(FOUR_BACKENDS)
        hosting._env = lambda: dict(self.env)
        hosting._ping_cache.update({"ts": 0.0, "key": "", "value": None})

    def tearDown(self):
        hosting._ping_openai = self._orig_ping
        hosting._env = self._orig_env
        hosting._ping_cache.clear()
        hosting._ping_cache.update(self._orig_cache)


class PingThrottleTest(_HostingCacheBase):
    def test_repeat_polls_do_not_re_ping_the_backends(self):
        """The 8s Hosting poll must not fan out to four backends every time."""
        spy = _PingSpy()
        hosting._ping_openai = spy
        for _ in range(5):
            hosting.status()
        self.assertEqual(len(spy.calls), 4, f"5 polls fired {len(spy.calls)} pings — not throttled")

    def test_cached_status_still_reports_every_backend(self):
        """R-0005: a throttle that drops data is not a throttle."""
        hosting._ping_openai = _PingSpy()
        first = hosting.status()
        second = hosting.status()
        for name in ("ollama", "vllm", "sglang", "colibri"):
            self.assertEqual(second[name]["status"], first[name]["status"], name)
            self.assertEqual(second[name]["base_url"], FOUR_BACKENDS[f"{name.upper()}_BASE_URL"], name)

    def test_repointing_a_base_url_busts_the_cache(self):
        """A cached verdict for the old URL is a lie about the new one."""
        spy = _PingSpy()
        hosting._ping_openai = spy
        hosting.status()
        self.env["VLLM_BASE_URL"] = "http://127.0.0.1:59099"
        hosting.status()
        self.assertIn("http://127.0.0.1:59099", spy.calls, "re-pointed backend served from stale cache")

    def test_ttl_expiry_re_pings(self):
        """Throttled, not frozen — a backend that comes up must be noticed."""
        spy = _PingSpy()
        hosting._ping_openai = spy
        hosting.status()
        hosting._ping_cache["ts"] = time.time() - (hosting.PING_TTL + 1.0)
        hosting.status()
        self.assertEqual(len(spy.calls), 8, "TTL expired but the backends were not re-pinged")

    def test_ttl_is_shorter_than_it_is_stale(self):
        self.assertGreater(hosting.PING_TTL, 8.0, "TTL below the 8s poll interval throttles nothing")
        self.assertLessEqual(hosting.PING_TTL, 60.0, "a minute-stale health verdict is not health")


class HostingRouteDeadlineTest(_HostingCacheBase):
    """The route must answer even while a cold fan-out is still blocking."""

    def setUp(self):
        super().setUp()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def _get_hosting(self) -> tuple[dict, float]:
        t0 = time.monotonic()
        with urllib.request.urlopen(f"{self.base}/api/hosting", timeout=30) as r:
            body = json.loads(r.read())
        return body, time.monotonic() - t0

    def test_slow_backend_does_not_hold_the_request_thread(self):
        # 4 x 3s serial = 12s of blocking I/O, the shape of two offline backends.
        hosting._ping_openai = _PingSpy(cost=3.0)
        body, elapsed = self._get_hosting()
        self.assertLess(elapsed, 6.0, f"/api/hosting blocked {elapsed:.1f}s on its own backend pings")
        self.assertTrue(body.get("pending"), f"deadline hit but the body did not say so: {body}")
        self.assertEqual(body["ollama"]["status"], "checking",
                         "a slow probe was reported as a dead backend")

    def test_warm_cache_serves_the_real_verdict(self):
        """R-0005: the deadline must not stand between the founder and real data."""
        hosting._ping_openai = _PingSpy()
        body, elapsed = self._get_hosting()
        self.assertFalse(body.get("pending"), f"fast backends still answered 'pending': {body}")
        self.assertEqual(body["ollama"]["status"], "offline")
        self.assertLess(elapsed, 3.0)


if __name__ == "__main__":
    unittest.main()

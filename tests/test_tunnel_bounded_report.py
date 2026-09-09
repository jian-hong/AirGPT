"""HOST-DEMO-03 cause 3: bounded time, and per-provider reasons on the wire.

The acceptance clause is "WHEN no provider is reachable, SHALL report within a bounded
time which providers were tried and the specific reason each failed". Both halves used
to fail.

Unbounded: `_probe_tunnel_url(attempts=24, delay=2.0)` could burn ~192s on one doomed
candidate, and `tunnel_worker` swept 4 providers x 2 attempts with read deadlines
totalling ~172s a pass. There was no wall clock anywhere in the worker.

Silent: the terminal state was one hardcoded sentence. The per-provider reasons the
code already knew were print()ed and thrown away, and `/api/info` carried single
`tunnel_status` / `tunnel_error` strings, not a list.

Every gate below asserts the `/api/info` body or the worker's own state, never a log
line (R-0001).
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")
os.environ.setdefault("AIRGPT_DATA_DIR", os.path.join(tempfile.gettempdir(), "airgpt_test_data"))

import auth  # noqa: E402
import clipdrop  # noqa: E402

NAMES = ["cloudflared", "localhost.run", "localtunnel", "serveo.net"]


def _stub(name: str, cost: float, *, wins: bool = False):
    """A provider that costs wall clock and honours whatever slice it is handed.

    The real providers bound themselves through `_read_tunnel_url(budget=...)`; this
    stands in for that. A stub that ignored `budget` would let the sweep overrun, which
    is exactly what the timing gate is watching for.
    """

    def fn(budget=None):
        started = time.monotonic()
        time.sleep(cost if budget is None else min(cost, budget))
        if wins:
            clipdrop._tunnel.update(url=f"https://x.{name}", provider=name, status="ready",
                                    error="", healthy=True)
            return clipdrop._attempt(name, True, "ready", f"https://x.{name}", started)
        return clipdrop._attempt(name, False, f"{name} said no", started=started)

    return fn


class _SweepBase(unittest.TestCase):
    """Shrinks the budgets so a sweep runs in seconds; the shapes stay the real ones."""

    SWEEP = 2.5
    SLICE = 1.0

    def setUp(self):
        self._orig = {k: getattr(clipdrop, k) for k in (
            "TUNNEL_SWEEP_BUDGET", "TUNNEL_PROVIDER_BUDGET", "TUNNEL_MIN_SLICE",
            "TUNNEL_PROVIDER_GAP", "tunnel_cloudflared", "tunnel_localhost_run",
            "tunnel_localtunnel", "tunnel_serveo",
        )}
        self._orig_tunnel = dict(clipdrop._tunnel)
        self._orig_attempts = list(clipdrop._tunnel_attempts)
        clipdrop.TUNNEL_SWEEP_BUDGET = self.SWEEP
        clipdrop.TUNNEL_PROVIDER_BUDGET = {n: self.SLICE for n in NAMES}
        clipdrop.TUNNEL_MIN_SLICE = 0.5
        clipdrop.TUNNEL_PROVIDER_GAP = 0.0
        # S1 locks the worker until a host passcode exists. Isolate the workspace
        # so this file can open the gate without leaking into other tests.
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._orig_ws = auth.WORKSPACE_FILE
        self._orig_toks = auth.TOKENS_FILE
        self._orig_tokens = dict(auth._tokens)
        auth.WORKSPACE_FILE = root / "workspace.json"
        auth.TOKENS_FILE = root / "auth_tokens.json"
        auth._tokens.clear()
        opened = auth.init_workspace("host@example.com", "secret123")
        self.assertTrue(opened.get("ok"), opened)

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(clipdrop, k, v)
        clipdrop._tunnel.clear()
        clipdrop._tunnel.update(self._orig_tunnel)
        clipdrop._tunnel_attempts.clear()
        clipdrop._tunnel_attempts.extend(self._orig_attempts)
        clipdrop._tunnel_deadline["at"] = 0.0
        auth.WORKSPACE_FILE = self._orig_ws
        auth.TOKENS_FILE = self._orig_toks
        auth._tokens.clear()
        auth._tokens.update(self._orig_tokens)
        self._tmp.cleanup()

    def _install(self, **costs):
        for name, attr in zip(NAMES, ("tunnel_cloudflared", "tunnel_localhost_run",
                                      "tunnel_localtunnel", "tunnel_serveo")):
            spec = costs.get(attr, (self.SLICE, False))
            setattr(clipdrop, attr, _stub(name, spec[0], wins=spec[1]))

    def _sweep(self) -> float:
        t0 = time.monotonic()
        clipdrop.tunnel_worker()
        return time.monotonic() - t0


class SweepIsBoundedTest(_SweepBase):
    def test_doomed_sweep_finishes_inside_its_budget(self):
        self._install()
        elapsed = self._sweep()
        self.assertLess(elapsed, self.SWEEP + 2.0,
                        f"sweep ran {elapsed:.1f}s against a {self.SWEEP:.0f}s budget")
        self.assertEqual(clipdrop._tunnel["status"], "failed")

    def test_providers_the_budget_ran_out_on_are_named_not_dropped(self):
        self._install()
        self._sweep()
        got = [a["provider"] for a in clipdrop._tunnel_attempts]
        self.assertEqual(sorted(set(got)), sorted(NAMES), f"providers went unreported: {got}")
        skipped = [a for a in clipdrop._tunnel_attempts if "not tried" in a["reason"]]
        self.assertTrue(skipped, "budget was spent but no provider was reported as not tried")
        self.assertIn("budget", skipped[0]["reason"])

    def test_a_provider_is_never_started_only_to_be_cut_off(self):
        """R-0005: below TUNNEL_MIN_SLICE, say so rather than fake an attempt."""
        self._install()
        self._sweep()
        for a in clipdrop._tunnel_attempts:
            if "not tried" in a["reason"]:
                self.assertEqual(a["elapsed_s"], 0.0, f"{a['provider']} was started and cut off")

    def test_slow_but_working_provider_still_wins(self):
        """R-0005: a control conservative enough to reject a working tunnel is a loss."""
        self._install(
            tunnel_cloudflared=(0.1, False),
            tunnel_localhost_run=(self.SLICE, True),  # uses its whole slice, then succeeds
        )
        self._sweep()
        self.assertEqual(clipdrop._tunnel["status"], "ready")
        self.assertEqual(clipdrop._tunnel["provider"], "localhost.run")
        self.assertTrue(clipdrop._tunnel_attempts[-1]["ok"])

    def test_shipped_budgets_are_bounded_and_not_stingy(self):
        for k, v in self._orig.items():
            if k == "TUNNEL_SWEEP_BUDGET":
                self.assertLessEqual(v, 120.0, "a sweep the founder waits 2min+ on reads as a hang")
                self.assertGreaterEqual(v, 60.0, "too tight to let a slow provider finish (R-0005)")
            if k == "TUNNEL_PROVIDER_BUDGET":
                self.assertEqual(sorted(v), sorted(NAMES))
                for name, slice_s in v.items():
                    self.assertGreaterEqual(slice_s, 15.0, f"{name} slice too tight to work (R-0005)")
        self.assertLessEqual(self._orig["TUNNEL_MIN_SLICE"], 15.0)


class ProbeBudgetTest(unittest.TestCase):
    """24 attempts x (6s urlopen + 2s sleep) was ~192s for one doomed candidate."""

    def setUp(self):
        self._orig_urlopen = urllib.request.urlopen

        def refuse(*_a, **_k):
            raise OSError("connection refused")

        urllib.request.urlopen = refuse

    def tearDown(self):
        urllib.request.urlopen = self._orig_urlopen

    def test_probe_stops_at_its_wall_clock(self):
        t0 = time.monotonic()
        ok, why = clipdrop._probe_tunnel_url("https://nope.example", budget=2.0)
        elapsed = time.monotonic() - t0
        self.assertFalse(ok)
        self.assertLess(elapsed, 5.0, f"probe ran {elapsed:.1f}s against a 2s budget")
        self.assertIn("OSError", why, f"the reason must name the failure, got {why!r}")
        self.assertIn("probe attempts", why)

    def test_default_probe_budget_is_bounded(self):
        self.assertLessEqual(clipdrop.TUNNEL_PROBE_BUDGET, 30.0)
        self.assertGreaterEqual(clipdrop.TUNNEL_PROBE_BUDGET, 10.0, "no room for edge propagation (R-0005)")

    def test_set_tunnel_hands_back_the_reason_it_rejected(self):
        ok, why = clipdrop._set_tunnel("https://nope.example", "cloudflared", probe_budget=1.0)
        self.assertFalse(ok)
        self.assertIn("did not pass /api/probe", why)
        self.assertIn("OSError", why, "the specific reason was swallowed")

    def test_probe_ipv4_fallback_when_getaddrinfo_11001(self):
        """Windows urllib often 11001s names that IPv4 getaddrinfo resolves."""

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.rstrip("/") == "/api/probe":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"ok": true}')
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, *_a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]

        def boom(*_a, **_k):
            raise OSError(11001, "getaddrinfo failed")

        urllib.request.urlopen = boom
        try:
            ok, why = clipdrop._probe_tunnel_url(
                f"http://127.0.0.1:{port}", budget=4.0, delay=0.1, timeout=2.0)
            self.assertTrue(ok, why)
        finally:
            srv.shutdown()
            srv.server_close()


class InfoReportsEveryProviderTest(_SweepBase):
    """What the phone actually receives (R-0001)."""

    def setUp(self):
        super().setUp()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def _info(self) -> dict:
        with urllib.request.urlopen(f"{self.base}/api/info", timeout=30) as r:
            return json.loads(r.read())

    def test_info_lists_which_providers_were_tried_and_why_each_failed(self):
        self._install(**{a: (0.2, False) for a in (
            "tunnel_cloudflared", "tunnel_localhost_run", "tunnel_localtunnel", "tunnel_serveo")})
        self._sweep()
        info = self._info()
        attempts = info.get("tunnel_attempts")
        self.assertIsInstance(attempts, list, "/api/info carries no tunnel_attempts list")
        self.assertEqual([a["provider"] for a in attempts[:4]], NAMES,
                         f"not every provider reached the phone: {attempts}")
        for a in attempts:
            self.assertFalse(a["ok"])
            self.assertTrue(a["reason"], f"{a['provider']} reported no reason")
            self.assertGreaterEqual(a["attempt"], 1, "an attempt with no round number is ambiguous")
        self.assertEqual(info["tunnel_status"], "failed")
        self.assertEqual(info["tunnel_last_provider"], "serveo.net",
                         "the last provider tried was discarded")
        self.assertEqual(info["tunnel_budget_s"], self.SWEEP)

    def test_terminal_error_is_not_one_hardcoded_sentence(self):
        self._install(**{a: (0.2, False) for a in (
            "tunnel_cloudflared", "tunnel_localhost_run", "tunnel_localtunnel", "tunnel_serveo")})
        self._sweep()
        err = self._info().get("tunnel_error") or ""
        for name in NAMES:
            self.assertIn(name, err, f"{name} missing from tunnel_error: {err!r}")

    def test_a_ready_tunnel_reports_the_winning_attempt(self):
        self._install(tunnel_cloudflared=(0.1, True))
        self._sweep()
        info = self._info()
        self.assertEqual(info["tunnel_status"], "ready")
        self.assertEqual([a["provider"] for a in info["tunnel_attempts"]], ["cloudflared"],
                         "a winning sweep should not report providers it never needed")
        self.assertTrue(info["tunnel_attempts"][0]["ok"])


class RecoveryPathStillGreenTest(_SweepBase):
    """tunnel_health_loop re-drives restart_tunnel off status=='failed'. Keep it true."""

    def test_failed_status_is_the_one_the_health_loop_watches_for(self):
        self._install()
        self._sweep()
        status = str(clipdrop._tunnel.get("status") or "")
        self.assertTrue(status in ("", "failed") or status.endswith("unreachable"),
                        f"health loop would never retry status={status!r}")
        self.assertFalse(clipdrop._tunnel.get("url"), "a failed sweep must leave no URL behind")


if __name__ == "__main__":
    unittest.main()

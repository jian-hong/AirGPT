"""A tunnel that failed to come up must keep trying.

`tunnel_worker` sweeps four providers twice and then sets status=failed and returns.
`tunnel_health_loop` only ran its probe when a URL existed. Between the two, a tunnel
that never came up stayed dead until somebody noticed and pressed Restart Tunnel — the
reported "tunnel already failed, gateway not changing".

Cloudflare rate-limits quick tunnels, so the retry has to back off rather than hammer.
"""
from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402


class TunnelRetryTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._orig_restart = clipdrop.restart_tunnel
        self._orig_time = clipdrop.time
        self._orig_tunnel = dict(clipdrop._tunnel)
        self.clock = time.monotonic()

        def fake_restart():
            self.calls.append(self.clock)
            clipdrop._tunnel["status"] = "starting"  # worker took over

        clipdrop.restart_tunnel = fake_restart

    def tearDown(self):
        clipdrop.restart_tunnel = self._orig_restart
        clipdrop.time = self._orig_time
        clipdrop._tunnel.clear()
        clipdrop._tunnel.update(self._orig_tunnel)

    def _run_loop(self, ticks):
        """Drive the health loop for N ticks on a fake clock.

        Only `clipdrop`'s view of the time module is replaced — patching the global
        `time.sleep` leaks into every other background thread in the process (it fired
        inside cortex-poller), which is precisely the kind of cross-test pollution that
        makes suites flaky.
        """
        counter = {"n": 0}
        test = self

        class _Clock:
            def sleep(self, _secs):
                counter["n"] += 1
                test.clock += 15  # one loop iteration == a 15s tick
                if counter["n"] >= ticks:
                    raise _StopLoop()

            def monotonic(self):
                return test.clock

            def __getattr__(self, name):
                return getattr(test._orig_time, name)

        clipdrop.time = _Clock()
        try:
            clipdrop.tunnel_health_loop()
        except _StopLoop:
            pass
        finally:
            clipdrop.time = self._orig_time

    def test_failed_tunnel_is_retried(self):
        clipdrop._tunnel.update(url="", status="failed", healthy=False)
        self._run_loop(ticks=3)
        self.assertTrue(self.calls, "a failed tunnel was never retried")

    def test_retry_backs_off_instead_of_hammering(self):
        """Cloudflare rate-limits; a retry every 15s would make things worse."""
        clipdrop._tunnel.update(url="", status="failed", healthy=False)

        # Keep it 'failed' so every eligible tick could retry if there were no backoff.
        orig = clipdrop.restart_tunnel

        def fake_restart():
            self.calls.append(self.clock)
            clipdrop._tunnel["status"] = "failed"

        clipdrop.restart_tunnel = fake_restart
        try:
            self._run_loop(ticks=8)   # 8 ticks == 120 simulated seconds
        finally:
            clipdrop.restart_tunnel = orig

        # 120s with 60s then 120s backoff means far fewer than 8 attempts.
        self.assertLessEqual(len(self.calls), 3, f"retried {len(self.calls)}x in 120s — no backoff")
        self.assertGreaterEqual(len(self.calls), 1)

    def test_mid_attempt_status_is_not_retried_over(self):
        """While the worker is starting up, do not stack another restart on top."""
        clipdrop._tunnel.update(url="", status="trying cloudflared", healthy=False)
        self._run_loop(ticks=4)
        self.assertEqual(self.calls, [], "restarted while a provider sweep was in flight")

    def test_live_tunnel_is_left_alone(self):
        clipdrop._tunnel.update(url="http://127.0.0.1:1", status="ready", healthy=True)
        self._run_loop(ticks=2)
        self.assertEqual(self.calls, [], "restarted a tunnel that had a URL")


class _StopLoop(Exception):
    pass


if __name__ == "__main__":
    unittest.main()

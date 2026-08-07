"""A provider's banner is not its tunnel URL.

localhost.run prints its admin console link (https://admin.localhost.run) several
lines before the real *.lhr.life forwarding URL. `_read_tunnel_url` returned on the
first line matching any pattern, so the console link won every time: `_set_tunnel`
probed it, correctly rejected it, and called `_kill_tunnel_procs()` - killing the ssh
session before the actual URL was ever printed. localhost.run could therefore never
succeed, on any network, on any attempt. Observed live as
tunnel_error="https://admin.localhost.run did not pass /api/probe".

The fix rejects the class (banner/console hostnames), not the one host, so the same
shape cannot land again on serveo or localtunnel.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402

LHR = [r"(https://[a-zA-Z0-9.-]+\.lhr\.life)", r"(https://\S+\.localhost\.run)"]
SERVEO = [r"(https://[a-z0-9-]+\.serveo\.net)", r"(https://\S+\.serveousercontent\.com)"]


class _FakeProc:
    """Stands in for subprocess.Popen: a finite stdout, then exit."""

    def __init__(self, lines):
        self.stdout = iter(lines)
        self._alive = True

    def poll(self):
        # Alive until the reader thread has drained stdout, then exited.
        return None if self._alive else 0

    def done(self):
        self._alive = False


class BannerUrlTest(unittest.TestCase):
    def setUp(self):
        self._procs = list(clipdrop._tunnel_procs)

    def tearDown(self):
        clipdrop._tunnel_procs.clear()
        clipdrop._tunnel_procs.extend(self._procs)

    def test_banner_labels_are_classified(self):
        for url in ("https://admin.localhost.run", "https://console.example.net",
                    "https://dashboard.loca.lt", "https://www.serveo.net"):
            self.assertTrue(clipdrop._is_banner_url(url), f"{url} should be banner text")

    def test_real_tunnel_urls_are_not_classified_as_banner(self):
        # R-0005: a control that refuses legitimate work is a failure.
        for url in ("https://fuzzy-pugs-draw.loca.lt", "https://a1b2c3.lhr.life",
                    "https://brave-cat-42.trycloudflare.com", "https://quiet-fox.serveo.net",
                    "https://adminvictory.lhr.life", "https://docsearch-7.loca.lt"):
            self.assertFalse(clipdrop._is_banner_url(url), f"{url} is a real tunnel")

    def test_localhost_run_banner_is_skipped_for_the_real_url(self):
        """The exact observed failure: admin link first, tunnel URL after."""
        proc = _FakeProc([
            "Welcome to localhost.run!\n",
            "Follow your favourite reverse tunnel at https://twitter.com/localhost_run\n",
            "**You need a SSH key to access this service.**\n",
            "To set up and manage custom domains go to https://admin.localhost.run/\n",
            "\n",
            "5c1f2a9b7e.lhr.life tunneled with tls termination, https://5c1f2a9b7e.lhr.life\n",
        ])
        got = clipdrop._read_tunnel_url(proc, LHR, timeout_lines=40)
        self.assertEqual(got, "https://5c1f2a9b7e.lhr.life")

    def test_banner_only_stream_yields_nothing(self):
        """No real URL means fail - never hand back the console link."""
        proc = _FakeProc(["go to https://admin.localhost.run/ for domains\n"])
        proc.done()
        self.assertIsNone(clipdrop._read_tunnel_url(proc, LHR, timeout_lines=10))

    def test_same_bug_shape_on_serveo(self):
        proc = _FakeProc([
            "Visit https://www.serveo.net for docs\n",
            "Forwarding HTTP traffic from https://silent-owl-19.serveo.net\n",
        ])
        got = clipdrop._read_tunnel_url(proc, SERVEO, timeout_lines=40)
        self.assertEqual(got, "https://silent-owl-19.serveo.net")


class _FakeKillProc:
    """Popen stand-in that records how it was asked to die."""

    def __init__(self, pid=4242):
        self.pid = pid
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class KillTreeHonestyTest(unittest.TestCase):
    """R-0011: a silent fallback is a lie.

    Off Windows there is no taskkill, and the tunnel children are not spawned with
    start_new_session - they share our process group, so os.killpg would take
    AirGPT down with them. _kill_proc_tree therefore degrades to terminating the
    wrapper alone, which is the exact orphan it exists to prevent. That degradation
    has to be visible in the output, not just implied by the platform.
    """

    def _run_on(self, os_name):
        import io
        from contextlib import redirect_stdout

        real_name = clipdrop.os.name
        real_run = clipdrop.subprocess.run
        calls = []
        proc = _FakeKillProc()
        buf = io.StringIO()
        try:
            clipdrop.os.name = os_name
            # Never let the test fire a real `taskkill /F /T` - pid 4242 belongs to
            # some process on the developer's machine, and this suite would kill it.
            clipdrop.subprocess.run = lambda *a, **k: calls.append(a) or None
            with redirect_stdout(buf):
                clipdrop._kill_proc_tree(proc)
        finally:
            clipdrop.os.name = real_name
            clipdrop.subprocess.run = real_run
        return proc, buf.getvalue(), calls

    def test_posix_announces_that_children_may_orphan(self):
        proc, out, calls = self._run_on("posix")
        self.assertTrue(proc.terminated, "wrapper must still be terminated")
        self.assertEqual(calls, [], "no taskkill off Windows")
        self.assertIn("no tree kill", out)
        self.assertIn("orphan", out)
        self.assertIn("4242", out, "the abandoned pid must be named")

    def test_windows_path_stays_quiet_about_orphans(self):
        # R-0005: the honesty print must not fire where the tree kill actually works.
        _proc, out, calls = self._run_on("nt")
        self.assertNotIn("no tree kill", out)
        self.assertEqual(len(calls), 1, "Windows must still attempt the tree kill")


if __name__ == "__main__":
    unittest.main()

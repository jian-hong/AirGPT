"""Range serving, inline preview types and host-only Open in Space for GET /data/.

Pure functions are tested directly; the handler is tested over real HTTP, reusing the
guest-scope harness so the token, share-scope and passcode gates are the real ones.
"""
from __future__ import annotations

import os
import stat
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import clipdrop  # noqa: E402
from config import DATA_DIR  # noqa: E402
from test_guest_scope import GuestScopeBase  # noqa: E402

P = clipdrop._parse_range


class ParseRangeTests(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(P("bytes=0-9", 100), (0, 9))
        self.assertEqual(P("bytes=90-", 100), (90, 99))
        self.assertEqual(P("bytes=-10", 100), (90, 99))
        self.assertEqual(P("bytes=50-5000", 100), (50, 99))
        self.assertEqual(P("bytes=-500", 100), (0, 99))
        self.assertEqual(P("BYTES = 0-0", 100), (0, 0))

    def test_unsatisfiable(self):
        for h in ("bytes=100-", "bytes=100-200", "bytes=-0"):
            self.assertEqual(P(h, 100), "unsatisfiable", h)
        self.assertEqual(P("bytes=0-0", 0), "unsatisfiable")
        self.assertEqual(P("bytes=-5", 0), "unsatisfiable")

    def test_ignored_means_whole_file(self):
        for h in (None, "", "items=0-5", "bytes=0-1,5-9", "bytes=", "bytes=-", "bytes=a-b", "bytes=9-3", "garbage"):
            self.assertIsNone(P(h, 100), h)

    def test_huge_values_do_not_overflow_or_raise(self):
        self.assertEqual(P("bytes=0-" + "9" * 5000, 100), (0, 99))
        self.assertEqual(P("bytes=-" + "9" * 5000, 100), (0, 99))
        self.assertEqual(P("bytes=" + "9" * 5000 + "-", 100), "unsatisfiable")
        self.assertEqual(P("bytes=0-99999999999999999999999", 100), (0, 99))


class PlanTests(unittest.TestCase):
    def plan(self, name):
        return clipdrop._data_response_plan(name)

    def test_inline_types(self):
        for name, mime in (("a.pdf", "application/pdf"), ("a.docx", clipdrop._OFFICE_MIME[".docx"]),
                           ("a.XLSX", clipdrop._OFFICE_MIME[".xlsx"]), ("a.pptx", clipdrop._OFFICE_MIME[".pptx"]),
                           ("a.doc", "application/msword"), ("a.txt", "text/plain")):
            ct, h = self.plan(name)
            self.assertEqual(ct, mime, name)
            self.assertTrue(h["Content-Disposition"].startswith("inline;"), name)
            self.assertEqual(h["X-Content-Type-Options"], "nosniff")
            self.assertEqual(h["Referrer-Policy"], "no-referrer")

    def test_script_capable_never_inline(self):
        for name in ("a.html", "a.htm", "a.svg", "a.xml", "a.js", "a.xhtml", "a.SVG", "a.pdf.html", "noext", "a.exe"):
            ct, h = self.plan(name)
            self.assertEqual(ct, "application/octet-stream", name)
            self.assertTrue(h["Content-Disposition"].startswith("attachment;"), name)
            self.assertEqual(h["X-Content-Type-Options"], "nosniff")

    def test_filename_cannot_inject_headers(self):
        ct, h = self.plan('x"\r\nSet-Cookie: a=b\r\n.pdf')
        for v in h.values():
            self.assertNotIn("\r", v)
            self.assertNotIn("\n", v)
        _, h = self.plan("r\u00e9sum\u00e9.pdf")
        self.assertIn("filename*=UTF-8''r%C3%A9sum%C3%A9.pdf", h["Content-Disposition"])
        self.assertTrue(h["Content-Disposition"].isascii())


class SpaceExeTests(unittest.TestCase):
    def test_resolution_order(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "env.exe")
            la = os.path.join(d, "local", "NetieSpace")
            os.makedirs(la)
            b = os.path.join(la, "NetieSpace.exe")
            for f in (a, b):
                open(f, "w").close()
            r = clipdrop._resolve_space_exe
            self.assertEqual(str(r({"NETIE_SPACE_EXE": a, "LOCALAPPDATA": d + "/local"})), a)
            self.assertEqual(str(r({"NETIE_SPACE_EXE": a + "x", "LOCALAPPDATA": d + "/local"})), b)
            self.assertIsNone(r({"NETIE_SPACE_EXE": a + "x"}))
            self.assertIsNone(r({}))


class DataHandlerTests(GuestScopeBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.body = os.urandom(10240)  # unique: the store refuses a duplicate upload
        cls.pdf = clipdrop.post_message("1.1.1.1", "d", file_data=b"%PDF-1.4\n" + cls.body, filename="doc.pdf", session_id=cls.sid_a, auto_analyze=False)
        cls.size = len(b"%PDF-1.4\n" + cls.body)

    def get(self, rel, rng=None, tok=None, remote=False, **kw):
        h = {"Range": rng} if rng else {}
        return self.req("GET", "/data/" + rel, tok or self.host_tok, remote=remote, raw=True, headers=h, **kw)

    def test_full_and_accept_ranges(self):
        st, h, b = self.get(self.pdf["filepath"])
        self.assertEqual(st, 200)
        self.assertEqual(h["accept-ranges"], "bytes")
        self.assertEqual(len(b), self.size)
        self.assertEqual(h["content-type"], "application/pdf")
        self.assertTrue(h["content-disposition"].startswith("inline;"))

    def test_single_suffix_open_ended(self):
        full = self.get(self.pdf["filepath"])[2]
        st, h, b = self.get(self.pdf["filepath"], "bytes=5-14")
        self.assertEqual((st, b, h["content-range"]), (206, full[5:15], "bytes 5-14/%d" % self.size))
        self.assertEqual(h["content-length"], "10")
        st, h, b = self.get(self.pdf["filepath"], "bytes=-20")
        self.assertEqual((st, b), (206, full[-20:]))
        st, h, b = self.get(self.pdf["filepath"], "bytes=%d-" % (self.size - 3))
        self.assertEqual((st, b, h["content-range"]), (206, full[-3:], "bytes %d-%d/%d" % (self.size - 3, self.size - 1, self.size)))

    def test_416_and_multirange(self):
        st, h, _ = self.get(self.pdf["filepath"], "bytes=%d-" % self.size)
        self.assertEqual(st, 416)
        self.assertEqual(h["content-range"], "bytes */%d" % self.size)
        st, _, b = self.get(self.pdf["filepath"], "bytes=0-1,5-6")
        self.assertEqual((st, len(b)), (200, self.size))

    def test_range_does_not_bypass_gates(self):
        # No token over a tunnel, another chat's file, traversal: same refusals with a Range.
        st, _, _ = self.req("GET", "/data/" + self.pdf["filepath"], None, raw=True, headers={"Range": "bytes=0-1"})
        self.assertIn(st, (401, 403, 404))
        st, _, _ = self.get(self.png_b["filepath"], "bytes=0-1", tok=self.view, remote=True)
        self.assertEqual(st, 404)
        for bad in ("../auth_tokens.json", "..%2Fauth_tokens.json", "%2e%2e/auth_tokens.json"):
            st, _, b = self.get(bad, "bytes=0-5")
            self.assertIn(st, (400, 404), bad)
        st, _, _ = self.get("auth_tokens.json", "bytes=0-5", tok=self.joined, remote=True)
        self.assertEqual(st, 404)

    def test_html_stays_attachment(self):
        st, h, _ = self.get(self.html_a["filepath"], "bytes=0-4")
        self.assertEqual(st, 206)
        self.assertEqual(h["content-type"], "application/octet-stream")
        self.assertTrue(h["content-disposition"].startswith("attachment;"))
        self.assertEqual(h["x-content-type-options"], "nosniff")

    def test_streams_in_chunks(self):
        big = DATA_DIR / "files" / "_range_big.bin"
        big.parent.mkdir(parents=True, exist_ok=True)
        big.write_bytes(b"x" * (clipdrop._RANGE_CHUNK * 3 + 7))
        self.addCleanup(lambda: big.unlink(missing_ok=True))
        with mock.patch.object(clipdrop.Path, "read_bytes", side_effect=AssertionError("read whole file")):
            st, _, b = self.req("GET", "/data/files/_range_big.bin", self.host_tok, remote=False, raw=True)
        self.assertEqual((st, len(b)), (200, clipdrop._RANGE_CHUNK * 3 + 7))


class OpenInSpaceTests(GuestScopeBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pdf = clipdrop.post_message("1.1.1.1", "d", file_data=b"%PDF-1.4 " + os.urandom(16), filename="s.pdf", session_id=cls.sid_a, auto_analyze=False)

    def fake_exe(self, tmp):
        out = os.path.join(tmp, "argv.txt")
        exe = os.path.join(tmp, "NetieSpace.exe")
        with open(exe, "w") as f:
            f.write('#!/bin/sh\nprintf "%%s\\n" "$@" > "%s"\n' % out)
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IXUSR)
        return exe, out

    def post_open(self, path, tok, remote, rel):
        return self.req("POST", path, tok, body={"path": rel}, remote=remote)

    def test_host_launches_with_list_argv(self):
        import tempfile
        if os.name == "nt":
            self.skipTest("fake exe is a shell script")
        with tempfile.TemporaryDirectory() as tmp:
            exe, out = self.fake_exe(tmp)
            with mock.patch.dict(os.environ, {"NETIE_SPACE_EXE": exe}):
                st, body = self.req("GET", "/api/space/status", self.host_tok, remote=False)
                self.assertEqual((st, body), (200, {"available": True}))
                st, body = self.post_open("/api/space/open", self.host_tok, False, self.pdf["filepath"])
                self.assertEqual((st, body.get("ok")), (200, True), body)
                for _ in range(50):
                    if os.path.isfile(out) and os.path.getsize(out):
                        break
                    time.sleep(0.1)
                argv = open(out).read().split("\n")[:2]
            self.assertEqual(argv[0], "--preview")
            self.assertEqual(argv[1], str((DATA_DIR / self.pdf["filepath"]).resolve()))

    def test_phone_and_tunnel_get_403_and_nothing_launches(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            exe, out = self.fake_exe(tmp)
            with mock.patch.dict(os.environ, {"NETIE_SPACE_EXE": exe}), \
                 mock.patch.object(clipdrop.subprocess, "Popen") as popen:
                for tok in (self.joined, self.view, self.post, self.host_tok):
                    st, _ = self.post_open("/api/space/open", tok, True, self.pdf["filepath"])
                    self.assertEqual(st, 403)
                st, _ = self.req("POST", "/api/space/open", None, body={"path": self.pdf["filepath"]}, remote=True)
                self.assertIn(st, (401, 403))
                st, _ = self.req("GET", "/api/space/status", self.joined, remote=True)
                self.assertEqual(st, 403)
                # a spoofed forwarding header does not make a tunnel peer the host
                st, _ = self.req("POST", "/api/space/open", self.joined, body={"path": self.pdf["filepath"]},
                                 remote=True, headers={"X-Forwarded-For": "127.0.0.1", "CF-Connecting-IP": "127.0.0.1"})
                self.assertEqual(st, 403)
                popen.assert_not_called()

    def test_traversal_and_missing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(clipdrop.subprocess, "Popen") as popen:
            exe, _ = self.fake_exe(tmp)
            with mock.patch.dict(os.environ, {"NETIE_SPACE_EXE": exe}):
                for rel in ("../auth_tokens.json", "..\\auth_tokens.json", "%2e%2e/x", "/etc/passwd",
                            "C:\\Windows\\win.ini", "", "files/\x00x"):
                    st, _ = self.post_open("/api/space/open", self.host_tok, False, rel)
                    self.assertIn(st, (400, 404), rel)
                st, _ = self.post_open("/api/space/open", self.host_tok, False, "files/nope.pdf")
                self.assertEqual(st, 404)
            popen.assert_not_called()

    def test_missing_exe_is_clear_and_status_false(self):
        with mock.patch.dict(os.environ, {"NETIE_SPACE_EXE": "/nonexistent/x", "LOCALAPPDATA": "/nonexistent",
                                          "ProgramFiles": "/nonexistent"}):
            st, body = self.req("GET", "/api/space/status", self.host_tok, remote=False)
            self.assertEqual((st, body), (200, {"available": False}))
            st, body = self.post_open("/api/space/open", self.host_tok, False, self.pdf["filepath"])
            self.assertEqual(st, 503)
            self.assertIn("not installed", body["error"])


if __name__ == "__main__":
    unittest.main()

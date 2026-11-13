"""Other web pages and forged Host headers must not act as the host.

The server used to decide "this is the host" from the socket address alone, while a
browser lets any page send requests to 127.0.0.1. These tests go over real HTTP and
pin the central guards: Host allow-list, cross-site Origin refusal, CORS without the
wildcard, body limits, and a 400/500 answer instead of a dropped connection.
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402
import db  # noqa: E402

EVIL = "https://evil.example"
XSS = '"><img src=x onerror=alert(1)>'


class OriginGuardTest(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]
        self.own = "127.0.0.1:%d" % self.port
        self._s1 = clipdrop._s1_remote_open
        clipdrop._s1_remote_open = lambda: True  # as if the host passcode is set

    def tearDown(self):
        clipdrop._s1_remote_open = self._s1
        self.srv.shutdown()
        self.srv.server_close()

    def req(self, method, path, headers=None, body=None, raw_cl=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        h = {"Host": self.own}
        h.update(headers or {})
        for k, v in h.items():
            c.putheader(k, v)
        data = body.encode() if isinstance(body, str) else body
        if raw_cl is not None:
            c.putheader("Content-Length", raw_cl)
        elif data is not None:
            c.putheader("Content-Length", str(len(data)))
        c.endheaders(data if raw_cl is None else None)
        r = c.getresponse()
        out = r.read()
        hdrs = {k.lower(): v for k, v in r.getheaders()}
        c.close()
        return r.status, hdrs, out

    # --- cross-site pages ---------------------------------------------------
    def test_cross_site_origin_is_refused(self):
        cases = [
            ("POST", "/api/terminal/exec", '{"cmd":"echo hi"}'),
            ("GET", "/api/settings?keys=1", None),
            ("POST", "/api/settings", "{}"),
            ("POST", "/api/import", "x"),
            ("POST", "/api/admin/validate-all", "x"),
            ("GET", "/api/wait", None),
        ]
        for method, path, body in cases:
            for ctype in ("application/json", "text/plain"):
                st, _h, out = self.req(method, path, {"Origin": EVIL, "Content-Type": ctype}, body)
                self.assertEqual(st, 403, (method, path, ctype, out[:80]))
                self.assertIn(b"another website", out)

    def test_null_origin_is_refused(self):
        st, *_ = self.req("GET", "/api/settings", {"Origin": "null"})
        self.assertEqual(st, 403)

    def test_same_origin_and_no_origin_pass(self):
        st, h, _ = self.req("GET", "/api/health", {"Origin": "http://" + self.own})
        self.assertEqual(st, 200)
        self.assertEqual(h.get("access-control-allow-origin"), "http://" + self.own)
        self.assertEqual(h.get("vary"), "Origin")
        st, *_ = self.req("GET", "/api/health")
        self.assertEqual(st, 200)

    def test_env_allow_list_is_the_escape_hatch(self):
        os.environ["AIRGPT_ALLOWED_ORIGINS"] = "https://app.example"
        try:
            st, h, _ = self.req("GET", "/api/health", {"Origin": "https://app.example"})
            self.assertEqual(st, 200)
            self.assertEqual(h.get("access-control-allow-origin"), "https://app.example")
        finally:
            del os.environ["AIRGPT_ALLOWED_ORIGINS"]

    def test_no_wildcard_cors_anywhere(self):
        for hdrs in ({}, {"Origin": EVIL}, {"Origin": "http://" + self.own}):
            for path in ("/api/health", "/api/info", "/", "/api/nope"):
                st, h, _ = self.req("GET", path, hdrs)
                self.assertNotEqual(h.get("access-control-allow-origin"), "*", (path, hdrs))
                if hdrs.get("Origin") == EVIL:
                    self.assertNotIn("access-control-allow-origin", h)

    def test_preflight(self):
        st, h, _ = self.req("OPTIONS", "/api/settings", {"Origin": EVIL, "Access-Control-Request-Method": "POST"})
        self.assertEqual(st, 403)
        self.assertNotIn("access-control-allow-origin", h)
        st, h, _ = self.req("OPTIONS", "/api/settings", {"Origin": "http://" + self.own})
        self.assertEqual(st, 204)
        self.assertEqual(h.get("access-control-allow-origin"), "http://" + self.own)

    # --- Host header ---------------------------------------------------------
    def test_unknown_host_is_not_the_host(self):
        st, _h, out = self.req("GET", "/api/audit", {"Host": "attacker.example"})
        self.assertEqual(st, 403, out[:80])
        self.assertIn(b"host only", out)
        st, *_ = self.req("GET", "/api/audit", {"Host": "127.0.0.1.evil.com:%d" % self.port})
        self.assertEqual(st, 403)

    def test_own_names_are_the_host(self):
        names = ["localhost:%d" % self.port, "127.0.0.1:%d" % self.port, "[::1]:%d" % self.port]
        ips = clipdrop.local_ips()
        if ips:
            names.append("%s:%d" % (ips[0], self.port))
        for n in names:
            st, _h, out = self.req("GET", "/api/audit", {"Host": n})
            self.assertEqual(st, 200, (n, out[:80]))

    def test_trusted_hosts_env(self):
        os.environ["AIRGPT_TRUSTED_HOSTS"] = "mybox.lan"
        try:
            st, *_ = self.req("GET", "/api/audit", {"Host": "mybox.lan"})
            self.assertEqual(st, 200)
        finally:
            del os.environ["AIRGPT_TRUSTED_HOSTS"]

    def test_auth_init_only_for_the_host(self):
        calls = []
        orig = clipdrop.app_auth.init_workspace
        clipdrop.app_auth.init_workspace = lambda *a, **k: calls.append(a) or {"ok": True}
        try:
            body = json.dumps({"email": "a@b.test", "passcode": "auditpass-1234"})
            for host in ("attacker.example", "abc.trycloudflare.com"):
                st, _h, out = self.req("POST", "/api/auth/init", {"Host": host, "Content-Type": "application/json"}, body)
                self.assertEqual(st, 403, out[:80])
                self.assertIn(b"first passcode", out)
            self.assertEqual(calls, [])
            st, *_ = self.req("POST", "/api/auth/init", {"Content-Type": "application/json"}, body)
            self.assertEqual(st, 200)
            self.assertEqual(len(calls), 1)
        finally:
            clipdrop.app_auth.init_workspace = orig

    def test_forged_forwarded_address_never_reaches_stored_peers(self):
        before = {d["ip"] for d in db.list_devices()}
        for hdr in ("CF-Connecting-IP", "X-Forwarded-For"):
            st, *_ = self.req("GET", "/api/sessions", {"Host": "abc.trycloudflare.com", hdr: XSS})
            self.assertNotEqual(st, 500)
        ips = [d["ip"] for d in db.list_devices() if d["ip"] not in before]
        self.assertFalse([i for i in ips if "<" in i or '"' in i], ips)
        self.assertEqual(clipdrop._forwarded_client_ip(
            {"Host": "x.trycloudflare.com", "CF-Connecting-IP": XSS}, "127.0.0.1"), clipdrop.TUNNEL_PEER)
        self.assertEqual(clipdrop._forwarded_client_ip(
            {"Host": "x.trycloudflare.com", "CF-Connecting-IP": "9.9.9.9"}, "127.0.0.1"), "9.9.9.9")

    def test_forwarded_address_scope_and_mapped_forms(self):
        # ip_address() accepts an IPv6 scope id with any text after the %, so a payload
        # hid behind a valid-looking address; mapped loopback must not look like a peer.
        f = lambda v: clipdrop._forwarded_client_ip(
            {"Host": "x.trycloudflare.com", "CF-Connecting-IP": v}, "127.0.0.1")
        self.assertEqual(f('fe80::1%' + XSS), "fe80::1")
        self.assertEqual(f("::ffff:9.9.9.9"), "9.9.9.9")
        self.assertEqual(f("::ffff:127.0.0.1"), clipdrop.TUNNEL_PEER)
        before = {d["ip"] for d in db.list_devices()}
        self.req("GET", "/api/sessions", {"Host": "abc.trycloudflare.com", "X-Forwarded-For": 'fe80::1%' + XSS})
        ips = [d["ip"] for d in db.list_devices() if d["ip"] not in before]
        self.assertFalse([i for i in ips if "<" in i or '"' in i], ips)

    # --- bodies and errors ----------------------------------------------------
    def test_oversized_body_is_413(self):
        st, _h, out = self.req("POST", "/api/messages", {"Content-Type": "application/json"},
                               raw_cl=str(clipdrop.MAX_BODY + 1))
        self.assertEqual(st, 413)
        self.assertIn(b"too large", out)

    def test_bad_content_length_is_400(self):
        for cl in ("abc", "-5"):
            st, _h, out = self.req("POST", "/api/messages", {"Content-Type": "application/json"}, raw_cl=cl)
            self.assertEqual(st, 400, cl)
            self.assertIn(b"Content-Length", out)
        st, *_ = self.req("POST", "/api/messages", {"Content-Type": "application/json"})
        self.assertEqual(st, 400)

    def test_bad_json_is_400_not_a_dropped_connection(self):
        st, _h, out = self.req("POST", "/api/messages", {"Content-Type": "application/json"}, "{bad")
        self.assertEqual(st, 400)
        self.assertIn(b"not valid JSON", out)

    def test_unexpected_error_is_a_json_500(self):
        orig = clipdrop.app_auth.status
        clipdrop.app_auth.status = lambda *a, **k: 1 / 0
        try:
            st, _h, out = self.req("GET", "/api/auth/status")
        finally:
            clipdrop.app_auth.status = orig
        self.assertEqual(st, 500)
        self.assertFalse(json.loads(out)["ok"])

    # --- headers --------------------------------------------------------------
    def test_security_headers(self):
        st, h, _ = self.req("GET", "/")
        self.assertEqual(h.get("x-content-type-options"), "nosniff")
        self.assertEqual(h.get("x-frame-options"), "SAMEORIGIN")
        self.assertIn("frame-ancestors 'self'", h.get("content-security-policy", ""))
        st, h, _ = self.req("GET", "/api/health")
        self.assertEqual(h.get("x-content-type-options"), "nosniff")
        self.assertNotIn("x-frame-options", h)

    def test_silent_connection_has_a_timeout(self):
        self.assertTrue(0 < (clipdrop.Handler.timeout or 0) <= 300)


if __name__ == "__main__":
    unittest.main()

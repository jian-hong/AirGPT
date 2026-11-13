"""What a share guest and a joined device can reach, over real HTTP.

A share guest holds a token scoped to one chat. A joined device holds an ordinary
token (the owner's own phone). Neither is the host. Before this change every route
was open unless someone remembered a check, and PATCH and DELETE ran no gates at all.
Each test below replays the request from the audit findings; the positive tests pin
that the normal paths (read your chat, post to it, get a reply, join and chat) stay open.
"""
from __future__ import annotations

import contextlib
import http.client
import io
import json
import os
import sys
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import auth  # noqa: E402
import clipdrop  # noqa: E402
import db  # noqa: E402
from config import DATA_DIR  # noqa: E402

TUNNEL = "x.trycloudflare.com"
STATE_FILES = ("workspace.json", "auth_tokens.json", "token_session_acl.json", "session_shares.json", "token_meta.json")
SECRET_B = "TOP-SECRET-B-MESSAGE"
HTML_BODY = b"<script>window.__xss=1</script>"


def _png() -> bytes:
    """A different picture each call, so the duplicate-upload check never swallows one."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), tuple(os.urandom(3))).save(buf, "PNG")
    return buf.getvalue()


class GuestScopeBase(unittest.TestCase):
    ip_n = 0

    @classmethod
    def setUpClass(cls):
        cls._saved = {}
        for name in STATE_FILES:
            f = DATA_DIR / name
            cls._saved[name] = f.read_bytes() if f.is_file() else None
            if f.is_file():
                f.unlink()
        auth._tokens.clear()
        auth._session_shares.clear()
        cls.host_tok = auth.init_workspace("host@example.com", "abcd1")["token"]
        cls.joined = auth.join_workspace("abcd1")["token"]
        cls.sid_a = db.create_session("Guest chat A")["id"]
        cls.sid_b = db.create_session("Secret chat B")["id"]
        db.add_message(device_ip="1.1.1.1", device_name="d", text="A-TEXT-visible", source="chat", session_id=cls.sid_a)
        cls.msg_b = db.add_message(device_ip="1.1.1.1", device_name="d", text=SECRET_B, source="chat", session_id=cls.sid_b)
        cls.png_a = clipdrop.post_message("1.1.1.1", "d", file_data=_png(), filename="a.png", session_id=cls.sid_a, auto_analyze=False)
        cls.png_b = clipdrop.post_message("1.1.1.1", "d", file_data=_png(), filename="b.png", session_id=cls.sid_b, auto_analyze=False)
        cls.html_body = HTML_BODY + os.urandom(4).hex().encode()
        cls.html_a = clipdrop.post_message("1.1.1.1", "d", file_data=cls.html_body, filename="evil.html", session_id=cls.sid_a, auto_analyze=False)
        cls.view = cls._guest(cls.sid_a, "view")
        cls.post = cls._guest(cls.sid_a, "post")
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_address[1]
        cls._nonce = {}

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        for name, data in cls._saved.items():
            f = DATA_DIR / name
            if data is None:
                if f.is_file():
                    f.unlink()
            else:
                f.write_bytes(data)
        auth._tokens.clear()
        auth._session_shares.clear()

    @staticmethod
    def _guest(sid, acl):
        share = auth.issue_session_share(sid, acl=acl, host_verified=True)["share_token"]
        return auth.redeem_session_share(share)["token"]

    def req(self, method, path, tok=None, body=None, remote=True, headers=None, raw=False, nonce=True):
        """One request. remote=True arrives as a tunnel peer (not the host)."""
        GuestScopeBase.ip_n += 1
        h = {"Host": TUNNEL if remote else "127.0.0.1:%d" % self.port}
        if remote:
            h["CF-Connecting-IP"] = "9.9.%d.%d" % (GuestScopeBase.ip_n // 200, GuestScopeBase.ip_n % 200 + 1)
        if tok:
            h["X-AirGPT-Token"] = tok
            if remote and nonce:
                h["X-AirGPT-Session-Nonce"] = self._establish(tok)
        h.update(headers or {})
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = r.read()
        hdrs = {k.lower(): v for k, v in r.getheaders()}
        c.close()
        if raw:
            return r.status, hdrs, out
        try:
            return r.status, json.loads(out or b"{}")
        except ValueError:
            return r.status, out.decode("utf-8", "replace")

    def _establish(self, tok):
        if tok not in self._nonce:
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
            c.request("POST", "/api/establish", headers={"Host": TUNNEL, "X-AirGPT-Token": tok, "CF-Connecting-IP": "9.9.250.1"})
            self._nonce[tok] = json.loads(c.getresponse().read())["session_nonce"]
            c.close()
        return self._nonce[tok]


class JoinedDeviceTests(GuestScopeBase):
    """A passcode-joined phone is the owner's own: it chats and sees chats, but not machine controls."""

    def test_input_notes_are_host_only(self):  # A0.7 / A7.9
        for method, path in (("POST", "/api/input-notes/start"), ("POST", "/api/input-notes/stop"),
                             ("POST", "/api/input-notes/append"), ("GET", "/api/input-notes")):
            st, _ = self.req(method, path, self.joined, {} if method == "POST" else None)
            self.assertEqual(st, 403, path)

    def test_machine_routes_are_host_only(self):  # A7.10 / A8.8
        for method, path, body in (
            ("POST", "/api/restart-tunnel", {}),
            ("POST", "/api/agents", {"name": "Evil"}),
            ("GET", "/api/agents", None),
            ("POST", "/api/optimizers/install", {"id": "huggingface_hub", "dry_run": True}),
        ):
            st, _ = self.req(method, path, self.joined, body)
            self.assertEqual(st, 403, path)

    def test_netie_and_license_writes_are_closed(self):  # A7.8
        link = {"action": "link", "email": "attacker@evil.io", "sku": "business", "session_token": "FAKE"}
        st, _ = self.req("POST", "/api/netie/account", None, link)
        self.assertEqual(st, 401, "no token")
        st, _ = self.req("POST", "/api/netie/account", self.joined, link)
        self.assertEqual(st, 403)
        st, _ = self.req("GET", "/api/netie/account", self.joined)
        self.assertEqual(st, 403)
        st, _ = self.req("POST", "/api/license", self.joined, {"activate": True, "key": "AAAA-BBBB", "email": "x@evil.io"})
        self.assertEqual(st, 403)
        st, _ = self.req("GET", "/api/license", self.joined)
        self.assertEqual(st, 200, "reading the licence state stays open")

    def test_joined_device_lists_opens_and_chats(self):
        st, out = self.req("GET", "/api/sessions", self.joined)
        self.assertEqual(st, 200)
        ids = {s["id"] for s in out["sessions"]}
        self.assertTrue({self.sid_a, self.sid_b} <= ids)
        st, out = self.req("GET", "/api/messages?session_id=%d" % self.sid_b, self.joined)
        self.assertIn(SECRET_B, json.dumps(out))
        st, out = self.req("POST", "/api/messages", self.joined, {"text": "joined says hi", "session_id": self.sid_b})
        self.assertEqual(st, 200, out)
        self.assertTrue(out.get("ok"))

    def test_joined_device_gets_no_join_link(self):  # A7.3 / A7.13
        orig = dict(clipdrop._tunnel)
        clipdrop._tunnel["url"] = "https://" + TUNNEL
        clipdrop._qr_join_cache.clear()
        try:
            st, host = self.req("GET", "/api/info", self.host_tok, remote=False)
            self.assertTrue(host.get("qr_token"), "the host still gets its join link")
            st, out = self.req("GET", "/api/info", self.joined)
            self.assertEqual(st, 200)
            self.assertFalse(out.get("qr_token"))
            self.assertNotIn("?qr=", out.get("join_url") or "")
            self.assertEqual(out.get("data_dir"), "")
            st, out = self.req("GET", "/api/wait?since=0", self.joined)
            self.assertFalse(out.get("qr_token"))
        finally:
            clipdrop._tunnel.clear()
            clipdrop._tunnel.update(orig)
            clipdrop._qr_join_cache.clear()

    def test_delete_message_with_a_bad_id_is_a_400(self):  # R-security-acc.2
        for remote, tok in ((True, self.joined), (False, self.host_tok)):
            st, out = self.req("DELETE", "/api/messages/abc", tok, remote=remote)
            self.assertEqual(st, 400, out)

    def test_joined_device_can_delete_a_message(self):
        mid = db.add_message(device_ip="1.1.1.1", device_name="d", text="bye", source="chat", session_id=self.sid_b)["id"]
        st, out = self.req("DELETE", "/api/messages/%d" % mid, self.joined)
        self.assertEqual(st, 200, out)

    def test_data_folder_files_are_not_served_to_a_joined_device(self):  # A7.0 / A8.3
        for name in ("auth_tokens.json", "workspace.json", "clipdrop.db", "audit.jsonl", "license.json", "network.json"):
            f = DATA_DIR / name
            if not f.exists():
                f.write_bytes(b"x")
                self.addCleanup(f.unlink)
            st, _, body = self.req("GET", "/data/" + name, self.joined, raw=True)
            self.assertEqual(st, 404, name)
        st, _, body = self.req("GET", "/data/" + self.png_b["filepath"], self.joined, raw=True)
        self.assertEqual(st, 200, "a chat image still shows")
        self.assertTrue(body.startswith(b"\x89PNG"))

    def test_query_token_still_opens_an_image(self):
        st, hdrs, _ = self.req("GET", "/data/%s?token=%s" % (self.png_a["filepath"], self.joined), None, raw=True)
        self.assertEqual(st, 200)
        self.assertEqual(hdrs["content-type"], "image/png")

    def test_token_in_the_address_is_masked_in_the_log(self):  # A8.9
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.req("GET", "/data/%s?token=SECRETTOKEN123&t=1" % self.png_a["filepath"], None, raw=True)
            time.sleep(0.3)
        log = buf.getvalue()
        self.assertNotIn("SECRETTOKEN123", log)
        self.assertIn("token=***", log)

    def test_qr_redeem_is_rate_limited(self):  # A7.12
        h = {"CF-Connecting-IP": "9.8.7.6"}
        codes = [self.req("POST", "/api/auth/qr-redeem", None, {"qr_token": "guess%d" % i}, headers=h)[0] for i in range(25)]
        self.assertIn(429, codes)
        self.assertEqual(codes[0], 200)


class ShareGuestTests(GuestScopeBase):
    def test_view_guest_reads_only_its_own_chat(self):  # A7.2
        for path in ("/api/history", "/api/history?since=1", "/api/search?q=SECRET", "/api/search?q=TOP",
                     "/api/sessions", "/api/vault", "/api/wait?since=1&hist_since=1&session_id=%d" % self.sid_b,
                     "/api/messages?session_id=%d" % self.sid_b):
            st, out = self.req("GET", path, self.view)
            self.assertEqual(st, 200, path)
            self.assertNotIn(SECRET_B, json.dumps(out), path)
            self.assertNotIn("Secret chat B", json.dumps(out), path)
        for path in ("/api/export", "/api/export?package=1", "/api/projects", "/api/drops", "/api/memory/overview",
                     "/api/hub", "/api/agents", "/api/research", "/api/summarize/today"):
            st, _ = self.req("GET", path, self.view)
            self.assertEqual(st, 403, path)

    def test_view_guest_sees_its_own_chat(self):
        st, out = self.req("GET", "/api/messages?session_id=%d&full=1" % self.sid_a, self.view)
        self.assertEqual(st, 200)
        self.assertIn("A-TEXT-visible", json.dumps(out))
        st, out = self.req("GET", "/api/history", self.view)
        self.assertIn("A-TEXT-visible", json.dumps(out))
        st, out = self.req("GET", "/api/sessions", self.view)
        self.assertEqual([s["id"] for s in out["sessions"]], [self.sid_a])
        st, out = self.req("GET", "/api/vault", self.view)
        self.assertIn(self.sid_a, [s["id"] for c in out["categories"] for s in c["sessions"]])
        st, out = self.req("GET", "/api/search?q=A-TEXT", self.view)
        self.assertTrue(out["messages"])

    def test_page_shell_and_status_stay_open_to_a_guest(self):
        for path in ("/", "/ui/phone.js", "/api/auth/status", "/api/probe", "/api/info"):
            st, _, _ = self.req("GET", path, self.view, raw=True)
            self.assertEqual(st, 200, path)

    def test_guest_info_has_no_host_network_details(self):  # A7.13 / A7.3
        st, out = self.req("GET", "/api/info", self.view)
        self.assertFalse(out.get("qr_token"))
        self.assertEqual(out.get("ips"), [])
        self.assertEqual(out.get("devices"), [])
        self.assertEqual(out.get("session_id"), self.sid_a)
        for key in ("recommended_url", "firewall", "network_profile", "lan_hint"):
            self.assertFalse(out.get(key), key)  # the host's LAN address and firewall state

    def test_guest_cannot_mint_a_share_link(self):  # A7.4
        for tok in (self.view, self.post):
            for sid in (self.sid_a, self.sid_b):
                st, out = self.req("POST", "/api/sessions/%d/share" % sid, tok, {"acl": "post"})
                self.assertEqual(st, 403, out)
                self.assertNotIn("share_token", out)

    def test_post_guest_posts_to_its_own_chat_and_gets_a_reply(self):
        st, out = self.req("POST", "/api/messages", self.post, {"text": "guest hello", "session_id": self.sid_a})
        self.assertEqual(st, 200, out)
        self.assertTrue(out.get("ok"))
        orig = clipdrop.Handler._handle_chat_stream
        clipdrop.Handler._handle_chat_stream = lambda self, ip, dname: self._json(200, {"ok": True, "reply": "pong"})
        try:
            st, out = self.req("POST", "/api/chat/stream", self.post, {"text": "hi", "session_id": self.sid_a})
        finally:
            clipdrop.Handler._handle_chat_stream = orig
        self.assertEqual((st, out.get("reply")), (200, "pong"))

    def test_guest_cannot_write_into_another_chat(self):  # A7.5
        before = len(db.get_messages(session_id=self.sid_b))
        for path in ("/api/messages", "/api/chat/stream"):
            for body in ({"text": "INJECT", "session_id": self.sid_b}, {"text": "INJECT", "session_id": 0},
                         {"text": "INJECT", "session_id": self.sid_a, "reply_to_id": self.msg_b["id"]},
                         {"text": "INJECT", "session_id": self.sid_a, "context_ids": [self.msg_b["id"]]}):
                st, out = self.req("POST", path, self.post, body)
                self.assertEqual(st, 404, (path, body, out))
        self.assertEqual(len(db.get_messages(session_id=self.sid_b)), before)

    def test_guest_cannot_pull_another_chat_in_through_a_long_context_list(self):
        # The chat handler reads the first 10 context ids; the gate used to look at 3.
        own = db.get_messages(session_id=self.sid_a)[0]["id"]
        other = self.msg_b["id"]
        for ctx in ([own, own, own, other], [own] * 9 + [other]):
            for path in ("/api/messages", "/api/chat/stream"):
                st, out = self.req("POST", path, self.post, {"text": "hi", "session_id": self.sid_a, "context_ids": ctx})
                self.assertEqual(st, 404, (path, ctx, out))

    def test_a_guest_never_loses_its_scope_while_others_join(self):
        # The scope file was rewritten in place with no lock: a reader could catch it half
        # written, and two redeems at once could drop one guest. Either made the guest
        # look like an ordinary device, which sees every chat.
        shares = [auth.issue_session_share(self.sid_a, acl="view", host_verified=True)["share_token"] for _ in range(40)]
        toks, lost, stop = [], [], threading.Event()

        def redeem(share):
            toks.append(auth.redeem_session_share(share)["token"])

        def watch():
            while not stop.is_set():
                if not auth.token_session_acl(self.view):
                    lost.append(1)

        watchers = [threading.Thread(target=watch) for _ in range(3)]
        workers = [threading.Thread(target=redeem, args=(s,)) for s in shares]
        for t in watchers + workers:
            t.start()
        for t in workers:
            t.join()
        stop.set()
        for t in watchers:
            t.join()
        self.assertEqual(len(toks), 40)
        self.assertEqual(lost, [], "an existing guest was seen as unscoped")
        self.assertEqual([t for t in toks if not auth.token_session_acl(t)], [], "a new guest lost its scope")

    def test_view_guest_cannot_post_even_to_its_own_chat(self):
        for path in ("/api/messages", "/api/chat/stream"):
            st, _ = self.req("POST", path, self.view, {"text": "x", "session_id": self.sid_a})
            self.assertEqual(st, 403, path)

    def _upload(self, tok, sid):
        body = (
            "--BOUND\r\nContent-Disposition: form-data; name=\"session_id\"\r\n\r\n%d\r\n"
            "--BOUND\r\nContent-Disposition: form-data; name=\"file\"; filename=\"x.txt\"\r\nContent-Type: text/plain\r\n\r\n"
            "hello %s\r\n--BOUND--\r\n" % (sid, os.urandom(4).hex())
        ).encode()
        return self.req("POST", "/api/messages", tok, body, headers={"Content-Type": "multipart/form-data; boundary=BOUND"})

    def test_guest_cannot_post_a_file_to_another_chat(self):
        st, out = self._upload(self.post, self.sid_b)
        self.assertEqual(st, 404, out)

    def test_post_guest_can_post_a_file_to_its_own_chat(self):
        st, out = self._upload(self.post, self.sid_a)
        self.assertEqual(st, 200, out)
        self.assertTrue(out.get("ok"))
        st, out = self.req("POST", "/api/presence/typing", self.view, {"session_id": self.sid_a, "typing": True})
        self.assertEqual(st, 200, "a view guest may show that it is typing in its own chat")

    def test_guest_cannot_change_machine_state(self):  # A7.10 / A7.8 / A7.9
        for method, path, body in (
            ("POST", "/api/agents", {"name": "EvilGuestAgent"}),
            ("POST", "/api/restart-tunnel", {}),
            ("POST", "/api/memory/add", {"title": "x", "body": "y"}),
            ("POST", "/api/memory/forget", {}),
            ("POST", "/api/optimizers/install", {"id": "huggingface_hub", "dry_run": True}),
            ("POST", "/api/apps/start", {"id": "x"}),
            ("POST", "/api/hosting/role", {}),
            ("POST", "/api/license", {"activate": True, "key": "AAAA-BBBB", "email": "gv@evil.io"}),
            ("POST", "/api/input-notes/start", {}),
            ("POST", "/api/ai/config", {"auto": True}),
            ("POST", "/api/mode", {"mode": "general"}),
            ("POST", "/api/clipboard", {"text": "x"}),
        ):
            for tok in (self.view, self.post):
                st, _ = self.req(method, path, tok, body)
                self.assertEqual(st, 403, (path, "view" if tok == self.view else "post"))

    def test_guest_cannot_download_the_data_folder(self):  # A7.0 / A8.3
        for name in ("auth_tokens.json", "workspace.json", "clipdrop.db", "audit.jsonl", "license.json",
                     "session_shares.json", "token_session_acl.json"):
            f = DATA_DIR / name
            if not f.exists():
                f.write_bytes(b"x")
                self.addCleanup(f.unlink)
            for tok in (self.view, self.post):
                st, _, _ = self.req("GET", "/data/" + name, tok, raw=True)
                self.assertEqual(st, 404, name)
                st, _, _ = self.req("GET", "/data/%s?token=%s" % (name, tok), None, raw=True)
                self.assertEqual(st, 404, name + " by query token")
        # Host and the guest's own chat attachment are unchanged; another chat's file is not served.
        st, _, body = self.req("GET", "/data/" + self.png_a["filepath"], self.view, raw=True)
        self.assertEqual(st, 200)
        self.assertTrue(body.startswith(b"\x89PNG"))
        st, _, _ = self.req("GET", "/data/" + self.png_b["filepath"], self.view, raw=True)
        self.assertEqual(st, 404)
        st, _, _ = self.req("GET", "/data/%s?token=%s" % (self.png_b["filepath"], self.view), None, raw=True)
        self.assertEqual(st, 404)

    def test_host_still_reads_the_data_folder_files_it_uses(self):
        st, hdrs, body = self.req("GET", "/data/" + self.png_b["filepath"], self.host_tok, remote=False, raw=True)
        self.assertEqual((st, hdrs["content-type"]), (200, "image/png"))

    def test_uploaded_html_is_a_download_not_a_page(self):  # A9.0
        for tok, remote in ((self.view, True), (self.joined, True), (self.host_tok, False)):
            st, hdrs, body = self.req("GET", "/data/" + self.html_a["filepath"], tok, remote=remote, raw=True)
            self.assertEqual(st, 200)
            self.assertIn("attachment", hdrs.get("content-disposition", ""))
            self.assertEqual(hdrs.get("x-content-type-options"), "nosniff")
            self.assertFalse(hdrs["content-type"].startswith("text/html"))
            self.assertEqual(body, self.html_body)

    def test_patch_runs_the_same_gates(self):  # A7.6, R-security-acc.0
        st, _ = self.req("PATCH", "/api/sessions/%d" % self.sid_b, None, {"title": "PWNED"}, nonce=False)
        self.assertEqual(st, 401, "no token")
        for sid, tok, want in (
            (self.sid_b, self.view, 404),     # another chat
            (self.sid_b, self.post, 404),
            (self.sid_a, self.view, 403),     # own chat, view only
        ):
            st, out = self.req("PATCH", "/api/sessions/%d" % sid, tok, {"title": "PWNED", "archived": True})
            self.assertEqual(st, want, out)
        st, out = self.req("PATCH", "/api/agents/1", self.view, {"pinned": True})
        self.assertEqual(st, 403)
        st, out = self.req("PATCH", "/api/agents/1", self.joined, {"pinned": True})
        self.assertEqual(st, 403)
        self.assertNotEqual(db.get_session(self.sid_b)["title"], "PWNED")
        st, out = self.req("PATCH", "/api/sessions/%d" % self.sid_a, self.post, {"title": "Renamed by guest"})
        self.assertEqual(st, 200, out)
        st, out = self.req("PATCH", "/api/sessions/%d" % self.sid_b, self.joined, {"title": "Secret chat B"})
        self.assertEqual(st, 200, "a joined device can still rename")

    def test_delete_message_checks_scope_and_acl(self):  # A7.7
        other = db.add_message(device_ip="1.1.1.1", device_name="d", text="victim", source="chat", session_id=self.sid_b)["id"]
        own = db.add_message(device_ip="1.1.1.1", device_name="d", text="mine", source="chat", session_id=self.sid_a)["id"]
        for tok in (self.view, self.post):
            st, _ = self.req("DELETE", "/api/messages/%d" % other, tok)
            self.assertEqual(st, 404)
        self.assertIsNotNone(db.get_message(other))
        st, _ = self.req("DELETE", "/api/messages/%d" % own, self.view)
        self.assertEqual(st, 403)
        self.assertIsNotNone(db.get_message(own))
        st, _ = self.req("DELETE", "/api/messages/abc", self.post)
        self.assertEqual(st, 403)
        st, _ = self.req("DELETE", "/api/messages/%d" % own, self.post)
        self.assertEqual(st, 200)
        self.assertIsNone(db.get_message(own))
        for path in ("/api/sessions/%d" % self.sid_b, "/api/messages"):
            st, _ = self.req("DELETE", path, self.post)
            self.assertEqual(st, 403, path)


class LockedStateTests(GuestScopeBase):
    def test_patch_before_a_passcode_is_set_is_refused(self):  # A7.6 (a)
        ws = DATA_DIR / "workspace.json"
        keep = ws.read_bytes()
        ws.unlink()
        try:
            st, out = self.req("PATCH", "/api/sessions/%d" % self.sid_b, None, {"title": "PWNED-by-N"}, nonce=False)
            self.assertEqual(st, 403, out)
            self.assertEqual(out.get("code"), "s1_passcode_required")
            self.assertNotEqual(db.get_session(self.sid_b)["title"], "PWNED-by-N")
            st, out = self.req("DELETE", "/api/messages/1", None, nonce=False)
            self.assertEqual(st, 403)
        finally:
            ws.write_bytes(keep)

    def test_a_browser_gets_a_readable_page_and_a_script_gets_json(self):  # A6.2
        ws = DATA_DIR / "workspace.json"
        keep = ws.read_bytes()
        ws.unlink()
        try:
            st, hdrs, body = self.req("GET", "/", None, raw=True, headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}, nonce=False)
            self.assertEqual(st, 403)
            self.assertTrue(hdrs["content-type"].startswith("text/html"))
            self.assertIn(b"passcode", body)
            self.assertIn(b"Settings", body)
            st, hdrs, body = self.req("GET", "/api/sessions", None, raw=True, headers={"Accept": "application/json"}, nonce=False)
            self.assertEqual(st, 403)
            self.assertTrue(hdrs["content-type"].startswith("application/json"))
            self.assertEqual(json.loads(body)["code"], "s1_passcode_required")
        finally:
            ws.write_bytes(keep)


class HostStillWorksTests(GuestScopeBase):
    def test_host_keeps_every_control(self):
        for method, path in (("GET", "/api/agents"), ("GET", "/api/input-notes"), ("GET", "/api/netie/account"),
                             ("GET", "/api/license"), ("GET", "/api/sessions"), ("GET", "/api/export"),
                             ("GET", "/api/hub"), ("GET", "/api/audit")):
            st, _ = self.req(method, path, self.host_tok, remote=False)
            self.assertEqual(st, 200, path)
        st, _ = self.req("PATCH", "/api/sessions/%d" % self.sid_b, self.host_tok, {"pinned": False}, remote=False)
        self.assertEqual(st, 200)
        st, out = self.req("POST", "/api/sessions/%d/share" % self.sid_a, self.host_tok, {"acl": "view"}, remote=False)
        self.assertEqual(st, 200, out)
        self.assertTrue(out.get("share_token"))


if __name__ == "__main__":
    unittest.main()

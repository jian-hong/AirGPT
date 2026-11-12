"""Fork a chat from one reply, and export a whole chat."""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402
import db  # noqa: E402


def _add(sid, who, text, **kw):
    src = "ai" if who == "ai" else "chat"
    return db.add_message(device_ip="1.2.3.4", device_name="AirGPT" if who == "ai" else "Laptop",
                          text=text, source=src, session_id=sid, **kw)


class ForkDbTest(unittest.TestCase):
    def setUp(self):
        self.sess = db.create_session("Plan", capture_type="ai", category="finance")
        self.sid = int(self.sess["id"])
        proj = db.get_or_create_project("Launch")
        db.update_session_meta(self.sid, project_id=int(proj["id"]))
        self.msgs = [_add(self.sid, "u" if i % 2 == 0 else "ai", f"message {i}") for i in range(6)]
        self.made = [self.sid]

    def tearDown(self):
        for s in self.made:
            db.delete_session(s)

    def _fork(self, idx):
        out = db.fork_session(self.sid, self.msgs[idx]["id"])
        self.made.append(int(out["session"]["id"]))
        return out

    def test_fork_holds_exactly_the_messages_up_to_that_reply_in_order(self):
        out = self._fork(3)
        new = db.get_messages(session_id=out["session"]["id"])
        self.assertEqual([m["text"] for m in new], [f"message {i}" for i in range(4)])
        self.assertEqual([m["source"] for m in new], [m["source"] for m in self.msgs[:4]])
        self.assertEqual([m["device_name"] for m in new], [m["device_name"] for m in self.msgs[:4]])
        self.assertEqual([m["created_at"] for m in new], [m["created_at"] for m in self.msgs[:4]])

    def test_title_project_and_original_untouched(self):
        before = db.get_messages(session_id=self.sid)
        out = self._fork(2)
        s = out["session"]
        self.assertEqual(s["title"], "Plan (fork)")
        self.assertEqual(s["project_id"], db.get_session(self.sid)["project_id"])
        self.assertTrue(s["project_id"])
        self.assertNotEqual(s["id"], self.sid)
        after = db.get_messages(session_id=self.sid)
        self.assertEqual([m["id"] for m in after], [m["id"] for m in before])
        self.assertEqual([m["text"] for m in after], [m["text"] for m in before])
        self.assertEqual(db.get_session(self.sid)["title"], "Plan")

    def test_fork_from_the_last_reply_copies_everything(self):
        out = self._fork(5)
        self.assertEqual(out["copied"], 6)
        self.assertEqual(len(db.get_messages(session_id=out["session"]["id"])), 6)

    def test_wrong_pairs_are_refused(self):
        other = db.create_session("Other")
        self.made.append(int(other["id"]))
        om = _add(int(other["id"]), "u", "elsewhere")
        with self.assertRaises(ValueError):
            db.fork_session(self.sid, om["id"])
        with self.assertRaises(LookupError):
            db.fork_session(self.sid, 987654321)
        with self.assertRaises(LookupError):
            db.fork_session(987654321, self.msgs[0]["id"])
        self.assertEqual(len(db.get_messages(session_id=other["id"])), 1)

    def test_attachment_points_at_the_same_file_and_survives_deleting_either_chat(self):
        rel = "files/chattools_shared_test.bin"
        p = db.DATA_DIR / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"abc")
        att = _add(self.sid, "u", "", kind="file", filename="a.bin", filepath=rel, mime="application/octet-stream", size=3)
        out = db.fork_session(self.sid, att["id"])
        nid = int(out["session"]["id"])
        copy = db.get_messages(session_id=nid)[-1]
        self.assertEqual(copy["filepath"], rel)
        db.delete_session(nid)
        self.assertTrue(p.is_file(), "deleting the fork must not delete the original's file")
        db.delete_message(att["id"])
        self.assertFalse(p.exists())


class ExportDbTest(unittest.TestCase):
    def setUp(self):
        self.sid = int(db.create_session("Export me")["id"])
        for i in range(5):
            _add(self.sid, "u" if i % 2 == 0 else "ai", f"line-{i}-text")

    def tearDown(self):
        db.delete_session(self.sid)

    def test_markdown_has_title_and_every_message_once_in_order(self):
        _, ctype, text = db.export_session(self.sid, "md")
        self.assertTrue(text.startswith("# Export me"))
        pos = [text.index(f"line-{i}-text") for i in range(5)]
        self.assertEqual(pos, sorted(pos))
        for i in range(5):
            self.assertEqual(text.count(f"line-{i}-text"), 1)
        self.assertIn("AirGPT", text)
        self.assertIn("Laptop", text)

    def test_json_has_every_message_once_in_order(self):
        _, ctype, text = db.export_session(self.sid, "json")
        d = json.loads(text)
        self.assertEqual(d["chat"]["title"], "Export me")
        self.assertEqual([m["text"] for m in d["messages"]], [f"line-{i}-text" for i in range(5)])
        self.assertEqual(d["messages"][1]["role"], "assistant")

    def test_unknown_chat(self):
        with self.assertRaises(LookupError):
            db.export_session(987654321, "md")


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]
        self.sid = int(db.create_session("Http chat")["id"])
        self.other = int(db.create_session("Not yours")["id"])
        self.m = [_add(self.sid, "u" if i % 2 == 0 else "ai", f"h{i}") for i in range(3)]
        self.om = _add(self.other, "u", "secret")
        self.made = [self.sid, self.other]
        self.orig = (clipdrop._is_host_request, clipdrop._s1_remote_open,
                     clipdrop.app_auth.token_session_acl if clipdrop.app_auth else None)

    def tearDown(self):
        clipdrop._is_host_request, clipdrop._s1_remote_open = self.orig[0], self.orig[1]
        if clipdrop.app_auth:
            clipdrop.app_auth.token_session_acl = self.orig[2]
        for s in self.made:
            db.delete_session(s)
        self.srv.shutdown()
        self.srv.server_close()

    def _guest(self, acl, sid=None):
        clipdrop._is_host_request = lambda headers, ip: False
        clipdrop._s1_remote_open = lambda: True
        clipdrop.app_auth.token_session_acl = lambda tok: {"session_id": sid or self.sid, "acl": acl}

    def _req(self, method, path, body=None):
        req = urllib.request.Request(
            self.base + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), dict(e.headers)

    def _fork(self, sid, mid):
        code, body, _ = self._req("POST", "/api/sessions/fork", {"session_id": sid, "upto_message_id": mid})
        j = json.loads(body)
        if code == 200:
            self.made.append(int(j["session"]["id"]))
        return code, j

    def test_host_fork_and_export(self):
        code, j = self._fork(self.sid, self.m[1]["id"])
        self.assertEqual(code, 200)
        self.assertEqual(j["session"]["title"], "Http chat (fork)")
        self.assertEqual([m["text"] for m in db.get_messages(session_id=j["session"]["id"])], ["h0", "h1"])
        code, body, hdr = self._req("GET", f"/api/sessions/export?session_id={self.sid}&format=md")
        self.assertEqual(code, 200)
        self.assertIn("attachment", hdr.get("Content-Disposition", ""))
        self.assertIn("h2", body)
        code, body, hdr = self._req("GET", f"/api/sessions/export?session_id={self.sid}&format=json")
        self.assertEqual(len(json.loads(body)["messages"]), 3)

    def test_fork_carries_the_chats_own_instructions(self):
        import chat_prefs

        chat_prefs.set(self.sid, "Answer in Malay.")
        code, j = self._fork(self.sid, self.m[1]["id"])
        self.assertEqual(code, 200)
        self.assertTrue(j.get("instructions_copied"))
        self.assertEqual(chat_prefs.get(int(j["session"]["id"])), "Answer in Malay.")
        # and a chat without instructions forks without inventing any
        code, j2 = self._fork(self.other, self.om["id"])
        self.assertEqual(code, 200)
        self.assertNotIn("instructions_copied", j2)
        self.assertEqual(chat_prefs.get(int(j2["session"]["id"])), "")

    def test_export_heading_stays_one_line_when_the_title_has_a_line_break(self):
        sid = int(db.create_session("Line one\nLine two")["id"])
        self.made.append(sid)
        _add(sid, "u", "hello")
        code, body, _ = self._req("GET", f"/api/sessions/export?session_id={sid}&format=md")
        self.assertEqual(code, 200)
        self.assertEqual(body.splitlines()[0], "# Line one Line two")

    def test_export_survives_titles_with_non_latin_quotes_and_newlines(self):
        # The file name goes into a header, which can only carry ASCII.
        for title in ('\u65e5\u672c\u8a9e', 'a"b/c\\d\r\nX-Evil: 1', '\u00e9\u00e8'):
            sid = int(db.create_session(title)["id"])
            self.made.append(sid)
            _add(sid, "u", "hello <script>x</script> </pre>")
            for fmt in ("md", "json"):
                code, body, hdr = self._req("GET", f"/api/sessions/export?session_id={sid}&format={fmt}")
                self.assertEqual(code, 200, title)
                disp = hdr.get("Content-Disposition", "")
                self.assertTrue(disp.isascii())
                self.assertNotIn("X-Evil", hdr)
                self.assertRegex(disp, r'^attachment; filename="[A-Za-z0-9._-]+"$')
                self.assertEqual(body.count("<script>x</script>"), 1)

    def test_errors_are_plain_404_and_400(self):
        self.assertEqual(self._fork(999999999, 1)[0], 404)
        self.assertEqual(self._fork(self.sid, 999999999)[0], 404)
        code, j = self._fork(self.sid, self.om["id"])
        self.assertEqual(code, 400)
        self.assertTrue(j["error"])
        self.assertEqual(self._req("GET", "/api/sessions/export?session_id=999999999&format=md")[0], 404)
        self.assertEqual(self._req("GET", f"/api/sessions/export?session_id={self.sid}&format=pdf")[0], 400)
        self.assertEqual(self._req("POST", "/api/sessions/fork", {"session_id": "x"})[0], 400)

    def test_view_only_guest_cannot_fork_but_can_export_own_chat(self):
        self._guest("view")
        count = len(db.list_sessions(500))
        code, j = self._fork(self.sid, self.m[0]["id"])
        self.assertEqual(code, 403)
        self.assertEqual(len(db.list_sessions(500)), count)
        self.assertEqual(self._req("GET", f"/api/sessions/export?session_id={self.sid}&format=md")[0], 200)

    def test_scoped_guest_touches_only_its_own_chat(self):
        self._guest("write")
        code, j = self._fork(self.sid, self.m[0]["id"])
        self.assertEqual(code, 200)
        self.assertEqual(self._fork(self.other, self.om["id"])[0], 404)
        code, body, _ = self._req("GET", f"/api/sessions/export?session_id={self.other}&format=md")
        self.assertEqual(code, 404)
        self.assertNotIn("secret", body)


if __name__ == "__main__":
    unittest.main()

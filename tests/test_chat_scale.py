"""Long chats, many chats and many devices stay complete and light.

Each test failed on the code before this lane's changes (see the commit messages for
what was seen failing). They drive the real HTTP handler on a throw-away port.
"""
from __future__ import annotations

import gzip
import http.client
import json
import os
import sys
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402
import db  # noqa: E402


class ScaleBase(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addr = self.srv.server_address
        self.sids: list[int] = []

    def tearDown(self):
        for sid in self.sids:
            db.delete_session(sid)
        self.srv.shutdown()
        self.srv.server_close()

    def new_chat(self, title="t") -> int:
        sid = int(db.create_session(title, capture_type="ai")["id"])
        self.sids.append(sid)
        return sid

    def get(self, path, headers=None):
        c = http.client.HTTPConnection(*self.addr, timeout=20)
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        raw = r.read()
        hdrs = {k.lower(): v for k, v in r.getheaders()}
        c.close()
        return r.status, hdrs, raw

    def get_json(self, path):
        st, _h, raw = self.get(path)
        return st, json.loads(raw or b"{}")


class MessagePaging(ScaleBase):
    def test_every_message_of_a_long_chat_is_reachable_page_by_page(self):
        sid = self.new_chat()
        made = [db.add_message(device_ip="127.0.0.1", device_name="Host", text=f"MARK-{i:04d}",
                               source="chat", session_id=sid)["id"] for i in range(650)]
        st, first = self.get_json(f"/api/messages?since=0&full=1&session_id={sid}&limit=200")
        self.assertEqual(st, 200)
        self.assertEqual(len(first["messages"]), 200)
        self.assertTrue(first["has_more"], "the page must say older messages remain")
        self.assertEqual(first["messages"][-1]["id"], made[-1])
        got = [m["id"] for m in first["messages"]]
        page = first
        while page["has_more"]:
            before = page["messages"][0]["id"]
            st, page = self.get_json(f"/api/messages?full=1&session_id={sid}&before_id={before}&limit=200")
            self.assertEqual(st, 200)
            got = [m["id"] for m in page["messages"]] + got
        self.assertEqual(got, made, "all 650 messages, in order, none twice")
        self.assertFalse(page["has_more"])
        # grouped by day too, so the page can draw them
        self.assertEqual(sum(len(g["messages"]) for g in page["by_date"]), len(page["messages"]))

    def test_default_and_incremental_requests_keep_their_shape(self):
        sid = self.new_chat()
        ids = [db.add_message(device_ip="127.0.0.1", device_name="Host", text=f"m{i}", source="chat",
                              session_id=sid)["id"] for i in range(5)]
        st, d = self.get_json(f"/api/messages?since=0&full=1&session_id={sid}")
        self.assertEqual([m["id"] for m in d["messages"]], ids)
        self.assertFalse(d["has_more"])
        st, d = self.get_json(f"/api/messages?since={ids[2]}&full=1&session_id={sid}")
        self.assertEqual([m["id"] for m in d["messages"]], ids[3:])
        self.assertFalse(d["has_more"])
        st, d = self.get_json(f"/api/messages?full=1&session_id={sid}&limit=oops")
        self.assertEqual(st, 400)


class SessionPaging(ScaleBase):
    def test_old_chats_are_listed_and_open_by_id(self):
        existing = db.count_sessions()
        for i in range(210):
            self.new_chat(f"chat {i}")
        total = db.count_sessions()
        self.assertGreater(total, 200)
        st, p1 = self.get_json("/api/sessions?limit=200")
        self.assertEqual(len(p1["sessions"]), 200)
        self.assertEqual(p1["total"], total)
        self.assertTrue(p1["has_more"])
        st, p2 = self.get_json("/api/sessions?limit=200&offset=200")
        self.assertEqual(len(p2["sessions"]), total - 200)
        self.assertFalse(p2["has_more"])
        ids = [s["id"] for s in p1["sessions"]] + [s["id"] for s in p2["sessions"]]
        self.assertEqual(len(ids), len(set(ids)), "no chat on two pages")
        self.assertEqual(len(ids), total, "every chat is on some page")
        self.assertIn(self.sids[0], ids)
        # the oldest chat is not in the first page, and opens by id
        self.assertNotIn(self.sids[0], [s["id"] for s in p1["sessions"]])
        st, one = self.get_json(f"/api/sessions/{self.sids[0]}")
        self.assertEqual(st, 200)
        self.assertEqual(one["session"]["id"], self.sids[0])
        st, _ = self.get_json("/api/sessions/99999999")
        self.assertEqual(st, 404)
        self.assertGreaterEqual(existing, 0)


class OldChatsAreStillFound(ScaleBase):
    def test_an_old_scratch_chat_is_still_the_scratch_chat(self):
        old = int(db.create_session("old scratch", capture_type="scratch")["id"])
        self.sids.append(old)
        for i in range(205):
            self.new_chat(f"newer {i}")
        clipdrop._scratch_ids.discard(old)
        self.assertTrue(clipdrop._is_scratch_session(old), "a scratch chat past the first page is still scratch")
        before = db.count_sessions()
        found = clipdrop._get_or_create_scratch_session()
        self.assertEqual(db.count_sessions(), before, "no second Scratch chat may be made")
        self.assertEqual(db.get_session(found)["capture_type"], "scratch")


class ReplyInProgress(ScaleBase):
    def setUp(self):
        super().setUp()
        self.release = threading.Event()
        self.fail = False
        self._orig = (clipdrop._chat_stream_events, clipdrop._check_ai_rate,
                      clipdrop._is_online, clipdrop._ai_allowed)
        clipdrop._check_ai_rate = lambda: None
        clipdrop._is_online = lambda: True
        clipdrop._ai_allowed = lambda: True
        clipdrop._chat_stream_events = self._slow_events

    def tearDown(self):
        self.release.set()
        (clipdrop._chat_stream_events, clipdrop._check_ai_rate,
         clipdrop._is_online, clipdrop._ai_allowed) = self._orig
        super().tearDown()

    def _slow_events(self, question, mode, history, abort, **kw):
        yield {"type": "token", "text": "Working "}
        self.release.wait(15)
        if self.fail:
            raise RuntimeError("model fell over")
        yield {"type": "done", "analysis": "Finished.", "model": "stand-in"}

    def _start_send(self, sid):
        def run():
            c = http.client.HTTPConnection(*self.addr, timeout=30)
            c.request("POST", "/api/chat/stream", json.dumps({"text": "hello there", "session_id": sid}),
                      {"Content-Type": "application/json"})
            c.getresponse().read()
            c.close()
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t

    def _wait_for(self, fn, secs=8):
        end = time.time() + secs
        while time.time() < end:
            if fn():
                return True
            time.sleep(0.05)
        return False

    def test_a_running_reply_is_visible_until_it_lands(self):
        sid, other = self.new_chat(), self.new_chat()
        t = self._start_send(sid)
        busy = lambda: self.get_json(f"/api/messages?full=1&session_id={sid}")[1].get("generating")
        self.assertTrue(self._wait_for(busy), "the chat must say a reply is being written")
        # the question is already saved, the reply is not: the bare-question state
        rows = db.get_messages(session_id=sid, limit=10)
        self.assertEqual([r["source"] for r in rows], ["ai-chat"])
        self.assertFalse(self.get_json(f"/api/messages?full=1&session_id={other}")[1]["generating"])
        wait = self.get_json(f"/api/wait?since=0&session_id={sid}")[1]
        self.assertIn(sid, wait["generating"])
        self.assertNotIn(other, wait["generating"])
        listed = {s["id"]: s for s in self.get_json("/api/sessions?limit=500")[1]["sessions"]}
        self.assertTrue(listed[sid].get("generating"))
        self.assertFalse(listed[other].get("generating"))
        self.release.set()
        t.join(15)
        self.assertTrue(self._wait_for(lambda: not busy()), "it clears when the reply is saved")
        self.assertEqual([r["source"] for r in db.get_messages(session_id=sid, limit=10)], ["ai-chat", "ai"])
        self.assertNotIn(sid, self.get_json("/api/wait?since=0")[1]["generating"])

    def test_it_clears_by_itself_when_the_model_fails(self):
        sid = self.new_chat()
        self.fail = True
        t = self._start_send(sid)
        busy = lambda: self.get_json(f"/api/messages?full=1&session_id={sid}")[1].get("generating")
        self.assertTrue(self._wait_for(busy))
        self.release.set()
        t.join(15)
        self.assertTrue(self._wait_for(lambda: not busy()), "a failed generation must not stay 'answering'")
        self.assertEqual([r["source"] for r in db.get_messages(session_id=sid, limit=10)], ["ai-chat"])


    def test_a_background_reply_is_listed_too_and_clears_if_it_crashes(self):
        sid = self.new_chat()
        gate = threading.Event()

        def slow_reply(question, mode, session_id, restrict_links):
            gate.wait(10)
            raise RuntimeError("crashed")

        orig = (clipdrop.run_text_chat, clipdrop._check_ai_rate)
        clipdrop.run_text_chat = slow_reply
        clipdrop._check_ai_rate = lambda: None
        try:
            clipdrop.queue_text_chat("hi", session_id=sid)
            self.assertTrue(self._wait_for(lambda: sid in clipdrop._generating_sessions()))
            gate.set()
            self.assertTrue(self._wait_for(lambda: sid not in clipdrop._generating_sessions()),
                            "a crashed reply must not leave the chat 'answering'")
        finally:
            gate.set()
            clipdrop.run_text_chat, clipdrop._check_ai_rate = orig


class Compression(ScaleBase):
    def test_big_json_is_gzipped_when_asked_and_identical_after(self):
        sid = self.new_chat()
        for i in range(120):
            db.add_message(device_ip="127.0.0.1", device_name="Host", text=f"line {i} " + "word " * 40,
                           source="chat", session_id=sid)
        path = f"/api/messages?since=0&full=1&session_id={sid}"
        st, h, plain = self.get(path)
        self.assertNotIn("content-encoding", h)
        st, h, packed = self.get(path, {"Accept-Encoding": "gzip"})
        self.assertEqual(h.get("content-encoding"), "gzip")
        self.assertEqual(h.get("vary"), "Accept-Encoding")
        self.assertLess(len(packed), len(plain) / 3)
        self.assertEqual(json.loads(gzip.decompress(packed)), json.loads(plain))
        self.assertEqual(int(h["content-length"]), len(packed))

    def test_small_json_is_left_alone(self):
        st, h, raw = self.get("/api/health", {"Accept-Encoding": "gzip"})
        self.assertNotIn("content-encoding", h)
        self.assertTrue(json.loads(raw)["ok"])

    def test_streams_are_never_compressed(self):
        orig = (clipdrop._chat_stream_events, clipdrop._check_ai_rate, clipdrop._is_online, clipdrop._ai_allowed)
        clipdrop._check_ai_rate = lambda: None
        clipdrop._is_online = lambda: True
        clipdrop._ai_allowed = lambda: True
        def big_reply(*a, **k):
            yield {"type": "token", "text": "x" * 3000}
            yield {"type": "done", "analysis": "x" * 3000, "model": "m"}
        clipdrop._chat_stream_events = big_reply
        try:
            sid = self.new_chat()
            c = http.client.HTTPConnection(*self.addr, timeout=20)
            c.request("POST", "/api/chat/stream", json.dumps({"text": "hi", "session_id": sid}),
                      {"Content-Type": "application/json", "Accept-Encoding": "gzip"})
            r = c.getresponse()
            body = r.read()
            self.assertTrue(r.getheader("Content-Type", "").startswith("text/event-stream"))
            self.assertIsNone(r.getheader("Content-Encoding"))
            self.assertIn(b'"type": "token"', body)
            c.close()
        finally:
            (clipdrop._chat_stream_events, clipdrop._check_ai_rate,
             clipdrop._is_online, clipdrop._ai_allowed) = orig


class StaticValidators(ScaleBase):
    def test_unchanged_files_answer_304(self):
        for path in ("/ui/palette.js", "/OpenIDE/ui/openide.js"):
            st, h, body = self.get(path, {"Accept-Encoding": "gzip"})
            self.assertEqual(st, 200, path)
            self.assertTrue(h.get("etag"), path)
            self.assertTrue(h.get("last-modified"), path)
            self.assertEqual(h.get("content-encoding"), "gzip", path)
            st, h2, body2 = self.get(path, {"If-None-Match": h["etag"]})
            self.assertEqual(st, 304, path)
            self.assertEqual(body2, b"")
            st, _h3, _b = self.get(path, {"If-Modified-Since": h["last-modified"]})
            self.assertEqual(st, 304, path)
            st, _h4, body4 = self.get(path, {"If-None-Match": '"something-else"'})
            self.assertEqual(st, 200, path)
            self.assertGreater(len(body4), 1000)
        # what the client gets after gunzip is the file on disk
        _st, h, packed = self.get("/ui/palette.js", {"Accept-Encoding": "gzip"})
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui", "palette.js"), "rb") as f:
            self.assertEqual(gzip.decompress(packed), f.read())

    def test_paths_outside_the_folder_are_still_refused(self):
        st, _h, _b = self.get("/ui/../clipdrop.py")
        self.assertIn(st, (400, 404))


if __name__ == "__main__":
    unittest.main()

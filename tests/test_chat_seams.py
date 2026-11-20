"""Chat seams: a turn is the question plus its files, and the server knows if a chat is busy.

Each test failed on the code before this lane's change (regenerate and edit lost the
file, an edit with a new file got 409, a busy chat could be edited under a running reply,
a failed edit deleted the old answer). They drive the real HTTP handler with a stand-in
for the model call.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clipdrop  # noqa: E402
import db  # noqa: E402
from test_chat_core import ChatCoreBase, _events  # noqa: E402


class SeamsBase(ChatCoreBase):
    def file_row(self, sid, name, text):
        d = db.FILES / "seams"
        d.mkdir(parents=True, exist_ok=True)
        rel = f"files/seams/{os.urandom(4).hex()}-{name}"
        (db.DATA_DIR / rel).write_text(text)
        return db.add_message(device_ip="x", device_name="x", text="", kind="file", filename=name,
                              filepath=rel, mime="text/plain", size=len(text), source="chat", session_id=sid,
                              content_hash="h-" + os.urandom(6).hex())

    def turn(self, sid, q="old question", a="old answer"):
        u = db.add_message(device_ip="x", device_name="me", text=q, source="ai-chat", session_id=sid)
        r = db.add_message(device_ip="x", device_name="AirGPT", text=a, source="ai", session_id=sid)
        return u, r

    def names(self, call):
        return [f["name"] for f in (call.get("attachments") or [])]


class FilesTravelWithTheTurn(SeamsBase):
    def test_regenerate_sends_the_question_s_file_again(self):
        sid = self.new_chat()
        f = self.file_row(sid, "notes.txt", "ZEBRA-4471")
        u, _ = self.turn(sid)
        code, _, _ = self.post("/api/chat/stream", {"session_id": sid, "regenerate_msg_id": u["id"]})
        self.assertEqual(code, 200)
        self.assertEqual(self.names(self.calls[0]), ["notes.txt"])
        self.assertTrue(f["id"])

    def test_edit_keeps_the_old_file_and_adds_the_new_one(self):
        sid = self.new_chat()
        self.file_row(sid, "notes.txt", "ZEBRA-4471")
        u, _ = self.turn(sid)
        new = self.file_row(sid, "n2.txt", "QUOKKA-9")  # uploaded by the page just before the edit
        code, _, out = self.post("/api/chat/stream", {
            "session_id": sid, "text": "edited", "replace_msg_id": u["id"], "attachment_ids": [new["id"]]})
        self.assertEqual(code, 200, out)
        self.assertEqual(sorted(self.names(self.calls[0])), ["n2.txt", "notes.txt"])
        kinds = [(m["kind"], m["text"] or m["filename"]) for m in self.rows(sid)]
        self.assertEqual(kinds[:3], [("file", "notes.txt"), ("file", "n2.txt"), ("text", "edited")])
        self.assertEqual(len(kinds), 4)

    def test_edit_without_a_new_file_keeps_the_old_file(self):
        sid = self.new_chat()
        self.file_row(sid, "notes.txt", "ZEBRA-4471")
        u, _ = self.turn(sid)
        self.post("/api/chat/stream", {"session_id": sid, "text": "edited", "replace_msg_id": u["id"]})
        self.assertEqual(self.names(self.calls[0]), ["notes.txt"])

    def test_a_file_of_the_previous_turn_is_not_pulled_in(self):
        sid = self.new_chat()
        self.file_row(sid, "old.txt", "belongs to the first question")
        self.turn(sid, "first", "a1")
        u, _ = self.turn(sid, "second", "a2")
        self.post("/api/chat/stream", {"session_id": sid, "regenerate_msg_id": u["id"]})
        self.assertEqual(self.names(self.calls[0]), [])

    def test_another_chat_s_file_id_is_ignored_on_an_edit_like_on_a_fresh_send(self):
        a, b = self.new_chat(), self.new_chat()
        theirs = self.file_row(b, "secret.txt", "not yours")
        u, _ = self.turn(a)
        self.post("/api/chat/stream", {"session_id": a, "text": "edited", "replace_msg_id": u["id"],
                                       "attachment_ids": [theirs["id"]]})
        self.assertEqual(self.names(self.calls[0]), [])
        self.post("/api/chat/stream", {"session_id": a, "text": "fresh", "attachment_ids": [theirs["id"]]})
        self.assertEqual(self.names(self.calls[1]), [])

    def test_a_file_row_that_is_not_one_of_this_requests_ids_still_blocks_the_edit(self):
        sid = self.new_chat()
        u, _ = self.turn(sid)
        self.file_row(sid, "later.txt", "uploaded after, not named in the request")
        code, _, out = self.post("/api/chat/stream", {"session_id": sid, "text": "edited", "replace_msg_id": u["id"]})
        self.assertEqual(code, 409)
        self.assertIn("last question", out["error"])


class TurnFileEdges(SeamsBase):
    def test_a_junk_attachment_ids_value_does_not_crash_regenerate_or_edit(self):
        sid = self.new_chat()
        u, _ = self.turn(sid)
        for junk in (5, True, 3.7, "7", {"a": 1}):
            code, _, out = self.post("/api/chat/stream", {"session_id": sid, "regenerate_msg_id": u["id"],
                                                          "attachment_ids": junk})
            self.assertEqual(code, 200, (junk, out))
            u = [m for m in self.rows(sid) if m["source"] == "ai-chat"][-1]
            code, _, out = self.post("/api/chat/stream", {"session_id": sid, "text": "edited",
                                                          "replace_msg_id": u["id"], "attachment_ids": junk})
            self.assertEqual(code, 200, (junk, out))
            u = [m for m in self.rows(sid) if m["source"] == "ai-chat"][-1]

    def test_edit_with_twelve_new_files_leaves_the_old_ones_out_and_says_so(self):
        sid = self.new_chat()
        for n in range(2):
            self.file_row(sid, f"old{n}.txt", "old")
        u, _ = self.turn(sid)
        new = [self.file_row(sid, f"new{n:02d}.txt", "new")["id"] for n in range(12)]
        code, evs, out = self.post("/api/chat/stream", {"session_id": sid, "text": "edited",
                                                        "replace_msg_id": u["id"], "attachment_ids": new})
        self.assertEqual(code, 200, out)
        self.assertEqual(sorted(self.names(self.calls[0])), [f"new{n:02d}.txt" for n in range(12)])
        blob = repr(evs)
        self.assertIn("old0.txt", blob)
        self.assertIn("old1.txt", blob)

    def test_edit_over_the_cap_names_the_files_that_were_left_out(self):
        sid = self.new_chat()
        for n in range(2):
            self.file_row(sid, f"old{n}.txt", "old")
        u, _ = self.turn(sid)
        new = [self.file_row(sid, f"new{n:02d}.txt", "new")["id"] for n in range(13)]
        code, evs, out = self.post("/api/chat/stream", {"session_id": sid, "text": "edited",
                                                        "replace_msg_id": u["id"], "attachment_ids": new})
        self.assertEqual(code, 200, out)
        got = self.names(self.calls[0])
        self.assertEqual(len(got), 12)
        self.assertNotIn("new12.txt", got)
        self.assertIn("new12.txt", repr(evs))

    def test_edit_under_the_cap_keeps_what_fits_and_says_nothing(self):
        sid = self.new_chat()
        self.file_row(sid, "old0.txt", "old")
        u, _ = self.turn(sid)
        new = [self.file_row(sid, f"new{n:02d}.txt", "new")["id"] for n in range(3)]
        code, evs, out = self.post("/api/chat/stream", {"session_id": sid, "text": "edited",
                                                        "replace_msg_id": u["id"], "attachment_ids": new})
        self.assertEqual(len(self.names(self.calls[0])), 4)
        self.assertNotIn("left out", repr(evs))


class FailedEditKeepsTheOldTurn(SeamsBase):
    def broken(self, question, mode, history, abort, **kw):
        yield {"type": "error", "text": "No text LLM available"}

    def test_failed_edit_keeps_old_question_and_answer_and_leaves_no_duplicate(self):
        sid = self.new_chat()
        self.turn(sid, "first", "a1")
        u, _ = self.turn(sid, "second", "a2")
        clipdrop._chat_stream_events = self.broken
        code, evs, _ = self.post("/api/chat/stream", {"session_id": sid, "text": "edited", "replace_msg_id": u["id"]})
        self.assertEqual(code, 200)
        self.assertEqual(evs[-1]["type"], "error")
        self.assertEqual([m["text"] for m in self.rows(sid)], ["first", "a1", "second", "a2"])
        # and the edit can be tried again with the same ids once the model is back
        clipdrop._chat_stream_events = self._fake_events
        code, _, _ = self.post("/api/chat/stream", {"session_id": sid, "text": "edited", "replace_msg_id": u["id"]})
        self.assertEqual(code, 200)
        self.assertEqual([m["text"] for m in self.rows(sid)],
                         ["first", "a1", "edited", "Answer to: edited"])

    def test_empty_reply_edit_also_keeps_the_old_turn(self):
        sid = self.new_chat()
        u, _ = self.turn(sid)

        def silent(question, mode, history, abort, **kw):
            return
            yield  # pragma: no cover

        clipdrop._chat_stream_events = silent
        self.post("/api/chat/stream", {"session_id": sid, "text": "edited", "replace_msg_id": u["id"]})
        self.assertEqual([m["text"] for m in self.rows(sid)], ["old question", "old answer"])

    def test_old_turn_is_not_history_for_its_own_edit(self):
        sid = self.new_chat()
        u, _ = self.turn(sid, "second", "a2")
        self.post("/api/chat/stream", {"session_id": sid, "text": "edited", "replace_msg_id": u["id"]})
        self.assertEqual(self.calls[0]["history"], [])

    def test_stopped_edit_with_no_text_keeps_old_turn_and_no_duplicate(self):
        sid = self.new_chat()
        u, _ = self.turn(sid)
        started = threading.Event()

        def hang(question, mode, history, abort, **kw):
            started.set()
            while not abort.is_set():
                time.sleep(0.02)
            return
            yield  # pragma: no cover

        clipdrop._chat_stream_events = hang
        out: dict = {}

        def run():
            out["r"] = self.post("/api/chat/stream", {"session_id": sid, "text": "edited", "replace_msg_id": u["id"]})

        t = threading.Thread(target=run)
        t.start()
        self.assertTrue(started.wait(5))
        for _ in range(50):
            runs = list(clipdrop._chat_streams.items())
            if runs:
                break
            time.sleep(0.02)
        self.post("/api/chat/cancel", {"stream_id": runs[0][0]})
        t.join(10)
        self.assertEqual([m["text"] for m in self.rows(sid)], ["old question", "old answer"])


class BusyChat(SeamsBase):
    def setUp(self):
        super().setUp()
        self.release = threading.Event()
        self.started = threading.Event()

    def slow(self, question, mode, history, abort, **kw):
        self.calls.append({"question": question, "history": history, **kw})
        if question == "slow one":
            self.started.set()
            self.release.wait(10)
        yield {"type": "token", "text": "ok"}
        yield {"type": "done", "analysis": "Answer to: " + question[:30], "model": "stand-in"}

    def test_edit_and_regenerate_are_refused_while_the_chat_is_answering(self):
        sid = self.new_chat()
        u, _ = self.turn(sid)
        clipdrop._chat_stream_events = self.slow
        t = threading.Thread(target=lambda: self.post("/api/chat/stream", {"session_id": sid, "text": "slow one"}))
        t.start()
        self.assertTrue(self.started.wait(5))
        before = [m["id"] for m in self.rows(sid)]
        for body in ({"replace_msg_id": u["id"], "text": "edited"}, {"regenerate_msg_id": u["id"]}):
            code, _, out = self.post("/api/chat/stream", {"session_id": sid, **body})
            self.assertEqual(code, 409, body)
            self.assertEqual(out["error"], "AirGPT is still answering in this chat. Wait for it or press Stop.")
        self.assertEqual([m["id"] for m in self.rows(sid)][:len(before)], before)
        self.release.set()
        t.join(10)
        texts = [m["text"] for m in self.rows(sid)]
        self.assertEqual(texts, ["old question", "old answer", "slow one", "Answer to: slow one"])

    def test_the_chat_is_free_before_the_final_event_reaches_the_page(self):
        """The page sends its next waiting line the moment it sees the final event."""
        sid = self.new_chat()
        seen = {}
        orig = clipdrop.Handler._sse_send

        def spy(handler, event):
            if isinstance(event, dict) and event.get("type") == "done":
                seen["busy_at_done"] = bool(clipdrop._generating_sessions(sid))
                seen["saved_at_done"] = len([m for m in db.get_messages(session_id=sid, limit=50) if m["source"] == "ai"])
            return orig(handler, event)

        clipdrop.Handler._sse_send = spy
        try:
            self.post("/api/chat/stream", {"session_id": sid, "text": "one"})
        finally:
            clipdrop.Handler._sse_send = orig
        self.assertEqual(seen, {"busy_at_done": False, "saved_at_done": 1})

    def test_two_regenerates_at_the_same_instant_give_one_reply(self):
        # The busy check and the claim on the chat are one step: slow the window between
        # them down and fire two requests together; only one may go through.
        sid = self.new_chat()
        u, _ = self.turn(sid)
        orig = clipdrop._last_turn

        def slow_last_turn(*a, **kw):
            time.sleep(0.4)
            return orig(*a, **kw)

        clipdrop._last_turn = slow_last_turn
        codes = []
        try:
            ts = [threading.Thread(target=lambda: codes.append(
                self.post("/api/chat/stream", {"session_id": sid, "regenerate_msg_id": u["id"]})[0])) for _ in range(2)]
            [t.start() for t in ts]
            [t.join(15) for t in ts]
        finally:
            clipdrop._last_turn = orig
        self.assertEqual(sorted(codes), [200, 409])
        self.assertEqual([m["source"] for m in self.rows(sid)], ["ai-chat", "ai"])
        self.assertFalse(clipdrop._generating_sessions(sid))

    def test_three_lines_sent_back_to_back_all_get_answered_in_order(self):
        sid = self.new_chat()
        for q in ("one", "two", "three"):
            code, evs, _ = self.post("/api/chat/stream", {"session_id": sid, "text": q})
            self.assertEqual((code, evs[-1]["type"]), (200, "done"))
        self.assertEqual([m["text"] for m in self.rows(sid)],
                         ["one", "Answer to: one", "two", "Answer to: two", "three", "Answer to: three"])
        # a redo straight after the last reply is not refused as busy
        last = [m for m in self.rows(sid) if m["source"] == "ai-chat"][-1]
        code, _, _ = self.post("/api/chat/stream", {"session_id": sid, "regenerate_msg_id": last["id"]})
        self.assertEqual(code, 200)


if __name__ == "__main__":
    unittest.main()

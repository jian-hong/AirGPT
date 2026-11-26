"""A dropped stream must not destroy a finished answer.

Reported from an iPad on a Cloudflare quick tunnel: the question posted, the tunnel
flapped, and no reply ever appeared — not in the stream, and not after reloading. The
cause was that `_handle_chat_stream` persisted the answer only `if not abort.is_set()`,
and `abort` was set the moment an SSE write failed. So a dropped socket meant the model
finished the work and the server threw the result away.

Mobile links drop constantly. Losing the reader has to stop the writing, never the work.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402
import db  # noqa: E402

ANSWER = "Time travel breaks the bootstrap paradox first."


class StreamDropTest(unittest.TestCase):
    def setUp(self):
        self.started = threading.Event()

        def slow_stream(question, mode, history, abort, **kw):
            """Emit a token, pause long enough for the client to vanish, then finish."""
            self.started.set()
            yield {"type": "token", "text": "Time "}
            time.sleep(0.6)
            yield {"type": "token", "text": "travel"}
            yield {"type": "done", "analysis": ANSWER, "model": "test"}

        self._orig = (
            clipdrop._chat_stream_events,
            clipdrop._check_ai_rate,
            clipdrop._is_online,
            clipdrop._ai_allowed,
        )
        clipdrop._chat_stream_events = slow_stream
        clipdrop._check_ai_rate = lambda: None
        clipdrop._is_online = lambda: True
        clipdrop._ai_allowed = lambda: True

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addr = self.srv.server_address
        self.sid = int(db.create_session("Tunnel drop", capture_type="ai")["id"])

    def tearDown(self):
        (
            clipdrop._chat_stream_events,
            clipdrop._check_ai_rate,
            clipdrop._is_online,
            clipdrop._ai_allowed,
        ) = self._orig
        db.delete_session(self.sid)
        self.srv.shutdown()
        self.srv.server_close()

    def _ai_replies(self):
        return [
            m for m in db.get_messages(session_id=self.sid, limit=50)
            if m.get("source") == "ai"
        ]

    def _send_and_drop(self, read_bytes=1):
        body = json.dumps(
            {"session_id": self.sid, "text": "If time travel existed, what breaks first?",
             "mode": "general"}
        ).encode()
        s = socket.create_connection(self.addr, timeout=10)
        s.sendall(
            b"POST /api/chat/stream HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\nAccept: text/event-stream\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        if read_bytes:
            s.recv(read_bytes)          # let the stream open
        self.assertTrue(self.started.wait(5), "generation never started")
        s.close()                        # the tunnel dies here, mid-answer
        return s

    def test_answer_survives_the_client_disappearing(self):
        self._send_and_drop()
        # Generation continues server-side; give it room to finish and persist.
        deadline = time.time() + 15
        while time.time() < deadline and not self._ai_replies():
            time.sleep(0.2)
        replies = self._ai_replies()
        self.assertTrue(replies, "the finished answer was discarded when the client dropped")
        self.assertEqual(replies[-1]["text"], ANSWER)

    def test_user_question_is_still_recorded(self):
        self._send_and_drop()
        time.sleep(0.5)
        asked = [
            m for m in db.get_messages(session_id=self.sid, limit=50)
            if m.get("source") == "ai-chat"
        ]
        self.assertTrue(asked, "the question itself was lost")

    def test_answer_is_not_duplicated_when_the_client_stays(self):
        """The happy path must still write exactly one reply."""
        body = json.dumps(
            {"session_id": self.sid, "text": "stay connected", "mode": "general"}
        ).encode()
        s = socket.create_connection(self.addr, timeout=20)
        s.sendall(
            b"POST /api/chat/stream HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\nAccept: text/event-stream\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        s.settimeout(20)
        buf = b""
        try:
            while b"0\r\n\r\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        except socket.timeout:
            pass
        s.close()
        self.assertIn(ANSWER.encode(), buf, "the answer never reached a connected client")
        deadline = time.time() + 10
        while time.time() < deadline and not self._ai_replies():
            time.sleep(0.2)
        self.assertEqual(len(self._ai_replies()), 1, "the reply was written twice")


if __name__ == "__main__":
    unittest.main()

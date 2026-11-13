"""Server defects that are not access rules: CSV length, SSE errors, agent routes and runs, link fetch."""
from __future__ import annotations

import http.client
import json
import os
import re
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import agent_runtime  # noqa: E402
import agent_store  # noqa: E402
import ai_engine  # noqa: E402
import clipdrop  # noqa: E402
import cortex_client  # noqa: E402
import db  # noqa: E402
import workflow_engine  # noqa: E402


class _Server:
    def __enter__(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]
        return self

    def __exit__(self, *a):
        self.srv.shutdown()
        self.srv.server_close()


class HttpRouteTest(unittest.TestCase):
    def test_usage_csv_has_a_length_so_a_kept_alive_connection_finishes(self):
        with _Server() as s:
            c = http.client.HTTPConnection("127.0.0.1", s.port, timeout=5)
            c.request("GET", "/api/usage?format=csv")
            r = c.getresponse()
            self.assertEqual(r.status, 200)
            self.assertIsNotNone(r.getheader("Content-Length"), "CSV sent with no length")
            body = r.read()  # would time out without a length on HTTP/1.1
            self.assertEqual(int(r.getheader("Content-Length")), len(body))
            c.close()

    def test_task_events_with_engine_down_is_one_clean_503(self):
        orig = (cortex_client.ensure_engine, cortex_client._cfg)
        cortex_client.ensure_engine = lambda **k: {}
        cortex_client._cfg = lambda: ("http://127.0.0.1:1", "k")
        try:
            with _Server() as s:
                c = http.client.HTTPConnection("127.0.0.1", s.port, timeout=10)
                c.request("GET", "/api/workflows/task/abc/events")
                r = c.getresponse()
                body = r.read().decode()
                self.assertEqual(r.status, 503)
                self.assertNotIn("HTTP/1.1", body)
                self.assertIn("error", json.loads(body))
        finally:
            cortex_client.ensure_engine, cortex_client._cfg = orig

    def test_agent_config_can_be_saved_and_the_page_uses_that_route(self):
        a = agent_store.create_agent("Cfg test", kind="special")
        try:
            with _Server() as s:
                c = http.client.HTTPConnection("127.0.0.1", s.port, timeout=10)
                c.request("PATCH", f"/api/agents/{a['id']}", body=json.dumps({"config": {"routine_id": 7}}),
                          headers={"Content-Type": "application/json"})
                r = c.getresponse()
                got = json.loads(r.read().decode())
                self.assertEqual(r.status, 200, got)
                self.assertEqual(agent_store.get_agent(a["id"])["config"].get("routine_id"), 7)
                c.request("PATCH", "/api/agents/99999999", body=json.dumps({"config": {"x": 1}}),
                          headers={"Content-Type": "application/json"})
                r = c.getresponse()
                r.read()
                self.assertEqual(r.status, 404)
        finally:
            agent_store.delete_agent(a["id"])
        html = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "index.html"), encoding="utf-8").read()
        self.assertNotRegex(html, r"api\('/api/agents/'\+agent\.id,\{method:'POST'")


class AgentRunTest(unittest.TestCase):
    def setUp(self):
        self.agent = agent_store.create_agent("Run test", kind="special")

    def tearDown(self):
        agent_store.delete_agent(self.agent["id"])

    def _status(self, rid):
        return [r for r in agent_store.list_runs(None, 200) if r["id"] == rid][0]["status"]

    def test_a_dropped_stream_ends_the_run(self):
        gen = agent_runtime.run_agent_events(self.agent["id"], "hello", thinking_mode="assist")
        first = next(gen)
        rid = first["run_id"]
        self.assertEqual(self._status(rid), "running")
        gen.close()
        self.assertNotEqual(self._status(rid), "running")

    def test_old_running_rows_are_expired_and_cancel_works(self):
        stale = agent_store.create_run(self.agent["id"], "old")["id"]
        live = agent_store.create_run(self.agent["id"], "new")["id"]
        with agent_store._conn() as conn:
            conn.execute("UPDATE agent_runs SET created_at=? WHERE id=?", (time.time() - 7200, stale))
        agent_store.expire_stale_runs()
        self.assertEqual(self._status(stale), "error")
        self.assertEqual(self._status(live), "running")
        res = workflow_engine.cancel(f"agent_run_{live}")
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(self._status(live), "cancelled")
        self.assertFalse(workflow_engine.cancel(f"agent_run_{live}").get("ok"))


class _Canary(BaseHTTPRequestHandler):
    hits: list = []

    def do_GET(self):
        type(self).hits.append(self.path)
        if self.path == "/hop":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:%d/secret" % self.server.server_address[1])
            self.end_headers()
            return
        body = ("INTERNAL-CANARY " + "x" * 200).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class LinkFetchTest(unittest.TestCase):
    def setUp(self):
        _Canary.hits = []
        self.srv = HTTPServer(("127.0.0.1", 0), _Canary)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d/page" % self.srv.server_address[1]

    def tearDown(self):
        ai_engine.set_link_fetch_restricted(False)
        self.srv.shutdown()
        self.srv.server_close()

    def test_host_can_still_fetch_a_local_link(self):
        ai_engine.set_link_fetch_restricted(False)
        out = ai_engine._fetch_url_evidence([self.url])
        self.assertIn("INTERNAL-CANARY", out)

    def test_joined_device_cannot_make_the_host_fetch_a_local_link(self):
        ai_engine.set_link_fetch_restricted(True)
        out = ai_engine._fetch_url_evidence([self.url, "http://169.254.169.254/latest/meta-data/",
                                             "http://192.168.1.1/", "http://[::1]/", "file:///etc/passwd"])
        self.assertEqual(_Canary.hits, [])
        self.assertNotIn("INTERNAL-CANARY", out)
        self.assertIn("private or internal address", out)

    def test_redirect_into_a_private_address_is_refused(self):
        h = ai_engine._PublicOnlyRedirect()
        req = urllib.request.Request("http://example.com/")
        for target in ("http://127.0.0.1:1/x", "http://169.254.169.254/", "http://10.0.0.5/"):
            with self.assertRaises(ai_engine._PrivateAddress):
                h.redirect_request(req, None, 302, "Found", {}, target)

    def test_chat_stream_marks_non_host_callers_restricted(self):
        seen = {}

        def stream(question, mode, history, abort, **kw):
            seen["restricted"] = getattr(ai_engine._fetch_ctx, "restricted", None)
            yield {"type": "done", "analysis": "ok", "model": "m"}

        orig = (clipdrop._chat_stream_events, clipdrop._check_ai_rate, clipdrop._is_online,
                clipdrop._ai_allowed, clipdrop._is_host_request)
        clipdrop._chat_stream_events = stream
        clipdrop._check_ai_rate = lambda: None
        clipdrop._is_online = lambda: True
        clipdrop._ai_allowed = lambda: True
        sid = int(db.create_session("Link test", capture_type="ai")["id"])
        try:
            for host, want in ((True, False), (False, True)):
                clipdrop._is_host_request = lambda h, ip, host=host: host
                with _Server() as s:
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{s.port}/api/chat/stream",
                        data=json.dumps({"session_id": sid, "text": "hi " + self.url}).encode(),
                        headers={"Content-Type": "application/json"})
                    # Non-host callers need the gates open; they only reach the handler if not blocked.
                    try:
                        urllib.request.urlopen(req, timeout=20).read()
                    except urllib.error.HTTPError:
                        if host:
                            raise
                        continue
                self.assertIs(seen.get("restricted"), want)
        finally:
            (clipdrop._chat_stream_events, clipdrop._check_ai_rate, clipdrop._is_online,
             clipdrop._ai_allowed, clipdrop._is_host_request) = orig
            db.delete_session(sid)


if __name__ == "__main__":
    unittest.main()

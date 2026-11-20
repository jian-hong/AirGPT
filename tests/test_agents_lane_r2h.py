"""Agents lane (R2H): the local agent loop offers no generic chat tools, keeps whole answers,
and plain sentences (not Python text) come back for odd ids.

Stand-ins only (mock.patch + a local test server); nothing touches the network.
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_runtime
import agent_store
import ai_engine
import chat_tools
import cortex_client


def _tool_reply():
    return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": "{\"query\": \"x\"}"}}]}}]}


class _Model:
    """Stand-in OpenAI-compatible model: logs bodies, asks for web_search whenever it is offered tools."""

    def __init__(self, answer="All done."):
        self.bodies, self.answer = [], answer

    def post(self, url, headers, body, timeout=12):
        self.bodies.append(json.loads(json.dumps(body)))
        if body.get("tools"):
            return _tool_reply()
        return {"choices": [{"message": {"role": "assistant", "content": self.answer}}]}


def _drive(tools, prompt="please look this up", mode="assist", answer="All done."):
    model, ran = _Model(answer), []
    ag = agent_store.create_agent("R2H agent", tools=tools, kind="custom")
    with mock.patch.object(ai_engine, "_http_post", model.post), \
         mock.patch.object(ai_engine, "_endpoint_reachable", lambda *_a, **_k: True), \
         mock.patch.object(ai_engine, "_provider_hot", lambda *_a, **_k: False), \
         mock.patch.object(ai_engine, "_local_openai_endpoint",
                           lambda env, kind: ("http://127.0.0.1:1/v1/chat/completions", "k", "stub") if kind == "ollama" else None), \
         mock.patch.object(chat_tools, "run_chat_tool", lambda name, args: ran.append(name) or {"ok": True}), \
         mock.patch.object(cortex_client, "engine_agent_loop", lambda *_a, **_k: {"ok": False, "error": "offline"}):
        evs = list(agent_runtime.run_agent_events(ag["id"], prompt, thinking_mode=mode))
    return model, ran, evs


class NoGenericToolsTests(unittest.TestCase):
    def test_fs_write_agent_is_offered_no_tools_and_runs_none(self):
        model, ran, evs = _drive(["fs_write"])
        self.assertTrue(model.bodies)
        self.assertFalse([b for b in model.bodies if "tools" in b])
        self.assertEqual(ran, [])
        self.assertEqual(evs[-1]["type"], "done")

    def test_web_search_agent_and_no_tool_agent_are_offered_no_tools_array(self):
        for tools in (["web_search"], []):
            model, ran, _ = _drive(tools, mode="deep")
            self.assertFalse([b for b in model.bodies if "tools" in b], tools)
            self.assertEqual(ran, [], tools)

    def test_normal_chat_still_gets_its_tools(self):
        self.assertTrue(ai_engine._chat_tool_defs("chat"))
        self.assertEqual(ai_engine._chat_tool_defs("agent"), [])


class LongAnswerTests(unittest.TestCase):
    def test_a_30000_character_answer_is_kept_whole(self):
        _, _, evs = _drive(["fs_write"], answer="a" * 30000)
        done = evs[-1]
        self.assertEqual(done["type"], "done")
        self.assertEqual(len(done["analysis"]), 30000)
        row = next(r for r in agent_store.list_runs(None, 200) if r["id"] == done["run_id"])
        self.assertEqual(row["result_chars"], 30000)
        self.assertGreater(len(row["result"]), 4000)


class OddIdRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import clipdrop
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def _req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request(method, path, body=body, headers={"Host": "127.0.0.1:%d" % self.port})
        r = c.getresponse()
        out = r.read().decode("utf-8", "replace")
        c.close()
        return r.status, out

    def test_odd_ids_never_show_python_text(self):
        big = "9" * 30
        cases = [("GET", p) for p in (
            "/api/agents/abc/runs", "/api/agents/%s/runs" % big, "/api/agents/-4/runs",
            "/api/agents/runs/abc/events", "/api/agents/runs/-4/events", "/api/agents/runs/%s/events" % big,
            "/api/agents/runs/1/events?after=zz", "/api/agents/runs/1/events?after=-2",
            "/api/agents/runs/1/events?after=%s" % big)]
        cases += [("POST", "/api/agents/abc/delete"), ("POST", "/api/agents/%s/delete" % big),
                  ("POST", "/api/agents/abc/run"), ("POST", "/api/workflows/clear"),
                  ("POST", "/api/workflows/run"), ("POST", "/api/workflows/cancel")]
        for method, path in cases:
            status, out = self._req(method, path, body=b"{\"prompt\":\"x\",\"breadth\":\"zz\",\"session_id\":\"q\"}" if method == "POST" else None)
            self.assertIn(status, (200, 400, 404, 422), (path, status, out))
            for bad in ("invalid literal", "int()", "too large", "SQLite", "Traceback", "OverflowError", "ValueError"):
                self.assertNotIn(bad, out, (path, out))

    def test_bad_ids_are_a_400_with_a_sentence(self):
        for path in ("/api/agents/abc/runs", "/api/agents/runs/1/events?after=zz", "/api/agents/runs/abc/events"):
            status, out = self._req("GET", path)
            self.assertEqual(status, 400, path)
            self.assertEqual(json.loads(out)["error"], "That id is not valid.")


if __name__ == "__main__":
    unittest.main()

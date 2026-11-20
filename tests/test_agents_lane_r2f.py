"""Agents lane (R2F): failed runs read as failed, plain refusals, tool list, cut answers, restarts.

Drives agent_runtime with stand-ins (mock.patch); nothing touches the network.
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_runtime
import agent_store
import cortex_client
import workflow_engine

NO_MODEL = "No AI model could be reached. Check your model in Settings."


class _DownModel:
    def _standard_llm(self, *a, **k):
        raise RuntimeError("No text LLM available (ollama(down) -> Groq(no key) -> SEA-LION(no key))")


def _agent(tools, kind="custom"):
    return agent_store.create_agent("R2F agent", tools=tools, kind=kind)


def _run(aid, prompt="tell me something about trains"):
    return list(agent_runtime.run_agent_events(aid, prompt, thinking_mode="assist"))


def _row(rid):
    return next(r for r in agent_store.list_runs(None, 200) if r["id"] == rid)


class ModelDownTests(unittest.TestCase):
    def test_no_model_is_a_failed_run_with_one_plain_sentence(self):
        ag = _agent(["fs_write"])
        with mock.patch.object(agent_runtime, "ai_engine", _DownModel()), mock.patch.object(
            cortex_client, "engine_agent_loop", lambda *_a, **_k: {"ok": False, "error": "offline"}
        ):
            evs = _run(ag["id"])
        self.assertEqual(evs[-1]["type"], "error")
        self.assertEqual(evs[-1]["text"], NO_MODEL)
        self.assertFalse([e for e in evs if e["type"] == "done"])
        row = _row(evs[-1]["run_id"])
        self.assertEqual((row["status"], row["error"]), ("error", NO_MODEL))
        blob = json.dumps(evs)
        self.assertNotIn("ollama", blob)
        self.assertNotIn("Groq", blob)
        card = workflow_engine._agent_card(row, {ag["id"]: ag})
        self.assertEqual(card["status"], "error")
        self.assertEqual(card["runner"], "")


class RefusalWordsTests(unittest.TestCase):
    def test_research_agent_with_cortex_down_gets_plain_words(self):
        ag = _agent(["web_search"], kind="research")
        raw = "http://127.0.0.1:12255 has no /api/engine/specs. Point CORTEX_API_URL at CortexOS.api.main."
        with mock.patch.object(
            cortex_client, "engine_agent_loop", lambda *_a, **_k: {"ok": False, "reason": "wrong_surface", "error": raw}
        ):
            evs = _run(ag["id"], "research python")
        text = evs[-1]["text"]
        self.assertEqual(evs[-1]["type"], "error")
        self.assertIn("not running", text)
        for bad in ("http", "CORTEX_API_URL", "/api/engine"):
            self.assertNotIn(bad, text)
        row = _row(evs[-1]["run_id"])
        self.assertEqual(row["error"], text)
        card = workflow_engine._agent_card(row, {ag["id"]: ag})
        self.assertEqual(card["runner"], "")

    def test_offline_words(self):
        w = agent_runtime._plain_engine_why({"ok": False, "error": "Cortex engine offline"})
        self.assertEqual(w, "Cortex is not running, so this research agent cannot run. Start it from Apps.")


class ToolListTests(unittest.TestCase):
    def _sent(self, tools):
        ag = _agent(tools)
        seen = {}

        def fake(prompt, **kw):
            seen.update(kw)
            return {"ok": True, "content": "hi", "telemetry": {"tools": []}}

        with mock.patch.object(cortex_client, "engine_agent_loop", fake):
            evs = _run(ag["id"])
        return seen, evs

    def test_fs_write_agent_sends_only_its_own_list(self):
        seen, evs = self._sent(["fs_write"])
        self.assertEqual(seen["tools"], ["fs_write"])
        done = [e for e in evs if e["type"] == "done"][0]
        self.assertEqual(done["tools_sent"], ["fs_write"])

    def test_agent_with_no_tools_never_sends_the_web(self):
        seen, _ = self._sent(["not_a_tool"])
        self.assertTrue(seen["tools"])
        self.assertNotIn("web_search", seen["tools"])


class CutAnswerTests(unittest.TestCase):
    def test_true_length_is_kept(self):
        ag = _agent(["fs_write"])
        rid = agent_store.create_run(ag["id"], "p")["id"]
        agent_store.finish_run(rid, status="done", result="x" * 31549)
        row = _row(rid)
        self.assertEqual(len(row["result"]), 20000)
        self.assertEqual(row["result_chars"], 31549)
        card = workflow_engine._agent_card(row, {ag["id"]: ag})
        self.assertEqual(card["phases"][0]["agents"][0]["excerpt_chars"], 31549)


class RestartTests(unittest.TestCase):
    def test_open_row_with_no_live_run_is_closed_and_a_live_one_is_not(self):
        ag = _agent(["fs_write"])
        dead = agent_store.create_run(ag["id"], "p")["id"]
        live = agent_store.create_run(ag["id"], "p")["id"]
        agent_runtime._LIVE.add(live)
        try:
            time.sleep(0.05)
            agent_runtime.close_interrupted(0)
        finally:
            agent_runtime._LIVE.discard(live)
        self.assertEqual((_row(dead)["status"], _row(dead)["error"]), ("error", "Interrupted when the app restarted"))
        self.assertEqual(_row(live)["status"], "running")
        agent_store.finish_run(live, status="done", result="ok")


if __name__ == "__main__":
    unittest.main()

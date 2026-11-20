"""Agent UI lane: privacy of the local run, Stop, runs that outlive the page, empty answers.

Each test drives agent_runtime with a stand-in model and stand-in Cortex (mock.patch);
nothing here touches the network.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_runtime
import agent_store
import agent_tools
import cortex_client
import workflow_engine

CORTEX_DOWN = lambda *_a, **_k: {"ok": False, "error": "Cortex engine offline"}  # noqa: E731


class _Model:
    """Stand-in for ai_engine: replies from a script, one entry per call."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def _standard_llm(self, user, sys_, max_tokens=600, task=""):
        self.calls += 1
        r = self.replies.pop(0) if self.replies else "All done."
        return r, "stub-model"


def _agent(tools):
    return agent_store.create_agent("Lane test agent", tools=tools)


def _events(agent_id, prompt, **kw):
    return list(agent_runtime.run_agent_events(agent_id, prompt, **kw))


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.searches = []

        def spy(query, *, run_id=0, agent_id=0):
            self.searches.append(query)
            return {"ok": True, "snippets": [{"excerpt": "x"}]}

        self.p1 = mock.patch.dict(agent_tools.TOOLS, {"web_search": spy})
        self.p2 = mock.patch.object(cortex_client, "engine_agent_loop", CORTEX_DOWN)
        self.p1.start()
        self.p2.start()

    def tearDown(self):
        self.p1.stop()
        self.p2.stop()

    def test_agent_without_web_search_never_searches(self):
        ag = _agent(["fs_write"])
        prompt = "Write my private plan about the merger with Acme Corp into a file " * 3
        with mock.patch.object(agent_runtime, "ai_engine", _Model(["Done."])):
            _events(ag["id"], prompt, thinking_mode="deep", require_approval=True)
        self.assertEqual(self.searches, [], "a search ran for an agent that was not given web_search")

    def test_agent_with_no_tools_does_not_get_web_search(self):
        ag = _agent(["fs_write"])
        bare = dict(ag, tools=[])  # a row with no tools at all (old data)
        with mock.patch.object(agent_store, "get_agent", lambda _i: bare):
            with mock.patch.object(agent_runtime, "ai_engine", _Model(["Done."])):
                _events(ag["id"], "Tell me about my confidential merger plan with Acme", thinking_mode="deep", require_approval=True)
        self.assertEqual(self.searches, [])

    def test_deep_search_uses_only_the_users_own_words_and_once(self):
        ag = _agent(["web_search"])
        wrapper = "Cortex create turn.\nUser: cheap flights to Lisbon\nPriority order (mandatory): ..."
        with mock.patch.object(agent_runtime, "ai_engine", _Model(["Done."])):
            _events(ag["id"], wrapper, thinking_mode="deep", require_approval=True, task="cheap flights to Lisbon")
        self.assertEqual(self.searches, ["cheap flights to Lisbon"])

    def test_failed_search_is_not_retried_with_extra_words(self):
        def failing(query, *, run_id=0, agent_id=0):
            self.searches.append(query)
            return {"ok": False, "error": "offline"}

        ag = _agent(["web_search"])
        with mock.patch.dict(agent_tools.TOOLS, {"web_search": failing}):
            with mock.patch.object(agent_runtime, "ai_engine", _Model(["Done."])):
                _events(ag["id"], "cheap flights to Lisbon in spring please", thinking_mode="deep", require_approval=True)
        self.assertEqual(len(self.searches), 1)


class CortexAnswerTests(unittest.TestCase):
    def test_empty_cortex_answer_is_not_a_success(self):
        ag = _agent(["fs_write"])
        empty = lambda *_a, **_k: {"ok": True, "content": "   ", "stop_reason": "quality", "telemetry": {"tools": []}}  # noqa: E731
        with mock.patch.object(cortex_client, "engine_agent_loop", empty):
            with mock.patch.object(agent_runtime, "ai_engine", _Model(["Local answer."])):
                evs = _events(ag["id"], "do the thing", thinking_mode="assist")
        texts = " ".join(str(e.get("text") or "") for e in evs)
        self.assertIn("empty", texts.lower())
        done = [e for e in evs if e.get("type") == "done"][0]
        self.assertEqual(done["analysis"], "Local answer.")
        self.assertNotEqual(done.get("runner"), "agent_task")

    def test_done_event_names_runner_and_model(self):
        ag = _agent(["fs_write"])
        with mock.patch.object(cortex_client, "engine_agent_loop", CORTEX_DOWN):
            with mock.patch.object(agent_runtime, "ai_engine", _Model(["Local answer."])):
                evs = _events(ag["id"], "do the thing", thinking_mode="assist")
        done = [e for e in evs if e.get("type") == "done"][0]
        self.assertEqual(done.get("runner"), "local")
        self.assertEqual(done.get("model"), "stub-model")

    def test_run_keeps_the_users_own_text_not_the_wrapper(self):
        ag = _agent(["fs_write"])
        with mock.patch.object(cortex_client, "engine_agent_loop", CORTEX_DOWN):
            with mock.patch.object(agent_runtime, "ai_engine", _Model(["ok"])):
                evs = _events(ag["id"], "WRAPPER with rules", thinking_mode="assist", task="my own words")
        rid = evs[0]["run_id"]
        row = [r for r in agent_store.list_runs(None, 50) if r["id"] == rid][0]
        self.assertEqual(row["prompt"], "my own words")


class StopTests(unittest.TestCase):
    def test_stop_between_steps_ends_the_run_as_stopped(self):
        ag = _agent(["fs_read"])
        call = json.dumps({"tool": "fs_read", "params": {"path": "x"}})
        model = _Model([call, call, call, "never reached"])
        holder = {}

        def tool(**_k):
            if holder.get("rid"):
                agent_store.cancel_run(holder["rid"])
            return {"ok": True}

        with mock.patch.object(cortex_client, "engine_agent_loop", CORTEX_DOWN):
            with mock.patch.dict(agent_tools.TOOLS, {"fs_read": tool}):
                with mock.patch.object(agent_runtime, "ai_engine", model):
                    gen = agent_runtime.run_agent_events(ag["id"], "read things", thinking_mode="assist", max_steps=6)
                    evs = []
                    for ev in gen:
                        evs.append(ev)
                        if ev.get("run_id"):
                            holder["rid"] = ev["run_id"]
        types = [e.get("type") for e in evs]
        self.assertIn("stopped", types)
        self.assertNotIn("done", types)
        self.assertLessEqual(model.calls, 2)
        row = [r for r in agent_store.list_runs(None, 50) if r["id"] == holder["rid"]][0]
        self.assertEqual(row["status"], "cancelled")

    def test_stop_after_the_result_does_not_change_a_finished_run(self):
        ag = _agent(["fs_write"])
        with mock.patch.object(cortex_client, "engine_agent_loop", CORTEX_DOWN):
            with mock.patch.object(agent_runtime, "ai_engine", _Model(["Answer."])):
                evs = _events(ag["id"], "quick", thinking_mode="assist")
        rid = evs[0]["run_id"]
        self.assertFalse(workflow_engine.cancel(f"agent_run_{rid}").get("ok"))
        row = [r for r in agent_store.list_runs(None, 50) if r["id"] == rid][0]
        self.assertEqual(row["status"], "done")

    def test_a_stopped_run_is_not_overwritten_by_a_late_result(self):
        rid = agent_store.create_run(_agent([])["id"], "x")["id"]
        agent_store.cancel_run(rid)
        agent_store.finish_run(rid, status="done", result="late")
        row = [r for r in agent_store.list_runs(None, 50) if r["id"] == rid][0]
        self.assertEqual(row["status"], "cancelled")

    def test_stop_while_cortex_is_busy_wins_over_its_late_answer(self):
        ag = _agent(["fs_write"])
        holder = {}

        def slow(*_a, **_k):
            agent_store.cancel_run(holder["rid"])  # the user pressed Stop while Cortex worked
            return {"ok": True, "content": "late answer", "stop_reason": "quality", "telemetry": {"tools": []}}

        with mock.patch.object(cortex_client, "engine_agent_loop", slow):
            gen = agent_runtime.run_agent_events(ag["id"], "slow job", thinking_mode="assist")
            evs = []
            for ev in gen:
                evs.append(ev)
                if ev.get("run_id"):
                    holder["rid"] = ev["run_id"]
        types = [e.get("type") for e in evs]
        self.assertIn("stopped", types)
        self.assertNotIn("done", types)
        row = [r for r in agent_store.list_runs(None, 50) if r["id"] == holder["rid"]][0]
        self.assertEqual(row["status"], "cancelled")


class OutlivePageTests(unittest.TestCase):
    def test_background_run_finishes_after_the_reader_leaves(self):
        ag = _agent(["fs_write"])

        def slow(*_a, **_k):
            time.sleep(0.6)
            return {"ok": True, "content": "finished anyway", "stop_reason": "quality", "telemetry": {"tools": []}}

        with mock.patch.object(cortex_client, "engine_agent_loop", slow):
            rid = agent_runtime.start_background_run(ag["id"], "wrapper", task="my text", thinking_mode="assist")
            it = agent_runtime.tail_run(rid)
            first = next(it)
            self.assertEqual(first.get("run_id"), rid)
            it.close()  # the page went away
            deadline = time.time() + 5
            while time.time() < deadline:
                row = [r for r in agent_store.list_runs(None, 50) if r["id"] == rid][0]
                if row["status"] != "running":
                    break
                time.sleep(0.1)
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["result"], "finished anyway")
        self.assertEqual(row["prompt"], "my text")

    def test_a_late_reader_gets_the_whole_run(self):
        ag = _agent(["fs_write"])
        with mock.patch.object(cortex_client, "engine_agent_loop", lambda *_a, **_k: {"ok": True, "content": "hello", "telemetry": {"tools": []}}):
            rid = agent_runtime.start_background_run(ag["id"], "p", thinking_mode="assist")
            time.sleep(0.5)
        evs = list(agent_runtime.tail_run(rid))
        self.assertEqual([e for e in evs if e.get("type") == "done"][0]["analysis"], "hello")

    def test_tail_of_an_unknown_run_is_none(self):
        self.assertIsNone(agent_runtime.tail_run(999999))


class CardTests(unittest.TestCase):
    def _run(self, **kw):
        base = {"id": 3, "agent_id": 1, "status": "done", "prompt": "mine", "result": "ok", "error": "",
                "created_at": 1.0, "finished_at": 4.0, "steps": "[]"}
        base.update(kw)
        return workflow_engine._agent_card(base, {1: {"name": "A"}})

    def test_card_counts_real_tools_and_names_the_runner(self):
        steps = json.dumps([{"tool": "think", "ok": True, "summary": "Cortex quality loop…"},
                            {"tool": "web_search", "ok": True, "summary": "5 results", "ms": 9}])
        card = self._run(steps=steps)
        self.assertEqual(card["totals"]["tools_real"], 1)
        self.assertEqual(card["runner"], "Cortex")
        self.assertEqual(self._run()["runner"], "local model")

    def test_card_shows_the_users_text_not_the_wrapper_and_flags_a_cut_answer(self):
        wrapped = "Cortex create turn for \u201cX\u201d.\nUser: my own words\n\nPriority order (mandatory): ..."
        card = self._run(prompt=wrapped, result="x" * 9000)
        self.assertEqual(card["description"], "my own words")
        ag = card["phases"][0]["agents"][0]
        self.assertEqual(len(ag["excerpt"]), 8000)
        self.assertEqual(ag["excerpt_chars"], 9000)


if __name__ == "__main__":
    unittest.main()

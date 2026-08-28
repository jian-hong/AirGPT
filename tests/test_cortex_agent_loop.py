"""AirGPT consumes Cortex AGENT_TASK quality loop (LOOP-02 / F20b)."""

from __future__ import annotations

import unittest
from unittest import mock

import agent_runtime
import agent_store
import cortex_client


class CortexAgentLoopTests(unittest.TestCase):
    def test_engine_agent_loop_posts_agent_preset(self):
        seen = {}

        def fake_post(path, body, timeout=1.5, **_k):
            seen["path"] = path
            seen["body"] = body
            seen["timeout"] = timeout
            return {
                "ok": True,
                "runner": "agent_task",
                "stop_reason": "quality",
                "quality_passed": True,
                "content": "hello",
                "telemetry": {"tools": [], "steps": 1},
            }

        with mock.patch.object(cortex_client, "ensure_engine", lambda **_k: {"ok": True}):
            with mock.patch.object(
                cortex_client,
                "health",
                lambda: {"ok": True, "url": "http://127.0.0.1:8011", "raw": {"status": "ok", "pack": "dms"}},
            ):
                with mock.patch.object(
                    cortex_client, "_get", lambda path, timeout=1.5, **_k: {"ok": True, "config": {}} if path.endswith("/specs") else None
                ):
                    with mock.patch.object(cortex_client, "_post", fake_post):
                        out = cortex_client.engine_agent_loop("hi", session_id="s1", max_steps=4)
        self.assertTrue(out["ok"])
        self.assertEqual(seen["path"], "/api/engine/run")
        self.assertEqual(seen["body"]["architecture_preset"], "agent")
        self.assertGreaterEqual(seen["timeout"], 60)

    def test_engine_agent_loop_names_constructor_surface(self):
        with mock.patch.object(cortex_client, "ensure_engine", lambda **_k: {"ok": True}):
            with mock.patch.object(
                cortex_client,
                "health",
                lambda: {
                    "ok": True,
                    "url": "http://127.0.0.1:8010",
                    "raw": {"status": "ok", "pack": "dms", "surface": "constructor"},
                },
            ):
                with mock.patch.object(cortex_client, "_get", lambda *a, **k: None):
                    out = cortex_client.engine_agent_loop("hi")
        self.assertFalse(out["ok"])
        self.assertEqual(out.get("reason"), "wrong_surface")
        self.assertIn("Constructor", out.get("error") or "")

    def test_engine_agent_loop_falls_back_off_constructor(self):
        seen = {}

        def fake_get(path, timeout=1.5, *, base=None, key=None):
            if base and ":8011" in str(base) and str(path).endswith("/specs"):
                return {"engine": "Netie Engine", "backends": ["ollama"]}
            return None

        def fake_post(path, body, timeout=1.5, *, base=None, key=None):
            seen["path"] = path
            seen["base"] = base
            seen["body"] = body
            return {
                "ok": True,
                "runner": "agent_task",
                "stop_reason": "quality",
                "content": "from-8011",
            }

        with mock.patch.object(cortex_client, "ensure_engine", lambda **_k: {"ok": True}):
            with mock.patch.object(
                cortex_client,
                "health",
                lambda: {
                    "ok": True,
                    "url": "http://127.0.0.1:8010",
                    "raw": {"status": "ok", "pack": "dms", "surface": "constructor"},
                },
            ):
                with mock.patch.object(cortex_client, "_get", fake_get):
                    with mock.patch.object(cortex_client, "_post", fake_post):
                        out = cortex_client.engine_agent_loop("hi")
        self.assertTrue(out["ok"])
        self.assertEqual(seen["path"], "/api/engine/run")
        self.assertIn("8011", seen["base"] or "")
        self.assertEqual(out["content"], "from-8011")

    def test_run_agent_events_uses_cortex_quality_stop(self):
        def fake_loop(prompt, **_k):
            return {
                "ok": True,
                "stop_reason": "quality",
                "quality_passed": True,
                "content": "done from cortex",
                "telemetry": {
                    "tools": [{"tool": "web_search", "ok": True, "ms": 9, "summary": "2 result(s)"}],
                    "steps": 2,
                },
            }

        with mock.patch.object(
            agent_store,
            "get_agent",
            lambda _aid: {"id": 1, "name": "t", "tools": ["web_search"], "config": {}},
        ):
            with mock.patch.object(agent_store, "create_run", lambda *_a, **_k: {"id": 9}):
                with mock.patch.object(agent_store, "finish_run", lambda *_a, **_k: None):
                    with mock.patch.object(cortex_client, "engine_agent_loop", fake_loop):
                        evs = list(
                            agent_runtime.run_agent_events(1, "what is X", thinking_mode="assist")
                        )
        types = [e.get("type") for e in evs]
        self.assertIn("tool", types)
        done = [e for e in evs if e.get("type") == "done"][0]
        self.assertEqual(done.get("stop_reason"), "quality")
        self.assertEqual(done.get("runner"), "agent_task")
        self.assertEqual(done.get("analysis"), "done from cortex")

    def test_run_agent_events_names_skip_when_cortex_down(self):
        with mock.patch.object(
            agent_store,
            "get_agent",
            lambda _aid: {"id": 1, "name": "t", "tools": ["web_search"], "config": {}},
        ):
            with mock.patch.object(agent_store, "create_run", lambda *_a, **_k: {"id": 9}):
                with mock.patch.object(agent_store, "finish_run", lambda *_a, **_k: None):
                    with mock.patch.object(
                        cortex_client,
                        "engine_agent_loop",
                        lambda *_a, **_k: {"ok": False, "error": "Cortex engine offline"},
                    ):
                        with mock.patch.object(agent_runtime, "ai_engine", None):
                            evs = list(
                                agent_runtime.run_agent_events(
                                    1, "what is X", thinking_mode="assist", max_steps=1
                                )
                            )
        texts = [e.get("text") or "" for e in evs]
        self.assertTrue(any("Quality loop skipped" in t for t in texts))
        self.assertTrue(any("offline" in t.lower() for t in texts))

    def test_chat_web_search_uses_cortex_quality_loop(self):
        import threading

        import clipdrop

        def fake_loop(*_a, **_k):
            return {
                "ok": True,
                "content": "OpenManus is on GitHub.",
                "stop_reason": "quality",
                "quality_passed": True,
                "telemetry": {"tools": [{"tool": "web_search", "ok": True, "summary": "2 result(s)"}]},
            }

        with mock.patch.object(clipdrop, "_ai_lockdown_block", lambda: None):
            with mock.patch.object(cortex_client, "engine_agent_loop", fake_loop):
                evs = list(
                    clipdrop._chat_stream_events(
                        "what is OpenManus",
                        "general",
                        [],
                        threading.Event(),
                        session_id=1,
                        web_search=True,
                    )
                )
        done = [e for e in evs if e.get("type") == "done"][0]
        self.assertEqual(done.get("runner"), "agent_task")
        self.assertEqual(done.get("stop_reason"), "quality")
        self.assertIn("OpenManus", done.get("analysis") or "")


if __name__ == "__main__":
    unittest.main()

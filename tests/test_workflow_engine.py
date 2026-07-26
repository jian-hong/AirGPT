"""AirGPT workflow_engine is a Cortex proxy — no in-process fan-out."""

from __future__ import annotations

from unittest.mock import patch

import workflow_engine


def test_list_workflows_proxies():
    with patch(
        "cortex_client.workflows_list",
        return_value={
            "ok": True,
            "workflows": [{"id": "smoothness_audit", "name": "Smoothness audit"}],
        },
    ):
        wfs = workflow_engine.list_workflows()
    assert wfs[0]["id"] == "smoothness_audit"


def test_list_workflows_raises_when_down():
    with patch(
        "cortex_client.workflows_list",
        return_value={"ok": False, "error": "offline"},
    ):
        try:
            workflow_engine.list_workflows()
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "offline" in str(e).lower() or "Cortex" in str(e)


def test_start_deep_research_alias():
    captured = {}

    def fake_run(body):
        captured.update(body)
        return {"ok": True, "run_id": "wf_x", "task_id": "wf_x"}

    with patch("cortex_client.workflows_run", side_effect=fake_run):
        with patch("cortex_client.workflows_push_hardware", return_value={"ok": True}):
            with patch.object(workflow_engine, "_push_hw"):
                out = workflow_engine.start("", goal="quantum foam")
    assert out["ok"] is True
    assert captured.get("template_id") == "deep_research"
    assert captured.get("goal") == "quantum foam"


def test_snapshot_soft_fail():
    with patch(
        "cortex_client.workflows_snapshot",
        return_value={"ok": False, "error": "down", "running": [], "finished": []},
    ):
        with patch("workflow_engine._local_agent_tasks", return_value=([], [])):
            snap = workflow_engine.snapshot()
    assert snap.get("running") == []
    # Degraded but still ok so the panel can show local agent history.
    assert snap.get("ok") is True
    assert snap.get("degraded") is True or snap.get("error")


def test_recognize_proxy():
    with patch(
        "cortex_client.workflows_recognize",
        return_value={
            "ok": True,
            "should_run": True,
            "template_id": "deep_research",
            "explicit": True,
        },
    ):
        rec = workflow_engine.recognize("invoke subagent to research X")
    assert rec["should_run"] is True
    assert rec["template_id"] == "deep_research"


def test_est_tokens_still_available():
    assert workflow_engine.est_tokens("abcd") == 1

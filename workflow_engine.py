"""Background workflows — thin proxy to Cortex (SoT on :8010).

Phased parallel fan-out, durable telemetry, and preset prompts live in
``D:\\Cortex`` (``workflow_runner`` / ``workflow_store``). AirGPT keeps the
same Python API the clipdrop routes and Background tasks panel already call,
so this file is only the bridge + soft-fail when the engine is down.

Also folds local Cortex orchestrator agent runs into the panel snapshot so
normal agentic chats (tool loops, subagents, skills) are auditable alongside
preset workflows.
"""
from __future__ import annotations

import time
from typing import Any

import cortex_client


def _push_hw() -> None:
    try:
        import marketplace

        hw = marketplace.effective_hardware()
        if isinstance(hw, dict) and hw:
            cortex_client.workflows_push_hardware(hw)
    except Exception:
        pass


def list_workflows() -> list[dict]:
    data = cortex_client.workflows_list()
    if not data.get("ok"):
        raise RuntimeError(data.get("error") or "Cortex engine offline")
    return list(data.get("workflows") or [])


def _tool_detail(run: dict) -> list[dict]:
    raw = run.get("steps") or "[]"
    parsed: list = []
    if isinstance(raw, str):
        try:
            import json

            maybe = json.loads(raw)
            if isinstance(maybe, list):
                parsed = maybe
        except Exception:
            parsed = []
    elif isinstance(raw, list):
        parsed = raw
    out: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "tool": str(item.get("tool") or item.get("name") or "?")[:80],
                "ok": bool(item.get("ok", True)),
                "ms": int(item.get("ms") or 0),
                "summary": str(item.get("summary") or "")[:240],
            }
        )
    return out


def _agent_card(run: dict, agents_by_id: dict[int, dict]) -> dict:
    """Shape one agent_store run for the Background tasks panel."""
    aid = int(run.get("agent_id") or 0)
    agent = agents_by_id.get(aid) or {}
    name = (agent.get("name") or f"Agent #{aid}")[:80]
    prompt = (run.get("prompt") or "")[:400]
    st = (run.get("status") or "queued").lower()
    if st in ("done", "completed", "finished"):
        panel_st = "done"
    elif st in ("error", "failed"):
        panel_st = "error"
    elif st in ("cancelled", "canceled", "stopped"):
        panel_st = "cancelled"
    elif st in ("running", "claimed", "active"):
        panel_st = "running"
    else:
        panel_st = "queued"
    started = float(run.get("created_at") or 0)
    ended = float(run.get("finished_at") or 0)
    elapsed = max(0.0, (ended or time.time()) - started) if started else 0.0
    meta: dict = {}
    raw_result = run.get("result") or ""
    if isinstance(raw_result, str) and raw_result.startswith("{"):
        try:
            import json

            parsed = json.loads(raw_result)
            if isinstance(parsed, dict) and ("is_subagent" in parsed or "skill_pack" in parsed):
                meta = parsed
        except Exception:
            meta = {}
    is_sub = bool(run.get("is_subagent") or meta.get("is_subagent")) or "subagent" in name.lower()
    kind = "Subagent" if is_sub else "Agent"
    # Prefer finished analysis over queued meta JSON for excerpt.
    excerpt = ""
    if panel_st in ("done", "error", "cancelled"):
        excerpt = (run.get("error") or raw_result or "")[:1200]
        if meta and excerpt.startswith("{"):
            excerpt = (run.get("error") or "")[:1200]
    else:
        excerpt = prompt[:400]
    tools = _tool_detail(run)
    names = [t["tool"] for t in tools if t.get("tool")]
    return {
        "id": f"agent_run_{run.get('id')}",
        "name": name,
        "kind": kind,
        "description": prompt or (agent.get("config") or ""),
        "status": panel_st,
        "elapsed": round(elapsed, 1),
        "tokens_estimated": True,
        "source": "cortex_agent",
        "totals": {
            "agents": 1,
            "agents_done": 1 if panel_st in ("done", "error", "cancelled") else 0,
            "tokens": 0,
            "tools": len(tools),
            "phases_done": 1 if panel_st in ("done", "error", "cancelled") else 0,
            "phases_total": 1,
            "cost_myr": 0,
        },
        "phases": [
            {
                "id": "run",
                "name": "Run",
                "detail": "Cortex agent tool loop",
                "status": panel_st if panel_st != "queued" else "pending",
                "agents": [
                    {
                        "id": name,
                        "purpose": prompt[:200] or "Agent run",
                        "status": panel_st if panel_st != "queued" else "pending",
                        "tokens": 0,
                        "tool_count": len(tools),
                        "tools": names,
                        "tool_detail": tools,
                        "excerpt": excerpt,
                        "error": (run.get("error") or "")[:500],
                        "elapsed": round(elapsed, 1),
                    }
                ],
            }
        ],
        "error": (run.get("error") or "")[:500],
        "started_at": started or None,
        "ended_at": ended or None,
    }


def _local_agent_tasks() -> tuple[list[dict], list[dict]]:
    """Pending + recent finished agent runs for the panel audit trail."""
    try:
        import agent_store
        import cortex_orchestrator

        agent_store.init()
        agents = {int(a["id"]): a for a in agent_store.list_agents()}
        pending = cortex_orchestrator.list_pending() or []
        recent = agent_store.list_runs(None, 25)
    except Exception:
        return [], []

    running: list[dict] = []
    seen: set[str] = set()
    for run in pending:
        card = _agent_card(run, agents)
        running.append(card)
        seen.add(card["id"])

    finished: list[dict] = []
    for run in recent:
        st = (run.get("status") or "").lower()
        if st in ("queued", "pending", "running", "claimed"):
            card = _agent_card(run, agents)
            if card["id"] not in seen and card["status"] in ("running", "queued"):
                running.append(card)
                seen.add(card["id"])
            continue
        card = _agent_card(run, agents)
        if card["id"] in seen:
            continue
        finished.append(card)
        if len(finished) >= 20:
            break
    return running, finished


def snapshot() -> dict:
    data = cortex_client.workflows_snapshot()
    if not data.get("ok") and not data.get("running") and not data.get("finished"):
        # Cortex down — still show local agent runs so the panel stays useful.
        local_run, local_fin = _local_agent_tasks()
        return {
            "ok": True,
            "error": data.get("error") or "Cortex engine offline",
            "hint": data.get("hint"),
            "running": local_run,
            "finished": local_fin,
            "degraded": True,
        }
    data.setdefault("ok", True)
    data.setdefault("running", [])
    data.setdefault("finished", [])
    local_run, local_fin = _local_agent_tasks()
    # Workflows first, then local agent cards (dedupe by id).
    ids = {t.get("id") for t in data["running"]}
    for t in local_run:
        if t.get("id") not in ids:
            data["running"].append(t)
    ids_f = {t.get("id") for t in data["finished"]}
    for t in local_fin:
        if t.get("id") not in ids_f:
            data["finished"].append(t)
    return data


def get_task(task_id: str) -> dict | None:
    if str(task_id).startswith("agent_run_"):
        try:
            import agent_store

            rid = int(str(task_id).rsplit("_", 1)[-1])
            runs = agent_store.list_runs(None, 80)
            agents = {int(a["id"]): a for a in agent_store.list_agents()}
            for run in runs:
                if int(run.get("id") or 0) == rid:
                    return _agent_card(run, agents)
        except Exception:
            return None
        return None
    data = cortex_client.workflows_get(task_id)
    if not data.get("ok"):
        return None
    return data.get("task")


def cancel(task_id: str) -> dict:
    if str(task_id).startswith("agent_run_"):
        return {"ok": False, "error": "cancel agent runs from Cortex Pending"}
    return cortex_client.workflows_cancel(task_id)


def clear_finished() -> dict:
    return cortex_client.workflows_clear()


def recognize(prompt: str) -> dict:
    return cortex_client.workflows_recognize(prompt)


def start(
    workflow_id: str = "",
    *,
    goal: str = "",
    breadth: int = 3,
    workflow: dict | None = None,
) -> dict:
    """Start a Cortex workflow. ``workflow`` is ignored (presets live in Cortex)."""
    _push_hw()
    body: dict[str, Any] = {
        "workflow_id": workflow_id or "",
        "template_id": workflow_id or "",
        "goal": goal or "",
        "topic": goal or "",
        "target": goal or "",
        "breadth": int(breadth or 3),
        "origin": "airgpt",
    }
    # Alias: empty id + goal → deep research (panel research() hook).
    if not workflow_id and goal:
        body["template_id"] = "deep_research"
        body["workflow_id"] = "deep_research"
    return cortex_client.workflows_run(body)


# Kept for tests / callers that still import the estimator name.
def est_tokens(*chunks: str) -> int:
    total = sum(len(c or "") for c in chunks)
    return int(total / 4)

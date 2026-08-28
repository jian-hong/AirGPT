"""Retired host clock for routines already on disk (SHELL-02, issue #60).

Cortex on :8010 today is pack=dms: /health is ok, /api/routines is 404. This module
was the fallback for that, but an AirGPT-owned cron is out of scope for F18 —
Cortex owns the scheduler — and the fallback displaced the honest refusal it was
supposed to complement. `cortex_client.routines_create` no longer calls `create()`;
a Cortex that cannot schedule now says so at the control.

What remains is the store for rows written before that decision. They stay listed,
runnable, pausable and deletable, always stamped `scheduler: "airgpt_host"`, so an
existing chip is neither silently dropped nor mistaken for a Cortex routine. Every
fire reports what actually happened: a fire that queued nothing is `ok: False`.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any

from config import DATA_DIR

STORE = DATA_DIR / "host_routines.json"
_lock = threading.Lock()


def interval_from_goal(goal: str) -> int:
    g = (goal or "").lower()
    if "week" in g or "monday" in g:
        return 7 * 86400
    if "hour" in g:
        return 3600
    if "daily" in g or "every day" in g or "morning" in g or "tonight" in g:
        return 86400
    return 86400


def _load() -> list[dict[str, Any]]:
    if not STORE.is_file():
        return []
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        rows = data.get("routines") if isinstance(data, dict) else data
        return list(rows) if isinstance(rows, list) else []
    except Exception:
        return []


def _save(rows: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps({"routines": rows}, indent=2), encoding="utf-8")


def create(goal: str, *, agent_id: int = 0, **_extra: Any) -> dict[str, Any]:
    """Legacy writer. Not on the Cortex create path — see the module docstring."""
    now = time.time()
    interval = interval_from_goal(goal)
    rid = "hr-" + uuid.uuid4().hex[:8]
    row = {
        "id": rid,
        "goal": (goal or "")[:600],
        "agent_id": int(agent_id or 0),
        "interval_seconds": interval,
        "next_run_at": now + interval,
        "last_run_at": 0.0,
        "last_status": "scheduled",
        "paused": False,
        "scheduler": "airgpt_host",
        "legacy": True,
        "created_at": now,
    }
    with _lock:
        rows = _load()
        rows.append(row)
        _save(rows)
    out = {
        "ok": True,
        "routine_id": rid,
        "id": rid,
        "routine": row,
        "interval_seconds": interval,
        "next_run_at": row["next_run_at"],
        "scheduler": "airgpt_host",
        "legacy": True,
        "hint": "Host clock, not a Cortex routine. Cortex owns the F18 scheduler.",
    }
    if not row["agent_id"]:
        # agent_id 0 means _fire has nothing to queue: the row would advance its
        # clock forever and run nothing. Say it here, not only in last_status.
        out["warning"] = "no agent bound (agent_id=0) — this routine will fire and run nothing"
    return out


def _row_problem(row: dict[str, Any]) -> str:
    """Non-empty when this row's last fire did not actually start work."""
    status = str(row.get("last_status") or "")
    if status in ("", "scheduled", "queued", "running", "done"):
        return ""
    if status == "fired_no_agent":
        return "fired but no agent is bound (agent_id=0) — nothing ran"
    if status == "deferred_idle":
        return "due, but thinking mode is idle so the queue is not draining"
    return str(row.get("last_error") or status)


def list_routines() -> dict[str, Any]:
    with _lock:
        rows = _load()
    unhealthy = [
        {"id": r.get("id"), "goal": r.get("goal"), "last_status": r.get("last_status"), "why": why}
        for r in rows
        if (why := _row_problem(r))
    ]
    return {
        "ok": True,
        "routines": rows,
        "scheduler": "airgpt_host",
        "legacy": True,
        "unhealthy": unhealthy,
    }


def pause(rid: str, reason: str = "user") -> dict[str, Any]:
    return _set_paused(rid, True, reason)


def resume(rid: str) -> dict[str, Any]:
    return _set_paused(rid, False, "")


def _set_paused(rid: str, paused: bool, reason: str) -> dict[str, Any]:
    with _lock:
        rows = _load()
        for r in rows:
            if r.get("id") == rid:
                r["paused"] = paused
                r["pause_reason"] = reason
                _save(rows)
                return {"ok": True, "routine": r}
    return {"ok": False, "error": "routine not found"}


def delete(rid: str) -> dict[str, Any]:
    with _lock:
        rows = _load()
        nxt = [r for r in rows if r.get("id") != rid]
        if len(nxt) == len(rows):
            return {"ok": False, "error": "routine not found"}
        _save(nxt)
    return {"ok": True}


def run_now(rid: str, *, now: float | None = None) -> dict[str, Any]:
    ts = float(now if now is not None else time.time())
    with _lock:
        rows = _load()
        row = next((r for r in rows if r.get("id") == rid), None)
        if not row:
            return {"ok": False, "error": "routine not found"}
        fired = _fire(row, ts)
        _save(rows)
    return fired


def tick(*, now: float | None = None, drains: bool = True) -> dict[str, Any]:
    """Fire everything due. `drains=False` means the orchestrator queue is parked.

    Queueing into a parked worker (thinking mode "idle") looked identical to a real
    run: next_run_at advanced, last_status said "queued", and nothing ever picked it
    up. A due row is now left due and marked `deferred_idle` instead, so it fires for
    real the moment the mode leaves idle.
    """
    ts = float(now if now is not None else time.time())
    fired: list[str] = []
    deferred: list[str] = []
    with _lock:
        rows = _load()
        for row in rows:
            if row.get("paused"):
                continue
            nxt = float(row.get("next_run_at") or 0)
            if nxt and nxt > ts:
                continue
            if not drains:
                row["last_status"] = "deferred_idle"
                row["last_error"] = (
                    "due, but thinking mode is idle — nothing drains the run queue; "
                    "leave idle and it fires"
                )
                deferred.append(str(row.get("id")))
                continue
            _fire(row, ts)
            fired.append(str(row.get("id")))
        if fired or deferred:
            _save(rows)
    return {"ok": True, "fired": fired, "deferred": deferred, "drains": bool(drains)}


def _fire(row: dict[str, Any], ts: float) -> dict[str, Any]:
    """Advance the clock and queue the agent. `ok` is false when nothing was queued.

    A fire that queues nothing used to be swallowed into last_status and read by no
    one, so a routine failing every night looked exactly like one succeeding.
    """
    interval = int(row.get("interval_seconds") or 86400)
    row["last_run_at"] = ts
    row["next_run_at"] = ts + max(60, interval)
    row.pop("last_error", None)
    aid = int(row.get("agent_id") or 0)
    if aid:
        try:
            from cortex_orchestrator import queue_run

            queued = queue_run(aid, str(row.get("goal") or ""))
            if queued.get("ok"):
                row["last_status"] = "queued"
            else:
                row["last_status"] = "queue_failed"
                row["last_error"] = str(queued.get("error") or "queue_run returned ok=false")
            row["last_run_id"] = queued.get("run_id")
        except Exception as exc:
            row["last_status"] = f"error:{type(exc).__name__}"
            row["last_error"] = str(exc)[:200]
    else:
        row["last_status"] = "fired_no_agent"
        row["last_error"] = "no agent bound (agent_id=0) — the clock advanced and nothing ran"
    problem = _row_problem(row)
    out: dict[str, Any] = {
        "ok": not problem,
        "routine": row,
        "status": row["last_status"],
        "next_run_at": row["next_run_at"],
        "scheduler": "airgpt_host",
    }
    if problem:
        out["error"] = problem
        out["reason"] = row["last_status"]
    return out

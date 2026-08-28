"""Cortex orchestrator: Thinking modes, queued runs, checklists (token-efficient)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import agent_store

from config import DATA_DIR

SETTINGS_FILE = DATA_DIR / "cortex_settings.json"
RECIPES_DIR = DATA_DIR / "openforge" / "recipes"
_worker_started = False
_worker_lock = threading.Lock()
_active_run_id: int | None = None


def _load_settings() -> dict:
    if SETTINGS_FILE.is_file():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"thinking_mode": "assist", "token_budget": 1200, "max_steps": 8}


def _save_settings(data: dict) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def get_settings() -> dict:
    s = _load_settings()
    mode = str(s.get("thinking_mode") or "assist").lower()
    if mode not in ("idle", "assist", "deep"):
        mode = "assist"
    return {
        "thinking_mode": mode,
        "token_budget": int(s.get("token_budget") or 1200),
        "max_steps": int(s.get("max_steps") or 8),
    }


def set_settings(*, thinking_mode: str | None = None, token_budget: int | None = None, max_steps: int | None = None) -> dict:
    s = get_settings()
    if thinking_mode:
        m = thinking_mode.lower()
        if m in ("idle", "assist", "deep"):
            s["thinking_mode"] = m
    if token_budget is not None:
        s["token_budget"] = max(100, min(int(token_budget), 8000))
    if max_steps is not None:
        s["max_steps"] = max(1, min(int(max_steps), 20))
    return _save_settings(s)


def queue_run(
    agent_id: int,
    prompt: str,
    *,
    session_id: int = 0,
    priority: int = 0,
    parent_run_id: int = 0,
    is_subagent: bool = False,
    skill_pack: str = "",
) -> dict:
    agent_store.init()
    now = time.time()
    # Store session_id / parent / skill in result JSON until schema migrates
    meta = json.dumps(
        {
            "session_id": int(session_id or 0),
            "priority": int(priority or 0),
            "parent_run_id": int(parent_run_id or 0),
            "is_subagent": bool(is_subagent or parent_run_id),
            "skill_pack": (skill_pack or "")[:120],
        }
    )
    with agent_store._conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_runs(agent_id,status,prompt,result,created_at) VALUES(?,?,?,?,?)",
            (int(agent_id), "queued", (prompt or "")[:4000], meta, now),
        )
        run_id = int(cur.lastrowid)
    return {
        "ok": True,
        "run_id": run_id,
        "agent_id": agent_id,
        "session_id": session_id,
        "priority": priority,
        "parent_run_id": int(parent_run_id or 0),
        "is_subagent": bool(is_subagent or parent_run_id),
    }


def _run_meta(run: dict) -> dict:
    try:
        meta = json.loads(run.get("result") or "{}")
        if isinstance(meta, dict):
            return meta
    except Exception:
        pass
    return {}


def _session_from_run(run: dict) -> int:
    return int(_run_meta(run).get("session_id") or 0)


def list_pending() -> list[dict]:
    agent_store.init()
    with agent_store._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_runs WHERE status IN ('queued','awaiting_human') ORDER BY id ASC LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]


def list_recipes() -> list[dict]:
    RECIPES_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for p in sorted(RECIPES_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            d["id"] = p.stem
            out.append(d)
        except Exception:
            pass
    if not out:
        default = RECIPES_DIR / "vault_digest.json"
        default.write_text(
            json.dumps(
                {
                    "name": "Vault digest",
                    "steps": [
                        {"op": "vault_read", "params": {"query": "{{prompt}}"}},
                        {"op": "llm", "params": {"max_tokens": 600}},
                        {"op": "vault_write", "params": {"category": "general"}, "gate": "approve_write"},
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        out.append(json.loads(default.read_text(encoding="utf-8")))
        out[0]["id"] = "vault_digest"
    return out


def _worker_tick() -> None:
    global _active_run_id
    settings = get_settings()
    idle = settings["thinking_mode"] == "idle"
    try:
        import host_routines

        # Ticking before the idle check queued runs that this worker then refused to
        # drain: last_status sat at "queued" forever with nothing disclosing it.
        # Tell the clock whether the queue is actually being served.
        host_routines.tick(drains=not idle)
    except Exception:
        pass
    if idle:
        return
    if _active_run_id is not None:
        return
    pending = list_pending()
    if not pending:
        return
    run = pending[0]
    run_id = int(run["id"])
    # Claim first so the same row is never re-picked every 3s
    claimed = agent_store.claim_run(run_id)
    if not claimed or claimed.get("status") != "running":
        return
    _active_run_id = run_id
    try:
        import agent_runtime

        meta = _run_meta(run)
        session_id = int(meta.get("session_id") or 0)
        for _ in agent_runtime.run_agent_events(
            int(run["agent_id"]),
            str(run.get("prompt") or ""),
            session_id=session_id,
            thinking_mode=settings["thinking_mode"],
            max_steps=settings["max_steps"],
            token_budget=settings["token_budget"],
            run_id=run_id,
            skill_override=str(meta.get("skill_pack") or ""),
            parent_run_id=int(meta.get("parent_run_id") or 0),
            is_subagent=bool(meta.get("is_subagent")),
        ):
            pass
    except Exception as e:
        try:
            agent_store.finish_run(run_id, status="error", error=str(e)[:500])
        except Exception:
            pass
    finally:
        _active_run_id = None


def _worker_loop() -> None:
    while True:
        try:
            _worker_tick()
        except Exception:
            pass
        time.sleep(3.0)


def ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        t = threading.Thread(target=_worker_loop, daemon=True, name="cortex-orchestrator")
        t.start()
        _worker_started = True


def deterministic_tick() -> dict:
    """Idle-mode maintenance — no LLM tokens."""
    results: list[str] = []
    try:
        import memory_index

        memory_index.thin_memories()
        results.append("memory_thin")
    except Exception:
        pass
    try:
        import audit

        audit.spotcheck()
        results.append("audit_spotcheck")
    except Exception:
        pass
    return {"ok": True, "actions": results}

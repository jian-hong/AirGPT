"""Cortex engine API client — AirGPT is the driver; Cortex must be running first.

Start Cortex (D:\\Cortex or RUMA/Cortex):
  .\\scripts\\start_cortex_engine.ps1 -Port 8010
Then set CORTEX_API_URL=http://127.0.0.1:8010 (and optional CORTEX_API_KEY).
Canonical port is 8010 (see apps_registry.json) — do not reuse 8001 (vLLM).

This module constantly polls /health + /api/engine/specs so Hosting/Cortex UI
can show live CRM-style status. Soft-fail for personal chat when offline;
engine config / business gate require a live sidecar.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from ai_engine import load_env

DEFAULT_URL = "http://127.0.0.1:8010"

# Soft-fail cache so offline sidecar doesn't add latency every chat turn
_avail_cache: dict[str, Any] = {"t": 0.0, "ok": False}
_poll: dict[str, Any] = {
    "t": 0.0,
    "health": {"ok": False, "status": "standby"},
    "engine": {},
    "memory": {},
}
_poll_lock = threading.Lock()
_poller_started = False
POLL_INTERVAL_SEC = 5.0


def _cfg() -> tuple[str, str]:
    env = load_env()
    return (env.get("CORTEX_API_URL") or DEFAULT_URL).rstrip("/"), env.get("CORTEX_API_KEY", "")


def _headers(key: str) -> dict[str, str]:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        h["X-API-Key"] = key
    return h


def _post(path: str, body: dict, timeout: float = 1.5) -> dict | None:
    base, key = _cfg()
    try:
        req = urllib.request.Request(
            f"{base}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers=_headers(key),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"[cortex] {path} soft-fail: {e}")
        return None


def _get(path: str, timeout: float = 1.5) -> dict | list | None:
    base, key = _cfg()
    try:
        req = urllib.request.Request(f"{base}{path}", headers=_headers(key))
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"[cortex] GET {path} soft-fail: {e}")
        return None


def health() -> dict[str, Any]:
    base, key = _cfg()
    try:
        req = urllib.request.Request(f"{base}/health", headers=_headers(key))
        with urllib.request.urlopen(req, timeout=0.45) as r:
            data = json.loads(r.read().decode())
        _avail_cache["t"] = time.monotonic()
        _avail_cache["ok"] = True
        return {"ok": True, "status": "live", "raw": data, "url": base}
    except Exception as e:
        _avail_cache["t"] = time.monotonic()
        _avail_cache["ok"] = False
        return {"ok": False, "status": "standby", "error": str(e)[:120], "url": base}


def available() -> bool:
    now = time.monotonic()
    if now - float(_avail_cache["t"]) < 12.0:
        return bool(_avail_cache["ok"])
    ok = health().get("ok") is True
    _avail_cache["t"] = now
    _avail_cache["ok"] = ok
    return ok


def engine_specs() -> dict[str, Any]:
    data = _get("/api/engine/specs", timeout=2.0)
    return data if isinstance(data, dict) else {"ok": False, "error": "unreachable"}


def engine_backends() -> dict[str, Any]:
    data = _get("/api/engine/backends", timeout=2.0)
    return data if isinstance(data, dict) else {"ok": False, "error": "unreachable"}


def engine_config(body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/engine/config — requires live Cortex engine."""
    if not available():
        return {
            "ok": False,
            "error": "Cortex engine offline. Start D:\\Cortex first: .\\scripts\\start_cortex_engine.ps1",
            "require_engine": True,
        }
    data = _post("/api/engine/config", body, timeout=3.0)
    return data if isinstance(data, dict) else {"ok": False, "error": "config failed"}


def memory_stats() -> dict[str, Any]:
    data = _get("/api/memory/stats", timeout=1.5)
    return data if isinstance(data, dict) else {"ok": False, "error": "unreachable"}


def context_assemble(body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/context/assemble — layered context engineering (soft-fail)."""
    data = _post("/api/context/assemble", body, timeout=2.5)
    return data if isinstance(data, dict) else {"ok": False, "error": "unreachable"}


def context_compact(messages: list[str], *, token_budget: int = 1200) -> dict[str, Any]:
    data = _post(
        "/api/context/compact",
        {"messages": messages, "token_budget": int(token_budget)},
        timeout=2.0,
    )
    return data if isinstance(data, dict) else {"ok": False, "error": "unreachable"}


def refresh_snapshot() -> dict[str, Any]:
    """One poll cycle: health + engine specs + memory stats."""
    h = health()
    eng: dict[str, Any] = {}
    mem: dict[str, Any] = {}
    if h.get("ok"):
        specs = engine_specs()
        if isinstance(specs, dict) and not specs.get("error"):
            eng = specs
        mem = memory_stats()
    snap = {
        "ok": bool(h.get("ok")),
        "status": h.get("status") or ("live" if h.get("ok") else "standby"),
        "url": h.get("url") or _cfg()[0],
        "error": h.get("error"),
        "pack": (h.get("raw") or {}).get("pack"),
        "engine": eng,
        "memory": mem,
        "polled_at": time.time(),
        "hint": None
        if h.get("ok")
        else "Start Cortex engine first (D:\\Cortex): .\\scripts\\start_cortex_engine.ps1",
    }
    with _poll_lock:
        _poll["t"] = time.monotonic()
        _poll["health"] = h
        _poll["engine"] = eng
        _poll["memory"] = mem
        _poll["snapshot"] = snap
    return snap


def snapshot() -> dict[str, Any]:
    """Cached CRM snapshot (updated by background poller)."""
    ensure_poller()
    with _poll_lock:
        snap = dict(_poll.get("snapshot") or {})
    if not snap:
        return refresh_snapshot()
    return snap


def _poll_loop() -> None:
    while True:
        try:
            refresh_snapshot()
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_SEC)


def ensure_poller() -> None:
    global _poller_started
    if _poller_started:
        return
    _poller_started = True
    t = threading.Thread(target=_poll_loop, name="cortex-poller", daemon=True)
    t.start()


def secure_message(text: str, block_scam: bool = True) -> str:
    """Pre-LLM gate. Returns sanitized text, or original on failure."""
    if not text:
        return text
    data = _post("/dms/secure", {"text": text, "block_scam": block_scam})
    if not data:
        data = _post("/dms/security/secure_message", {"text": text, "block_scam": block_scam})
    if isinstance(data, dict):
        if data.get("blocked"):
            return "[blocked by Cortex security harness]"
        return str(data.get("text") or data.get("sanitized") or text)
    return text


def classify_message(text: str) -> dict:
    if not text:
        return {}
    data = _post("/dms/classify", {"text": text}) or _post("/dms/security/classify", {"text": text})
    return data if isinstance(data, dict) else {}


def gate_user_text(text: str, *, business_require: bool = False) -> dict:
    """Run secure_message + classify. Business mode warns/blocks when Cortex is offline."""
    if not text:
        return {"ok": True, "text": text, "classify": {}, "blocked": False}
    live = available()
    if business_require and not live:
        return {
            "ok": False,
            "blocked": True,
            "warning": "Cortex engine required for Business safety but is offline. Start D:\\Cortex first.",
            "text": text,
            "classify": {},
        }
    if not live:
        return {"ok": True, "blocked": False, "text": text, "classify": {}, "cortex": "standby"}
    secured = secure_message(text)
    if secured == "[blocked by Cortex security harness]":
        return {"ok": False, "blocked": True, "text": secured, "classify": {}}
    classify = classify_message(text)
    return {"ok": True, "blocked": False, "text": secured, "classify": classify}


def append_ledger(actor: str, event_type: str, payload: dict | None = None) -> bool:
    body = {"actor": actor, "event_type": event_type, "payload": payload or {}}
    data = _post("/dms/audit/append", body) or _post("/dms/ledger/append", body)
    return bool(data and data.get("ok", True))


def audit_tail(limit: int = 20) -> list[dict]:
    data = _get(f"/dms/audit?limit={limit}") or _get(f"/dms/audit/tail?limit={limit}")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.get("events") or data.get("items") or [])
    return []


def verify_ledger() -> dict:
    data = _post("/dms/audit/verify", {}) or _get("/dms/audit/verify")
    return data if isinstance(data, dict) else {"ok": False, "error": "unreachable"}


# --- O5: Agent SDK bridge (governed DMS reads/actions for agents) ------------
# Cortex-side gate: CortexOS/agent_sdk via /dms/sidecar/* — PII columns never
# cross this wire; writes run registry -> RBAC -> confirm -> F8 -> ledger.


def _post_status(path: str, body: dict, timeout: float = 6.0) -> dict:
    """POST keeping HTTP error bodies (403 rbac / 409 confirm) instead of None."""
    base, key = _cfg()
    try:
        req = urllib.request.Request(
            f"{base}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers=_headers(key),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"status": r.status, **json.loads(r.read().decode())}
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get("detail", {})
        except Exception:
            detail = {}
        return {
            "ok": False,
            "status": e.code,
            "error": detail.get("error") or str(e),
            "verdict": detail.get("verdict", "http_error"),
        }
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e)[:200], "verdict": "offline"}


def query_objects(object_type: str, filters: dict | None = None, limit: int = 20) -> dict:
    """Read DMS objects through the Agent SDK (agent-visible columns only)."""
    return _post_status(
        "/dms/sidecar/query-objects",
        {"object_type": object_type, "filters": filters or {}, "limit": int(limit)},
        timeout=6.0,
    )


def call_action(
    action_id: str,
    params: dict | None = None,
    *,
    confirmed: bool = False,
    run_id: str | None = None,
) -> dict:
    """Invoke a registered DMS action type through the governed F8 path."""
    return _post_status(
        "/dms/sidecar/call-action",
        {
            "action_id": action_id,
            "params": params or {},
            "confirmed": bool(confirmed),
            "run_id": run_id,
        },
        timeout=10.0,
    )


# Start background poll when module is imported (AirGPT server boot)
try:
    ensure_poller()
except Exception:
    pass

"""Cortex engine API client — AirGPT is the driver; Cortex must be running first.

Start Cortex (D:\\Cortex or RUMA/Cortex):
  .\\scripts\\start_cortex_engine.ps1 -Port 8010
Then set CORTEX_API_URL=http://127.0.0.1:8010 (and optional CORTEX_API_KEY).
Canonical port is 8010 (see apps_registry.json) — do not reuse 8001 (vLLM).

This module constantly polls /health + /api/engine/specs so Hosting/Cortex UI
can show live CRM-style status. Soft-fail for personal chat when offline;
engine config / business gate require a live sidecar.

When CORTEX_AUTOSPAWN=1 (default), a single spawn attempt runs if /health is down
and D:\\Cortex\\scripts\\start_cortex_engine.ps1 is reachable.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ai_engine import load_env

DEFAULT_URL = "http://127.0.0.1:8010"
DEFAULT_CORTEX_ROOT = Path(os.environ.get("CORTEX_ROOT") or r"D:\Cortex")

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
_spawn_lock = threading.Lock()
_spawn_state: dict[str, Any] = {"attempted": False, "ok": False, "error": None, "t": 0.0}
POLL_INTERVAL_SEC = 5.0


_LOOPBACK_DEMO_KEY = "dms-demo-viewer-key"
_ENGINE_FALLBACKS = ("http://127.0.0.1:8011",)
_engine_seat: dict[str, Any] = {"t": 0.0, "url": "", "key": ""}


def _loopback_key(url: str, key: str) -> str:
    """Local Netie engine demo key. Never attach it to a remote Cortex URL."""
    if key:
        return key
    host = urlparse(url).hostname or ""
    if host in ("127.0.0.1", "localhost", "::1"):
        return _LOOPBACK_DEMO_KEY
    return ""


def _cfg() -> tuple[str, str]:
    env = load_env()
    url = (
        os.environ.get("CORTEX_API_URL")
        or env.get("CORTEX_API_URL")
        or _read_url_hint()
        or DEFAULT_URL
    ).rstrip("/")
    key = os.environ.get("CORTEX_API_KEY") or env.get("CORTEX_API_KEY", "")
    return url, _loopback_key(url, key)


def _is_engine_specs(data: Any) -> bool:
    return isinstance(data, dict) and (
        data.get("ok") is True or "engine" in data or "config" in data or "backends" in data
    )


def _probe_engine(url: str, path: str, key: str, timeout: float = 2.0) -> dict | None:
    try:
        req = urllib.request.Request(f"{url}{path}", headers=_headers(key))
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _engine_cfg() -> tuple[str, str]:
    """Stay on CORTEX_API_URL unless that URL is proven Constructor.

    Hopping on a failed probe used to schedule against whatever was on :8011
    while the configured seat was down, still starting, or a test mock. Only a
    Constructor/DMS health payload (surface=constructor) authorizes the fallback.
    """
    now = time.monotonic()
    base, key = _cfg()
    cached = str(_engine_seat.get("url") or "")
    if now - float(_engine_seat["t"]) < 20 and cached and cached == base:
        return cached, str(_engine_seat["key"])
    raw = _probe_engine(base, "/health", key, 1.2) or {}
    surface = str(raw.get("surface") or "")
    if surface != "constructor":
        _engine_seat.update(t=now, url=base, key=key)
        return base, key
    for alt in _ENGINE_FALLBACKS:
        alt = alt.rstrip("/")
        if alt == base.rstrip("/"):
            continue
        alt_key = _loopback_key(alt, os.environ.get("CORTEX_API_KEY") or "")
        if _is_engine_specs(_probe_engine(alt, "/api/engine/specs", alt_key, 3.0)):
            _engine_seat.update(t=now, url=alt, key=alt_key)
            return alt, alt_key
    # Do not cache a Constructor seat for 20s — the engine on :8011 may come up.
    _engine_seat.update(t=0.0, url=base, key=key)
    return base, key


def _headers(key: str) -> dict[str, str]:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        h["X-API-Key"] = key
    return h


def _post(path: str, body: dict, timeout: float = 1.5, *, base: str | None = None, key: str | None = None) -> dict | None:
    cfg_base, cfg_key = _engine_cfg()
    base = (base or cfg_base).rstrip("/")
    key = cfg_key if key is None else key
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


def _get(path: str, timeout: float = 1.5, *, base: str | None = None, key: str | None = None) -> dict | list | None:
    cfg_base, cfg_key = _engine_cfg()
    base = (base or cfg_base).rstrip("/")
    key = cfg_key if key is None else key
    try:
        req = urllib.request.Request(f"{base}{path}", headers=_headers(key))
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"[cortex] GET {path} soft-fail: {e}")
        return None


def health() -> dict[str, Any]:
    base, key = _engine_cfg()
    # 1.2s: cold Cortex / Windows Defender can miss a 0.45s probe and falsely show offline
    try:
        req = urllib.request.Request(f"{base}/health", headers=_headers(key))
        with urllib.request.urlopen(req, timeout=1.2) as r:
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


def _autospawn_enabled() -> bool:
    env = load_env()
    raw = (env.get("CORTEX_AUTOSPAWN") or os.environ.get("CORTEX_AUTOSPAWN") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _cortex_root() -> Path:
    env = load_env()
    raw = (env.get("CORTEX_ROOT") or os.environ.get("CORTEX_ROOT") or "").strip()
    if raw:
        return Path(raw)
    for cand in (Path(r"E:\Cortex"), Path(r"D:\Cortex"), DEFAULT_CORTEX_ROOT):
        if (cand / "scripts" / "start_cortex_engine.ps1").is_file():
            return cand
    return DEFAULT_CORTEX_ROOT


def _port_from_url(url: str) -> int:
    try:
        p = urlparse(url)
        if p.port:
            return int(p.port)
    except Exception:
        pass
    return 8010


def _read_url_hint() -> str | None:
    hint = _cortex_root() / "data" / "engine" / "cortex_api_url.txt"
    try:
        if hint.is_file():
            text = hint.read_text(encoding="utf-8").strip()
            if text.startswith("http"):
                return text.rstrip("/")
    except Exception:
        pass
    return None


def _powershell_exe() -> str:
    for name in ("pwsh", "powershell"):
        try:
            subprocess.run([name, "-NoProfile", "-Command", "exit 0"], capture_output=True, timeout=5)
            return name
        except Exception:
            continue
    return "powershell"


def spawn_engine(*, wait_sec: float = 12.0) -> dict[str, Any]:
    """Start Cortex once via start_cortex_engine.ps1; poll /health until live or timeout."""
    with _spawn_lock:
        if available():
            _spawn_state.update({"attempted": True, "ok": True, "error": None, "t": time.time()})
            return {"ok": True, "already": True, "url": _cfg()[0]}
        if _spawn_state.get("attempted") and not _spawn_state.get("ok"):
            # One attempt per process unless forced by ensure_engine(force=True)
            return {
                "ok": False,
                "error": _spawn_state.get("error") or "spawn already attempted",
                "url": _cfg()[0],
            }

        root = _cortex_root()
        script = root / "scripts" / "start_cortex_engine.ps1"
        if not script.is_file():
            err = f"missing launcher: {script}"
            _spawn_state.update({"attempted": True, "ok": False, "error": err, "t": time.time()})
            return {"ok": False, "error": err}

        base, _ = _cfg()
        port = _port_from_url(base)
        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
                    subprocess, "DETACHED_PROCESS", 0x00000008
                )
            shell = _powershell_exe()
            subprocess.Popen(
                [
                    shell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                    str(script),
                    "-Port",
                    str(port),
                ],
                cwd=str(root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
        except Exception as exc:
            err = f"spawn failed: {exc}"[:200]
            _spawn_state.update({"attempted": True, "ok": False, "error": err, "t": time.time()})
            return {"ok": False, "error": err, "url": base}

        deadline = time.monotonic() + max(1.0, float(wait_sec))
        while time.monotonic() < deadline:
            if health().get("ok"):
                hint = _read_url_hint()
                _spawn_state.update({"attempted": True, "ok": True, "error": None, "t": time.time()})
                return {"ok": True, "spawned": True, "url": hint or base}
            time.sleep(0.4)

        err = "spawned but /health did not come up in time"
        _spawn_state.update({"attempted": True, "ok": False, "error": err, "t": time.time()})
        return {"ok": False, "error": err, "url": base}


def ensure_engine(*, force: bool = False, wait_sec: float = 12.0) -> dict[str, Any]:
    """Return live health; optionally spawn once when offline and CORTEX_AUTOSPAWN=1."""
    if available():
        return {"ok": True, "status": "live", "url": _cfg()[0], "spawned": False}
    if not _autospawn_enabled() and not force:
        return {
            "ok": False,
            "status": "standby",
            "url": _cfg()[0],
            "error": "offline (CORTEX_AUTOSPAWN disabled)",
            "hint": r"Start Cortex: .\scripts\start_cortex_engine.ps1 -Port 8010",
        }
    if force:
        with _spawn_lock:
            _spawn_state["attempted"] = False
    result = spawn_engine(wait_sec=wait_sec)
    if result.get("ok"):
        return {"ok": True, "status": "live", "url": result.get("url") or _cfg()[0], "spawned": True}
    return {
        "ok": False,
        "status": "standby",
        "url": result.get("url") or _cfg()[0],
        "error": result.get("error"),
        "hint": r"Start Cortex: .\scripts\start_cortex_engine.ps1 -Port 8010",
    }


def engine_specs() -> dict[str, Any]:
    data = _get("/api/engine/specs", timeout=2.0)
    return data if isinstance(data, dict) else {"ok": False, "error": "unreachable"}


def engine_activity() -> dict[str, Any]:
    """GET /api/engine/activity — routines/workflows/races/apps control panel."""
    data = _get("/api/engine/activity", timeout=3.0)
    return data if isinstance(data, dict) else {"ok": False, "error": "unreachable"}


def engine_backends() -> dict[str, Any]:
    data = _get("/api/engine/backends", timeout=2.0)
    return data if isinstance(data, dict) else {"ok": False, "error": "unreachable"}


def engine_just_works(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """POST /api/engine/just-works — one-button plan for the current machine.

    The lubricant surface: Cortex picks a backend that actually runs here and
    reports it in plain language. Research boosters stay off until a bench gate
    is green, so this never turns on something unproven behind the user's back.
    """
    if not available():
        ensure_engine(wait_sec=10.0)
    if not available():
        return {
            "ok": False,
            "require_engine": True,
            "human": [
                "The Cortex engine is not running yet, so I cannot check this machine.",
                "Start it, then press the button again.",
            ],
            "error": "Cortex engine offline",
        }
    data = _post("/api/engine/just-works", body or {}, timeout=25.0)
    if not isinstance(data, dict):
        return {
            "ok": False,
            "human": ["Could not work out a setup for this machine. Nothing was changed."],
            "error": "just-works failed",
        }
    return data


def engine_bakeoff(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """POST /api/engine/bakeoff — soft probe of local backends (reachability).

    Slow by nature: it dials every candidate backend and waits out the ones that
    are not there. A cold probe can take most of a minute, so the timeout is
    generous and a timeout is never reported as "engine offline" — saying the
    engine is down when it is merely busy sends people to fix the wrong thing.
    """
    if not available():
        return {
            "ok": False,
            "require_engine": True,
            "human": ["The Cortex engine is not running, so nothing could be checked."],
            "error": "Cortex engine offline",
        }
    data = _post("/api/engine/bakeoff", body or {}, timeout=90.0)
    if isinstance(data, dict):
        return data
    return {
        "ok": False,
        "human": [
            "Checking the backends took too long, so this was stopped.",
            "The engine is still running. Try again in a moment.",
        ],
        "error": "bakeoff timed out",
    }


def _resolve_engine_for_loop() -> tuple[str, str, dict[str, Any]]:
    """Constructor on :8010 is not the engine. Prefer a live Netie /api/engine/specs."""
    base, key = _cfg()
    h = health()
    raw = h.get("raw") if isinstance(h.get("raw"), dict) else {}
    specs = _get("/api/engine/specs", timeout=3.0, base=base, key=key)
    if str(raw.get("surface") or "") != "constructor" and _is_engine_specs(specs):
        return base, key, raw
    for alt in _ENGINE_FALLBACKS:
        alt = alt.rstrip("/")
        if alt == base.rstrip("/"):
            continue
        alt_key = _loopback_key(alt, os.environ.get("CORTEX_API_KEY") or "")
        alt_specs = _get("/api/engine/specs", timeout=3.0, base=alt, key=alt_key)
        if _is_engine_specs(alt_specs):
            return alt, alt_key, {"status": "ok", "pack": "dms"}
    return base, key, raw


def engine_agent_loop(
    prompt: str,
    *,
    session_id: str = "",
    max_steps: int = 8,
    tools: list | None = None,
    quality_criteria: list | None = None,
    prompt_id: str = "",
    params: dict | None = None,
    max_tokens: int = 0,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """POST /api/engine/run architecture_preset=agent (F20b quality loop)."""
    ensure_engine(wait_sec=8.0)
    base, key, raw = _resolve_engine_for_loop()
    if str(raw.get("surface") or "") == "constructor":
        return {
            "ok": False,
            "reason": "wrong_surface",
            "error": (
                f"{base} is Constructor, not the Cortex engine. "
                "/api/engine/run is 404 here."
            ),
        }
    specs = _get("/api/engine/specs", timeout=3.0, base=base, key=key)
    if not _is_engine_specs(specs):
        return {
            "ok": False,
            "reason": "wrong_surface",
            "error": (
                f"{base} has no /api/engine/specs. "
                "Point CORTEX_API_URL at CortexOS.api.main, not constructor_app."
            ),
        }
    body: dict[str, Any] = {
        "prompt": prompt,
        "architecture_preset": "agent",
        "session_id": session_id or "",
        "max_steps": max(1, min(int(max_steps), 20)),
    }
    if tools:
        body["tools"] = list(tools)
    if quality_criteria:
        body["quality_criteria"] = list(quality_criteria)
    if prompt_id:
        body["prompt_id"] = str(prompt_id)
    if params:
        body["params"] = dict(params)
    if max_tokens:
        body["max_tokens"] = max(256, min(int(max_tokens), 8192))
    data = _post("/api/engine/run", body, timeout=float(timeout), base=base, key=key)
    if isinstance(data, dict) and data.get("ok"):
        return data
    if isinstance(data, dict):
        return {
            "ok": False,
            "error": str(data.get("error") or data.get("detail") or "engine agent loop failed")[:300],
        }
    return {"ok": False, "error": "Cortex engine offline"}


def engine_config(body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/engine/config — requires live Cortex engine (one autospawn try)."""
    if not available():
        ensure_engine(wait_sec=10.0)
    if not available():
        return {
            "ok": False,
            "error": "Cortex engine offline. Start D:\\Cortex first: .\\scripts\\start_cortex_engine.ps1 -Port 8010",
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
    """One poll cycle: health + engine specs + memory stats (autospawn once if offline)."""
    h = health()
    if not h.get("ok") and _autospawn_enabled() and not _spawn_state.get("attempted"):
        ensure_engine(wait_sec=8.0)
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
        "spawn": dict(_spawn_state),
        "hint": None
        if h.get("ok")
        else "Start Cortex engine first (D:\\Cortex): .\\scripts\\start_cortex_engine.ps1 -Port 8010",
    }
    with _poll_lock:
        _poll["t"] = time.monotonic()
        _poll["health"] = h
        _poll["engine"] = eng
        _poll["memory"] = mem
        _poll["snapshot"] = snap
    return snap


def snapshot(*, fresh: bool = False) -> dict[str, Any]:
    """Cached CRM snapshot (updated by background poller).

    Pass fresh=True from Hosting UI so a stale offline cache cannot linger
    after Cortex has come up.
    """
    ensure_poller()
    if fresh:
        return refresh_snapshot()
    with _poll_lock:
        snap = dict(_poll.get("snapshot") or {})
        age = time.monotonic() - float(_poll.get("t") or 0)
    if not snap:
        return refresh_snapshot()
    # Re-probe when last sample said offline or is older than two poll cycles
    if (not snap.get("ok")) or age > (POLL_INTERVAL_SEC * 2):
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
            raw = r.read().decode() or "{}"
            data = json.loads(raw)
            if not isinstance(data, dict):
                return {
                    "ok": False,
                    "status": r.status,
                    "error": f"non-dict body: {str(data)[:160]}",
                    "verdict": "http_error",
                }
            return {"status": r.status, **data}
    except urllib.error.HTTPError as e:
        try:
            parsed = json.loads(e.read().decode() or "{}")
        except Exception:
            parsed = {}
        detail = parsed.get("detail", {}) if isinstance(parsed, dict) else {}
        if isinstance(detail, str):
            detail = {"error": detail}
        if not isinstance(detail, dict):
            detail = {}
        return {
            "ok": False,
            "status": e.code,
            "error": str(detail.get("error") or parsed.get("error") or e)[:240],
            "verdict": str(detail.get("verdict") or "http_error"),
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


# -- Routines + installed apps (Cortex SoT; AirGPT UI is the driver) ----------


def _detail_from_http(exc: urllib.error.HTTPError) -> Any:
    try:
        payload = json.loads(exc.read().decode())
        return payload.get("detail", payload)
    except Exception:
        return str(exc)


def _json_call(
    method: str,
    path: str,
    body: dict | None = None,
    *,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """JSON call that keeps FastAPI error bodies (humanize.explain objects)."""
    base, key = _engine_cfg()
    data = None if body is None else json.dumps(body).encode("utf-8")
    try:
        req = urllib.request.Request(
            f"{base}{path}",
            data=data,
            headers=_headers(key),
            method=method.upper(),
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            out = json.loads(raw) if raw else {"ok": True}
            if isinstance(out, dict):
                out.setdefault("ok", True)
                out["_http"] = r.status
                return out
            return {"ok": True, "data": out, "_http": r.status}
    except urllib.error.HTTPError as e:
        detail = _detail_from_http(e)
        return {"ok": False, "detail": detail, "error": detail, "_http": e.code}
    except Exception as e:
        return {**_wf_down(str(e)[:200]), "_http": 503}


def _wf_down(detail: str = "Cortex engine offline") -> dict[str, Any]:
    return {
        "ok": False,
        "reason": "cortex_down",
        "error": detail,
        "hint": "Start Cortex on :8010 (CORTEX_AUTOSPAWN=1) or open Hosting → Netie Engine",
    }


def _next_run_at(obj: dict[str, Any] | None) -> Any:
    """next_run_at wherever Cortex put it — top level or nested under routine."""
    if not isinstance(obj, dict):
        return None
    if obj.get("next_run_at") not in (None, ""):
        return obj.get("next_run_at")
    rt = obj.get("routine") if isinstance(obj.get("routine"), dict) else {}
    return rt.get("next_run_at")


def scheduler_status(*, try_spawn: bool = False) -> dict[str, Any]:
    """Named reason the Cortex scheduler can or cannot fire. Never a silent no-op.

    :8010 answering GET /health is not enough. Constructor/DMS answers /health with
    {status:ok, pack:dms, surface:constructor} and 404s /api/routines, so a caller
    that only probes /health believes it scheduled something that will never run.
    Every non-live outcome carries a `reason` the UI can name at the control.
    """
    h = health()
    if not h.get("ok") and try_spawn:
        ensure_engine(wait_sec=6.0)
        h = health()
    raw = h.get("raw") if isinstance(h.get("raw"), dict) else {}
    pack = str(raw.get("pack") or "")
    surface = str(raw.get("surface") or "")
    url = str(h.get("url") or _cfg()[0])
    base = {"url": url, "pack": pack, "surface": surface, "scheduler": "cortex"}
    if not h.get("ok"):
        err = str(h.get("error") or "Cortex engine offline")
        return {
            **base,
            "ok": False,
            "reason": "cortex_down",
            "error": f"Cortex down at {url}: {err}",
            "hint": r"Start Cortex: .\scripts\start_cortex_engine.ps1 -Port 8010",
        }
    # Constructor-only FastAPI sets surface=constructor. The Netie engine also
    # reports pack=dms -- that is the product pack, not a wrong surface.
    if surface == "constructor":
        who = surface or "Constructor/DMS"
        return {
            **base,
            "ok": False,
            "reason": "wrong_surface",
            "error": (
                f"{url} is {who} (pack={pack or 'dms'}), not the Cortex engine. "
                "/api/routines is 404 here; the scheduler cannot fire."
            ),
            "hint": "Point CORTEX_API_URL at Cortex, or stop Constructor/DMS on that port.",
        }
    listed = _json_call("GET", "/api/routines", None, timeout=3.0)
    http = listed.get("_http")
    if listed.get("ok"):
        return {**listed, **base, "ok": True, "reason": "live"}
    if http == 404:
        return {
            **base,
            "ok": False,
            "reason": "no_scheduler",
            "error": (
                f"{url} answered /health but GET /api/routines returned 404. "
                "Whatever is on that port, it is not a Cortex scheduler."
            ),
            "hint": "Point CORTEX_API_URL at the Cortex engine.",
        }
    return {
        **base,
        "ok": False,
        "reason": "cortex_down",
        "error": str(listed.get("error") or listed.get("detail") or "Cortex scheduler unreachable"),
        "hint": "Start Cortex on :8010.",
        "_http": http,
    }


def _legacy_host_rows() -> dict[str, Any]:
    """Rows the retired AirGPT host clock already wrote to disk (SHELL-02).

    The host clock is out of scope for F18 — Cortex owns the scheduler — so nothing
    creates these any more. They stay listable and deletable, marked `airgpt_host`,
    so an existing chip is neither silently dropped nor mistaken for a Cortex routine.
    """
    try:
        import host_routines

        return host_routines.list_routines()
    except Exception as e:  # store unreadable: say so, do not pretend it is empty
        return {"ok": False, "error": str(e)[:200], "routines": []}


def routines_list() -> dict[str, Any]:
    """GET /api/routines. `ok` tracks the Cortex scheduler, never the local store."""
    st = scheduler_status(try_spawn=True)
    host = _legacy_host_rows()
    rows = list(host.get("routines") or [])
    st["host_routines"] = rows
    st["host_routine_count"] = len(rows)
    if host.get("unhealthy"):
        st["host_unhealthy"] = host["unhealthy"]
    if not st.get("ok"):
        st.setdefault("routines", [])
    return st


def routines_draft(goal: str) -> dict[str, Any]:
    """POST /api/routines/draft — preview only; nothing saved.

    A draft the UI can render a Create button under must carry the fields that
    button implies. A 404 from Cortex is a refusal, not a blank preview card.
    """
    st = scheduler_status(try_spawn=True)
    if not st.get("ok"):
        return st
    out = _json_call("POST", "/api/routines/draft", {"goal": goal}, timeout=6.0)
    if not out.get("ok"):
        return out
    draft = out.get("draft") if isinstance(out.get("draft"), dict) else out
    missing = [k for k in ("name", "schedule_text", "prompt") if not draft.get(k)]
    if missing:
        return {
            "ok": False,
            "reason": "empty_draft",
            "error": (
                "Cortex returned a draft with no " + ", ".join(missing) +
                " — nothing to preview, and nothing worth a Create button."
            ),
            "hint": "Rephrase the goal, or check the Cortex draft endpoint.",
            "url": st.get("url"),
            "_http": out.get("_http"),
        }
    out["reason"] = "live"
    out["scheduler"] = "cortex"
    return out


def routines_create(goal: str, **extra: Any) -> dict[str, Any]:
    """POST /api/routines — one sentence is enough; extras optional overrides.

    Two outcomes only: a real Cortex routine with a real next_run_at, or a named
    refusal. There is deliberately no AirGPT-owned cron behind this call (issue #60
    out-of-scope: Cortex owns the scheduler); a host clock here is the third outcome
    that made a chip look scheduled while nothing ran.
    """
    st = scheduler_status(try_spawn=True)
    if not st.get("ok"):
        return st
    body = {"goal": goal, **{k: v for k, v in extra.items() if v is not None}}
    out = _json_call("POST", "/api/routines", body, timeout=8.0)
    nxt = _next_run_at(out)
    if out.get("ok") and nxt in (None, ""):
        out["ok"] = False
        out["reason"] = "no_next_run"
        out["error"] = "Cortex accepted the goal but returned no next_run_at — not scheduled"
    elif out.get("ok"):
        out["reason"] = "live"
        out["scheduler"] = "cortex"
        out["next_run_at"] = nxt
    return out


def routines_pause(rid: str, reason: str = "user") -> dict[str, Any]:
    if str(rid).startswith("hr-"):
        import host_routines

        return host_routines.pause(rid, reason)
    st = scheduler_status()
    if not st.get("ok"):
        return st
    return _json_call("POST", f"/api/routines/{rid}/pause", {"reason": reason}, timeout=4.0)


def routines_resume(rid: str) -> dict[str, Any]:
    if str(rid).startswith("hr-"):
        import host_routines

        return host_routines.resume(rid)
    st = scheduler_status()
    if not st.get("ok"):
        return st
    return _json_call("POST", f"/api/routines/{rid}/resume", {}, timeout=4.0)


def routines_run(rid: str) -> dict[str, Any]:
    """Forced run. `fired` is true only when next_run_at actually advanced."""
    if str(rid).startswith("hr-"):
        import host_routines

        return host_routines.run_now(rid)
    st = scheduler_status()
    if not st.get("ok"):
        return st
    before = _next_run_at(_json_call("GET", f"/api/routines/{rid}", None, timeout=4.0))
    out = _json_call("POST", f"/api/routines/{rid}/run", {}, timeout=60.0)
    after = _next_run_at(out)
    if after in (None, ""):
        after = _next_run_at(_json_call("GET", f"/api/routines/{rid}", None, timeout=4.0))
    out["next_run_at_before"] = before
    out["next_run_at_after"] = after
    if after not in (None, ""):
        out["next_run_at"] = after
    out["fired"] = bool(out.get("ok") and after not in (None, "") and after != before)
    run = out.get("run") if isinstance(out.get("run"), dict) else {}
    if run.get("steps"):
        out["steps"] = run["steps"]
    if run.get("output") is not None:
        out.setdefault("output", run.get("output"))
    if run.get("work_kinds"):
        out["work_kinds"] = run["work_kinds"]
    if out.get("ok") and not out["fired"]:
        out["error"] = "routine did not fire: next_run_at did not advance"
        out["reason"] = "did_not_fire"
    return out


def routines_runs(rid: str) -> dict[str, Any]:
    st = scheduler_status()
    if not st.get("ok"):
        return st
    return _json_call("GET", f"/api/routines/{rid}/runs", None, timeout=4.0)


def routines_delete(rid: str) -> dict[str, Any]:
    if str(rid).startswith("hr-"):
        import host_routines

        return host_routines.delete(rid)
    st = scheduler_status()
    if not st.get("ok"):
        return st
    return _json_call("DELETE", f"/api/routines/{rid}", timeout=4.0)


def cortex_apps_list() -> dict[str, Any]:
    """GET Cortex /api/apps — installed package store (not AirGPT port registry)."""
    ensure_engine(wait_sec=6.0)
    data = _get("/api/apps", timeout=3.0)
    if isinstance(data, dict) and data.get("ok"):
        return data
    return _wf_down((data or {}).get("error") if isinstance(data, dict) else "unreachable")


def cortex_apps_import_folder(path: str, name: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"path": path}
    if name:
        body["name"] = name
    ensure_engine(wait_sec=6.0)
    return _json_call("POST", "/api/apps/import-folder", body, timeout=30.0)


def cortex_apps_approve(app_id: str) -> dict[str, Any]:
    return _json_call("POST", f"/api/apps/{app_id}/approve", {}, timeout=8.0)


def cortex_apps_reject(app_id: str, reason: str = "rejected") -> dict[str, Any]:
    return _json_call("POST", f"/api/apps/{app_id}/reject", {"reason": reason}, timeout=6.0)


def cortex_apps_dockerize(app_id: str) -> dict[str, Any]:
    return _json_call("POST", f"/api/apps/{app_id}/dockerize", {}, timeout=15.0)


def cortex_apps_start(app_id: str) -> dict[str, Any]:
    return _json_call("POST", f"/api/apps/{app_id}/start", {}, timeout=20.0)


def cortex_apps_stop(app_id: str) -> dict[str, Any]:
    return _json_call("POST", f"/api/apps/{app_id}/stop", {}, timeout=8.0)


def cortex_apps_delete(app_id: str) -> dict[str, Any]:
    return _json_call("DELETE", f"/api/apps/{app_id}", timeout=6.0)


def constructor_ghost(nodes: list | None = None, edges: list | None = None) -> dict[str, Any]:
    """Compile a Constructor canvas on Cortex (no LLM run)."""
    return _post_status(
        "/cortex/constructor/ghost",
        {"nodes": nodes or [], "edges": edges or []},
        timeout=8.0,
    )


def constructor_recommend(nodes: list | None = None, edges: list | None = None) -> dict[str, Any]:
    return _post_status(
        "/cortex/constructor/recommend",
        {"nodes": nodes or [], "edges": edges or []},
        timeout=8.0,
    )


def constructor_generate(
    prompt: str,
    nodes: list | None = None,
    edges: list | None = None,
) -> dict[str, Any]:
    """Constructor generate requires `prompt` (422 without it)."""
    return _post_status(
        "/cortex/constructor/generate",
        {
            "prompt": (prompt or "")[:4000],
            "nodes": nodes or [],
            "edges": edges or [],
        },
        timeout=45.0,
    )


def mcp_list_tools() -> dict[str, Any]:
    data = _get("/mcp/tools", timeout=4.0)
    return data if isinstance(data, dict) else {"ok": False, "error": "unreachable"}


def mcp_call(name: str, arguments: dict | None = None) -> dict[str, Any]:
    return _post_status("/mcp/call", {"name": name, "arguments": arguments or {}}, timeout=12.0)



def goals_list() -> dict[str, Any]:
    ensure_engine(wait_sec=6.0)
    data = _get("/api/goals", timeout=3.0)
    if isinstance(data, dict) and data.get("ok"):
        return data
    return _wf_down((data or {}).get("error") if isinstance(data, dict) else "unreachable")


def goals_create(statement: str, **extra: Any) -> dict[str, Any]:
    ensure_engine(wait_sec=6.0)
    body: dict[str, Any] = {"statement": statement}
    for key in ("org_id", "measurable_criteria", "hard_constraints", "soft_preferences", "audit_required"):
        if key in extra and extra[key] is not None:
            body[key] = extra[key]
    return _json_call("POST", "/api/goals", body, timeout=8.0)


def goals_get(goal_id: str) -> dict[str, Any]:
    ensure_engine(wait_sec=4.0)
    data = _get(f"/api/goals/{goal_id}", timeout=3.0)
    if isinstance(data, dict) and data.get("ok"):
        return data
    return _wf_down((data or {}).get("error") if isinstance(data, dict) else "unreachable")


def goals_delete(goal_id: str) -> dict[str, Any]:
    return _json_call("DELETE", f"/api/goals/{goal_id}", timeout=4.0)


def goals_seeks(goal_id: str) -> dict[str, Any]:
    ensure_engine(wait_sec=4.0)
    data = _get(f"/api/goals/{goal_id}/seeks", timeout=3.0)
    if isinstance(data, dict) and data.get("ok"):
        return data
    return _wf_down((data or {}).get("error") if isinstance(data, dict) else "unreachable")


def goals_outcome(goal_id: str, proposal_id: str, outcome: str) -> dict[str, Any]:
    """POST /api/goals/{id}/outcome — teach the value table from a user decision."""
    ensure_engine(wait_sec=4.0)
    return _json_call(
        "POST",
        f"/api/goals/{goal_id}/outcome",
        {"proposal_id": proposal_id, "outcome": outcome},
        timeout=8.0,
    )


def goals_values(goal_id: str) -> dict[str, Any]:
    ensure_engine(wait_sec=4.0)
    data = _get(f"/api/goals/{goal_id}/values", timeout=3.0)
    if isinstance(data, dict) and data.get("ok"):
        return data
    return _wf_down((data or {}).get("error") if isinstance(data, dict) else "unreachable")


def engine_seek(goal_id: str | None = None, *, trigger: str = "manual", limit: int = 8) -> dict[str, Any]:
    """POST /api/engine/seek — proactive proposals; no inbox required."""
    ensure_engine(wait_sec=6.0)
    body: dict[str, Any] = {"trigger": trigger, "limit": int(limit)}
    if goal_id:
        body["goal_id"] = goal_id
    return _json_call("POST", "/api/engine/seek", body, timeout=12.0)


# -- Background workflows (Cortex SoT) ---------------------------------------


def workflows_list() -> dict[str, Any]:
    ensure_engine(wait_sec=8.0)
    data = _get("/api/workflows", timeout=3.0)
    if isinstance(data, dict) and data.get("ok"):
        return data
    return _wf_down((data or {}).get("error") if isinstance(data, dict) else "Cortex engine offline")


def workflows_snapshot() -> dict[str, Any]:
    ensure_engine(wait_sec=4.0)
    # This endpoint aggregates every workflow run and measures ~4.5s on a warm engine,
    # so the old 3.0s budget could never succeed — it soft-failed on every single poll
    # and the Hub silently showed no tasks. Give it real headroom.
    data = _get("/api/workflows/tasks", timeout=12.0)
    if isinstance(data, dict) and data.get("ok"):
        return data
    return {**_wf_down(), "running": [], "finished": []}


def workflows_get(task_id: str) -> dict[str, Any]:
    ensure_engine(wait_sec=4.0)
    data = _get(f"/api/workflows/task/{task_id}", timeout=3.0)
    if isinstance(data, dict) and (data.get("ok") or data.get("task")):
        return data
    return _wf_down()


def workflows_run(body: dict[str, Any]) -> dict[str, Any]:
    ensure_engine(wait_sec=10.0)
    data = _post("/api/workflows/run", body, timeout=8.0)
    if isinstance(data, dict) and data.get("ok"):
        return data
    if isinstance(data, dict) and data.get("error"):
        return {"ok": False, "error": str(data.get("error"))[:300]}
    return _wf_down()


def workflows_cancel(task_id: str) -> dict[str, Any]:
    ensure_engine(wait_sec=4.0)
    data = _post("/api/workflows/cancel", {"task_id": task_id}, timeout=4.0)
    if isinstance(data, dict) and data.get("ok"):
        return data
    return _wf_down()


def workflows_clear() -> dict[str, Any]:
    ensure_engine(wait_sec=4.0)
    data = _post("/api/workflows/clear", {}, timeout=4.0)
    if isinstance(data, dict) and data.get("ok"):
        return data
    return _wf_down()


def workflows_recognize(prompt: str) -> dict[str, Any]:
    ensure_engine(wait_sec=4.0)
    data = _post("/api/workflows/recognize", {"prompt": prompt}, timeout=4.0)
    if isinstance(data, dict) and data.get("ok") is not False:
        return data if data.get("ok") is not None else {"ok": True, **data}
    return {**_wf_down(), "should_run": False, "template_id": None}


def workflows_push_hardware(hardware: dict[str, Any]) -> dict[str, Any]:
    ensure_engine(wait_sec=3.0)
    data = _post("/api/workflows/hardware", {"hardware": hardware or {}}, timeout=3.0)
    return data if isinstance(data, dict) else _wf_down()


# Start background poll when module is imported (AirGPT server boot)
try:
    ensure_poller()
except Exception:
    pass

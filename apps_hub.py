"""Press-to-activate app hub — unique ports, discover peers, start/stop children.

Canonical ports live in apps_registry.json. Never bind two apps to the same port.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import re

from config import DATA_DIR, ROOT

REGISTRY_FILE = ROOT / "apps_registry.json"
STATE_ROOT = DATA_DIR / "apps"
_procs: dict[str, subprocess.Popen] = {}
_lock = threading.Lock()
_state_lock = threading.Lock()


def _load_registry() -> dict[str, Any]:
    try:
        return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 0, "apps": []}


def registry() -> dict[str, Any]:
    return _load_registry()


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_ok(url: str, timeout: float = 0.8) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= int(r.status) < 500
    except Exception:
        return False


def _app_by_id(app_id: str) -> dict[str, Any] | None:
    for a in _load_registry().get("apps") or []:
        if a.get("id") == app_id:
            return a
    return None


def _conflict_on_port(port: int, exclude_id: str = "") -> str | None:
    """Only flag conflicts among distinct TCP services (not surfaces sharing a port)."""
    for a in _load_registry().get("apps") or []:
        if a.get("id") == exclude_id:
            continue
        if a.get("kind") == "surface":
            continue
        if int(a.get("port") or 0) == int(port) and a.get("id"):
            if _port_open(int(port)):
                return str(a["id"])
    return None


def probe(app: dict[str, Any]) -> dict[str, Any]:
    port = int(app.get("port") or 0)
    running = _port_open(port) if port else False
    healthy = False
    if running and app.get("health") and app.get("url"):
        base = str(app["url"]).rstrip("/")
        # url may already include path (/v1) — health is relative to host:port
        host_base = f"http://127.0.0.1:{port}"
        healthy = _http_ok(host_base + str(app["health"]))
    with _lock:
        managed = app.get("id") in _procs and _procs[app["id"]].poll() is None
    return {
        "id": app.get("id"),
        "name": app.get("name"),
        "port": port,
        "url": app.get("url"),
        "kind": app.get("kind"),
        "open": app.get("open"),
        "running": running,
        "healthy": healthy or (running and not app.get("health")),
        "managed": managed,
        "can_start": bool(app.get("start")) and app.get("kind") != "self",
    }


def status() -> dict[str, Any]:
    reg = _load_registry()
    apps = [probe(a) for a in (reg.get("apps") or [])]
    # Surfaces intentionally share AirGPT's port — exclude from conflict check
    ports = [
        int(a.get("port") or 0)
        for a in (reg.get("apps") or [])
        if a.get("port") and a.get("kind") != "surface"
    ]
    dupes = sorted({p for p in ports if ports.count(p) > 1})
    return {
        "ok": True,
        "version": reg.get("version"),
        "apps": apps,
        "port_conflicts_in_registry": dupes,
        "note": reg.get("note") or "",
    }


def start(app_id: str) -> dict[str, Any]:
    app = _app_by_id(app_id)
    if not app:
        return {"ok": False, "error": f"unknown app: {app_id}"}
    if app.get("kind") == "self":
        return {"ok": True, "status": "self", "app": probe(app)}
    if not app.get("start"):
        return {"ok": False, "error": "no start command (detect-only)"}
    port = int(app.get("port") or 0)
    if _port_open(port):
        return {"ok": True, "status": "already_running", "app": probe(app)}
    other = _conflict_on_port(port, exclude_id=app_id)
    if other:
        return {"ok": False, "error": f"port {port} held by {other}"}

    cwd = app.get("cwd") or "."
    cwd_path = Path(cwd)
    if not cwd_path.is_absolute():
        cwd_path = (ROOT / cwd).resolve()
    if not cwd_path.exists():
        return {"ok": False, "error": f"cwd missing: {cwd_path}"}

    cmd = list(app["start"])
    env = os.environ.copy()
    for k, v in (app.get("env") or {}).items():
        env[str(k)] = str(v)

    try:
        creationflags = 0
        use_shell = False
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            # npm/npx are .cmd shims — need shell on Windows
            if cmd and str(cmd[0]).lower() in ("npm", "npx", "pnpm", "yarn"):
                use_shell = True
        proc = subprocess.Popen(
            cmd if not use_shell else subprocess.list2cmdline(cmd),
            cwd=str(cwd_path),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            shell=use_shell,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

    with _lock:
        _procs[app_id] = proc

    # brief wait for bind
    deadline = time.time() + 8.0
    while time.time() < deadline:
        if _port_open(port):
            break
        if proc.poll() is not None:
            return {"ok": False, "error": f"exited early code={proc.returncode}", "app": probe(app)}
        time.sleep(0.25)

    return {"ok": True, "status": "started", "pid": proc.pid, "app": probe(app)}


def stop(app_id: str) -> dict[str, Any]:
    app = _app_by_id(app_id)
    if not app:
        return {"ok": False, "error": f"unknown app: {app_id}"}
    if app.get("kind") == "self":
        return {"ok": False, "error": "cannot stop self via hub"}
    with _lock:
        proc = _procs.pop(app_id, None)
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception as e:
            return {"ok": False, "error": str(e)[:200], "app": probe(app) if app else None}
        return {"ok": True, "status": "stopped", "app": probe(app)}
    # not managed — report if something else is on the port
    if app and _port_open(int(app.get("port") or 0)):
        return {
            "ok": False,
            "error": "process not managed by hub (started externally); stop it manually",
            "app": probe(app),
        }
    return {"ok": True, "status": "not_running", "app": probe(app) if app else None}


def open_target(app_id: str) -> dict[str, Any]:
    app = _app_by_id(app_id)
    if not app:
        return {"ok": False, "error": f"unknown app: {app_id}"}
    if app.get("kind") == "surface":
        return {
            "ok": True,
            "url": app.get("url"),
            "open": "panel",
            "surface": app_id,
            "app": probe(app),
        }
    st = probe(app)
    if not st.get("running"):
        started = start(app_id)
        if not started.get("ok") and started.get("status") != "already_running":
            return started
        st = started.get("app") or probe(app)
    return {
        "ok": True,
        "url": app.get("url"),
        "open": app.get("open") or "browser",
        "app": st,
    }


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "app").lower()).strip("-")
    return s or "app"


def allowlisted_ports() -> list[int]:
    """Ports that may be embedded in Live App Cards (registered apps only)."""
    ports: list[int] = []
    for a in _load_registry().get("apps") or []:
        p = int(a.get("port") or 0)
        if p and a.get("kind") not in ("self", "surface"):
            ports.append(p)
    return sorted(set(ports))


def next_free_port(start: int = 9100) -> int:
    """Pick the next unused TCP port not claimed in the registry."""
    reg = _load_registry()
    used = {int(a.get("port") or 0) for a in (reg.get("apps") or []) if a.get("port")}
    for k in (reg.get("reserved") or {}):
        try:
            used.add(int(k))
        except (TypeError, ValueError):
            pass
    port = max(int(start), 9100)
    while port in used or _port_open(port):
        port += 1
        if port > 65000:
            raise RuntimeError("no free app port")
    return port


def register_app(entry: dict[str, Any]) -> dict[str, Any]:
    """Append an app to apps_registry.json. Guarantees unique port."""
    app_id = str(entry.get("id") or "").strip()
    if not app_id:
        return {"ok": False, "error": "id required"}
    if _app_by_id(app_id):
        return {"ok": False, "error": f"app already registered: {app_id}"}
    port = int(entry.get("port") or 0)
    if not port:
        port = next_free_port()
        entry = {**entry, "port": port}
    other = _conflict_on_port(port, exclude_id=app_id)
    if other:
        return {"ok": False, "error": f"port {port} held by {other}"}
    if not entry.get("url"):
        entry["url"] = f"http://127.0.0.1:{port}/"
    reg = _load_registry()
    apps = list(reg.get("apps") or [])
    apps.append(entry)
    reg["apps"] = apps
    reg["version"] = int(reg.get("version") or 0) + 1
    REGISTRY_FILE.write_text(json.dumps(reg, indent=2), encoding="utf-8")
    return {"ok": True, "app": entry, "ports": allowlisted_ports()}


def _health_label(app: dict[str, Any] | None) -> str:
    if not app:
        return "error"
    st = probe(app)
    if st.get("healthy"):
        return "live"
    if st.get("running"):
        return "building"
    phase = ""
    try:
        path = _state_path(str(app.get("id") or ""))
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            phase = str((raw.get("state") or raw).get("phase") or raw.get("phase") or "")
    except Exception:
        phase = ""
    if phase == "error":
        return "error"
    if phase in ("scaffolding", "building"):
        return phase
    return "scaffolding" if not st.get("running") else "building"


def _state_path(app_id: str) -> Path:
    return STATE_ROOT / app_id / "state.json"


_app_state_epoch = 0
_app_state_dirty: dict[str, float] = {}


def get_app_state(app_id: str) -> dict[str, Any]:
    app = _app_by_id(app_id)
    path = _state_path(app_id)
    state: dict[str, Any] = {}
    updated_at = 0.0
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                inner = data.get("state", data)
                state = inner if isinstance(inner, dict) else {"value": inner}
                updated_at = float(data.get("updated_at") or 0)
        except Exception:
            state = {}
    st = probe(app) if app else {}
    return {
        "ok": True,
        "app_id": app_id,
        "name": (app or {}).get("name") or app_id,
        "port": int((app or {}).get("port") or 0),
        "slug": str((app or {}).get("cwd") or "").replace("\\", "/").split("/")[-1] or app_id,
        "state": state,
        "updated_at": updated_at,
        "health": _health_label(app) if app else "scaffolding",
        "running": bool(st.get("running")),
        "healthy": bool(st.get("healthy")),
    }


def set_app_state(app_id: str, state: dict[str, Any] | None = None, *, merge: bool = True) -> dict[str, Any]:
    global _app_state_epoch
    if not (app_id or "").strip():
        return {"ok": False, "error": "app_id required"}
    if not isinstance(state, dict):
        return {"ok": False, "error": "state must be an object"}
    path = _state_path(app_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    cur: dict[str, Any] = {}
    if merge and path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            inner = data.get("state", data) if isinstance(data, dict) else {}
            if isinstance(inner, dict):
                cur = dict(inner)
        except Exception:
            cur = {}
    cur.update(state)
    now = time.time()
    path.write_text(json.dumps({"state": cur, "updated_at": now}, indent=2), encoding="utf-8")
    _app_state_epoch += 1
    _app_state_dirty[app_id] = now
    return {"ok": True, "app_id": app_id, "state": cur, "updated_at": now, "epoch": _app_state_epoch}


def app_state_poll(since_epoch: int = 0) -> dict[str, Any]:
    """Delta for /api/wait — peers sync Live App Card state without websockets."""
    if int(since_epoch or 0) >= _app_state_epoch:
        return {"epoch": _app_state_epoch, "updates": [], "ports": allowlisted_ports()}
    updates = []
    for app_id in list(_app_state_dirty.keys()):
        st = get_app_state(app_id)
        if st.get("ok"):
            updates.append(st)
    return {"epoch": _app_state_epoch, "updates": updates, "ports": allowlisted_ports()}


def card_payload(app_id: str) -> dict[str, Any]:
    row = get_app_state(app_id)
    if not row.get("ok"):
        return row
    return {
        "app_id": app_id,
        "name": row.get("name") or app_id,
        "port": row.get("port"),
        "health": row.get("health") or "scaffolding",
        "slug": row.get("slug") or app_id,
    }

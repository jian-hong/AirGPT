"""Live D08 stamp + D03 tunnel restart against 127.0.0.1:8765."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("AIRGPT_BASE", "http://127.0.0.1:8765")


def _req(method: str, path: str, body=None, timeout: float = 30.0) -> tuple[int, dict]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return r.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            parsed = {"error": raw[:300]}
        return e.code, parsed


def d08() -> dict:
    src = Path.cwd() / "scripts" / "_live_d08_note.md"
    src.write_text("# graph space\nThis corpus is about retrieval architecture stamps.\n", encoding="utf-8")
    code, space = _req(
        "POST",
        "/api/rag/spaces",
        {"name": "D08 live stamp", "depth_default": "manual", "config": {"architecture": "graph"}},
    )
    if code != 200 or not space.get("ok"):
        return {"ok": False, "step": "create", "code": code, "body": space}
    sid = int(space["space"]["id"])
    code, srcs = _req("POST", f"/api/rag/spaces/{sid}/sources", {"paths": [str(src)]})  # adding never clears; the build below re-reads everything
    if code != 200 or not srcs.get("ok"):
        return {"ok": False, "step": "ingest", "code": code, "body": srcs, "sid": sid}
    code, saved = _req(
        "POST",
        f"/api/rag/spaces/{sid}/settings",
        {"depth_default": "manual", "config": {"architecture": "graph"}},
    )
    if code != 200 or not saved.get("ok"):
        return {"ok": False, "step": "settings", "code": code, "body": saved, "sid": sid}
    got_depth = (saved.get("space") or {}).get("depth_default")
    got_arch = ((saved.get("space") or {}).get("config") or {}).get("architecture")
    code, built = _req("POST", f"/api/rag/spaces/{sid}/build", {"depth": "manual"}, timeout=60.0)
    profile = str((built or {}).get("revision_profile") or "")
    return {
        "ok": bool(
            built.get("ok")
            and "graph" in profile
            and "_hybrid_" not in profile
            and got_depth == "manual"
            and got_arch == "graph"
        ),
        "sid": sid,
        "saved_depth": got_depth,
        "saved_arch": got_arch,
        "revision_profile": profile,
        "chunks": built.get("chunks"),
        "build": built,
        "code": code,
    }


def restart_tunnel() -> dict:
    code, body = _req("POST", "/api/restart-tunnel", {})
    return {"http": code, "body": body}


def info() -> dict:
    _code, body = _req("GET", "/api/info")
    return {
        "tunnel_status": body.get("tunnel_status"),
        "tunnel_url": body.get("tunnel_url"),
        "tunnel_error": (body.get("tunnel_error") or "")[:400],
        "attempts": body.get("tunnel_attempts") or [],
        "port": body.get("port"),
    }


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["d08"])[0]
    if cmd == "d08":
        print(json.dumps(d08(), indent=2))
    elif cmd == "restart":
        print(json.dumps(restart_tunnel(), indent=2))
    elif cmd == "info":
        print(json.dumps(info(), indent=2))
    else:
        sys.exit("d08|restart|info")

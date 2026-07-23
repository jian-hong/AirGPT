"""Local audit trail — every action logged for company security review."""
from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict
from pathlib import Path

from config import DATA_DIR

AUDIT_FILE = DATA_DIR / "audit.jsonl"
_lock = threading.Lock()
_MAX_BYTES = 50 * 1024 * 1024

_LEAK_RE = re.compile(
    r"(api[_-]?key|secret|password|token|bearer\s+[a-z0-9]|sk-[a-z0-9]{10,}|AKIA[0-9A-Z]{12,})",
    re.I,
)
_DANGER_ACTIONS = {
    "auth_fail",
    "auth_blocked",
    "auth_qr_fail",
    "download_denied",
    "security.block",
    "wasm.block",
}


def log(
    action: str,
    ip: str = "",
    detail: str = "",
    user: str = "",
    ok: bool = True,
    *,
    category: str = "",
    session_id: int = 0,
    model: str = "",
    tokens: int = 0,
) -> None:
    entry = {
        "ts": time.time(),
        "action": action[:80],
        "ip": ip[:45],
        "user": (user or ip or "local")[:60],
        "ok": ok,
        "detail": (detail or "")[:500],
        "category": (category or "general")[:40],
        "session_id": int(session_id or 0),
        "model": (model or "")[:80],
        "tokens": int(tokens or 0),
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _lock:
        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        if AUDIT_FILE.is_file() and AUDIT_FILE.stat().st_size > _MAX_BYTES:
            old = AUDIT_FILE.read_text(encoding="utf-8")
            AUDIT_FILE.write_text(old[-(_MAX_BYTES // 2) :], encoding="utf-8")
        with AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(line)


def recent(limit: int = 100) -> list[dict]:
    if not AUDIT_FILE.is_file():
        return []
    lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def tail(limit: int = 100) -> list[dict]:
    """Alias for recent — admin dashboard compatibility."""
    return recent(limit)


def _flag_event(e: dict) -> list[str]:
    flags: list[str] = []
    action = (e.get("action") or "").lower()
    detail = e.get("detail") or ""
    if action in _DANGER_ACTIONS or e.get("ok") is False:
        flags.append("dangerous")
    if _LEAK_RE.search(detail) or "leak" in action:
        flags.append("leak_suspect")
    if "download_denied" in action or "blocked" in action:
        flags.append("access_denied")
    return flags


def spotcheck(limit: int = 800) -> dict:
    """Aggregate users/sessions for workforce spot-check review."""
    events = recent(max(100, limit))
    usage_events: list[dict] = []
    try:
        from hosting import USAGE_FILE

        if USAGE_FILE.is_file():
            for line in USAGE_FILE.read_text(encoding="utf-8").splitlines()[-limit:]:
                try:
                    usage_events.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass

    by_user: dict[str, dict] = {}

    def slot(key: str) -> dict:
        if key not in by_user:
            by_user[key] = {
                "user": key,
                "tokens": 0,
                "models": {},
                "actions": 0,
                "fails": 0,
                "flags": set(),
                "sessions": set(),
                "last_ts": 0.0,
                "timeline": [],
                "categories": defaultdict(int),
            }
        return by_user[key]

    for e in events:
        key = (e.get("user") or e.get("ip") or "local").strip() or "local"
        s = slot(key)
        s["actions"] += 1
        if e.get("ok") is False:
            s["fails"] += 1
        s["tokens"] += int(e.get("tokens") or 0)
        model = e.get("model") or ""
        if model:
            s["models"][model] = s["models"].get(model, 0) + int(e.get("tokens") or 0)
        sid = int(e.get("session_id") or 0)
        if sid:
            s["sessions"].add(sid)
        ts = float(e.get("ts") or 0)
        if ts > s["last_ts"]:
            s["last_ts"] = ts
        cat = e.get("category") or "general"
        s["categories"][cat] += 1
        for f in _flag_event(e):
            s["flags"].add(f)
        if len(s["timeline"]) < 12:
            s["timeline"].append(
                {
                    "ts": ts,
                    "action": e.get("action"),
                    "detail": (e.get("detail") or "")[:160],
                    "ok": e.get("ok", True),
                    "model": model,
                    "tokens": int(e.get("tokens") or 0),
                }
            )

    for e in usage_events:
        key = (e.get("user") or e.get("ip") or "local").strip() or "local"
        s = slot(key)
        tok = int(e.get("tokens") or 0)
        s["tokens"] += tok
        model = e.get("model") or "unknown"
        s["models"][model] = s["models"].get(model, 0) + tok
        ts = float(e.get("ts") or 0)
        if ts > s["last_ts"]:
            s["last_ts"] = ts

    rows = []
    for s in by_user.values():
        flags = sorted(s["flags"])
        status = "safe"
        if "leak_suspect" in flags or "dangerous" in flags:
            status = "concern" if "leak_suspect" in flags else "suspicious"
        elif s["fails"] >= 3:
            status = "suspicious"
            flags.append("auth_burst")
        rows.append(
            {
                "user": s["user"],
                "tokens": s["tokens"],
                "models": [
                    {"model": m, "tokens": n}
                    for m, n in sorted(s["models"].items(), key=lambda x: -x[1])[:8]
                ],
                "actions": s["actions"],
                "fails": s["fails"],
                "flags": flags,
                "status": status,
                "sessions": len(s["sessions"]),
                "last_ts": s["last_ts"],
                "last_seen": time.strftime("%Y-%m-%d %H:%M", time.localtime(s["last_ts"]))
                if s["last_ts"]
                else "—",
                "categories": dict(s["categories"]),
                "timeline": list(reversed(s["timeline"]))[:10],
            }
        )
    rows.sort(key=lambda r: (-len(r["flags"]), -r["tokens"], -r["actions"]))
    return {
        "ok": True,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "users": rows,
        "totals": {
            "users": len(rows),
            "tokens": sum(r["tokens"] for r in rows),
            "flagged": sum(1 for r in rows if r["flags"]),
            "events": len(events),
        },
    }

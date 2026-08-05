"""Host-surface hardening (EPIC-D03 F7a/F8a).

F7a: cheap caching helpers. F8a: establish handshake (session nonce).
True load balancer / multi-worker remains PARK P8 — one strong PC only.
"""
from __future__ import annotations

import secrets
import threading
import time
from typing import Any

SECURITY_VERSION = "airgpt-sec-1"
ESTABLISH_TTL_SEC = 3600.0

_lock = threading.Lock()
_sessions: dict[str, dict[str, Any]] = {}


def _key(ip: str, token: str) -> str:
    return f"{(ip or '').strip()}|{(token or '').strip()[:80]}"


def establish(*, ip: str, token: str = "", host_verified: bool = False) -> dict[str, Any]:
    """Issue a session nonce bound to client ip (+ optional chat token)."""
    nonce = secrets.token_urlsafe(24)
    now = time.time()
    rec = {
        "nonce": nonce,
        "ip": ip,
        "token": (token or "")[:80],
        "host_verified": bool(host_verified),
        "created_at": now,
        "expires_at": now + ESTABLISH_TTL_SEC,
        "security_version": SECURITY_VERSION,
    }
    with _lock:
        # prune occasionally
        if len(_sessions) > 5000:
            dead = [k for k, v in _sessions.items() if float(v.get("expires_at") or 0) < now]
            for k in dead[:2000]:
                _sessions.pop(k, None)
        _sessions[_key(ip, token)] = rec
        _sessions[nonce] = rec  # lookup by nonce header too
    return {
        "ok": True,
        "security_version": SECURITY_VERSION,
        "session_nonce": nonce,
        "expires_in": int(ESTABLISH_TTL_SEC),
        "host_verified": bool(host_verified),
        "policy": {
            "require_establish_remote": True,
            "host_local_bypass": True,
            "load_balancer": False,
            "note": "Single-PC ThreadingHTTPServer; true LB is parked (P8).",
        },
    }


def verify(*, ip: str, token: str = "", nonce: str = "", local_bypass: bool = False) -> dict[str, Any]:
    if local_bypass:
        return {"ok": True, "bypass": "local_host", "security_version": SECURITY_VERSION}
    n = (nonce or "").strip()
    if not n:
        return {"ok": False, "error": "establish_required", "hint": "POST /api/establish first"}
    now = time.time()
    with _lock:
        rec = _sessions.get(n) or _sessions.get(_key(ip, token))
    if not rec:
        return {"ok": False, "error": "establish_unknown", "hint": "POST /api/establish"}
    if float(rec.get("expires_at") or 0) < now:
        return {"ok": False, "error": "establish_expired", "hint": "re-POST /api/establish"}
    if rec.get("nonce") != n:
        return {"ok": False, "error": "establish_mismatch"}
    # soft bind: ip should match; allow if host_verified session
    if rec.get("ip") and rec.get("ip") != ip and not rec.get("host_verified"):
        return {"ok": False, "error": "establish_ip_mismatch"}
    return {
        "ok": True,
        "security_version": SECURITY_VERSION,
        "session_nonce": n,
        "host_verified": bool(rec.get("host_verified")),
    }


def security_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h = {
        "X-AirGPT-Security-Version": SECURITY_VERSION,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Connection": "keep-alive",
    }
    if extra:
        h.update(extra)
    return h


# Paths that need establish for non-local clients
_PROTECTED_PREFIXES = (
    "/api/rag/answers",
    "/api/ai/",
    "/api/chat",
    "/api/cortex/invoke",
)


def path_needs_establish(path: str) -> bool:
    p = path or ""
    return any(p == pref or p.startswith(pref) for pref in _PROTECTED_PREFIXES)

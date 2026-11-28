"""Status and setup payloads. These dicts never carry the token."""
from __future__ import annotations

from bundle.onboarding import public_steps
from bundle.posture import (
    BIND_ALL_WARNING,
    LOOPBACK,
    TUNNEL_OPT_IN_WARNING,
    resolve_bind_host,
    tunnel_opted_in,
)
from bundle.token_store import describe, ensure

_SECRET_KEYS = frozenset({"token", "secret", "password", "service_token", "value"})


def _public(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k not in _SECRET_KEYS}


def status_payload() -> dict:
    info = describe()
    host = resolve_bind_host()
    return _public({
        "ok": True,
        "token_stored": bool(info["stored"]),
        "token_where": info.get("where") or "",
        "token_path": info.get("path") or "",
        "bind": host,
        "loopback": host == LOOPBACK,
        "tunnel": "on" if tunnel_opted_in() else "off",
        "tunnel_warning": TUNNEL_OPT_IN_WARNING,
        "bind_warning": BIND_ALL_WARNING,
        "steps": public_steps(),
    })


def setup_payload() -> dict:
    info = ensure()
    return _public({
        "ok": True,
        "token_stored": True,
        "token_where": info.get("where") or "",
        "token_path": info.get("path") or "",
        "tunnel_warning": TUNNEL_OPT_IN_WARNING,
    })

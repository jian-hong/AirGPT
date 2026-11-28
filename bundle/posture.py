"""Bind address and public-tunnel defaults.

The server listens on loopback unless AIRGPT_BIND says otherwise.
The public tunnel stays off unless AIRGPT_TUNNEL is set, or the host
confirms it in the UI. Neither path prints a secret.
"""
from __future__ import annotations

import os

LOOPBACK = "127.0.0.1"

TUNNEL_OPT_IN_WARNING = (
    "Public tunnel is off by default. Turning it on publishes this computer "
    "on the internet through cloudflared or another provider. Anyone with the "
    "URL can reach the sign-in page. Only continue if you accept that."
)

BIND_ALL_WARNING = (
    "AIRGPT_BIND is not loopback. AirGPT will accept connections from other "
    "machines. The default is 127.0.0.1, this computer only."
)

_TUNNEL_ON = frozenset({"1", "true", "yes", "on"})


def _env(env: dict | None) -> dict:
    if env is None:
        return os.environ
    return env


def resolve_bind_host(env: dict | None = None) -> str:
    src = _env(env)
    raw = str(src.get("AIRGPT_BIND") or src.get("AIRGPT_HOST") or LOOPBACK).strip()
    if not raw or raw.lower() in ("loopback", "localhost"):
        return LOOPBACK
    return raw


def tunnel_opted_in(env: dict | None = None) -> bool:
    raw = str(_env(env).get("AIRGPT_TUNNEL") or "").strip().lower()
    return raw in _TUNNEL_ON


def bind_is_loopback(host: str | None = None) -> bool:
    value = LOOPBACK if host is None else host
    return value in (LOOPBACK, "::1", "localhost")

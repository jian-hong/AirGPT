"""Cortex runtime isolation — prevent secret/runtime leaks.

Boundaries:
  - Local Cortex agent runtime never embeds DMS/sidecar secrets in prompts or tool dumps
  - Sidecar receives only gated user text / audit events — never raw API keys
  - Cloud BYOK keys stay in env.local; redacted from logs and agent results
  - memory_scope project|local never exfiltrates via web_search without audit

Product posture: we sell *management + auditable governance*; inference backends
(vLLM/Colibri/GGUF/cloud) are swappable. Governance stays local-first; cloud access
is explicit and logged.
"""
from __future__ import annotations

import os
import re
from typing import Any

# Patterns that must never appear in agent SSE / audit payloads
_SECRET_KEYS = (
    "API_KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PRIVATE_KEY",
    "CORTEX_API_KEY",
    "STRIPE_",
    "RESEND_API_KEY",
)

_RE_KEYISH = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer\s+[a-z0-9\-._~+/]+=*|sk-[a-z0-9]{10,}|ghp_[a-z0-9]{20,})"
)


def redact_text(text: str, *, max_len: int = 4000) -> str:
    if not text:
        return text
    out = _RE_KEYISH.sub("[redacted]", text)
    # scrub env values if they appear verbatim
    for k, v in os.environ.items():
        if not v or len(v) < 8:
            continue
        if any(s in k.upper() for s in _SECRET_KEYS):
            if v in out:
                out = out.replace(v, "[redacted]")
    return out[:max_len]


def redact_obj(obj: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "[truncated]"
    if isinstance(obj, dict):
        clean = {}
        for k, v in obj.items():
            ku = str(k).upper()
            if any(s in ku for s in _SECRET_KEYS):
                clean[k] = "[redacted]"
            else:
                clean[k] = redact_obj(v, depth=depth + 1)
        return clean
    if isinstance(obj, list):
        return [redact_obj(x, depth=depth + 1) for x in obj[:50]]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


def safe_tool_result(result: dict) -> dict:
    """Sanitize tool outputs before SSE / UI."""
    if not isinstance(result, dict):
        return {"ok": False, "error": "invalid"}
    return redact_obj(result)  # type: ignore[return-value]


def cortex_cloud_allowed() -> bool:
    """Business/cloud governance switch — default allow BYOK; set CORTEX_LOCAL_ONLY=1 to lock."""
    v = (os.environ.get("CORTEX_LOCAL_ONLY") or "").strip().lower()
    if v in ("1", "true", "yes"):
        return False
    try:
        from ai_engine import load_env

        env = load_env()
        v2 = (env.get("CORTEX_LOCAL_ONLY") or "").strip().lower()
        return v2 not in ("1", "true", "yes")
    except Exception:
        return True


def isolation_status() -> dict:
    return {
        "ok": True,
        "local_only": not cortex_cloud_allowed(),
        "sidecar": "optional soft-fail DMS — never receives API keys",
        "agent_runtime": "in-process AirGPT; tools audited; outputs redacted",
        "inference": "vLLM/Colibri/GGUF/cloud are backends only — Cortex orchestrates",
        "leak_controls": [
            "redact_text on agent SSE tool dumps",
            "CORTEX_LOCAL_ONLY blocks cloud BYOK when set",
            "env.local secrets never posted to Cortex sidecar",
            "audit hashes args — not raw secrets",
        ],
    }

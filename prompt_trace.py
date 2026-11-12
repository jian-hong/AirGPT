"""Prompt lens: a record of what one chat turn actually sent to the model.

The trace is assembled at the same lines that build the real request, so it cannot
describe a prompt that was not sent. It is stored next to the reply it produced and
read back by `GET /api/chat/prompt-trace`.

Two honesty limits, both stated in the trace itself rather than hidden:

- Token counts are an ESTIMATE (characters / 4). No provider tokenizer runs here.
- On the Cortex route AirGPT only knows what it handed to Cortex. Cortex adds its own
  system prompt and tool schemas on its side; those are not visible from here and the
  trace says so instead of inventing them.
"""
from __future__ import annotations

import json
import math
import time

import db

VERSION = 1
KEEP_ROWS = 400          # newest traces kept; older ones are pruned on write
MAX_SECTION_CHARS = 24000  # stored text per section; the real size is kept in `chars`


def est_tokens(text: str) -> int:
    return int(math.ceil(len(text or "") / 4))


def section(key: str, label: str, text: str, *, private: bool = False, note: str = "") -> dict:
    text = text or ""
    out = {
        "key": key,
        "label": label,
        "chars": len(text),
        "tokens_est": est_tokens(text),
        "text": text[:MAX_SECTION_CHARS],
    }
    if len(text) > MAX_SECTION_CHARS:
        out["text_truncated"] = True
    if private:
        out["private"] = True
    if note:
        out["note"] = note
    return out


def new(route: str, *, mode: str = "", tier: str = "") -> dict:
    return {
        "v": VERSION,
        "route": route,
        "mode": mode,
        "tier": tier,
        "sections": [],
        "notes": [],
        "token_method": "estimate: characters / 4",
    }


def add(trace: dict | None, key: str, label: str, text: str, **kw) -> None:
    """Append a section. Empty text is skipped: an empty block was not sent."""
    if trace is None or not (text or "").strip():
        return
    trace["sections"].append(section(key, label, text, **kw))


def finalize(trace: dict) -> dict:
    secs = trace.get("sections") or []
    trace["total_chars"] = sum(int(s.get("chars") or 0) for s in secs)
    trace["tokens_est"] = sum(int(s.get("tokens_est") or 0) for s in secs)
    return trace


def redact_private(trace: dict) -> dict:
    """Copy of the trace with private section text removed (sizes stay)."""
    out = dict(trace)
    secs = []
    for s in trace.get("sections") or []:
        if s.get("private"):
            s = {k: v for k, v in s.items() if k != "text"}
            s["redacted"] = True
        secs.append(s)
    out["sections"] = secs
    return out


# --- storage ------------------------------------------------------------------------

_ready = False


def _ensure() -> None:
    global _ready
    if _ready:
        return
    with db._lock, db._connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS prompt_traces ("
            "message_id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL DEFAULT 0, "
            "created_at REAL NOT NULL, trace TEXT NOT NULL)"
        )
        conn.commit()
    _ready = True


def save(message_id: int, session_id: int, trace: dict) -> bool:
    if not message_id or not isinstance(trace, dict):
        return False
    _ensure()
    blob = json.dumps(finalize(trace), ensure_ascii=False)
    with db._lock, db._connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO prompt_traces(message_id,session_id,created_at,trace) VALUES(?,?,?,?)",
            (int(message_id), int(session_id or 0), time.time(), blob),
        )
        conn.execute(
            "DELETE FROM prompt_traces WHERE message_id NOT IN "
            "(SELECT message_id FROM prompt_traces ORDER BY message_id DESC LIMIT ?)",
            (KEEP_ROWS,),
        )
        conn.commit()
    return True


def load(message_id: int) -> dict | None:
    """Return {message_id, session_id, created_at, trace} or None when not recorded."""
    if not message_id:
        return None
    _ensure()
    with db._lock, db._connect() as conn:
        row = conn.execute(
            "SELECT message_id,session_id,created_at,trace FROM prompt_traces WHERE message_id=?",
            (int(message_id),),
        ).fetchone()
    if not row:
        return None
    try:
        trace = json.loads(row["trace"])
    except (TypeError, ValueError):
        return None
    return {
        "message_id": int(row["message_id"]),
        "session_id": int(row["session_id"]),
        "created_at": float(row["created_at"]),
        "trace": trace,
    }


def latest_for_session(session_id: int) -> dict | None:
    if not session_id:
        return None
    _ensure()
    with db._lock, db._connect() as conn:
        row = conn.execute(
            "SELECT message_id FROM prompt_traces WHERE session_id=? ORDER BY message_id DESC LIMIT 1",
            (int(session_id),),
        ).fetchone()
    return load(int(row["message_id"])) if row else None

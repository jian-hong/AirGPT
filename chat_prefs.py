"""Custom instructions for one chat: standing text sent with every turn of that chat.

Stored in its own small table, created lazily (same way prompt_trace.py does it), so
the main schema is untouched. The text is sent only on turns of the chat it belongs to.
"""
from __future__ import annotations

import time

import db

MAX_CHARS = 4000

_ready = False


def _ensure() -> None:
    global _ready
    if _ready:
        return
    with db._lock, db._connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS session_prefs ("
            "session_id INTEGER PRIMARY KEY, instructions TEXT NOT NULL DEFAULT '', "
            "updated_at REAL NOT NULL DEFAULT 0)"
        )
        conn.commit()
    _ready = True


def get(session_id: int) -> str:
    try:
        sid = int(session_id or 0)
    except (TypeError, ValueError):
        return ""
    if sid <= 0:
        return ""
    _ensure()
    with db._lock, db._connect() as conn:
        row = conn.execute(
            "SELECT instructions FROM session_prefs WHERE session_id=?", (sid,)
        ).fetchone()
    return str(row["instructions"] or "") if row else ""


def set(session_id: int, text: str) -> str:  # noqa: A001 - name is the agreed API
    """Save (or clear, when empty). Raises ValueError with a plain message if refused."""
    sid = int(session_id or 0)
    if sid <= 0:
        raise ValueError("This chat has not been created yet. Send a message first.")
    if not isinstance(text, str):
        raise ValueError("Instructions must be text.")
    text = text.strip()
    if len(text) > MAX_CHARS:
        raise ValueError(
            f"Too long: {len(text):,} characters. The limit is {MAX_CHARS:,}. Shorten it and try again."
        )
    _ensure()
    with db._lock, db._connect() as conn:
        if text:
            conn.execute(
                "INSERT OR REPLACE INTO session_prefs(session_id,instructions,updated_at) VALUES(?,?,?)",
                (sid, text, time.time()),
            )
        else:
            conn.execute("DELETE FROM session_prefs WHERE session_id=?", (sid,))
        conn.commit()
    return text


def block(text: str) -> str:
    """The exact block added to a prompt. Empty when there is nothing to send."""
    text = (text or "").strip()
    if not text:
        return ""
    return (
        "\n## Chat instructions (set by the user for this chat only; follow them on every reply)\n"
        f"{text}\n"
        "## End of chat instructions\n"
    )

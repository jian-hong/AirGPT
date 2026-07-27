"""Who else is in this chat right now.

Live message delivery already works: `syncLoop()` long-polls `/api/wait`, and a peer's
message lands in your open session without a refresh. What was missing is that nothing
on screen said so — `renderMsg()` used `device_name` only to pick left/right alignment,
so a shared session looked exactly like a private one.

This module is the missing half: an in-memory roster of who is currently in each
session. It is deliberately not persisted. Presence is a statement about *now*; a
roster that survives a restart would be a roster of ghosts.

Piggybacks on the existing `/api/wait` poll — every poll is a heartbeat, so there is no
second timer and no websocket.
"""
from __future__ import annotations

import threading
import time

# A peer is "here" if they polled within this window. The client polls continuously
# while the tab is open, so this only needs to survive a slow round-trip, not a nap.
HERE_WINDOW_SEC = 30.0

# Typing decays fast on its own: the client sends typing=false on send, but it can also
# just close the laptop mid-word, and a three-dot chip that never goes away is worse
# than no chip at all.
TYPING_WINDOW_SEC = 6.0

_lock = threading.Lock()
# {session_id: {ip: {...}}}
_rooms: dict[int, dict[str, dict]] = {}


def _icon_for(name: str, ua: str = "") -> str:
    """Reuse the Hub's device classification so the two surfaces never disagree."""
    try:
        import hub

        return hub._device_icon(name, ua)
    except Exception:
        return "desktop"


def _prune(room: dict[str, dict], now: float) -> None:
    for ip in [ip for ip, m in room.items() if now - m.get("last_seen", 0) > HERE_WINDOW_SEC]:
        room.pop(ip, None)


def touch(
    session_id: int | None,
    ip: str,
    *,
    name: str = "",
    user_agent: str = "",
    device_id: str = "",
) -> None:
    """Heartbeat. Called from the /api/wait poll — never on its own timer."""
    if not session_id or not ip:
        return
    now = time.time()
    sid = int(session_id)
    with _lock:
        room = _rooms.setdefault(sid, {})
        entry = room.get(ip) or {}
        # A later poll with a blank name must not erase a name we already learned.
        display = (name or entry.get("name") or "").strip()[:60]
        entry.update(
            {
                "ip": ip,
                "name": display,
                "device_id": device_id or entry.get("device_id") or ip,
                "icon": _icon_for(display, user_agent) if display or user_agent else entry.get("icon", "desktop"),
                "last_seen": now,
            }
        )
        entry.setdefault("typing_at", 0.0)
        entry.setdefault("first_seen", now)
        room[ip] = entry
        _prune(room, now)


def set_typing(session_id: int | None, ip: str, typing: bool) -> dict:
    if not session_id or not ip:
        return {"ok": False, "error": "session_id and ip required"}
    now = time.time()
    sid = int(session_id)
    with _lock:
        room = _rooms.setdefault(sid, {})
        entry = room.setdefault(ip, {"ip": ip, "name": "", "icon": "desktop", "first_seen": now})
        entry["last_seen"] = now
        entry["typing_at"] = now if typing else 0.0
    return {"ok": True}


def members(session_id: int | None, *, exclude_ip: str = "") -> list[dict]:
    """Everyone currently in the room, newest arrival last. Excludes the caller."""
    if not session_id:
        return []
    now = time.time()
    sid = int(session_id)
    with _lock:
        room = _rooms.get(sid)
        if not room:
            return []
        _prune(room, now)
        out = []
        for ip, m in room.items():
            if exclude_ip and ip == exclude_ip:
                continue
            out.append(
                {
                    "ip": ip,
                    "name": m.get("name") or ip,
                    "icon": m.get("icon") or "desktop",
                    "typing": (now - m.get("typing_at", 0)) < TYPING_WINDOW_SEC,
                    "idle": (now - m.get("last_seen", 0)) > 60,
                    "since": m.get("first_seen") or now,
                }
            )
    out.sort(key=lambda x: x["since"])
    return out


def forget(session_id: int | None, ip: str) -> None:
    """Explicit leave — the host kicking a peer should empty the seat immediately."""
    if not session_id or not ip:
        return
    with _lock:
        room = _rooms.get(int(session_id))
        if room:
            room.pop(ip, None)


def snapshot() -> dict:
    """Debug view: every room and its occupants. Used by /api/presence."""
    now = time.time()
    with _lock:
        return {
            str(sid): [
                {"ip": ip, "name": m.get("name"), "age": round(now - m.get("last_seen", now), 1)}
                for ip, m in room.items()
            ]
            for sid, room in _rooms.items()
        }

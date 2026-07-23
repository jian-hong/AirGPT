"""Record keyboard input into timestamped note files (5-minute session labels)."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTES_DIR = ROOT / "data" / "input_notes"
NOTES_DIR.mkdir(parents=True, exist_ok=True)
GAP_SEC = 300

_lock = threading.Lock()
_state: dict = {
    "recording": False,
    "entries": [],
    "buffer": "",
    "listener": None,
    "global_hook": False,
}


def _flush_buffer() -> None:
    text = _state["buffer"]
    if text:
        _state["entries"].append({"ts": time.time(), "text": text})
        _state["buffer"] = ""


def _on_press(key) -> None:
    if not _state["recording"]:
        return
    try:
        ch = key.char
        if ch:
            _state["buffer"] += ch
            return
    except AttributeError:
        pass
    from pynput.keyboard import Key

    if key == Key.space:
        _state["buffer"] += " "
    elif key == Key.enter:
        _state["buffer"] += "\n"
        _flush_buffer()
    elif key == Key.backspace:
        _state["buffer"] = _state["buffer"][:-1]
    elif key == Key.tab:
        _state["buffer"] += "\t"


def append_text(text: str, source: str = "browser") -> None:
    if not _state["recording"] or not text:
        return
    with _lock:
        _state["entries"].append({"ts": time.time(), "text": text, "source": source})
        _state["buffer"] = ""


def append_char(ch: str) -> None:
    if not _state["recording"] or not ch:
        return
    with _lock:
        if ch == "\n":
            _state["buffer"] += "\n"
            _flush_buffer()
        elif ch == "\b":
            _state["buffer"] = _state["buffer"][:-1]
        else:
            _state["buffer"] += ch


def _group_entries(entries: list) -> list[dict]:
    groups: list[dict] = []
    last_ts = 0.0
    for e in entries:
        ts = float(e["ts"])
        if not groups or ts - last_ts >= GAP_SEC:
            groups.append({"ts": ts, "lines": []})
        groups[-1]["lines"].append(e.get("text", ""))
        last_ts = ts
    return groups


def _render_markdown(entries: list) -> str:
    groups = _group_entries(entries)
    lines = [f"# Input notes — {datetime.now():%Y-%m-%d %H:%M:%S}", ""]
    for g in groups:
        label = datetime.fromtimestamp(g["ts"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f"## {label}")
        lines.append("")
        body = "".join(g["lines"]).strip()
        if body:
            lines.append(body)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def start_recording() -> dict:
    with _lock:
        if _state["recording"]:
            return {"ok": True, "recording": True, "global_hook": _state["global_hook"]}
        _state["entries"] = []
        _state["buffer"] = ""
        _state["recording"] = True
        _state["global_hook"] = False
        try:
            from pynput import keyboard

            _state["listener"] = keyboard.Listener(on_press=_on_press)
            _state["listener"].start()
            _state["global_hook"] = True
        except Exception:
            _state["listener"] = None
    return {
        "ok": True,
        "recording": True,
        "global_hook": _state["global_hook"],
        "hint": "Global keyboard hook active" if _state["global_hook"] else "Keep ClipDrop focused — install pynput for system-wide capture",
    }


def stop_recording() -> dict:
    with _lock:
        if not _state["recording"]:
            return {"ok": False, "error": "not recording"}
        _flush_buffer()
        _state["recording"] = False
        if _state["listener"]:
            try:
                _state["listener"].stop()
            except Exception:
                pass
            _state["listener"] = None
        entries = list(_state["entries"])
        _state["entries"] = []
    if not entries:
        return {"ok": True, "saved": False, "message": "Nothing recorded"}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = NOTES_DIR / f"notes_{stamp}.md"
    json_path = NOTES_DIR / f"notes_{stamp}.json"
    md_path.write_text(_render_markdown(entries), encoding="utf-8")
    json_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "saved": True,
        "path": str(md_path.relative_to(ROOT)).replace("\\", "/"),
        "entries": len(entries),
        "preview": _render_markdown(entries)[:800],
    }


def status() -> dict:
    with _lock:
        return {
            "recording": _state["recording"],
            "global_hook": _state["global_hook"],
            "buffer_len": len(_state["buffer"]),
            "entries": len(_state["entries"]),
        }


def list_notes(limit: int = 20) -> list[dict]:
    files = sorted(NOTES_DIR.glob("notes_*.md"), reverse=True)[:limit]
    out = []
    for p in files:
        out.append({
            "name": p.name,
            "path": str(p.relative_to(ROOT)).replace("\\", "/"),
            "size": p.stat().st_size,
            "modified": p.stat().st_mtime,
        })
    return out


def read_note(name: str) -> str | None:
    safe = Path(name).name
    p = NOTES_DIR / safe
    if not p.is_file() or p.suffix != ".md":
        return None
    return p.read_text(encoding="utf-8")

"""Global slash-command registry (Cursor/Claude-style)."""
from __future__ import annotations

from typing import Any

COMMANDS: list[dict[str, Any]] = [
    {"name": "rag", "description": "Open RAG page or select a knowledge space", "args": "[name]"},
    {"name": "rag new", "description": "Create a new RAG knowledge space", "args": "<name>"},
    {"name": "ingest", "description": "Ingest files/folder into current RAG", "args": "<path>"},
    {"name": "search", "description": "Retrieval-only search in current RAG", "args": "<query>"},
    {"name": "cite", "description": "Force citation mode on next answer", "args": ""},
    {"name": "trace", "description": "Show last retrieval trace", "args": "[trace_id]"},
    {"name": "agents", "description": "Open Apps (built agents catalog)", "args": ""},
    {"name": "memory", "description": "Open Memory Agent / panel", "args": ""},
    {"name": "depth", "description": "Set turn depth", "args": "basic|high|max"},
    {"name": "create-subagent", "description": "Create a focused subagent and open Cortex", "args": "<name> [prompt]"},
    {"name": "edit", "description": "Tweak the last agent / open edit hints", "args": "[what to change]"},
    {"name": "skill", "description": "Enable a skill pack", "args": "<pack> [global|project|off]"},
    {"name": "rules", "description": "Show or edit workspace rules", "args": "[edit]"},
    {"name": "subagent", "description": "Queue a helper subagent", "args": "<prompt>"},
    {"name": "research", "description": "Fan out background research subagents on a topic", "args": "<topic>"},
    {"name": "workflow", "description": "Run a preset background workflow", "args": "[id]"},
]


def _all_commands() -> list[dict[str, Any]]:
    """Static COMMANDS + dynamic skill/rules/subagent entries from invoke_registry."""
    out = list(COMMANDS)
    seen = {c["name"] for c in out}
    try:
        import invoke_registry

        for c in invoke_registry.skill_slash_commands():
            name = c.get("name") or ""
            if name and name not in seen:
                out.append(c)
                seen.add(name)
    except Exception:
        pass
    return out


def list_commands(prefix: str = "") -> list[dict]:
    cmds = _all_commands()
    p = (prefix or "").lstrip("/").lower()
    if not p:
        return list(cmds)
    return [c for c in cmds if c["name"].startswith(p) or p in c["name"]]


def parse_slash(text: str) -> dict | None:
    """Parse leading /command from a message. Returns None if not a slash command."""
    s = (text or "").strip()
    if not s.startswith("/"):
        return None
    body = s[1:].strip()
    if not body:
        return {"command": "", "args": "", "raw": s}
    # longest-name match first
    names = sorted({c["name"] for c in _all_commands()}, key=len, reverse=True)
    lower = body.lower()
    for name in names:
        if lower == name or lower.startswith(name + " "):
            args = body[len(name) :].strip()
            return {"command": name, "args": args, "raw": s}
    # first token fallback
    parts = body.split(None, 1)
    return {"command": parts[0].lower(), "args": parts[1] if len(parts) > 1 else "", "raw": s}

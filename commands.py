"""Global slash-command registry (Cursor/Claude-style)."""
from __future__ import annotations

import re
from typing import Any

_SKILL_SCOPES = frozenset({"global", "project", "off"})
_COLON_SKILL_RE = re.compile(
    r"^/(anthropic-skills|skill):([A-Za-z0-9][\w.-]*)(?:\s+(.*))?$",
    re.IGNORECASE | re.DOTALL,
)
_HYPHEN_SKILL_RE = re.compile(
    r"^/skill-([A-Za-z0-9][\w.-]*)(?:\s+(.*))?$",
    re.IGNORECASE | re.DOTALL,
)
_BARE_SKILL_RE = re.compile(r"^/skill(?:\s+|$)(.*)$", re.IGNORECASE | re.DOTALL)

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
    {"name": "skill", "description": "Force a skill pack (always wins over auto-wire)", "args": "<pack> [global|project|off] [job]"},
    {"name": "anthropic-skills", "description": "Force a skill pack (colon form)", "args": ":<pack> [job]"},
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


def peel_skill_slash(text: str) -> dict | None:
    """Pull a forced skill pack off the leading slash; remainder is the job.

    Forms (SHELL-03 / DR-0002):
      /skill <pack> [global|project|off] [job]
      /skill:<pack> [job]
      /skill-<pack> [job]
      /anthropic-skills:<pack> [job]
    Returns None when the text is not a skill slash.
    """
    s = (text or "").strip()
    if not s.startswith("/"):
        return None
    m = _COLON_SKILL_RE.match(s)
    if m:
        return {
            "pack": m.group(2).lower(),
            "scope": "",
            "rest": (m.group(3) or "").strip(),
            "form": m.group(1).lower(),
            "raw": s,
        }
    m = _HYPHEN_SKILL_RE.match(s)
    if m:
        return {
            "pack": m.group(1).lower(),
            "scope": "",
            "rest": (m.group(2) or "").strip(),
            "form": "skill-id",
            "raw": s,
        }
    m = _BARE_SKILL_RE.match(s)
    if not m:
        return None
    tail = (m.group(1) or "").strip()
    if not tail:
        return {"pack": "", "scope": "", "rest": "", "form": "skill", "raw": s}
    bits = tail.split()
    pack = bits[0].lower().lstrip(":")
    scope = ""
    rest = ""
    if len(bits) >= 2 and bits[1].lower() in _SKILL_SCOPES:
        scope = bits[1].lower()
        rest = " ".join(bits[2:])
    else:
        rest = " ".join(bits[1:])
    return {"pack": pack, "scope": scope, "rest": rest, "form": "skill", "raw": s}


def parse_slash(text: str) -> dict | None:
    """Parse leading /command from a message. Returns None if not a slash command."""
    s = (text or "").strip()
    if not s.startswith("/"):
        return None
    peeled = peel_skill_slash(s)
    if peeled and peeled.get("pack"):
        form = peeled.get("form") or "skill"
        if form == "skill-id":
            cmd = f"skill-{peeled['pack']}"
            args = peeled.get("rest") or ""
        elif form == "anthropic-skills":
            cmd = "anthropic-skills"
            args = peeled["pack"] + ((" " + peeled["rest"]) if peeled.get("rest") else "")
        else:
            cmd = "skill"
            parts = [peeled["pack"]]
            if peeled.get("scope"):
                parts.append(peeled["scope"])
            if peeled.get("rest"):
                parts.append(peeled["rest"])
            args = " ".join(parts)
        return {
            "command": cmd,
            "args": args,
            "raw": s,
            "pack": peeled["pack"],
            "scope": peeled.get("scope") or "",
            "rest": peeled.get("rest") or "",
        }
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

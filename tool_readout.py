"""Claude Code-style grouped tool-call readout (F20a / SHELL-01).

The host shell (index.html runCortexAgentStream) mirrors this grouping:
consecutive tool / tool_call events collapse into one expandable row with
kinds, counts, and +N -M from fs_write / fs_patch line deltas.
"""
from __future__ import annotations

from typing import Any


def group_tool_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse a consecutive tool burst into one summary segment."""
    kinds: dict[str, int] = {}
    plus = 0
    minus = 0
    has_delta = False
    items: list[dict[str, Any]] = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        name = str(ev.get("name") or "tool")
        kinds[name] = kinds.get(name, 0) + 1
        result = ev.get("result") if isinstance(ev.get("result"), dict) else {}
        # Key names must match the producer. OpenIDE/workspace_api.py `line_delta`
        # returns {"added", "removed"} and index.html reads j.result.added /
        # .removed; this gated on added_lines/deleted_lines, so it never matched a
        # real fs_write result and every delta was silently dropped. The gate did
        # not catch it because it hand-fed the names this side expected.
        if "added" in result and "removed" in result:
            plus += int(result.get("added") or 0)
            minus += int(result.get("removed") or 0)
            has_delta = True
        items.append(ev)
    kind_list = sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "count": len(items),
        "kinds": kinds,
        "kind_list": kind_list,
        "added_lines": plus if has_delta else None,
        "deleted_lines": minus if has_delta else None,
        "items": items,
    }


def format_delta(added: int | None, deleted: int | None) -> str:
    if added is None or deleted is None:
        return ""
    return f" +{int(added)} -{int(deleted)}"

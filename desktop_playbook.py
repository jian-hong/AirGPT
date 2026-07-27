"""Human-style task routing: research first, then pick the best open surface.

Example: write an essay -> prefer Word if open; else ChatGPT/Claude tab if
present and tokens remain; else tutorial-only plan. Mid-task hop when rate-limited.
"""
from __future__ import annotations

from typing import Any

import desktop_control


_WRITING = ("essay", "novel", "article", "blog", "write", "draft", "story", "paper")
_CODE = ("code", "refactor", "bug", "implement", "pr", "repo", "typescript", "python")
_RESEARCH = ("research", "compare", "find", "search", "what is", "how does")


def _task_kind(goal: str) -> str:
    g = (goal or "").lower()
    if any(w in g for w in _CODE):
        return "code"
    if any(w in g for w in _WRITING):
        return "writing"
    if any(w in g for w in _RESEARCH):
        return "research"
    return "general"


def plan_task(
    goal: str,
    *,
    tokens_left: int | None = None,
    prefer: str | None = None,
    act: bool = False,
) -> dict[str, Any]:
    """Build a chill-but-smart plan. Does not move the mouse unless act+confirmed later."""
    kind = _task_kind(goal)
    scene = desktop_control.observe()
    wins = (scene.get("windows") or {}).get("windows") or []
    kinds = {w.get("kind") for w in wins}
    fg = (scene.get("foreground") or {})
    fg_title = str(fg.get("title") or "")
    fg_kind = "other"
    low = fg_title.lower()
    for k, needles in (
        ("word", ("word", ".docx", ".doc")),
        ("chatgpt", ("chatgpt", "openai")),
        ("claude", ("claude",)),
        ("cursor", ("cursor",)),
        ("browser", ("chrome", "edge", "firefox", "brave")),
    ):
        if any(n in low for n in needles):
            fg_kind = k
            break

    steps: list[dict[str, Any]] = []
    primary = prefer or ""
    rationale: list[str] = []

    if kind == "writing":
        if prefer in ("word", "chatgpt", "claude"):
            primary = prefer
            rationale.append(f"User preferred {prefer}.")
        elif "word" in kinds or fg_kind == "word":
            primary = "word"
            rationale.append("Word is already open - write there so you keep formatting/control.")
        elif "claude" in kinds and (tokens_left is None or tokens_left > 500):
            primary = "claude"
            rationale.append("Claude window is open and tokens look fine - draft there, paste to Word later.")
        elif "chatgpt" in kinds and (tokens_left is None or tokens_left > 500):
            primary = "chatgpt"
            rationale.append("ChatGPT is open - draft there, then paste into Word if you need a doc.")
        else:
            primary = "tutorial"
            rationale.append("No writing surface open - give a clear tutorial instead of guessing.")
        if primary == "word":
            steps = [
                {"do": "focus", "target": "word", "why": "Use the open document"},
                {"do": "type_or_paste", "target": "word", "content": "outline then full draft"},
                {"do": "save", "target": "word", "hotkey": ["ctrl", "s"]},
            ]
        elif primary in ("claude", "chatgpt"):
            steps = [
                {"do": "focus", "target": primary},
                {"do": "paste_brief", "target": primary, "content": goal},
                {"do": "wait_generate", "target": primary},
                {"do": "copy_result", "target": primary},
                {"do": "optional_paste_word", "target": "word", "if": "user wants a .docx"},
                {
                    "do": "fallback_on_limit",
                    "why": "If rate-limited mid-run, hop to the other chat or Word with the outline already captured",
                },
            ]
        else:
            steps = [
                {"do": "explain", "content": "Open Word for long-form, or Claude/ChatGPT if you want a faster first draft."},
                {"do": "outline_in_chat", "content": "I can draft the outline here first so nothing is lost."},
            ]
    elif kind == "code":
        primary = "cursor" if ("cursor" in kinds or fg_kind == "cursor") else "tutorial"
        rationale.append("Code work stays in Cursor/IDE when available.")
        steps = [
            {"do": "focus", "target": "cursor"},
            {"do": "search_workspace", "query": goal},
            {"do": "edit_with_tools", "tools": ["fs_search", "fs_patch", "run_command"]},
        ]
    elif kind == "research":
        primary = "browser" if "browser" in kinds else "web_search"
        rationale.append("Research: look at the current page, then web_search; never invent cites.")
        steps = [
            {"do": "observe_screen", "why": "See what tab/app is already open"},
            {"do": "web_search", "query": goal},
            {"do": "ground_claims", "rule": "only quote fetched pages; walls are not content"},
        ]
    else:
        primary = "observe"
        rationale.append("General: look first, then act or teach.")
        steps = [
            {"do": "observe_screen"},
            {"do": "decide_act_or_tutorial"},
        ]

    return {
        "ok": True,
        "goal": (goal or "")[:500],
        "kind": kind,
        "primary": primary,
        "act_mode": bool(act),
        "rationale": rationale,
        "steps": steps,
        "foreground": {"title": fg_title, "kind": fg_kind},
        "open_kinds": sorted(k for k in kinds if k),
        "human": _human_summary(kind, primary, rationale),
        "policy": {
            "input_needs_confirm": True,
            "style": "relax_chill_smart",
            "prefer_existing_apps": True,
            "use_external_tools_over_inventing": True,
            "hop_on_rate_limit": True,
        },
    }


def _human_summary(kind: str, primary: str, rationale: list[str]) -> list[str]:
    lines = [f"Task looks like {kind}. Best surface: {primary}."]
    lines.extend(rationale)
    lines.append("I will not click or type until you approve. Looking first is free.")
    return lines

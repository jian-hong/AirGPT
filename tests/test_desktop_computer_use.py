"""Desktop computer-use foundation + playbook (no real clicks in unit tests)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import desktop_control
import desktop_playbook
import agent_tools


def test_available_reports_platform():
    a = desktop_control.available()
    assert a["ok"] is True
    assert "platform" in a


def test_click_requires_confirm():
    out = desktop_control.click(10, 10, confirmed=False)
    assert out["ok"] is False
    assert out["error"] == "confirm_required"


def test_type_requires_confirm():
    out = desktop_control.type_text("hi", confirmed=False)
    assert out["error"] == "confirm_required"


def test_plan_writing_prefers_word_when_open(monkeypatch):
    monkeypatch.setattr(
        desktop_control,
        "observe",
        lambda: {
            "ok": True,
            "foreground": {"title": "Essay.docx - Word", "pid": 1},
            "windows": {
                "windows": [
                    {"title": "Essay.docx - Word", "kind": "word"},
                    {"title": "Claude", "kind": "claude"},
                ]
            },
        },
    )
    plan = desktop_playbook.plan_task("write an essay about nets")
    assert plan["kind"] == "writing"
    assert plan["primary"] == "word"
    assert plan["policy"]["input_needs_confirm"] is True


def test_plan_writing_falls_back_to_claude(monkeypatch):
    monkeypatch.setattr(
        desktop_control,
        "observe",
        lambda: {
            "ok": True,
            "foreground": {"title": "Claude", "pid": 1},
            "windows": {"windows": [{"title": "Claude", "kind": "claude"}]},
        },
    )
    plan = desktop_playbook.plan_task("draft a novel chapter", tokens_left=9000)
    assert plan["primary"] == "claude"


def test_plan_tutorial_when_nothing_open(monkeypatch):
    monkeypatch.setattr(
        desktop_control,
        "observe",
        lambda: {"ok": True, "foreground": {"title": ""}, "windows": {"windows": []}},
    )
    plan = desktop_playbook.plan_task("write an essay")
    assert plan["primary"] == "tutorial"


def test_agent_tools_expose_desktop():
    names = {s["name"] for s in agent_tools.tool_schemas()}
    assert "desktop_observe" in names
    assert "desktop_plan" in names
    assert "desktop_click" in names


def test_desktop_click_tool_confirm_gate():
    out = agent_tools.run_tool("desktop_click", {"x": 1, "y": 2, "confirmed": False})
    assert out.get("error") == "confirm_required"

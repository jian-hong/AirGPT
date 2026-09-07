"""AirGPT can reach Constructor + MCP auto-caller through the Cortex sidecar."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_tools  # noqa: E402
import chat_tools  # noqa: E402
import marketplace  # noqa: E402


def test_constructor_is_a_marketplace_builtin() -> None:
    item = next(i for i in marketplace.SOFTWARE_MODULES if i.get("builtin") == "constructor")
    assert item["id"] == "mod-constructor"
    assert item.get("serving") == "module"
    blurb = item.get("blurb", "").lower()
    assert "hosted inside cortex" not in blurb
    assert "/cortex/constructor/" not in blurb


def test_airgpt_tool_names_include_constructor_and_auto_caller() -> None:
    for name in ("constructor_ghost", "constructor_recommend", "auto_caller_pick", "dms_query"):
        assert name in agent_tools.TOOLS
        assert name in chat_tools.CHAT_SAFE_TOOLS


def test_constructor_ghost_and_auto_caller_hit_cortex_client(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    fake = SimpleNamespace(
        constructor_ghost=lambda nodes, edges: calls.append(("ghost", nodes)) or {"ok": True, "ghost": True},
        constructor_recommend=lambda nodes, edges: {"ok": True, "approaches": []},
        mcp_call=lambda name, args: calls.append(("mcp", name, args))
        or {
            "ok": True,
            "result": {
                "ok": True,
                "first_party": [{"name": "brain.draft_whatsapp"}],
                "live_whatsapp_connector": False,
            },
        },
    )
    monkeypatch.setattr(agent_tools, "cortex_client", fake)

    ghost = agent_tools.constructor_ghost(nodes=[{"id": "n1", "kind": "audit"}], edges=[])
    assert ghost["ok"] is True
    assert calls[0][0] == "ghost"

    picked = agent_tools.auto_caller_pick("whatsapp connector")
    assert picked["live_whatsapp_connector"] is False
    assert picked["first_party"][0]["name"] == "brain.draft_whatsapp"

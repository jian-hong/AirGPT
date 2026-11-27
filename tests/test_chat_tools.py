"""Native tool calling in ordinary chat.

Tools existed only inside agent_runtime, behind a prompt convention, so plain chat
never advertised any - which is why the assistant answered, truthfully, that it had
no tool orchestration. These tests pin the two things that make chat tools safe:
the schemas match the real signatures, and the write/desktop half stays out.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_tools  # noqa: E402
import chat_tools  # noqa: E402


def test_every_allowlisted_tool_exports_a_schema() -> None:
    names = {t["function"]["name"] for t in chat_tools.openai_tools()}
    missing = set(chat_tools.CHAT_SAFE_TOOLS) - names
    assert not missing, f"allowlisted but no schema: {sorted(missing)}"


def test_schemas_are_openai_shaped() -> None:
    for t in chat_tools.openai_tools():
        assert t["type"] == "function"
        fn = t["function"]
        assert fn["name"] and fn["description"]
        params = fn["parameters"]
        assert params["type"] == "object"
        assert isinstance(params["properties"], dict)
        assert isinstance(params["required"], list)
        # Everything required must actually exist as a property.
        assert set(params["required"]) <= set(params["properties"])


def test_schema_params_match_the_real_signature() -> None:
    """Hand-copied schemas drift; these are derived, and this proves it.

    A parameter the model is told to send but the function will not accept becomes a
    TypeError mid-conversation.
    """
    import inspect

    for t in chat_tools.openai_tools():
        name = t["function"]["name"]
        fn = agent_tools.TOOLS[name]
        real = set(inspect.signature(fn).parameters) - {"run_id", "agent_id"}
        advertised = set(t["function"]["parameters"]["properties"])
        assert advertised <= real, f"{name} advertises unknown params: {advertised - real}"


def test_internal_params_are_never_advertised() -> None:
    """run_id / agent_id are injected by the runtime, not chosen by the model."""
    for t in chat_tools.openai_tools():
        props = t["function"]["parameters"]["properties"]
        assert "run_id" not in props and "agent_id" not in props


@pytest.mark.parametrize(
    "blocked",
    ["fs_write", "fs_patch", "vault_write", "run_command", "app_scaffold",
     "dms_action", "desktop_click", "desktop_type", "desktop_scroll", "desktop_drag",
     "browser_click", "browser_type", "browser_select", "browser_submit",
     "browser_navigate", "browser_snapshot"],
)
def test_write_and_desktop_tools_are_refused_in_chat(blocked: str) -> None:
    """Chat has no approval gate, so it must not reach anything that mutates.

    agent_runtime routes these through write_preview and a human approve/reject;
    a plain text box has no such step.
    """
    assert not chat_tools.is_chat_safe(blocked)
    out = chat_tools.run_chat_tool(blocked, "{}")
    assert out["ok"] is False
    assert blocked in out["error"]
    assert blocked not in {t["function"]["name"] for t in chat_tools.openai_tools()}


def test_refusal_explains_itself_rather_than_failing_silently() -> None:
    out = chat_tools.run_chat_tool("run_command", '{"cmd":"echo hi"}')
    assert "approval gate" in out["reason"]


def test_unknown_tool_is_refused_not_dispatched() -> None:
    out = chat_tools.run_chat_tool("definitely_not_a_tool", "{}")
    assert out["ok"] is False


def test_malformed_arguments_do_not_raise() -> None:
    """Bad JSON from the model must end the call, not the conversation."""
    out = chat_tools.run_chat_tool("memory_search", "{not json")
    assert out["ok"] is False
    assert "parse" in out["error"].lower()


def test_unexpected_keys_are_dropped_not_forwarded() -> None:
    """Observed live: the model sent {"depth":"0"} to rag_list_spaces, which takes
    no arguments. Forwarding it would raise TypeError and kill the turn."""
    out = chat_tools.run_chat_tool("rag_list_spaces", '{"depth":"0","bogus":1}')
    assert isinstance(out, dict)
    assert "unexpected keyword" not in json.dumps(out).lower()


def test_result_is_always_json_serialisable() -> None:
    """Results go straight back to the model as a tool message."""
    out = chat_tools.run_chat_tool("rag_list_spaces", "{}")
    json.dumps(out)  # must not raise


def test_allowlist_has_no_overlap_with_agent_write_tools() -> None:
    """One policy, asserted - not two lists that drift apart."""
    import agent_runtime

    overlap = set(chat_tools.CHAT_SAFE_TOOLS) & set(agent_runtime.WRITE_TOOLS)
    assert not overlap, f"chat exposes gated write tools: {sorted(overlap)}"

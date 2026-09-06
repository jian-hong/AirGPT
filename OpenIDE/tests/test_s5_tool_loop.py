"""S5: OpenAI/Cursor function-call JSON is accepted; schemas are function-shaped."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import agent_runtime  # noqa: E402
import chat_tools  # noqa: E402


def test_agent_tool_hint_is_openai_function_array() -> None:
    hint = agent_runtime._agent_tool_hint(["fs_read", "fs_patch"])
    assert hint
    assert all(row["type"] == "function" for row in hint)
    names = {row["function"]["name"] for row in hint}
    assert names == {"fs_read", "fs_patch"}
    fs = next(row for row in hint if row["function"]["name"] == "fs_patch")
    props = fs["function"]["parameters"]["properties"]
    assert "path" in props and "old" in props and "new" in props


def test_parse_legacy_tool_json() -> None:
    got = agent_runtime._parse_tool_call('{"tool":"fs_read","params":{"path":"a.py"}}')
    assert got == {"tool": "fs_read", "params": {"path": "a.py"}}


def test_parse_openai_name_arguments() -> None:
    got = agent_runtime._parse_tool_call(
        '{"name":"fs_read","arguments":{"path":"a.py"}}'
    )
    assert got == {"tool": "fs_read", "params": {"path": "a.py"}}


def test_parse_openai_function_arguments_string() -> None:
    inner = json.dumps({"path": "a.py"})
    got = agent_runtime._parse_tool_call(
        '{"function":{"name":"fs_read","arguments":' + json.dumps(inner) + "}}"
    )
    assert got == {"tool": "fs_read", "params": {"path": "a.py"}}


def test_parse_openai_tool_calls_array() -> None:
    payload = {
        "tool_calls": [
            {"function": {"name": "git_status", "arguments": "{}"}},
        ]
    }
    got = agent_runtime._parse_tool_call(json.dumps(payload))
    assert got == {"tool": "git_status", "params": {}}


def test_chat_tools_openai_shape_used_by_openide_catalog() -> None:
    """Parity vs Cursor Agents: type=function + JSON Schema parameters."""
    row = chat_tools.openai_tools(["fs_read"])[0]
    assert row["type"] == "function"
    assert row["function"]["parameters"]["type"] == "object"

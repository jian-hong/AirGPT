"""Native OpenAI-shaped tool calling for ordinary chat.

Tools existed here already, but only inside `agent_runtime.run_agent_events`, and
only through a prompt convention - the model was asked to emit
`{"tool":..., "params":...}` as text and the reply was parsed back. Plain chat never
sent tool definitions at all, so when asked "can you orchestrate tools?" the model
answered honestly that it could not. It was never told.

This module is the bridge. It does three things and nothing else:

    openai_tools(names)     agent_tools' catalog -> the `tools` array wire format
    run_chat_tool(name, a)  dispatch, refusing anything not read-only
    CHAT_SAFE_TOOLS         the allowlist plain chat is permitted

Schemas are derived from the real function signatures via `inspect`, not
hand-copied, so a parameter rename cannot silently desynchronise the advertised
schema from the code that receives it.

Why an allowlist instead of every tool: `agent_tools` also exposes `fs_write`,
`run_command` and the `desktop_*` family. Those run behind `agent_runtime`'s
approval gate (`WRITE_TOOLS` -> write_preview -> human approve/reject). Ordinary
chat has no such gate, so it gets the read-only half. Widening this set without
first giving chat an approval step would hand a text box the ability to write files
and drive the mouse.
"""
from __future__ import annotations

import inspect
import json
from typing import Any

import agent_tools

# Read-only, no side effects the user has to undo, safe without an approval gate.
# Deliberately excludes: fs_write, fs_patch, vault_write, run_command, app_scaffold,
# dms_action, subagent_dispatch and every desktop_* mutation.
CHAT_SAFE_TOOLS: tuple[str, ...] = (
    "memory_search",
    "memory_add",
    "vault_read",
    "rag_list_spaces",
    "rag_search",
    "rag_answer",
    "web_search",
    "fs_read",
    "fs_search",
    "fs_glob",
    "git_status",
    "git_diff",
    "session_summarize",
    "dms_query",
    "constructor_ghost",
    "constructor_recommend",
    "auto_caller_pick",
    "desktop_observe",
)

# memory_add writes, but only to the user's own memory and only what they asked to be
# remembered - the one exception, and it is why this is a named set rather than
# "everything not in WRITE_TOOLS".
_WRITES_ALLOWED_IN_CHAT: frozenset[str] = frozenset({"memory_add"})

_JSON_TYPES: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}

# Params the runtime injects; the model must never be asked to supply them.
_INTERNAL_PARAMS: frozenset[str] = frozenset({"run_id", "agent_id"})


def _json_type(annotation: Any, default: Any) -> str:
    if annotation in _JSON_TYPES:
        return _JSON_TYPES[annotation]
    # `list | None` and friends: fall back to the default's type, then string.
    for typ, name in _JSON_TYPES.items():
        if isinstance(default, typ) and not isinstance(default, bool):
            return name
    if isinstance(default, bool):
        return "boolean"
    return "string"


def _schema_for(name: str) -> dict | None:
    """Build one OpenAI function schema from the live signature."""
    fn = agent_tools.TOOLS.get(name)
    if fn is None:
        return None
    meta = {d["name"]: d for d in agent_tools.tool_schemas([name])}.get(name, {})

    props: dict[str, dict] = {}
    required: list[str] = []
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None

    for pname, param in sig.parameters.items():
        if pname in _INTERNAL_PARAMS or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        has_default = param.default is not inspect.Parameter.empty
        default = param.default if has_default else None
        props[pname] = {"type": _json_type(param.annotation, default)}
        # A parameter with no default is genuinely required; everything else is not,
        # so the model is never forced to invent a value it has no basis for.
        if not has_default:
            required.append(pname)

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": meta.get("description") or f"{name} tool",
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        },
    }


def openai_tools(names: tuple[str, ...] | list[str] | None = None) -> list[dict]:
    """The `tools` array to send with a chat completion. Never raises."""
    wanted = tuple(names) if names else CHAT_SAFE_TOOLS
    out: list[dict] = []
    for n in wanted:
        try:
            schema = _schema_for(n)
        except Exception:
            schema = None
        if schema:
            out.append(schema)
    return out


def is_chat_safe(name: str) -> bool:
    return name in CHAT_SAFE_TOOLS


def run_chat_tool(name: str, arguments: Any, *, run_id: int = 0) -> dict:
    """Execute one model-requested tool call under the chat allowlist.

    `arguments` arrives as a JSON *string* from the wire. Returns a dict that is
    always JSON-serialisable, because it goes straight back to the model as a
    tool message - raising here would abort a conversation mid-turn.
    """
    if not is_chat_safe(name):
        # Refusing loudly beats executing quietly. The model sees why and can adapt.
        return {
            "ok": False,
            "error": f"tool '{name}' is not available in chat",
            "reason": (
                "write and desktop-control tools require the agent approval gate; "
                "run this from an agent instead"
            ),
        }
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"could not parse tool arguments: {e}"}
    elif isinstance(arguments, dict):
        args = arguments
    else:
        args = {}

    if not isinstance(args, dict):
        return {"ok": False, "error": "tool arguments must be a JSON object"}

    # Drop anything the model invented that the function will not accept, rather than
    # letting a stray key raise TypeError and kill the turn.
    fn = agent_tools.TOOLS.get(name)
    if fn is not None:
        try:
            allowed = set(inspect.signature(fn).parameters) - _INTERNAL_PARAMS
            args = {k: v for k, v in args.items() if k in allowed}
        except (TypeError, ValueError):
            pass

    try:
        result = agent_tools.run_tool(name, args, run_id=run_id)
    except Exception as e:  # a tool blowing up must not end the conversation
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}

    try:
        json.dumps(result)
    except (TypeError, ValueError):
        return {"ok": True, "result": str(result)[:4000]}
    return result

"""Cortex in-app agent runtime — multi-step tool loop, Thinking modes."""
from __future__ import annotations

import json
import logging
import re
import threading
from typing import Iterator

import agent_store
import agent_tools
import audit

try:
    import ai_engine
except ImportError:
    ai_engine = None  # type: ignore

WRITE_TOOLS = frozenset({
    "fs_write", "fs_patch", "vault_write",
    "desktop_click", "desktop_type", "desktop_scroll", "desktop_drag",
})
FILE_MENTION_RE = re.compile(r"@([\w.\-/\\]+(?:\.\w+)?)")
CORTEX_RESEARCH_PROMPT_ID = "research.idea_to_paper"
_log = logging.getLogger("airgpt.agents")
_NO_MODEL_SENTENCE = "No AI model could be reached. Check your model in Settings."


def _think_event(steps: list, text: str) -> dict:
    """SSE thinking row that also lands on the Background tasks card."""
    msg = text if str(text).endswith("\n") else f"{text}\n"
    summary = str(text or "").strip()[:240]
    if summary:
        steps.append({"tool": "think", "ok": True, "summary": summary})
    return {"type": "thinking", "text": msg}


def _cortex_owns_brain(agent: dict) -> bool:
    """Research agents: Cortex owns prompts. AirGPT is shell only."""
    if not isinstance(agent, dict):
        return False
    cfg = agent.get("config") if isinstance(agent.get("config"), dict) else {}
    kind = str(agent.get("kind") or "").lower()
    name = str(agent.get("name") or "")
    return (
        kind == "research"
        or str(cfg.get("pipeline") or "") == "idea_to_paper"
        or name == "OpenResearch"
    )


def _load_skill(skill_pack: str) -> str:
    if not skill_pack:
        return ""
    try:
        import invoke_registry

        return invoke_registry.load_skill(skill_pack)
    except Exception:
        pass
    from config import DATA_DIR

    p = DATA_DIR / "skills" / f"{skill_pack}.md"
    if p.is_file():
        try:
            # utf-8-sig so a BOM never leaks into the prompt as a stray character
            return p.read_text(encoding="utf-8-sig")[:6000]
        except OSError:
            pass
    return ""


def _rules_block() -> str:
    try:
        import workspace_api

        text = (workspace_api.rules_text() or "").strip()
        return text[:4000]
    except Exception:
        return ""


def _spawn_subagent(
    prompt: str,
    *,
    parent_run_id: int,
    session_id: int = 0,
    agent_id: int = 0,
    children_spawned: int = 0,
    max_children: int = 2,
) -> dict:
    """Queue a child agent run. Cap fan-out; never recurse from a child."""
    try:
        import access_policy

        blocked = access_policy.lockdown_block()
        if blocked:
            return dict(blocked)
    except Exception:
        pass
    if children_spawned >= max_children:
        return {"ok": False, "error": f"subagent fan-out cap ({max_children}) reached"}
    if not (prompt or "").strip():
        return {"ok": False, "error": "subagent prompt required"}
    try:
        import cortex_orchestrator

        child_agent = agent_id
        if not child_agent:
            ensure_default_agent()
            agents = agent_store.list_agents(limit=20)
            child_agent = int(agents[0]["id"]) if agents else 0
        if not child_agent:
            return {"ok": False, "error": "no agent available for subagent"}
        queued = cortex_orchestrator.queue_run(
            child_agent,
            (prompt or "")[:4000],
            session_id=session_id,
            parent_run_id=int(parent_run_id or 0),
            is_subagent=True,
        )
        return {
            "ok": True,
            "run_id": queued.get("run_id"),
            "agent_id": child_agent,
            "name": f"subagent-{queued.get('run_id')}",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

def _memory_context() -> str:
    try:
        import memory_index

        pack = memory_index.carry_pack(max_chars=2000) or ""
        nxt = memory_index.list_memories(kind="next_action", limit=1)
        na = (nxt[0].get("body") or "") if nxt else ""
        parts = [x for x in (pack, f"Next action: {na}" if na else "") if x]
        return "\n".join(parts)[:4000]
    except Exception:
        return ""


def _notes_context(workspace_root: str = "") -> str:
    try:
        from context_engineering import NoteStore, default_notes_path

        path = default_notes_path(workspace_root) if workspace_root else None
        if path is None:
            try:
                import workspace_api

                ws = workspace_api.get_workspace()
                path = default_notes_path(ws.get("root") or "")
            except Exception:
                path = None
        if path is None:
            return ""
        return NoteStore(path).read_recent()
    except Exception:
        return ""


def _assemble_agent_prompt(
    *,
    agent_name: str,
    rules: str,
    skill: str,
    tool_hint: list | dict,
    context_blocks: list[str],
    prompt: str,
    token_budget: int,
    prior_steps: int,
) -> tuple[str, str, dict]:
    """Layered context engineering assemble → (system, user, meta)."""
    from context_engineering import ContextRequest, assemble_context, estimate_tokens

    instructions = (
        f"You are {agent_name}, a Cortex agent. Use tools when needed.\n"
        'To call a tool respond with ONLY JSON: {"tool":"NAME","params":{...}}\n'
        'OpenAI/Cursor shape is also accepted: {"name":"NAME","arguments":{...}}\n'
        "Prefer fs_patch over fs_write for edits.\n"
        "When done, respond with plain text (no JSON).\n\n"
        f"{(rules or '').strip()}"
    ).strip()
    tools = f"Available tools:\n{json.dumps(tool_hint, separators=(',', ':'))}"
    skill_block = (skill or "").strip()
    if skill_block:
        instructions = f"{instructions}\n\nSkill pack:\n{skill_block[:2000]}"

    state_parts: list[str] = []
    mem_parts: list[str] = []
    retrieval_parts: list[str] = []
    message_parts: list[str] = []
    for b in context_blocks:
        s = (b or "").strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith("workspace fingerprint") or low.startswith("<state"):
            state_parts.append(s)
        elif low.startswith("memory:") or low.startswith("notes:") or low.startswith("## "):
            mem_parts.append(s)
        elif low.startswith("rules:"):
            continue
        elif "snippet" in low or (s[:1] in "{[" and len(s) > 2):
            retrieval_parts.append(s)
        else:
            message_parts.append(s)

    assemble_budget = max(800, min(int(token_budget) * 4, 8000))
    assembled = assemble_context(
        ContextRequest(
            instructions=instructions,
            tools=tools,
            memory="\n\n".join(mem_parts),
            retrieval="\n\n".join(retrieval_parts),
            state="\n\n".join(state_parts),
            messages=message_parts,
            token_budget=assemble_budget,
        )
    )
    try:
        from cortex_runtime import redact_text

        user = (
            f"Request:\n{redact_text(prompt or '')}\n\n"
            f"{redact_text(assembled.user_context) or '(no extra context)'}\n\n"
            f"Prior steps: {prior_steps}"
        )
        system = redact_text(assembled.system)
    except Exception:
        user = (
            f"Request:\n{prompt or ''}\n\n"
            f"{assembled.user_context or '(no extra context)'}\n\n"
            f"Prior steps: {prior_steps}"
        )
        system = assembled.system
    meta = {
        "token_estimate": assembled.token_estimate,
        "compacted": assembled.compacted,
        "truncated_layers": assembled.truncated_layers,
        "prompt_tokens": estimate_tokens(system) + estimate_tokens(user),
    }
    return system, user, meta


def _maybe_compact_blocks(context_blocks: list[str], *, soft_limit: int = 5000) -> list[str]:
    joined_len = sum(len(b) for b in context_blocks)
    if joined_len < soft_limit:
        return context_blocks
    try:
        from context_engineering import compact_messages

        blocks, _ = compact_messages(context_blocks, token_budget=max(400, soft_limit // 4))
        return blocks
    except Exception:
        return context_blocks[-12:]


def _looks_like_tool_json(candidate: str) -> bool:
    """Accept legacy {"tool"} plus OpenAI/Cursor function-call shapes."""
    return (
        '"tool"' in candidate
        or '"tool_calls"' in candidate
        or ('"function"' in candidate and '"name"' in candidate)
        or ('"name"' in candidate and '"arguments"' in candidate)
    )


def _extract_balanced_json(text: str) -> str | None:
    """Find first brace-balanced JSON object that looks like a tool call."""
    start = text.find("{")
    while start >= 0:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    if _looks_like_tool_json(candidate):
                        return candidate
                    break
        start = text.find("{", start + 1)
    return None


def _json_args(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _normalize_tool_obj(obj: object) -> dict | None:
    """Map legacy, OpenAI, and Cursor tool JSON onto {tool, params}."""
    if not isinstance(obj, dict):
        return None
    if obj.get("tool"):
        params = obj.get("params") if isinstance(obj.get("params"), dict) else {}
        return {"tool": str(obj["tool"]), "params": params}
    calls = obj.get("tool_calls")
    if isinstance(calls, list) and calls:
        first = calls[0]
        if isinstance(first, dict):
            nested = _normalize_tool_obj(first)
            if nested:
                return nested
    fn = obj.get("function") if isinstance(obj.get("function"), dict) else obj
    if not isinstance(fn, dict):
        return None
    name = fn.get("name") or obj.get("name")
    if not name:
        return None
    args = fn.get("arguments", obj.get("arguments"))
    return {"tool": str(name), "params": _json_args(args)}


def _parse_tool_call(text: str) -> dict | None:
    """Parse TOOL_CALL JSON from model output (legacy + OpenAI/Cursor)."""
    raw = _extract_balanced_json(text or "")
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return _normalize_tool_obj(obj)


def _agent_tool_hint(names: list[str] | None) -> list:
    """OpenAI/Cursor `tools` array. Falls back to the catalog rows."""
    wanted = list(names or [])
    try:
        import chat_tools

        shaped = chat_tools.openai_tools(wanted)
        have = {row["function"]["name"] for row in shaped}
        missing = [n for n in wanted if n not in have]
        if missing:
            for row in agent_tools.tool_schemas(missing):
                props = {p: {"type": "string"} for p in (row.get("params") or [])}
                shaped.append(
                    {
                        "type": "function",
                        "function": {
                            "name": row["name"],
                            "description": row.get("description") or row["name"],
                            "parameters": {
                                "type": "object",
                                "properties": props,
                                "required": list(props),
                            },
                        },
                    }
                )
        return shaped
    except Exception:
        return agent_tools.tool_schemas(wanted)


def _inject_file_mentions(prompt: str, *, active_file: str = "") -> tuple[str, list[str]]:
    blocks: list[str] = []
    seen: set[str] = set()
    try:
        import workspace_api
    except ImportError:
        return prompt, blocks

    def _attach(path: str, label: str) -> None:
        path = (path or "").replace("\\", "/").lstrip("/")
        if not path or path in seen:
            return
        seen.add(path)
        rf = workspace_api.read_file(path)
        if rf.get("ok"):
            blocks.append(f"{label} `{path}`:\n{(rf.get('content') or '')[:8000]}")

    if active_file:
        _attach(active_file, "Active editor file")
    for m in FILE_MENTION_RE.finditer(prompt or ""):
        _attach(m.group(1), "Attached")
    return prompt, blocks


def _write_preview_event(tname: str, params: dict, result: dict, *, run_id: int) -> dict:
    path = str(params.get("path") or result.get("path") or "")
    if tname == "fs_patch":
        return {
            "type": "write_preview",
            "gate": "approve_write",
            "run_id": run_id,
            "tool": tname,
            "path": path,
            "mode": "patch",
            "old": str(params.get("old") or ""),
            "new": str(params.get("new") or ""),
            "content": None,
            "preview": True,
        }
    return {
        "type": "write_preview",
        "gate": "approve_write",
        "run_id": run_id,
        "tool": tname,
        "path": path,
        "mode": "write",
        "old": None,
        "new": None,
        "content": str(params.get("content") or params.get("body") or "")[:120000],
        "preview": True,
    }


def ensure_default_agent() -> dict | None:
    """No legacy Vault Summarizer. Prefer pinned OpenResearch / RAG if present."""
    agents = agent_store.list_agents(limit=40)
    for prefer in ("OpenResearch", "RAG", "OpenVertex"):
        for a in agents:
            if a.get("name") == prefer:
                return a
    return agents[0] if agents else None


def create_agent(payload: dict) -> dict:
    pinned = payload.get("pinned")
    return agent_store.create_agent(
        str(payload.get("name") or "Agent"),
        kind=str(payload.get("kind") or "special"),
        skill_pack=str(payload.get("skill_pack") or ""),
        tools=payload.get("tools"),
        memory_scope=str(payload.get("memory_scope") or "project"),
        project_id=int(payload.get("project_id") or 0),
        config=payload.get("config") if isinstance(payload.get("config"), dict) else {},
        pinned=bool(pinned) if pinned is not None else None,
    )


def run_agent_events(*args, **kwargs) -> Iterator[dict]:
    """Run an agent and stream events. If the reader goes away (browser closed, tunnel
    dropped) the generator is closed mid-run; end that run instead of leaving it
    'running' forever. A run that already finished is left alone."""
    seen_run_id = int(kwargs.get("run_id") or 0)
    inner = _run_agent_events(*args, **kwargs)
    if seen_run_id:
        _LIVE.add(seen_run_id)
    try:
        for ev in inner:
            if isinstance(ev, dict) and ev.get("run_id"):
                seen_run_id = int(ev["run_id"])
                _LIVE.add(seen_run_id)
            yield ev
    except GeneratorExit:
        inner.close()
        if seen_run_id:
            agent_store.cancel_run(seen_run_id, "The page closed before this run finished.")
        raise
    finally:
        _LIVE.discard(seen_run_id)


# ---- Runs that outlive the page --------------------------------------------------
# The route starts the run on its own thread and the page only watches it. Closing the
# tab, refreshing or switching view no longer ends the work, and the page can read the
# same events again by run id. Stop is agent_store.cancel_run (the loop checks it).
_BG: dict[int, dict] = {}
_BG_LOCK = threading.Lock()
_BG_KEEP = 40
_BG_EVENTS = 3000
_LIVE: set[int] = set()  # run ids some thread of this app is working on right now


def close_interrupted(min_age: float = 3.0) -> int:
    """Close open runs nothing here is working on. A live run is never closed."""
    try:
        return agent_store.close_interrupted(set(_LIVE), min_age)
    except Exception:
        return 0


def start_background_run(agent_id: int, prompt: str, **kw) -> int:
    """Create the run row, start the loop on a thread, return the run id."""
    agent = agent_store.get_agent(int(agent_id))
    if not agent:
        raise LookupError("agent not found")
    run = agent_store.create_run(int(agent_id), (kw.get("task") or "").strip() or prompt)
    rid = int(run["id"])
    kw["run_id"] = rid
    _LIVE.add(rid)
    slot = {"events": [], "done": False, "cv": threading.Condition()}
    with _BG_LOCK:
        _BG[rid] = slot
        for old in sorted(_BG)[:-_BG_KEEP]:
            if _BG[old]["done"]:
                _BG.pop(old, None)

    def push(ev: dict) -> None:
        with slot["cv"]:
            if len(slot["events"]) < _BG_EVENTS or ev.get("type") in ("done", "error", "stopped"):
                slot["events"].append(ev)
            slot["cv"].notify_all()

    def work() -> None:
        try:
            for ev in _run_agent_events(int(agent_id), prompt, **kw):
                push(ev)
        except Exception as e:  # the loop reports its own errors; this is the last resort
            try:
                agent_store.finish_run(rid, status="error", error=str(e)[:500])
            except Exception:
                pass
            push({"type": "error", "text": str(e)[:500], "run_id": rid})
        finally:
            try:
                # Anything still open here lost its loop (for example a closed generator).
                agent_store.cancel_run(rid, "This run ended before it finished.")
            except Exception:
                pass
            _LIVE.discard(rid)
            with slot["cv"]:
                slot["done"] = True
                slot["cv"].notify_all()

    threading.Thread(target=work, name=f"agent-run-{rid}", daemon=True).start()
    return rid


def tail_run(run_id: int, after: int = 0, idle: float = 15.0):
    """Events of a background run from `after`. None when this process does not hold the
    run (use the saved row instead). Yields {"type":"ping"} while idle so a closed
    reader is noticed."""
    with _BG_LOCK:
        slot = _BG.get(int(run_id))
    if slot is None:
        return None

    def gen():
        i = max(0, int(after))
        while True:
            with slot["cv"]:
                while i >= len(slot["events"]) and not slot["done"]:
                    if not slot["cv"].wait(idle):
                        break
                batch = slot["events"][i:]
                finished = slot["done"] and i + len(batch) >= len(slot["events"])
            if batch:
                i += len(batch)
                for ev in batch:
                    yield ev
            elif finished:
                return
            else:
                yield {"type": "ping"}

    return gen()


def _run_agent_events(
    agent_id: int,
    prompt: str,
    *,
    session_id: int = 0,
    thinking_mode: str = "assist",
    max_steps: int = 8,
    token_budget: int = 1200,
    backend: str = "local",
    run_id: int | None = None,
    require_approval: bool = False,
    file_context: bool = False,
    active_file: str = "",
    resume: bool = False,
    cursor_run_id: str = "",
    skill_override: str = "",
    parent_run_id: int = 0,
    is_subagent: bool = False,
    task: str = "",
) -> Iterator[dict]:
    """Yield SSE-style events for an agent run with multi-step tool loop.

    `prompt` may be a wrapper the page built around the user's request; `task` is the
    user's own words. The run row and any web search use `task` when it is given."""
    task = (task or "").strip()
    try:
        import access_policy

        blocked = access_policy.lockdown_block()
        if blocked:
            if run_id:
                try:
                    agent_store.finish_run(int(run_id), status="error", error="ai_lockdown")
                except Exception:
                    pass
            yield {
                "type": "error",
                "ok": False,
                "error": blocked["error"],
                "by": blocked.get("by") or "host",
                "text": "Host disabled AI. Your work is saved.",
            }
            return
    except Exception:
        pass

    agent = agent_store.get_agent(agent_id)
    if not agent:
        yield {"type": "error", "text": "agent not found"}
        return

    if thinking_mode == "idle":
        yield {"type": "status", "text": "Idle mode — deterministic tick only"}
        try:
            import cortex_orchestrator

            tick = cortex_orchestrator.deterministic_tick()
            yield {"type": "tool", "name": "deterministic_tick", "result": tick}
        except Exception:
            pass
        if run_id:
            agent_store.finish_run(int(run_id), status="done", result="Idle maintenance complete")
        yield {"type": "done", "analysis": "Idle maintenance complete", "steps": []}
        return

    if backend in ("cursor_local", "cursor_cloud"):
        try:
            import cursor_bridge
            import workspace_api

            ws = workspace_api.get_workspace()
            cwd = ws.get("root") or ""
            for ev in cursor_bridge.run_cursor_events(
                prompt,
                cwd=cwd,
                backend=backend,
                resume=resume,
                run_id=cursor_run_id,
            ):
                yield ev
            if run_id:
                agent_store.finish_run(int(run_id), status="done", result="Cursor run complete")
            return
        except Exception as e:
            if run_id:
                agent_store.finish_run(int(run_id), status="error", error=str(e)[:500])
            yield {"type": "error", "text": f"Cursor bridge failed: {e}"}
            return

    if run_id:
        agent_store.claim_run(int(run_id))
        run_id = int(run_id)
    else:
        run = agent_store.create_run(agent_id, task or prompt)
        run_id = int(run["id"])

    audit.log("agent.run.start", detail=f"agent={agent_id} run={run_id} mode={thinking_mode}", ok=True)
    yield {"type": "status", "text": f"Running {agent['name']} ({thinking_mode})…", "run_id": run_id, "agent_id": agent_id}

    if agent_tools.is_pomodoro_ask(prompt or "") and not is_subagent:
        pomo_steps: list[dict] = []
        yield _think_event(pomo_steps, "Scaffolding pomodoro…")
        sc = agent_tools.scaffold_from_ask(prompt or "", run_id=run_id, agent_id=agent_id)
        pomo_steps.append({"tool": "app_scaffold", "ok": bool(sc.get("ok"))})
        yield _safe_tool_event("app_scaffold", sc)
        if sc.get("ok"):
            analysis = f"Live app at {sc.get('url')}"
            try:
                agent_store.finish_run(run_id, status="done", result=analysis, steps=pomo_steps)
            except Exception:
                pass
            yield {
                "type": "done",
                "run_id": run_id,
                "agent_id": agent_id,
                "analysis": analysis,
                "stop_reason": "quality",
                "quality_passed": True,
                "runner": "app_scaffold",
                "steps": pomo_steps,
            }
            return

    if not require_approval and not is_subagent:
        owns = _cortex_owns_brain(agent)
        try:
            import cortex_client

            loop_kw: dict = {
                "session_id": f"airgpt-{run_id}",
                "max_steps": max_steps,
            }
            if owns:
                agent_tools_list = [
                    t
                    for t in (agent.get("tools") or [])
                    if t in ("web_search", "web_fetch")
                ]
                loop_kw.update(
                    prompt_id=CORTEX_RESEARCH_PROMPT_ID,
                    params={"stage": "research", "topic": (prompt or "")[:800]},
                    tools=agent_tools_list or ["web_search", "web_fetch"],
                    max_tokens=4096,
                    quality_criteria=[
                        "does not invent metrics, DOIs, hostnames, or pytest scores",
                    ],
                    timeout=180.0,
                )
            else:
                # Every agent sends its own tool list. Cortex is outside this app and may still ignore it.
                loop_kw["tools"] = _effective_tools(agent)
            cortex = cortex_client.engine_agent_loop(prompt or "", **loop_kw)
        except Exception as e:
            cortex = {"ok": False, "error": str(e)[:200]}
        if isinstance(cortex, dict) and cortex.get("ok") and agent_store.is_cancelled(run_id):
            # Stop was pressed while Cortex worked. Its late answer is dropped, not shown as done.
            yield _stopped_event(run_id, agent_id)
            return
        if (
            isinstance(cortex, dict)
            and cortex.get("ok")
            and not str(cortex.get("content") or cortex.get("output") or "").strip()
        ):
            # ok:true with nothing to say is not a finished run (the chat path checks this too).
            cortex = {"ok": False, "error": "Cortex sent back an empty answer"}
        if isinstance(cortex, dict) and cortex.get("ok"):
            tel = cortex.get("telemetry") if isinstance(cortex.get("telemetry"), dict) else {}
            packed: list[dict] = []
            yield {
                "type": "status",
                "text": "Cortex quality loop" if not owns else "Cortex research brain",
                "runner": "agent_task",
                "prompt_id": CORTEX_RESEARCH_PROMPT_ID if owns else "",
            }
            yield _think_event(
                packed,
                "Cortex research brain…" if owns else "Cortex quality loop…",
            )
            for t in (tel.get("tools") or []):
                if not isinstance(t, dict):
                    continue
                packed.append(
                    {
                        "tool": str(t.get("tool") or "tool")[:80],
                        "ok": bool(t.get("ok", True)),
                        "summary": str(t.get("summary") or "")[:240],
                        "ms": int(t.get("ms") or 0),
                    }
                )
                yield {
                    "type": "tool",
                    "name": str(t.get("tool") or "tool"),
                    "result": {"ok": t.get("ok"), "summary": t.get("summary"), "ms": int(t.get("ms") or 0)},
                }
            analysis = str(cortex.get("content") or cortex.get("output") or "")
            yield {"type": "token", "text": analysis}
            try:
                agent_store.finish_run(run_id, status="done", result=analysis, steps=packed)
            except Exception:
                pass
            yield {
                "type": "done",
                "run_id": run_id,
                "agent_id": agent_id,
                "analysis": analysis,
                "stop_reason": cortex.get("stop_reason"),
                "quality_passed": cortex.get("quality_passed"),
                "runner": "agent_task",
                "model": str(cortex.get("model") or "")[:80],
                # own_tools: this agent's list was sent. Cortex may still ignore it (it is not run here).
                "own_tools": True,
                "tools_sent": list(loop_kw.get("tools") or []),
                "prompt_id": CORTEX_RESEARCH_PROMPT_ID if owns else "",
                "steps": packed,
            }
            return
        why = _plain_engine_why(cortex, owns)
        if owns:
            try:
                agent_store.finish_run(run_id, status="error", error=why)
            except Exception:
                pass
            yield {"type": "error", "text": why, "run_id": run_id, "agent_id": agent_id}
            return
        yield {"type": "status", "text": f"Quality loop skipped: {why}"}

    # An agent with no tools of its own gets a small offline set, never the web.
    tools = _effective_tools(agent)
    # Only the agent's own tools run. web_search is used only when the agent was given it.
    # Deep parents may dispatch isolated child runs (Assist = no fan-out; children never recurse)
    allow_subagents = (
        str(thinking_mode).lower() == "deep"
        and not is_subagent
        and not parent_run_id
    )
    if allow_subagents and "subagent_dispatch" not in tools:
        tools = list(tools) + ["subagent_dispatch"]

    steps: list[dict] = []
    context_blocks: list[str] = []
    tokens_used = 0
    children_spawned = 0
    max_children = 2 if allow_subagents else 0

    try:
        pack = (skill_override or "").strip() or str(agent.get("skill_pack") or "")
        skill = _load_skill(pack)
        rules = _rules_block()
        if rules:
            context_blocks.append(f"Rules:\n{rules}")
        mem = _memory_context()
        if mem:
            context_blocks.append(f"Memory:\n{mem}")
        notes = _notes_context()
        if notes:
            context_blocks.append(f"Notes:\n{notes}")
        if file_context or active_file:
            prompt, mention_blocks = _inject_file_mentions(prompt, active_file=active_file)
            context_blocks.extend(mention_blocks)

        try:
            import workspace_api

            fp = workspace_api.fingerprint(use_cache=True, light=True)
            if fp.get("ok"):
                context_blocks.append(
                    "Workspace fingerprint:\n"
                    f"branch={fp.get('branch') or '?'} head={(fp.get('head') or '')[:12]} "
                    f"dirty={fp.get('dirty_count', 0)}"
                )
                yield {
                    "type": "status",
                    "text": f"Context · {fp.get('branch') or 'detached'}@{(fp.get('head') or '')[:7]} · {fp.get('dirty_count', 0)} dirty",
                }
        except Exception:
            pass

        if "session_summarize" in tools and session_id:
            yield _think_event(steps, "Summarizing session…")
            sm = agent_tools.run_tool("session_summarize", {"session_id": session_id}, run_id=run_id, agent_id=agent_id)
            steps.append({"tool": "session_summarize", "ok": sm.get("ok")})
            if sm.get("summary"):
                context_blocks.append(sm["summary"][:3000])
            yield _safe_tool_event("session_summarize", sm)

        if "vault_read" in tools:
            yield _think_event(steps, "Searching vault…")
            vr = agent_tools.run_tool("vault_read", {"query": (prompt or "")[:200]}, run_id=run_id, agent_id=agent_id)
            steps.append({"tool": "vault_read", "ok": vr.get("ok")})
            if vr.get("snippets"):
                context_blocks.append(json.dumps(vr["snippets"])[:2000])
            yield _safe_tool_event("vault_read", vr)

        goal_driven = bool((agent.get("config") or {}).get("goal_driven")) if isinstance(agent.get("config"), dict) else False
        if thinking_mode == "deep" and "web_search" in tools and len(task or prompt or "") > 20:
            yield _think_event(steps, "Web search…")
            # Only the user's own words go to the web, once. No second query with extra words.
            ws = agent_tools.run_tool("web_search", {"query": (task or prompt)[:120]}, run_id=run_id, agent_id=agent_id)
            steps.append({"tool": "web_search", "ok": ws.get("ok")})
            if not ws.get("ok") or not ws.get("snippets"):
                yield {"type": "status", "text": "Web search found nothing usable. Continuing without it."}
            if ws.get("snippets"):
                context_blocks.append(json.dumps(ws["snippets"])[:2000])
            yield _safe_tool_event("web_search", ws)

        analysis = ""
        model = "agent-local"
        step = 0
        llm_fail_streak = 0
        no_answer = ""  # plain sentence when no model could answer: the run is failed, not done
        while step < max_steps and tokens_used < token_budget:
            if agent_store.is_cancelled(run_id):
                yield _stopped_event(run_id, agent_id)
                return
            step += 1
            if not ai_engine:
                no_answer = _NO_MODEL_SENTENCE
                break

            yield _think_event(steps, f"Step {step}…")
            tool_hint = _agent_tool_hint(tools)
            context_blocks = _maybe_compact_blocks(context_blocks)
            try:
                sys, user, ctx_meta = _assemble_agent_prompt(
                    agent_name=str(agent["name"]),
                    rules=rules,
                    skill=skill,
                    tool_hint=tool_hint,
                    context_blocks=context_blocks,
                    prompt=prompt or "",
                    token_budget=token_budget,
                    prior_steps=len(steps),
                )
                if goal_driven and step == 1:
                    sys = (sys or "") + (
                        "\nYou are goal-driven: search tools, gather facts, self-critique, "
                        "retry with alternate APIs on failure, and only finish when the plan works."
                    )
                if step == 1 and (ctx_meta.get("compacted") or ctx_meta.get("truncated_layers")):
                    yield {
                        "type": "status",
                        "text": (
                            f"Context engineered · ~{ctx_meta.get('prompt_tokens', '?')} tok"
                            + (" · compacted" if ctx_meta.get("compacted") else "")
                        ),
                    }
                text, model = ai_engine._standard_llm(
                    user, sys, max_tokens=min(600, token_budget - tokens_used), task="agent"
                )
                tokens_used += min(600, len(text or ""))
                llm_fail_streak = 0
                try:
                    from cortex_runtime import redact_text

                    text = redact_text(text or "")
                except Exception:
                    text = text or ""
            except Exception as e:
                llm_fail_streak += 1
                if llm_fail_streak < 3 and goal_driven:
                    yield {"type": "status", "text": f"The model did not answer. Trying again ({llm_fail_streak})…"}
                if llm_fail_streak >= 3 or not goal_driven:
                    _log.warning("agent run %s: no model answered: %s", run_id, str(e)[:500])
                    no_answer = _NO_MODEL_SENTENCE
                    break
                continue

            if agent_store.is_cancelled(run_id):
                # Stop landed while the model was thinking: do not run the tool it asked for.
                yield _stopped_event(run_id, agent_id)
                return
            call = _parse_tool_call(text)
            if call and call["tool"] in tools:
                tname = call["tool"]
                params = dict(call["params"] or {})
                if require_approval and tname in WRITE_TOOLS:
                    params["apply"] = False
                yield {"type": "tool_call", "name": tname, "params": {k: v for k, v in params.items() if k != "content" or len(str(v)) < 200}}
                if tname == "subagent_dispatch":
                    if not allow_subagents:
                        tres = {"ok": False, "error": "subagents only in deep mode for parent runs"}
                    else:
                        tres = _spawn_subagent(
                            str(params.get("prompt") or params.get("text") or ""),
                            parent_run_id=run_id,
                            session_id=session_id,
                            agent_id=int(params.get("agent_id") or 0),
                            children_spawned=children_spawned,
                            max_children=max_children,
                        )
                        if tres.get("ok"):
                            children_spawned += 1
                            child_id = tres.get("run_id")
                            child_name = str(tres.get("name") or f"subagent-{child_id}")
                            yield {"type": "subagent_start", "id": child_id, "name": child_name, "parent_run_id": run_id}
                            yield {"type": "subagent_done", "id": child_id, "status": "queued", "parent_run_id": run_id}
                else:
                    tres = agent_tools.run_tool(tname, params, run_id=run_id, agent_id=agent_id)
                steps.append({"tool": tname, "ok": tres.get("ok")})
                # Keep context lean — never dump full file bodies back into the loop
                lean = {"ok": tres.get("ok"), "path": tres.get("path") or params.get("path"), "preview": tres.get("preview"), "error": tres.get("error")}
                if tname == "subagent_dispatch":
                    lean["run_id"] = tres.get("run_id")
                context_blocks.append(f"Tool {tname}: {json.dumps(lean)[:800]}")
                yield _safe_tool_event(tname, tres)
                if require_approval and tname in ("fs_patch", "fs_write") and tres.get("ok"):
                    yield _write_preview_event(tname, params, tres, run_id=run_id)
                elif tname == "fs_patch" and tres.get("content") and not params.get("apply", True):
                    yield _write_preview_event(tname, params, tres, run_id=run_id)
                continue
            analysis = text
            yield {"type": "token", "text": analysis}
            break

        if agent_store.is_cancelled(run_id):
            yield _stopped_event(run_id, agent_id)
            return
        if no_answer:
            agent_store.finish_run(run_id, status="error", error=no_answer)
            audit.log("agent.run.error", detail=no_answer, ok=False)
            yield {"type": "error", "text": no_answer, "run_id": run_id, "agent_id": agent_id}
            return
        if not analysis and steps:
            analysis = f"Finished {len(steps)} tool steps."

        if "vault_write" in tools and analysis and thinking_mode == "deep" and not require_approval:
            vw = agent_tools.run_tool(
                "vault_write",
                {"title": f"Agent {agent['name']} run {run_id}", "body": analysis[:4000], "category": "general"},
                run_id=run_id,
                agent_id=agent_id,
            )
            steps.append({"tool": "vault_write", "ok": vw.get("ok")})
            yield _safe_tool_event("vault_write", vw)

        # Structured note-taking outside the window (Anthropic long-horizon pattern)
        if thinking_mode == "deep" and analysis and not is_subagent:
            try:
                from context_engineering import NoteStore, default_notes_path

                import workspace_api

                ws = workspace_api.get_workspace()
                npath = default_notes_path(ws.get("root") or "")
                if npath is not None:
                    NoteStore(npath).append(
                        f"Run {run_id} ({agent['name']}): {analysis[:1200]}",
                        heading="Agent run",
                    )
            except Exception:
                pass

        agent_tools.run_tool(
            "audit_append",
            {"action": "agent.run.done", "detail": f"run={run_id} steps={len(steps)}"},
            run_id=run_id,
            agent_id=agent_id,
        )
        agent_store.finish_run(
            run_id, status="done", result=analysis, audit_ref=f"run:{run_id}", steps=steps
        )
        yield {"type": "done", "run_id": run_id, "agent_id": agent_id, "analysis": analysis, "model": model, "runner": "local", "steps": steps}
        audit.log("agent.run.done", detail=f"agent={agent_id} run={run_id}", ok=True)
    except Exception as e:
        agent_store.finish_run(run_id, status="error", error=str(e)[:500])
        audit.log("agent.run.error", detail=str(e)[:300], ok=False)
        yield {"type": "error", "text": str(e)[:500], "run_id": run_id}


def _effective_tools(agent: dict) -> list[str]:
    """The tools this agent may use: its own list, or a small offline set (never the web)."""
    tools = [t for t in (agent.get("tools") or []) if t in agent_tools.TOOLS]
    if not tools:
        tools = [t for t in agent_tools.TOOLS if t not in ("web_search", "web_fetch")][:6]
    return tools


def _plain_engine_why(cortex, owns: bool = True) -> str:
    """Engine refusal as a sentence a person can act on. Raw text stays in the server log."""
    raw = str((cortex or {}).get("error") or "") if isinstance(cortex, dict) else "Cortex down"
    reason = str((cortex or {}).get("reason") or "") if isinstance(cortex, dict) else ""
    _log.warning("Cortex engine refused an agent run: %s %s", reason, raw[:300])
    low = raw.lower()
    if "not the cortex engine" in low:
        return "Cortex is running, but it is not the part that runs agents. Check it from Apps."
    if "loop failed" in low or "model backend" in low:
        return "Cortex is running, but it could not finish this. Try again."
    if "timed out" in low or "timeout" in low:
        return "Cortex took too long to answer. Try again."
    if "empty answer" in low:
        return "Cortex sent back an empty answer."
    if not raw or reason == "wrong_surface" or any(
        w in low for w in ("offline", "down", "unreachable", "refused", "connect", "not running", "has no /api/engine")
    ):
        if not owns:
            return "Cortex is not running"
        return "Cortex is not running, so this research agent cannot run. Start it from Apps."
    return "Cortex could not run this agent. Try again."


def _stopped_event(run_id: int, agent_id: int) -> dict:
    audit.log("agent.run.stopped", detail=f"agent={agent_id} run={run_id}", ok=True)
    return {"type": "stopped", "run_id": run_id, "agent_id": agent_id, "text": "Stopped. Nothing more was run."}


def _safe_tool_event(name: str, result: dict) -> dict:
    try:
        from cortex_runtime import safe_tool_result

        ev = {"type": "tool", "name": name, "result": safe_tool_result(result)}
    except Exception:
        ev = {"type": "tool", "name": name, "result": {"ok": result.get("ok")}}
    return ev

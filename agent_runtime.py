"""Cortex in-app agent runtime — multi-step tool loop, Thinking modes."""
from __future__ import annotations

import json
import re
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
        "Prefer fs_patch over fs_write for edits.\n"
        "When done, respond with plain text (no JSON).\n\n"
        f"{(rules or '').strip()}"
    ).strip()
    tools = f"Available tools:\n{json.dumps(tool_hint)}"
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
                    if '"tool"' in candidate:
                        return candidate
                    break
        start = text.find("{", start + 1)
    return None


def _parse_tool_call(text: str) -> dict | None:
    """Parse TOOL_CALL JSON from model output (supports nested params)."""
    raw = _extract_balanced_json(text or "")
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        if obj.get("tool"):
            params = obj.get("params") if isinstance(obj.get("params"), dict) else {}
            return {"tool": str(obj["tool"]), "params": params}
    except json.JSONDecodeError:
        pass
    return None


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


def run_agent_events(
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
) -> Iterator[dict]:
    """Yield SSE-style events for an agent run with multi-step tool loop."""
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
        run = agent_store.create_run(agent_id, prompt)
        run_id = int(run["id"])

    audit.log("agent.run.start", detail=f"agent={agent_id} run={run_id} mode={thinking_mode}", ok=True)
    yield {"type": "status", "text": f"Running {agent['name']} ({thinking_mode})…", "run_id": run_id, "agent_id": agent_id}

    tools = [t for t in (agent.get("tools") or []) if t in agent_tools.TOOLS]
    if not tools:
        tools = list(agent_tools.TOOLS.keys())[:6]
    # web_search is the primary organ — always first when available
    if "web_search" in agent_tools.TOOLS:
        tools = ["web_search"] + [t for t in tools if t != "web_search"]
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
            yield {"type": "thinking", "text": "Summarizing session…\n"}
            sm = agent_tools.run_tool("session_summarize", {"session_id": session_id}, run_id=run_id, agent_id=agent_id)
            steps.append({"tool": "session_summarize", "ok": sm.get("ok")})
            if sm.get("summary"):
                context_blocks.append(sm["summary"][:3000])
            yield _safe_tool_event("session_summarize", sm)

        if "vault_read" in tools:
            yield {"type": "thinking", "text": "Searching vault…\n"}
            vr = agent_tools.run_tool("vault_read", {"query": (prompt or "")[:200]}, run_id=run_id, agent_id=agent_id)
            steps.append({"tool": "vault_read", "ok": vr.get("ok")})
            if vr.get("snippets"):
                context_blocks.append(json.dumps(vr["snippets"])[:2000])
            yield _safe_tool_event("vault_read", vr)

        goal_driven = bool((agent.get("config") or {}).get("goal_driven")) if isinstance(agent.get("config"), dict) else False
        if thinking_mode == "deep" and "web_search" in tools and len(prompt or "") > 20:
            yield {"type": "thinking", "text": "Web search…\n"}
            ws = agent_tools.run_tool("web_search", {"query": prompt[:120]}, run_id=run_id, agent_id=agent_id)
            steps.append({"tool": "web_search", "ok": ws.get("ok")})
            if not ws.get("ok") or not ws.get("snippets"):
                # Alternate query — goal-driven runs keep probing until a source works
                alt_q = " ".join((prompt or "").split()[:12]) + " free API tools"
                yield {"type": "status", "text": "Web search fallback query…"}
                ws2 = agent_tools.run_tool("web_search", {"query": alt_q[:120]}, run_id=run_id, agent_id=agent_id)
                steps.append({"tool": "web_search", "ok": ws2.get("ok"), "fallback": True})
                if ws2.get("snippets"):
                    ws = ws2
                yield _safe_tool_event("web_search", ws2)
            if ws.get("snippets"):
                context_blocks.append(json.dumps(ws["snippets"])[:2000])
            yield _safe_tool_event("web_search", ws)

        analysis = ""
        model = "agent-local"
        step = 0
        llm_fail_streak = 0
        while step < max_steps and tokens_used < token_budget:
            step += 1
            if not ai_engine:
                analysis = f"Completed {len(steps)} tool step(s). LLM unavailable."
                break

            yield {"type": "thinking", "text": f"Step {step}…\n"}
            tool_hint = agent_tools.tool_schemas(tools)
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
                yield {"type": "status", "text": f"LLM provider failed — trying fallback APIs ({llm_fail_streak})…"}
                if llm_fail_streak >= 3 or not goal_driven:
                    analysis = f"LLM error: {e}"
                    yield {"type": "error", "text": analysis}
                    break
                continue

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
        agent_store.finish_run(run_id, status="done", result=analysis, audit_ref=f"run:{run_id}")
        yield {"type": "done", "run_id": run_id, "agent_id": agent_id, "analysis": analysis, "model": model, "steps": steps}
        audit.log("agent.run.done", detail=f"agent={agent_id} run={run_id}", ok=True)
    except Exception as e:
        agent_store.finish_run(run_id, status="error", error=str(e)[:500])
        audit.log("agent.run.error", detail=str(e)[:300], ok=False)
        yield {"type": "error", "text": str(e)[:500], "run_id": run_id}


def _safe_tool_event(name: str, result: dict) -> dict:
    try:
        from cortex_runtime import safe_tool_result

        ev = {"type": "tool", "name": name, "result": safe_tool_result(result)}
    except Exception:
        ev = {"type": "tool", "name": name, "result": {"ok": result.get("ok")}}
    return ev

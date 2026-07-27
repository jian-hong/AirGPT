"""First-party tools for Cortex agent runs — all calls are audited."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

import agent_store
import audit
import db

try:
    import cortex_client
except ImportError:
    cortex_client = None  # type: ignore

try:
    from ai_engine import retrieve_vault_snippets, web_search_snippets
except Exception:
    retrieve_vault_snippets = None  # type: ignore
    web_search_snippets = None  # type: ignore


def _audit(tool: str, args: dict, result: Any, *, ok: bool = True, run_id: int = 0, agent_id: int = 0) -> None:
    detail = json.dumps(
        {
            "tool": tool,
            "args_hash": hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:16],
            "result_hash": hashlib.sha256(str(result)[:2000].encode()).hexdigest()[:16],
            "run_id": run_id,
            "agent_id": agent_id,
        },
        ensure_ascii=False,
    )[:500]
    audit.log(f"agent.tool.{tool}", detail=detail, ok=ok)
    if cortex_client:
        try:
            cortex_client.append_ledger(f"agent.tool.{tool}", detail)
        except Exception:
            pass


def vault_read(path: str = "", query: str = "", *, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"path": path, "query": query}
    try:
        if query:
            snippets = []
            if retrieve_vault_snippets:
                raw = retrieve_vault_snippets(query, k=8) or ""
                if raw:
                    snippets.append({"excerpt": raw[:2000]})
            else:
                from config import DATA_DIR

                root = DATA_DIR / "vault"
                if root.is_dir():
                    q = query.lower()
                    for p in root.rglob("*.md"):
                        text = p.read_text(encoding="utf-8", errors="ignore")
                        if q in text.lower():
                            snippets.append({"path": str(p), "excerpt": text[:400]})
                        if len(snippets) >= 8:
                            break
            out = {"ok": True, "snippets": snippets}
        else:
            tree = db.list_vault_tree() if hasattr(db, "list_vault_tree") else {"categories": []}
            out = {"ok": True, "tree": tree}
        _audit("vault_read", args, out, ok=True, run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("vault_read", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def vault_write(title: str, body: str, category: str = "general", *, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"title": title, "category": category, "len": len(body or "")}
    try:
        import vault as vault_mod

        backend = "local_vault"
        try:
            backend = str(agent_store.memory_overview().get("backend") or "local_vault")
        except Exception:
            pass

        if backend == "project_wing":
            rel = vault_mod.write_drawer(
                project=category or "general",
                title=title or "note",
                body=body or "",
                room="general",
                source="agent",
            )
            path_str = str((vault_mod.ROOT / "data" / rel).resolve())
        else:
            from config import DATA_DIR
            from datetime import datetime

            folder = DATA_DIR / "vault" / (category or "general")
            folder.mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in (title or "note"))[:60].strip() or "note"
            path = folder / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe}.md"
            path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
            path_str = str(path)
            rel = None

        if cortex_client:
            try:
                cortex_client.append_ledger("vault.saved", path_str)
            except Exception:
                pass
        out = {"ok": True, "path": path_str, "backend": backend}
        if rel:
            out["rel"] = rel
        _audit("vault_write", args, out, ok=True, run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("vault_write", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def audit_append(action: str, detail: str = "", *, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"action": action, "detail": detail[:200]}
    try:
        audit.log(action[:80], detail=detail[:500], ok=True)
        out = {"ok": True}
        _audit("audit_append", args, out, ok=True, run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("audit_append", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def session_summarize(session_id: int = 0, *, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"session_id": session_id}
    try:
        msgs = db.get_messages(session_id=int(session_id) or None) if session_id else db.get_messages()
        lines = []
        for m in (msgs or [])[-40:]:
            who = m.get("device_name") or "?"
            text = (m.get("text") or m.get("ai_analysis") or "")[:240]
            if text:
                lines.append(f"- {who}: {text}")
        summary = "Session summary\n" + ("\n".join(lines) if lines else "(empty)")
        out = {"ok": True, "summary": summary[:6000], "count": len(lines)}
        _audit("session_summarize", args, out, ok=True, run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("session_summarize", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def fs_read(path: str = "", *, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"path": path}
    try:
        import workspace_api

        out = workspace_api.read_file(path)
        _audit("fs_read", args, out, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("fs_read", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def fs_write(path: str, content: str, *, apply: bool = True, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"path": path, "len": len(content or ""), "apply": apply}
    try:
        import workspace_api

        out = workspace_api.write_file(path, content, apply=apply)
        _audit("fs_write", args, out, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("fs_write", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def fs_patch(path: str, old: str, new: str, *, apply: bool = True, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"path": path, "apply": apply}
    try:
        import workspace_api

        out = workspace_api.patch_file(path, old, new, apply=apply)
        _audit("fs_patch", args, out, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("fs_patch", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def fs_search(query: str, *, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"query": query}
    try:
        import workspace_api

        out = workspace_api.search_files(query)
        _audit("fs_search", args, out, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("fs_search", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def fs_glob(pattern: str = "**/*", *, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"pattern": pattern}
    try:
        import workspace_api

        out = workspace_api.glob_paths(pattern)
        _audit("fs_glob", args, out, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("fs_glob", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def run_command(cmd: str, *, cwd: str = "", run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"cmd": cmd[:200], "cwd": cwd}
    try:
        import terminal_pty

        out = terminal_pty.run_command(cmd, cwd=cwd)
        _audit("run_command", args, out, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("run_command", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def git_status(*, run_id: int = 0, agent_id: int = 0) -> dict:
    return run_command("git status", run_id=run_id, agent_id=agent_id)


def git_diff(path: str = "", *, run_id: int = 0, agent_id: int = 0) -> dict:
    path = (path or "").replace("\\", "/").strip()
    if path and (".." in path.split("/") or any(c in path for c in '|;&`"\'<>\n')):
        return {"ok": False, "error": "invalid path", "exit_code": -1, "stdout": "", "stderr": ""}
    cmd = f"git diff -- {path}" if path else "git diff"
    return run_command(cmd, run_id=run_id, agent_id=agent_id)


def memory_add(fact: str, *, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"fact": (fact or "")[:500]}
    try:
        import memory_index

        memory_index.add_memory(kind="memory", title="agent fact", body=fact, source="agent")
        out = {"ok": True}
        _audit("memory_add", args, out, ok=True, run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("memory_add", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def memory_search(query: str, *, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"query": query}
    try:
        import memory_index

        hits = memory_index.search(query, k=8) or []
        out = {"ok": True, "hits": hits}
        _audit("memory_search", args, out, ok=True, run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("memory_search", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def memory_forget(memory_id: int, *, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"id": memory_id}
    try:
        import memory_index

        memory_index.delete_memory(int(memory_id))
        out = {"ok": True}
        _audit("memory_forget", args, out, ok=True, run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("memory_forget", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def web_search(query: str, *, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"query": query}
    try:
        snippets = []
        if web_search_snippets and query:
            raw = web_search_snippets(query, max_results=5) or ""
            if raw:
                snippets.append({"excerpt": raw[:2000]})
        out = {"ok": True, "snippets": snippets}
        _audit("web_search", args, out, ok=True, run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("web_search", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def rag_list_spaces(*, run_id: int = 0, agent_id: int = 0) -> dict:
    args: dict = {}
    try:
        from rag import store as rag_store
        from rag.agents import seed_rag_agents

        seed_rag_agents()
        spaces = rag_store.list_spaces()
        out = {"ok": True, "spaces": spaces}
        _audit("rag_list_spaces", args, {"ok": True, "n": len(spaces)}, ok=True, run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("rag_list_spaces", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def rag_ingest(space_id: int = 0, path: str = "", paths: list | None = None, *, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"space_id": space_id, "path": path, "paths": paths}
    try:
        from rag import ingest as rag_ingest_mod
        from rag import store as rag_store

        sid = int(space_id or 0)
        if sid <= 0:
            sp = rag_store.create_space("Agent RAG")
            sid = int(sp["id"])
        plist = list(paths or [])
        if path:
            plist.append(path)
        if not plist:
            out = {"ok": False, "error": "path or paths required"}
            _audit("rag_ingest", args, out, ok=False, run_id=run_id, agent_id=agent_id)
            return out
        out = rag_ingest_mod.ingest_paths(sid, plist, force=True)
        out["space_id"] = sid
        _audit("rag_ingest", args, {"ok": out.get("ok"), "job_id": out.get("job_id")}, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("rag_ingest", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def rag_search(query: str, space_id: int = 0, depth: str = "high", *, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"query": query, "space_id": space_id, "depth": depth}
    try:
        from rag import retrieve as rag_retrieve
        from rag import store as rag_store

        sid = int(space_id or 0)
        if sid <= 0:
            spaces = rag_store.list_spaces(limit=1)
            if not spaces:
                out = {"ok": False, "error": "no RAG spaces"}
                _audit("rag_search", args, out, ok=False, run_id=run_id, agent_id=agent_id)
                return out
            sid = int(spaces[0]["id"])
        out = rag_retrieve.search(sid, query, depth=depth or "high", top_k=8, debug=False)
        _audit("rag_search", args, {"ok": out.get("ok"), "trace_id": out.get("trace_id")}, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("rag_search", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def rag_answer(query: str, space_id: int = 0, depth: str = "high", chat_id: int = 0, *, run_id: int = 0, agent_id: int = 0) -> dict:
    args = {"query": query, "space_id": space_id, "depth": depth, "chat_id": chat_id}
    try:
        from rag import answer as rag_answer_mod
        from rag import store as rag_store

        sid = int(space_id or 0)
        if sid <= 0:
            spaces = rag_store.list_spaces(limit=1)
            if not spaces:
                out = {"ok": False, "error": "no RAG spaces"}
                _audit("rag_answer", args, out, ok=False, run_id=run_id, agent_id=agent_id)
                return out
            sid = int(spaces[0]["id"])
        out = rag_answer_mod.answer(sid, query, depth=depth or "high", chat_id=int(chat_id or 0), use_llm=True)
        _audit("rag_answer", args, {"ok": out.get("ok"), "trace_id": out.get("trace_id")}, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
        return out
    except Exception as e:
        out = {"ok": False, "error": str(e)[:300]}
        _audit("rag_answer", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out


def dms_query(object_type: str = "", filters: dict | None = None, limit: int = 20, *, run_id: int = 0, agent_id: int = 0) -> dict:
    """O5 — read DMS objects via the Cortex Agent SDK sidecar (PII-scoped)."""
    args = {"object_type": object_type, "filters": filters or {}, "limit": limit}
    if not cortex_client or not hasattr(cortex_client, "query_objects"):
        out = {"ok": False, "error": "cortex sidecar unavailable"}
        _audit("dms_query", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out
    out = cortex_client.query_objects(object_type, filters or {}, limit=limit)
    _audit("dms_query", args, out, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
    return out


def dms_action(action_id: str = "", params: dict | None = None, confirmed: bool = False, *, run_id: int = 0, agent_id: int = 0) -> dict:
    """O5 — invoke a registered DMS action type (governed F8 path, ledgered).

    Denials come back with a verdict (rbac / confirm_required / unregistered)
    instead of raising — the agent loop can surface "needs human confirm".
    """
    args = {"action_id": action_id, "confirmed": bool(confirmed)}
    if not cortex_client or not hasattr(cortex_client, "call_action"):
        out = {"ok": False, "error": "cortex sidecar unavailable"}
        _audit("dms_action", args, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out
    out = cortex_client.call_action(
        action_id, params or {}, confirmed=bool(confirmed), run_id=f"agent{agent_id}r{run_id}" if run_id else None
    )
    _audit("dms_action", args, out, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
    return out


def desktop_observe(*, run_id: int = 0, agent_id: int = 0) -> dict:
    """See the screen: cursor, foreground app, windows, screenshot meta."""
    import desktop_control

    out = desktop_control.observe()
    # Never put megabyte screenshots into the audit log
    audit_out = {k: v for k, v in out.items() if k != "screenshot"}
    if isinstance(out.get("screenshot"), dict):
        audit_out["screenshot"] = {
            k: out["screenshot"].get(k)
            for k in ("ok", "width", "height", "bytes", "png_omitted")
        }
    _audit("desktop_observe", {}, audit_out, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
    return out


def desktop_plan(goal: str = "", tokens_left: int = 0, prefer: str = "", *, run_id: int = 0, agent_id: int = 0) -> dict:
    """Chill plan: pick Word vs ChatGPT vs Claude vs tutorial from what is open."""
    import desktop_playbook

    out = desktop_playbook.plan_task(
        goal,
        tokens_left=int(tokens_left) if tokens_left else None,
        prefer=prefer or None,
    )
    _audit("desktop_plan", {"goal": goal[:200]}, out, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
    return out


def desktop_click(x: int = 0, y: int = 0, button: str = "left", confirmed: bool = False, *, run_id: int = 0, agent_id: int = 0) -> dict:
    import desktop_control

    out = desktop_control.click(int(x), int(y), button=button or "left", confirmed=bool(confirmed))
    _audit("desktop_click", {"x": x, "y": y, "confirmed": confirmed}, out, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
    return out


def desktop_type(text: str = "", confirmed: bool = False, *, run_id: int = 0, agent_id: int = 0) -> dict:
    import desktop_control

    out = desktop_control.type_text(text or "", confirmed=bool(confirmed))
    _audit("desktop_type", {"chars": len(text or ""), "confirmed": confirmed}, out, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
    return out


def desktop_scroll(dy: int = -3, confirmed: bool = False, *, run_id: int = 0, agent_id: int = 0) -> dict:
    import desktop_control

    out = desktop_control.scroll(int(dy), confirmed=bool(confirmed))
    _audit("desktop_scroll", {"dy": dy, "confirmed": confirmed}, out, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
    return out


def desktop_drag(x1: int = 0, y1: int = 0, x2: int = 0, y2: int = 0, confirmed: bool = False, *, run_id: int = 0, agent_id: int = 0) -> dict:
    import desktop_control

    out = desktop_control.drag(int(x1), int(y1), int(x2), int(y2), confirmed=bool(confirmed))
    _audit("desktop_drag", {"confirmed": confirmed}, out, ok=bool(out.get("ok")), run_id=run_id, agent_id=agent_id)
    return out


TOOLS: dict[str, Callable[..., dict]] = {
    "vault_read": vault_read,
    "vault_write": vault_write,
    "audit_append": audit_append,
    "session_summarize": session_summarize,
    "web_search": web_search,
    "fs_read": fs_read,
    "fs_write": fs_write,
    "fs_patch": fs_patch,
    "fs_search": fs_search,
    "fs_glob": fs_glob,
    "run_command": run_command,
    "git_status": git_status,
    "git_diff": git_diff,
    "memory_add": memory_add,
    "memory_search": memory_search,
    "memory_forget": memory_forget,
    "rag_list_spaces": rag_list_spaces,
    "rag_ingest": rag_ingest,
    "rag_search": rag_search,
    "rag_answer": rag_answer,
    "dms_query": dms_query,
    "dms_action": dms_action,
    "desktop_observe": desktop_observe,
    "desktop_plan": desktop_plan,
    "desktop_click": desktop_click,
    "desktop_type": desktop_type,
    "desktop_scroll": desktop_scroll,
    "desktop_drag": desktop_drag,
    # Handled specially in agent_runtime (needs parent run context); stub keeps schema discovery working
    "subagent_dispatch": lambda prompt="", text="", agent_id=0, run_id=0, **kw: {
        "ok": False,
        "error": "subagent_dispatch must run inside agent_runtime",
    },
}


def tool_schemas(names: list[str] | None = None) -> list[dict]:
    """JSON schemas for LLM tool-calling loop."""
    catalog = {
        "vault_read": {"description": "Search vault notes", "params": ["query", "path"]},
        "vault_write": {"description": "Save note to vault", "params": ["title", "body", "category"]},
        "web_search": {"description": "Search the web", "params": ["query"]},
        "session_summarize": {"description": "Summarize chat session", "params": ["session_id"]},
        "fs_read": {"description": "Read workspace file", "params": ["path"]},
        "fs_write": {"description": "Write workspace file", "params": ["path", "content"]},
        "fs_patch": {"description": "Patch workspace file", "params": ["path", "old", "new"]},
        "fs_search": {"description": "Search workspace files", "params": ["query"]},
        "run_command": {"description": "Run allowlisted shell command", "params": ["cmd", "cwd"]},
        "git_status": {"description": "Git status in workspace", "params": []},
        "git_diff": {"description": "Git diff for path", "params": ["path"]},
        "memory_add": {"description": "Remember a fact", "params": ["fact"]},
        "memory_search": {"description": "Search memories", "params": ["query"]},
        "rag_list_spaces": {"description": "List RAG knowledge spaces", "params": []},
        "rag_ingest": {"description": "Ingest path(s) into a RAG space", "params": ["space_id", "path", "paths"]},
        "rag_search": {"description": "Hybrid search a RAG space", "params": ["query", "space_id", "depth"]},
        "rag_answer": {"description": "Answer from a RAG space with citations", "params": ["query", "space_id", "depth", "chat_id"]},
        "dms_query": {"description": "Read DMS warehouse objects (inventory/suppliers/locations/shipments/transactions/alerts) via Cortex; PII columns are never returned", "params": ["object_type", "filters", "limit"]},
        "dms_action": {"description": "Invoke a governed DMS action type (e.g. export_pptx); may return confirm_required — ask the human, then retry with confirmed=true", "params": ["action_id", "params", "confirmed"]},
        "desktop_observe": {"description": "See the desktop: cursor position, foreground app, open windows, screenshot", "params": []},
        "desktop_plan": {"description": "Plan a human-style action path (Word vs ChatGPT vs Claude vs tutorial) from what is already open", "params": ["goal", "tokens_left", "prefer"]},
        "desktop_click": {"description": "Click at screen x,y (needs confirmed=true)", "params": ["x", "y", "button", "confirmed"]},
        "desktop_type": {"description": "Type/paste text into the focused app (needs confirmed=true)", "params": ["text", "confirmed"]},
        "desktop_scroll": {"description": "Scroll the focused window (needs confirmed=true)", "params": ["dy", "confirmed"]},
        "desktop_drag": {"description": "Drag cursor from x1,y1 to x2,y2 (needs confirmed=true)", "params": ["x1", "y1", "x2", "y2", "confirmed"]},
        "subagent_dispatch": {
            "description": "Queue an isolated child subagent (deep mode only, max 2)",
            "params": ["prompt", "agent_id"],
        },
    }
    keys = names or list(catalog.keys())
    return [{"name": k, **catalog[k]} for k in keys if k in catalog]

def run_tool(name: str, params: dict | None = None, *, run_id: int = 0, agent_id: int = 0) -> dict:
    fn = TOOLS.get(name)
    if not fn:
        out = {"ok": False, "error": f"unknown tool: {name}"}
        _audit(name or "unknown", params or {}, out, ok=False, run_id=run_id, agent_id=agent_id)
        return out
    params = params or {}
    return fn(**params, run_id=run_id, agent_id=agent_id)

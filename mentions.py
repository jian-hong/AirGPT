"""Global @ mention resolver — extends OpenIDE @path with chat/project/rag/memory."""
from __future__ import annotations

import re
from typing import Any

# @rag:name | @chat:id | @project:name | @memory | @file:path | bare @path
MENTION_RE = re.compile(
    r"@(?P<kind>rag|chat|project|file|agent):(?P<value>[^\s@]+)"
    r"|@(?P<memory>memory)\b"
    r"|@(?P<path>(?:[A-Za-z]:)?[^\s@]+(?:[/\\][^\s@]+)*)",
    re.IGNORECASE,
)


def find_mentions(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in MENTION_RE.finditer(text or ""):
        if m.group("kind"):
            out.append({"kind": m.group("kind").lower(), "value": m.group("value") or ""})
        elif m.group("memory"):
            out.append({"kind": "memory", "value": ""})
        else:
            out.append({"kind": "file", "value": m.group("path") or ""})
    return out


def suggest(query: str, *, space_id: int = 0, limit: int = 12) -> list[dict[str, Any]]:
    """Autocomplete suggestions for the @ picker."""
    q = (query or "").lstrip("@").strip().lower()
    items: list[dict[str, Any]] = []

    # static kinds
    for kind, label in (
        ("memory", "Memory Agent"),
        ("rag", "RAG space"),
        ("agent", "Cortex agent"),
        ("project", "Project"),
        ("chat", "Chat"),
        ("file", "File path"),
    ):
        if not q or kind.startswith(q) or q in label.lower():
            items.append({"kind": kind, "label": label, "insert": f"@{kind}:" if kind != "memory" else "@memory"})

    try:
        import agent_store

        agent_store.init()
        for a in agent_store.list_agents(limit=30):
            name = str(a.get("name") or "")
            if name.lower() == "vault summarizer":
                continue
            if not q or q in name.lower() or q.startswith("agent"):
                items.append(
                    {
                        "kind": "agent",
                        "label": f"Agent · {name}",
                        "insert": f"@agent:{a.get('id')}",
                        "agent_id": a.get("id"),
                    }
                )
    except Exception:
        pass

    try:
        from rag import store as rag_store

        for sp in rag_store.list_spaces(limit=30):
            name = str(sp.get("name") or "")
            slug = str(sp.get("slug") or "")
            if not q or q in name.lower() or q in slug.lower() or q.startswith("rag"):
                items.append(
                    {
                        "kind": "rag",
                        "label": f"RAG · {name}",
                        "insert": f"@rag:{slug}",
                        "space_id": sp.get("id"),
                    }
                )
    except Exception:
        pass

    if space_id:
        try:
            from rag import store as rag_store

            for src in rag_store.list_sources(space_id)[:40]:
                path = str(src.get("path") or "")
                title = str(src.get("title") or "")
                if not q or q in path.lower() or q in title.lower():
                    items.append(
                        {
                            "kind": "file",
                            "label": title or path,
                            "insert": f"@file:{path}",
                            "source_id": src.get("id"),
                        }
                    )
        except Exception:
            pass

    return items[:limit]


def resolve(text: str, *, max_chars: int = 6000) -> dict[str, Any]:
    """Resolve mentions into bounded context + retrieval filters."""
    mentions = find_mentions(text)
    contexts: list[dict[str, Any]] = []
    filters: dict[str, Any] = {"space_ids": [], "paths": []}
    used = 0

    for m in mentions:
        kind = m["kind"]
        value = m["value"]
        if kind == "memory":
            try:
                import memory_index

                hits = memory_index.search(value or "recent", k=4) or []
                body = "\n".join(f"- {h.get('title')}: {(h.get('body') or '')[:240]}" for h in hits)
                if body and used + len(body) < max_chars:
                    contexts.append({"kind": "memory", "text": body})
                    used += len(body)
            except Exception:
                pass
        elif kind == "rag":
            try:
                from rag import store as rag_store

                sp = rag_store.get_space_by_slug(value) or None
                if not sp and value.isdigit():
                    sp = rag_store.get_space(int(value))
                if sp:
                    filters["space_ids"].append(int(sp["id"]))
                    contexts.append({"kind": "rag", "space_id": sp["id"], "name": sp.get("name")})
            except Exception:
                pass
        elif kind == "file":
            filters["paths"].append(value)
            try:
                import workspace_api

                data = workspace_api.read_file(value) if hasattr(workspace_api, "read_file") else None
                content = ""
                if isinstance(data, dict):
                    content = str(data.get("content") or data.get("text") or "")
                elif isinstance(data, str):
                    content = data
                content = content[:8000]
                if content and used + len(content) < max_chars:
                    contexts.append({"kind": "file", "path": value, "text": content})
                    used += len(content)
            except Exception:
                contexts.append({"kind": "file", "path": value, "text": ""})
        elif kind == "project":
            filters.setdefault("projects", []).append(value)
            try:
                import vault as vault_mod

                hits = vault_mod.search_wings(value, project=value, k=4) if hasattr(vault_mod, "search_wings") else []
                body = "\n".join(str(h)[:240] for h in (hits or [])[:4])
                if body and used + len(body) < max_chars:
                    contexts.append({"kind": "project", "project": value, "text": body})
                    used += len(body)
            except Exception:
                pass
        elif kind == "chat":
            filters.setdefault("chat_refs", []).append(value)

    return {"mentions": mentions, "contexts": contexts, "filters": filters}

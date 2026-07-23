"""Seed RAG (and related) agents into agent_store.

Memory is NOT an agent — it is the chat memory panel (memFab / memory_index).
Only pin-able workers belong here.
"""
from __future__ import annotations


def seed_rag_agents() -> dict:
    try:
        import agent_store

        agent_store.init()
        existing = {a.get("name"): a for a in agent_store.list_agents(100)}
        created: list[int] = []

        if "RAG" not in existing:
            a = agent_store.create_agent(
                "RAG",
                kind="rag_service",
                skill_pack="rag",
                tools=[
                    "rag_list_spaces",
                    "rag_ingest",
                    "rag_search",
                    "rag_answer",
                    "memory_search",
                    "vault_read",
                    "audit_append",
                ],
                config={
                    "description": "RAG Agent — build/chat knowledge spaces with High/Max depth and citations.",
                    "role": "rag_service",
                    "depth_default": "high",
                    "surface": "rag",
                },
                pinned=True,
            )
            created.append(int(a.get("id") or 0))
        else:
            # Ensure RAG stays pin-able; do not force re-pin if user unpinned
            pass

        return {"ok": True, "created": [c for c in created if c]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

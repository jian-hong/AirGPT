"""AirGPT RAG Agent service — local-first knowledge spaces.

Phase 0/1 foundation. See docs/RAG_AGENT_IMPLEMENTATION_PLAN.md.
Personal default: SQLite + FTS (+ optional vector later). No Docker required.
"""
from __future__ import annotations

from rag.agents import seed_rag_agents
from rag.store import init as init_store

__all__ = ["init_store", "seed_rag_agents"]

# Memory and RAG: three planes, profile-selected backends

Decision memo. Reconciles what was chosen across the memory/RAG design docs with
what the code does today, so future work maps decide -> implement -> gap cleanly.
No new research; this records the settled architecture.

Canonical sources: `docs/RAG_AGENT_IMPLEMENTATION_PLAN.md`,
`docs/SCALING_POSTGRES_REDIS.md`, `docs/memory-layer.md`, and (in Cortex)
`docs/research/findings/G1_GEN_CFSM_JEPA.md`.

## The rule that governs everything

**A profile flag picks the backend. It never changes the feature.** Personal
stays Docker-free (SQLite only). Redis and Qdrant are opt-in profiles, not a
replacement for SQLite on a laptop. Do not expose internal engine names
(GraphRAG, HybridRAG, SiRA) as product nouns.

## Three planes (keep separate; do not merge into one store)

| Plane | Role | Backend (decided) | Status in code |
|---|---|---|---|
| 1. Agentic / orchestration memory (Cortex, G1) | working turns, episodic traces, habits, audit | Redis hot -> RawKnn/Qdrant warm -> MemPalace verbatim -> Mem0-style facts; F1 append-only; fetch-before-forget | Cortex: Redis + RawKnn working; Qdrant partial; Mem0/MemPalace not productized |
| 2. RAG knowledge corpus (AirGPT `rag/`) | user docs, spaces, citations | Personal: SQLite + FTS + sqlite-vec. Local+: + Qdrant + Redis. Business: Postgres + pgvector/Qdrant + Redis | Personal path shipped and local-first; Local+/Business backends not built |
| 3. Default Memory Agent (AirGPT) | everyday chat / project recall | `memory_index` + MemPalace vault wings + a mem0-shaped API on SQLite | Live; stays on SQLite; keep separate from RAG corpora |

The sqlite-vec finding (dense retrieval on laptops) and the Redis->Qdrant scaling
plan are two different planes, not a contradiction.

## Architecture (what the user picks) vs storage (what runs)

Users pick a **depth**; Cortex picks the internal engine; storage is chosen by
the **profile**, independently.

| Depth (product noun) | Internal engine | Storage today |
|---|---|---|
| Basic | one-pass hybrid | sqlite-vec |
| High (default) | hybrid + SiRA + <=1 corrective pass | sqlite-vec |
| Max | agentic / graph / HybridRAG (KG + vector) when triggered | sqlite-vec until Local+/Business |
| Manual | preset ids only (`hybrid_rrf`, `agentic`, `graph`, `hybrid_kg`) | same |

SiRA is a lexical sidecar, not a store. GraphRAG / HybridRAG are query DAGs, not
"swap SQLite for Neo4j."

## Where the seam already is (verified in code)

- `knowledge_spaces.profile` exists, default `'local'` (`rag/store.py`). The
  backend selector is already persisted per space; the adapters behind it are
  what is missing.
- `rag/vectors.py` is "sqlite-vec when available, else blob + cosine" with a
  `backend` column. Local-first with graceful fallback. No Redis/Qdrant on the
  retrieval path.
- `rag/adaptive.py` resolves **depth** only (`recommended_depth`,
  `resolve_depth`). It does not yet route Max into graph/agentic lanes.
- Blob store is per space under `data/rag/<id>/`; blobs are post-extraction
  **text stored as `.txt`** so rebuild and export/import re-ingest them without
  re-running a binary extractor.

## Gap vs the ask

1. **Backends by profile.** Wired: `rag/vector_backends.py` dispatches on
   `knowledge_spaces.profile`. Local+ needs `QDRANT_URL` + `qdrant-client`;
   Business still "not built" (Postgres/pgvector).
2. **Adaptive architecture by task/DAG.** `rag/adaptive.py` picks depth; the Max
   graph/agentic lanes and the Cortex `rag_*` DAG nodes are still thin.
3. **Any filetype.** Smart normalize + gated media Phase 1 landed; image OCR /
   keyframe captions remain Phase 2–3.
4. **Cortex temporary memory.** G1 Redis working set (2h / 10 turns) exists; the
   spin-up/teardown facade for gen-cFSM is still to wire.

## Shipped this pass (A and E)

- **A - Rebuild.** RAG settings has a "Rebuild whole pipeline" control that
  re-extracts, re-chunks, and re-embeds every source. Depth stays
  Basic/High/Max/Manual (no new tier; the product noun set is settled).
- **E - local-first correctness.** Confirmed the corpus is local per space
  (sqlite + sqlite-vec + `data/rag/<id>/`), no Redis/Qdrant on the path. Fixed
  the blob/export/import architecture so a rebuild or import never drops
  uploaded sources (text blobs carry `.txt`; rebuild falls back to the local
  blob when the original upload path is gone). Verified end-to-end with the real
  embedder in an isolated data dir.

## Shipped next (adapters + smart ingest + C/D)

1. **VectorStore adapters** behind `knowledge_spaces.profile`:
   `local` | `local_qdrant` | `business` via `rag/vector_backends.py`.
   Local+ Qdrant upserts when `QDRANT_URL` + `qdrant-client` exist; otherwise
   ingest fails loudly and search soft-falls to local with
   `backend_fallback=local`. Redis is semantic-cache only (`rag/semantic_cache.py`).
2. **Smart normalize** (`rag/normalize.py`) + Jaccard demotion in chunking;
   media Phase 1 gated in `rag/media.py`.
3. **C/D UX:** Settings no longer authors agents; Cortex one-click subagent +
   trend chips; GitHub device OAuth (`github_auth.py`).

## Sequenced later

1. Wire Mem0/MemPalace only on the agentic plane (Cortex `memory/vault_layers.py`, G1 P3).
2. Video keyframe captions + frame OCR (Phase 2–3).
3. Full Business Postgres/pgvector.
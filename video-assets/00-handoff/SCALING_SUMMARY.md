# Scaling summary (handoff note)

Full design: `docs/SCALING_POSTGRES_REDIS.md`. Design only — **local-first
default is untouched**; Personal mode stays SQLite + files in `data/`, zero
services, EXE-friendly.

## Decision in one table

| Layer | Personal (default) | Business / scale |
|-------|--------------------|------------------|
| Durable DB | SQLite (as today) | PostgreSQL (chats, audit, users, vault metadata) |
| Cache / sessions / hot memory | in-process + SQLite | Redis (TTL'd, always reconstructible) |
| Vector memory | sqlite-vec inside the existing `index.db` (FTS5 stays the fallback) | pgvector inside the same Postgres |
| Vault drawer bodies | filesystem | filesystem or S3; only metadata moves to Postgres |

## Key calls

- **ChromaDB is out**: heavy dependency tree + telemetry, duplicates our SQLite
  layer, and its scale path is running Chroma Server — a third service we
  refuse to operate. sqlite-vec → pgvector keeps one SQL mental model with
  zero extra services.
- Flags: `AIRGPT_STORAGE=sqlite|postgres`, `AIRGPT_CACHE=none|redis`,
  `AIRGPT_VECTOR=auto` (auto degrades to FTS5, same soft-fail as Chroma today).
- Business mode with unreachable Postgres **fails closed** (no silent
  split-brain); Redis loss degrades gracefully, never fatal.
- Migration is a one-shot script with dry-run + verify; rollback = flip the
  flag back, SQLite files are never touched.
- SQLite in WAL mode is fine to ~25 seats on one host — don't deploy Postgres
  before that.

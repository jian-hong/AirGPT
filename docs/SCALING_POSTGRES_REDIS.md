# Scaling AirGPT — Postgres + Redis + vector memory (design)

**Status: design doc. Nothing here changes the local-first default.**
Personal mode stays SQLite + files under `data/`, zero services, EXE-friendly.
This plan covers the **Business / scale path** only: what we add when one host
serves many seats, needs durable multi-writer storage, or runs behind more than
one process.

## Where state lives today (reality check)

| State | Current store | Notes |
|-------|---------------|-------|
| Chats, sessions, projects, devices | SQLite `data/clipdrop.db` (`db.py`) | Single writer, `threading.Lock`, ad-hoc `ALTER TABLE` migrations |
| Memory index (hot/warm) | SQLite + FTS5 `data/memory/index.db` (`memory_index.py`) | Chroma already **optional**, FTS is the always-on path |
| Agents | SQLite `data/agents.db` (`agent_store.py`) | |
| Audit | Append-only `data/audit.jsonl` (`audit.py`) | 50MB cap, truncates head — lossy at scale |
| Auth / ACL / join codes | JSON files (`auth_tokens.json`, `session_shares.json`, `token_session_acl.json`, ...) | Read-modify-write, no concurrency story |
| Vault wings (MemPalace) | Filesystem `data/vault/{project}/rooms/{topic}/` | Verbatim drawers, cold tier |
| Server | stdlib `ThreadingHTTPServer`, one process | Threads share one SQLite connection path |

The scaling ceiling is not SQLite itself — it is **one process, one disk, one
writer**. SQLite in WAL mode happily serves a 10–30 seat Hub host. The switch
matters when: multiple app processes, HA requirements, audit retention
guarantees (Business compliance), or >1 host sharing state.

## Recommended stack — decision table

| Layer | Personal / local (default) | Business / scale | Why this pick |
|-------|---------------------------|------------------|---------------|
| Durable storage | SQLite (`clipdrop.db`, `index.db`, `agents.db`) | **PostgreSQL 16+** — chats, audit, users/tokens, vault *metadata* | Boring, everywhere, one backup story, row-level locking for multi-writer |
| Cache / sessions / hot memory | In-process dicts + SQLite hot tier | **Redis 7** — session tokens, ACL cache, carry-pack hot snippets, rate limits, SSE fan-out (pub/sub) | Single binary, trivially managed (Upstash/ElastiCache), TTL semantics match hot/warm/cold model |
| Vector memory | **sqlite-vec** (optional, replaces Chroma slot) | **pgvector** (extension in the same Postgres) | See below — one SQL mental model at both tiers, zero extra services |
| Vault blobs | Filesystem `data/vault/` | Filesystem or S3-compatible; **metadata + FTS in Postgres** | Verbatim drawers stay files; only the index scales |
| Audit | `audit.jsonl` (local mirror) | Postgres append-only table, partitioned by month | JSONL truncation is unacceptable for Business compliance |

**Rule: the flag picks the backend, never the feature.** Every feature works in
both modes; Business mode only changes durability/concurrency.

## Vector memory: pick and why not ChromaDB

### Pick: sqlite-vec (local) → pgvector (scale)

- **sqlite-vec** — pure-C SQLite extension, `pip install sqlite-vec`, loads into
  the *existing* `data/memory/index.db` connection. Vectors live next to the
  FTS5 rows they describe; hybrid search is one SQL query. Brute-force scan =
  exact recall, ~3–20ms up to a few hundred thousand vectors — far beyond any
  single-user memory index. No server, no Docker, PyInstaller-friendly (one
  loadable `.dll`).
- **pgvector** — extension in the same Postgres we already run for Business.
  HNSW index when the corpus grows, `tsvector` + vector in one query for hybrid
  search. No third service to operate.

The pair keeps **one mental model** (SQL rows with an embedding column) and the
same `memory_index.search()` contract at both tiers — swap the `_embed_*`
functions, keep everything else.

### Why not ChromaDB

1. **Dependency weight vs. our ops reality.** `chromadb` pulls a large
   transitive tree (onnxruntime, tokenizers, posthog telemetry, a FastAPI
   server core). AirGPT ships as a PyInstaller EXE with a 7-line
   `requirements.txt`; Chroma roughly triples the packaging surface for a
   feature FTS5 + sqlite-vec covers in-process.
2. **It duplicates a layer we already have.** Chroma's persistence *is* SQLite
   underneath, plus its own segment files — a second database beside
   `index.db` with its own compaction and migration story.
3. **API churn.** Pre-1.0 history of breaking persistence-format and client API
   changes; our `_chroma()` glue already carries version-guard scar tissue.
4. **No path to the Business tier.** Chroma's scale story is running Chroma
   Server — a *new* service to deploy, monitor, back up, and secure, exactly
   what this plan avoids. pgvector rides the Postgres we must run anyway.
5. **Telemetry-by-default** conflicts with the local-first / Cortex-isolation
   posture (`CORTEX_LOCAL_ONLY=1` should mean *nothing* phones home).

Runner-up considered: **LanceDB** (embedded, Rust, ANN built in). Good fallback
if a single host ever needs multi-million-vector ANN *without* Postgres, but it
adds an Arrow-format data directory and a second storage engine to learn.
FAISS was rejected as index-only (no persistence/metadata story — we would
rebuild half a database around it). Qdrant embedded mode is not offered in
Python (server-only), so it fails the easy-setup bar.

## Target architecture (Business mode)

```
UI / guests ──► app process(es)  (clipdrop handler, N workers behind a port share or reverse proxy)
                    │
                    ├─► Redis ── sessions, token/ACL cache, rate limits,
                    │            carry-pack hot snippets (TTL), SSE pub/sub between workers
                    │
                    ├─► Postgres ── chats, projects, messages, users/tokens,
                    │               audit (partitioned), vault metadata,
                    │               memories + FTS(tsvector) + pgvector embeddings
                    │
                    └─► Filesystem / S3 ── vault drawer bodies, files, thumbs
```

Redis key sketch (all TTL'd, all reconstructible from Postgres):

| Key | Value | TTL |
|-----|-------|-----|
| `sess:{token}` | auth payload + ACL | share TTL (7d) |
| `hot:{session_id}` | next_action + carry pack | 24h |
| `rl:{ip}:{route}` | rate-limit counter | 1m window |
| `sub:chat:{session_id}` | pub/sub channel for SSE fan-out | — |

## Config flags (env.local)

```ini
# Storage backend — default sqlite; postgres requires DATABASE_URL
AIRGPT_STORAGE=sqlite          # sqlite | postgres
DATABASE_URL=                  # postgresql://user:pass@host:5432/airgpt

# Cache — default none (in-process); redis requires REDIS_URL
AIRGPT_CACHE=none              # none | redis
REDIS_URL=                     # redis://host:6379/0

# Vector memory — default none (FTS5 only), sqlite_vec if installed
AIRGPT_VECTOR=auto             # auto | none | sqlite_vec | pgvector
```

Resolution rules:

- `AIRGPT_STORAGE=sqlite` (default) → everything behaves exactly as today.
- `AIRGPT_STORAGE=postgres` with unreachable DB → **fail closed at startup**
  (refuse to serve Business writes against a stale SQLite copy — no silent
  split-brain). Explicit `--fallback-local` escape hatch for demos.
- `AIRGPT_VECTOR=auto` → `pgvector` when storage is postgres, else `sqlite_vec`
  if importable, else `none` (FTS5 only). This mirrors how Chroma is optional
  today, so removing Chroma is a doc change, not a behavior change.

## Code seams (when we implement — light, in order of pain relief)

1. **`memory_index.py`** — smallest seam. Replace `_chroma()/_embed_*` with a
   `_vector_backend()` returning sqlite-vec or pgvector ops. FTS fallback path
   already exists.
2. **`audit.py`** — `log()` writes to a backend: JSONL (default) or Postgres
   table (+ keep JSONL as local mirror for the host UI).
3. **`auth.py` JSON files → table-backed** — the JSON read-modify-write files
   are the first real multi-process correctness bug; move to `kv`/token tables
   (SQLite table locally, Postgres row + Redis cache at scale).
4. **`db.py`** — biggest surface (~1100 lines of module functions). Do NOT
   rewrite; extract a `storage/` package with `sqlite_impl.py` as the moved
   code and `pg_impl.py` implementing the same function signatures. Keep SQL
   dialect-portable (avoid SQLite-only tricks in new queries).

## Migration sketch (SQLite → Postgres, one-shot)

```
scripts/migrate_to_pg.py --database-url ... [--dry-run]
```

1. **Schema**: generate Postgres DDL — `INTEGER PRIMARY KEY AUTOINCREMENT` →
   `bigint generated always as identity`; `REAL` epoch timestamps → keep
   `double precision` (code passes floats everywhere; converting to
   `timestamptz` is a later cleanup); tags/JSON `TEXT` → `jsonb`.
2. **Copy**: stream rows per table in batches via `COPY`; order:
   projects → chat_sessions → messages → memories → agents → devices.
3. **Audit**: replay `audit.jsonl` into the partitioned audit table.
4. **Auth**: import the five JSON files into `users` / `tokens` / `acl` tables.
5. **Search**: build `tsvector` generated columns (replaces FTS5); re-embed
   memories into pgvector (embeddings are derived data — recompute, don't port).
6. **Verify**: row counts + max(id) + sampled checksums per table; print diff.
7. **Cutover**: stop server → run migration → set `AIRGPT_STORAGE=postgres` →
   start. **Rollback** = flip the flag back; SQLite files are never modified.
   (Writes made after cutover are lost on rollback — acceptable for a
   one-host cutover window, stated plainly to the operator.)

## Failure modes

| Failure | Behavior | Mitigation |
|---------|----------|------------|
| Postgres unreachable at startup (Business) | Fail closed, clear error + doc link | Health probe in `/api/hosting` panel; `--fallback-local` for demos |
| Postgres drops mid-session | Writes error, reads may serve from Redis cache | Retry with backoff; surface banner in UI; audit buffer to local JSONL and replay |
| Redis down | **Degrade, don't die**: fall back to in-process cache; sessions re-auth; SSE falls back to per-process only | Everything in Redis is reconstructible by design |
| Split-brain (SQLite edited while PG live) | Prevented: postgres mode never opens SQLite for writes | Migration renames `data/*.db` → `*.db.migrated` |
| Partial migration crash | Idempotent: `--resume` re-runs per-table with upsert-by-id | Verify step is mandatory before cutover |
| pgvector index bloat / slow HNSW build | Start with exact scan (<100k rows needs no index) | Add HNSW only when p95 search >50ms |
| sqlite-vec extension fails to load (locked-down Windows) | `AIRGPT_VECTOR=auto` silently degrades to FTS5 | Same soft-fail contract Chroma has today |

## Cost / ops complexity

| Tier | Stack | Infra cost | Ops burden |
|------|-------|-----------|------------|
| Personal (default) | SQLite + FTS5 (+ sqlite-vec) | $0 | None — ships in the EXE |
| Small Business (≤~25 seats, one host) | Same as Personal, WAL mode | $0 | None. **Don't reach for Postgres here.** |
| Business managed | Neon/Supabase Postgres (pgvector included) + Upstash Redis | ~$0–25/mo entry tiers | Near-zero: backups/HA are theirs; we own schema + migration script |
| Business self-hosted | docker-compose: postgres:16 + redis:7 on one VM | ~$20–40/mo VM | `pg_dump` nightly, Redis is disposable, one compose file |

The deliberate non-goals keeping ops flat: no Kubernetes, no message queue, no
separate vector service, no read replicas until a real workload demands them.

## Rollout order

1. Docs + flags reserved (this doc) — done.
2. Swap the optional Chroma slot for sqlite-vec in `memory_index.py` (pure win,
   local-only, no infra).
3. Postgres audit backend (first genuine Business need: durable compliance log).
4. Auth/token tables + Redis session cache.
5. `db.py` storage split + migration script + cutover runbook.

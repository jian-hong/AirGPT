# Project + chat memory layer

## Chat glass panel (normal chat)

Small square **top-right** of the chat column opens a liquid-glass overlay:

| Section | Purpose |
|---------|---------|
| Temporary next action | Session-scoped hot scratch |
| Global goals + current state | Project north-star (vault `goals.json`) |
| Memories | Indexed notes for this chat / project |
| Folders | Attached wing rooms used in this session |
| Drop to index | `.txt` / `.md` / pasted text → FTS (+ Chroma if installed) |

```http
GET  /api/memory/panel?session_id=&project=
GET  /api/memory/search?q=&project=&session_id=
POST /api/memory/add
POST /api/memory/ingest
POST /api/memory/folder
POST /api/memory/goals
```

## Storage stack (local-first)

| Layer | Role |
|-------|------|
| **SQLite + FTS5** | Always-on structured memories (`data/memory/index.db`) |
| **Carry pack (JEPA-light)** | Compressed hot/warm snippets injected into prompts (cap ~1200 chars). No heavy vector search product. |
| **Thin / forget** | Age demotion to short cold summaries; hard delete after retention |
| **Chroma** (optional) | Embeddings under `data/memory/chroma/` when `chromadb` is installed. Planned replacement: **sqlite-vec** in `index.db`, pgvector at Business scale — see [SCALING_POSTGRES_REDIS.md](SCALING_POSTGRES_REDIS.md) |
| **MemPalace wings** | Verbatim drawers `data/vault/{project}/rooms/{topic}/` |
| **Company feedback wing** | Dual-brain verified snippets → `data/vault/_company/rooms/feedback/` |
| **mem0** | Shape/API compatible locally; cloud sync deferred |

Hot / warm / cold (MEXT-inspired): next-action stays hot in SQLite; goals warm in rail/panel; older wings cold on SSD and retrieved by search.

```http
POST /api/memory/forget   {"thin": true, "days": 14}
POST /api/memory/forget   {"days": 90}
GET  /api/memory/thin
```

## DSA-style context (DeepSeek analog, message-level)

On each turn AirGPT:

1. Scores history (recency + query overlap + pin + compressed bonus)
2. Always keeps a sliding window of the last ~8 turns
3. Ditches low-score turns from the *prompt* when over ~12k chars or on hard topic shift
4. Indexes keepers into SQLite/FTS + vault wings; writes a carry summary for ditched topic
5. Saves each substantive Q/A turn into project memory (`session` room)

This mirrors DSA "lightning indexer → select" and NSA "compress + select + sliding" without sparse attention kernels.

See `db.ditch_context`, `db.index_important_from_ditch`, `ai_engine.persist_turn_memory`.


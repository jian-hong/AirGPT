# Division of labour: Cursor vs Claude (updated 2026-07-26)

Split by **work shape**, not by file size.

| Lane | Owner | Owns |
|------|--------|------|
| **Research + foundation + measured impl** | Cursor | Profiling, RAG/store/ANN, Mermaid aesthetics, model routing, stress harnesses |
| **Planning + product build from queue** | Claude Code | P0/P1 in `docs/claude-ui-queue.md` (backfill UI, paused pill, project suggest, skills API, passcode toggle) |

One owner of `index.html` per session — Claude owns the queue UI pass now.

## Cursor — landed this pass

| Item | Status |
|------|--------|
| RAG store session + ANN (measured) | Landed |
| Mermaid: framed flowcharts (no circle mindmaps) + `visual-diagrams` skill | Landed |
| Use-case routing: Gemini early for chat/RAG; SEA-LION for multilingual | Landed |
| `scripts/stress_model_routing.py` | Landed |
| Brand → vault + Cortex; snippet **shell**; leave-RAG Build? | Landed earlier |

## Claude — build next (`docs/claude-ui-queue.md`)

| Item | Priority |
|------|----------|
| Invisible dense-index backfill on space open | P0 |
| Rate-limit / restart "paused ≠ dead" composer pill | P0 |
| Project auto-suggest (3-turn classifier agree) | P1 |
| `GET /api/skills` + wire snippet cards | P1 |
| Host-only passcode off-switch | P1 |

## Anti-patterns

- Do not hand Cursor “make RAG answers better” (silent wrong).
- Do not hand Claude “move rebuild button 8px”.
- No Rust/Go/CUDA on this box — profile first; use existing `sqlite-vec`.
- Do not re-author Mermaid or `data/routing.json` unless a regression is measured.

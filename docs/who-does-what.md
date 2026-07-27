# Division of labour: Cursor vs Claude (updated 2026-07-27)

Split by **work shape**. **One owner of `index.html` per session.**

| Lane | Owner | Owns |
|------|--------|------|
| **Foundation + UX + mechanical RAG tools** | Cursor | Create toast, host-path priors, Docs canvas, purge/exclude chats, web-intent client, Mermaid, routing |
| **Grounding correctness + live proof + Cortex seams** | Claude Code | `authority`/`goal` depth, fabrication scrub, ingest-time tags, Space-5 live verify, file-scoped retrieve |

---

## Already landed (do not rebuild)

| Item | Owner |
|------|--------|
| Authority classes + never-cite chats + 0.25× | Claude |
| Goal distance + diagnosis + refine | Claude (+ Cursor wired refine retry + UI gap card) |
| Create BR progress + View + prior-RAG import | Cursor |
| Injection refuse (delete-all → Build ✕) | Cursor |
| Docs: MD / Open canvas / Source | Cursor |
| **Settings: chats_as_evidence + Purge chat sources** | Cursor (2026-07-27) |

---

## Next — Cursor

1. **Async create ingest** — toast already survives nav; make `/sources` job + poll so long embeds do not freeze the tab.
2. **Media Phase 2/3** — captions / OCR (`rag/media.py`).
3. Computer-use deepen (microanalysis, UIA URL) — only when Claude is not in `index.html`.

## Claude — landed 2026-07-27 (items 2 and 3 done)

**Ingest-time authority.** `ingest_paths(..., authority=)` records how material
entered; `ingest_sessions` declares `conversation`, `ingest_urls` declares `web`.
Path regex is now only a fallback. This closed a real laundering path: an export
pack names members `0001__chat_126.md`, and `classify()` needs `chat_` right
after a separator, so a round trip promoted a transcript to a **citable
document**. Export now carries `authority` per source (`store.source_authority`)
and import ingests one batch per class. Proven end to end: a transcript survives
export -> import still classed `conversation`, still non-citable.

**Fabrication scrub, both halves.**
- *Prevention*: `persist_turn_memory` no longer stores the assistant's account of
  a link. Memory is injected into later prompts, so saving that answer turns one
  guess into a durable fact. The question is still remembered; the claim is not.
  Same guard on the vault drawer write.
- *Cleanup*: `memory_scrub.py` (dry-run default, `--apply` to write). Rewrites
  rather than deletes, so "we discussed netie.ai" survives. **Run on the live
  store: 4 of 10 memories were poisoned, now 0.** One held
  `"that guy" refers to Jae Hoong ... Founder &` as durable fact.

Tests: `test_authority_roundtrip.py` (6), `test_memory_scrub.py` (8),
`test_link_grounding.py` (11).

## Next — Claude (prefer this order)

1. **Live re-ask Space 5** after restart + **Purge chat sources**: prove 0 `chat_*` cites on Netie / JEPA asks.
2. **File-scoped retrieval** (“what did the docx say” answers from that file only).
3. Confirm skills cards + passcode toggle on hard-reload.
4. **RAG-side scrub**: chat transcripts already indexed before ingest-time authority
   still carry whatever `_migrate_authority` guessed. A re-classify pass keyed on
   source origin (not path) would close the last gap for old spaces.

## Claude start prompt

```
Read docs/who-does-what.md (2026-07-27).
1) Live-verify Good Good after purge/exclude chats.
2) Fabrication scrub on chat ingest.
3) Ingest-time authority tag.
Do not touch create toast, Docs canvas, or purge UI — Cursor owns those.
```

## Anti-patterns

- Do not dual-edit `index.html` the same hour.
- Do not scrape Google AI Overview.
- Do not re-author Mermaid / `data/routing.json` without a measured regression.

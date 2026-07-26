# Division of labour: Cursor vs Claude (updated 2026-07-26)

Split by **work shape**, not by file size.

| Lane | Owner | Owns |
|------|--------|------|
| **Research + foundation + measured impl** | Cursor | Profiling, RAG/store/ANN, Mermaid aesthetics, model routing, stress harnesses |
| **Cross-repo seams + correctness + live verification** | Claude Code | AirGPT<->Cortex seam, grounding/truthfulness, anything where being wrong is expensive, root-causing breakages |

**One owner of `index.html` per session.** Two owners cost us a fully broken app
this pass (see "Collision log"), so this is not a style preference.

---

## Landed this pass

### Claude
| Item | Commit |
|------|--------|
| Blocked link can no longer become an invented biography | `c80dfc7` |
| "Set it up for me" one-button engine setup (lubricant thesis) | `318322a` |
| Bakeoff timeout + honest failure copy; RAG `_open()` parent-dir fix | `c90f838` |
| Clipboard: no slow work while the OS lock is held | `de299ef` |
| Rebuild/export/import keep uploaded sources (text blobs as `.txt`) | `efd01c0` |

### Cursor
| Item | Status |
|------|--------|
| RAG store session + ANN backfill (measured) | Landed |
| `GET /api/skills` real registry (`_skill_tools` reads pack text) | Landed |
| Mermaid framed flowcharts + `visual-diagrams` skill | Landed |
| Use-case model routing (Gemini early for chat/RAG, SEA-LION multilingual) | Landed |
| Pixel content hash at all four image sites | Landed |
| Rate-limit pill, restart toast, recents opacity, project menu spacing | Landed |

Full suite: **167 passed, 0 failed** (playwright excluded; needs a live browser).

---

## Next up

### Claude
1. **Wire snippet cards to `GET /api/skills`** and drop `data-wired="0"`.
   Contract: Skill -> pending modifier chip in the composer (does **not** send);
   Subagent -> `createSubagentQuick()`. Endpoint exists; only the UI is left.
2. **Passcode / 2FA off-switch** (queue item 5). Settings -> Access, default **on**,
   host-side confirm only, persistent amber line when off. Security-shaped, so it
   stays in the Claude lane.
3. **Purge fabricated answers already in memory.** Pre-fix confabulations about a real
   person are still stored and can be recalled as established fact. Needs a targeted
   scrub plus a rule that low-confidence link answers are not persisted.
4. **File-scoped retrieval**: "what did the docx say" must answer from that file only,
   not fan across the whole space.

### Cursor
1. **ASCII sweep of Cortex engine copy** (`CortexOS/engine/registry.py`,
   `just_works.py`, `lubricant.py`, `bakeoff.py`). Em dashes and arrows reach the UI;
   AirGPT normalises them at render, but the source should not carry them.
2. **Bakeoff cold-probe speed.** A cold probe takes ~45s because absent backends are
   dialled serially. Probe concurrently and cap per-backend timeout; the 90s client
   budget is a bandage, not a fix.
3. **Media Phase 2/3**: keyframe captions, then OCR for images (`rag/media.py`).
   Phase 1 audio transcript is gated and landed.
4. **UI motion polish**: fade/morph page transitions, generating-state animation.
   Mechanical and single-file once Claude is out of `index.html`.

### Held
- draw.io / routing graphs for skills — unblocked now that `/api/skills` is real, but
  hold until the snippet cards are wired.
- Business profile (Postgres/pgvector) — see `docs/memory-rag-planes-decision.md`.

---

## Anti-patterns

- Do not hand Cursor "make RAG answers better" (silent wrong).
- Do not hand Claude "move rebuild button 8px".
- No Rust/Go/CUDA on this box — profile first; use existing `sqlite-vec`.
- Do not re-author Mermaid or `data/routing.json` unless a regression is measured.

## Collision log (why the one-owner rule exists)

- An `async` keyword was orphaned onto its own line above `openAirgptHome`, leaving
  `showHubPage` non-async while it still contained `await renderHubPage()`. A newline
  between `async` and `function` means the function is not async, so the entire main
  `<script>` failed to parse and **every** UI function was undefined. HEAD parsed
  clean; only the working copy was broken.
- Two `/api/skills` handlers existed briefly (both tracks built it at once). Cursor's
  is canonical; the duplicate was removed.

**Before an edit burst on a shared file:** check mtime stability, confirm the exact
text right before each edit, and stage file by file. Never `git add -A` blind — a
personal PDF nearly went in this pass.

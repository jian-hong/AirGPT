# Claude build queue (2026-07-26) — Claude implements, Cursor researched

Verified against the tree before writing. Markers below returned **zero** matches
at authoring time. Cursor has since shipped Mermaid aesthetics + use-case model
routing (see "Already done by Cursor" at the bottom) — do **not** re-touch those.

Ownership flip per user: **Claude Code builds this queue.** Cursor stays on
research / measured foundation / UI polish that Claude plans.

Full acceptance criteria stay below. Ship P0 first.

## Build status — 2026-07-26 (Claude)

| Item | State |
|------|-------|
| P0.1 ANN backfill | **Already shipped by Cursor** — verified, not rebuilt (`ragMaybeAnnBackfill`, `/ann-status`, `/ann-backfill`, silent + self-dismissing) |
| P0.2 paused ≠ dead | **Already shipped by Cursor** — verified (`showComposerPause` countdown + Retry, `Backend restarted` notice) |
| P1.3 project auto-suggest | **Built** — `project_suggest.py`, `POST /api/chat/project-suggest`, composer chip. 17 tests |
| P1.4 skills registry | **Built** — `GET /api/skills`, real cards, armed-skill chip reaches the prompt. 10 tests |
| P1.5 passcode off-switch | **Built** — `POST /api/access/passcode-required`, host-only, standing amber warning. 9 tests |

Suite: **208 passed** (`tests/`, playwright excluded).

Fixed in passing, outside the queue:
- `invoke_registry.list_skills` / `load_skill` and `agent_runtime._load_skill` read
  BOM-prefixed packs as `utf-8-sig`. Four packs were BOM'd, so `# heading` never
  matched: `ml` was titled "Ml", its heading was served as the description, and
  `finance` / `general` were dropped entirely. 13 packs now serve instead of 11.
- `vectors._local_search` ANN branch returned `1/(1+distance)` — same ranking as brute
  force but a different **scale** (orthogonal scored 0.5 instead of 0.0). Coverage and
  fusion read the score, not the rank, so which path ran could change the answer. Now
  returns `1 - distance`, numerically identical to the brute-force branch.

---

## P0 — the user is silently getting the worse behaviour

### 1. Dense index backfill must be invisible

**Why now:** the ANN index (`sqlite-vec`, cosine, `chunk_vec_idx_384`) is live and
measured at **2.8× with recall 1.00** — but only for chunks written *after* the fix.
Every existing space still brute-forces. Activating it today requires Rebuild; users
will never know.

**Build:**
- On space open, compare `COUNT(chunk_vectors)` vs `COUNT(chunk_vec_idx_384)` for that
  space. Mismatch → silent background backfill (no dialog).
- Re-pack existing blobs into the vec table. **Do not re-embed** — seconds, not minutes.
- Thin self-dismissing progress line on the space header. Never a modal.
- Fail silently; brute force is already correct.

**Files:** `rag/vectors.py`, `rag/store.py`, thin UI hook in `index.html` RAG header.
**Done when:** opening a space indexed last week is fast with no user action; no
persistent UI after finish.

### 2. "Paused" must look different from "dead"

**Why now:** `supervisor.py` + `data/crash.log` + keep-alive mean restarts are
recoverable — UI has no words for that.

**Build:**
- Provider 429 / quota → inline composer pill: *"Rate limited — chat saved, retry in Ns"*
  with live countdown + Retry. **Not a toast.**
- Never clear the transcript on any error path. Reuse `sendStream`'s
  `{ok, opened, paused}` — no second path.
- Health poll fail→succeed → once: *"Backend restarted — your chats are intact"*.

**Files:** `index.html` composer / `sendStream`, health poll near existing `/api/health`.
**Done when:** throttle spam leaves every prior message on screen with a countdown.

---

## P1 — Claude lane

### 3. Project auto-suggest on domain shift

Markers `suggestProject` / `projectSuggest`: still **0 matches**.

**Policy (do not weaken):**
- Fire only when classifier disagrees for **three consecutive** user turns.
- Never auto-move — suggest only.
- Chip above composer: *"This looks like Engineering — move?"* **Move** / **Not now**.
- "Not now" suppresses for the session.
- Never suggest current project; never in Scratch.

**Backend:** `chat_classifier.py` already has the category — add small endpoint
`{suggest, project, confidence}` so the client does not re-classify.

### 4. Snippet cards → real registry

Shell at `cortexSnippetCardsHtml` (hard-coded stubs, `data-wired="0"`).

**Sources already on disk:**
- `data/skills/*.md` (read by `agent_runtime` / `invoke_registry`)
- `GET /api/agents`

**Gap:** there is still **no `GET /api/skills`**. That endpoint is the work —
`{id, title, summary, tools}` from pack front matter / first heading.

**Contract for `Use`:**
- Skill → pending modifier chip in composer (**does not send**).
- Subagent → keep `createSubagentQuick()`.
- Drop `data-wired="0"` and the placeholder toast once both paths are real.

### 5. Optional passcode / 2FA off-switch

Settings → Access: toggle *"Require passcode on phone"*, default **on**.
Off requires **host-side** confirm only (never from a phone session); persistent
amber line when off. Escape hatch, not a convenience default.

---

## P2 — hold

### 6. draw.io / routing graphs for skills

Hold until item 4 gives skills a real registry. Mindmap→flowchart beautify already
ships (Cursor); do not invent a second diagram format yet.

---

## Do not touch (Cursor finished)

- Reply chip, project contrast, Ask about, `+` menu, Memory panel, RAG FAB/tiles/URL/
  Build? modal, sleuth words, pipeline tips, `openVaultAndCortex()`
- `sanitizeMermaidSrc` — keep for legacy DB mindmaps
- **Mermaid aesthetics** (`mermaid_normalize.py` → framed flowcharts; prompts;
  `data/skills/visual-diagrams.md`; Mermaid theme tokens)
- **Use-case model routing** (`data/routing.json`, `_TASK_CLOUD_ORDER`, Gemini before
  SEA-LION for English chat/RAG; multilingual promotes SEA-LION;
  `scripts/stress_model_routing.py`)
- **RAG create BR toast** (1/6…chunking, spinning Create, prior-RAG import, **View** when done) — Cursor owns; do not dual-edit
- **Authority / goal modules** — Claude authored; Cursor wired `refine_query` + UI gap card. Prefer extending `rag/goal.py` / `rag/authority.py` over rewrites in `index.html`

---

## New Claude work (2026-07-27) — after Cursor purge UI

Cursor shipped Settings → **Evidence policy** (`chats_as_evidence`) + **Purge chat sources**.

Your turn:

1. **Live proof on Space 5** after restart: ask user to Purge (or uncheck chats), then `web search about cortex … jepa` and `what is netie ai`. Expect 0 `chat_*` citations.
2. **Fabrication scrub** at chat-ingest (prefer next code).
3. **Ingest-time authority** column + Settings already has exclude toggle — extend store schema if needed.
4. Confirm skills cards + passcode toggle still green.

Do **not** rebuild create-progress, Docs canvas, or purge UI.

---

## Claude start prompt (copy)

```
Read docs/who-does-what.md (2026-07-27) + this queue.
Live-verify Space 5 after purge; then fabrication scrub + ingest-time authority.
Do not touch create toast / Docs canvas / purge UI / Mermaid / routing.json.
```

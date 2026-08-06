# Vendor UI references - salvaged verdicts (P5)

Cites `PARKING_LOT.md` **P5** (dbgate / Outerbase / Grafana plug-in sheet+CSV full
view + multichart). Founder picks one thin viewer after EPIC-D01 click-through lands.

Three data-IDE repos were shallow-cloned under `vendor/` for design study only. The
clones are disposable (~12GB, gitignored, re-clonable with `--depth 1`); this file is
the part worth keeping. **No code was copied from any of them.**

## Verdicts

| Repo | License | Verdict | Why |
|------|---------|---------|-----|
| [dbgate](https://github.com/dbgate/dbgate) | GPL v3 | **EXTRACT patterns only** | Copyleft on distribution; Electron desktop shell out of scope. Reimplement UX, do not vend. |
| [Outerbase Studio](https://github.com/outerbase/studio) | AGPL v3 | **EXTRACT patterns only** | Network use can trigger AGPL. Next.js runtime + direct DB drivers conflict with our boundary. |
| [Redis Insight](https://github.com/redis/RedisInsight) | SSPL | **DO NOT USE** | SSPL blocks embedding in a commercial product. Layout inspiration only, no code copy. |

None is embeddable as an iframe: each assumes its own Node/Next backend and its own
DB-credential trust model.

## Patterns worth stealing (reimplement, do not copy)

1. **Table / data browser** - filterable grid over query results; the strongest fit for
   xlsx sheet preview next to a RAG answer. (dbgate `packages/web`, Outerbase data editor.)
2. **Schema tree + object explorer** - spaces -> sources -> sheets -> columns, as a
   sidebar. Maps onto our RAG space -> workbook -> sheet hierarchy.
3. **SQL editor + tabbed result panes** - Outerbase uses CodeMirror 6 with
   `@codemirror/lang-sql`; dbgate uses Ace. Relevant to the SELECT-only lane (#21).
4. **Preview-before-commit grid** - Outerbase stages edits and shows a diff before
   writing. This is the same shape as our ops amend-confirm gate (EPIC-D02).
5. **Flow / lineage graph** - Outerbase uses `@xyflow/react` + Dagre. Candidate for
   showing ontology relations (#15) rather than an op-code list.

## Stacks (for reference when picking)

- **dbgate:** Svelte 4 + Tailwind, Node API, Electron, plugin architecture.
- **Outerbase Studio:** Next.js 15 + React 19, Tailwind 4, Radix/shadcn, CodeMirror 6,
  Dexie (IndexedDB), Cloudflare Workers deploy.
- **Redis Insight:** Electron + React/Vite + Monaco, NestJS backend, SQLite local state.

## Not salvaged

`vendor/vendor/caddy` and `vendor/vendor/lakehouse-at-home` were cloned but never
analysed. `vendor/vendor/sira` is empty - full Meta SiRA stays **P2**; the inspired
path lives in `rag/sira.py`.

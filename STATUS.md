# STATUS

**Hard cap: 60 lines.** Older narrative moves to CHANGELOG.md.

## Now

0. **All 16 orphans re-parented 2026-08-21** - no ticket may lack a live parent (founder;
   `DOCUMENT_SYSTEM.md` Tier 6). Closing D01 #6 / D02 #16 orphaned **seventeen**, not the
   five that were noticed. D07 #36: #13 #21 #31. D06 #37: #17 #18 #19 #32 #35. D08 #38:
   #14 #15 #20 #25 #33 #34. #9/#10 parked (P11); #3 exempt repo hygiene.
1. **F13a and F13b BOTH MET: 720/720.** Clean 400/400 (5 seeds, error <=0.75%);
   messy pack **320/320 at n=320** (<=0.94%), up from 0.5375. Schema-link 720/720,
   zero lucky passes, `malformed_ask_rate` 0.0. Every F13b clause passes: pooled
   1.0>=0.99, no workbook <0.95, no family <0.90. Four root-cause fixes, all one
   class (match without excluding the non-target case): banner-row header, duplicate
   columns, sheet name binding a column, and short column names being invisible.
2. **#31 independently verified** - all six claims CONFIRMED by a different run,
   which found 3 further defects (stale artifact string, banner substring match,
   forward-path sheet/column collision). All three fixed; 720/720 re-measured after.
3. **Verified live, not taken on trust:** #21 numeric KPI over SSE (0.9441, Carriers);
   #15 reasoning chain over SSE; #20 Docs originals 7/7 sha256; #14 reveal `origin:
   "docs"`; #25 Settings depth+arch+Save (3 of 4). All await a **different-run** close.
4. **D02 works in Python and nowhere else** - `ops_demo_e2e.py` is 32/32 but imports
   `rag.ops_amend` directly (line 25). The six HTTP endpoints have zero coverage and
   `index.html` has zero callers. Gate: #32. Surface: P12.

## Next

0. **#31 landed (`091bc109`, `64ad0b33`) but MUST NOT close** - acceptance needs
   `malformed_ask_rate` in the artifact. Absent under any name. `header_drift` is `[]`
   post-fix **and was `[]` pre-fix when 89/320 were malformed** - identical in the broken
   and the fixed state, so 0/320 is as unreproducible as 89/320 (R-0007). F13b gates on it.
   Also open: retained `sira_max` vs `hybrid_max` (`frtr_cross_latest.json` holds **one**).
1. **#32 D02 HTTP gate** - assert the loop where a client calls it (R-0001).
2. **#33 Rebuild ignores saved config** - `depth_default` only stamps a revision label
   at `ingest.py:340`; `architecture` is never read at ingest. Needs a DR.
3. **#34 backfill `docs_path`** - #20 covers new ingests only. Space 8, the demo space,
   is 0/6 and degrades to the `host` or `blob` origin.
4. **#35 production imports from `tests/`** - `rag/answer.py:900` and
   `clipdrop.py:5171`. A deploy without `tests/` loses the xlsx lane silently. Needs a DR.
5. **P13 multilingual** - `sira.py:13` ASCII-only, so non-Latin scripts tokenize to
   nothing and `_coverage` returns 1.0. `multilingual_gate.py` is **7/25 and deliberately
   red** - do not quiet it (R-0002).
6. **Routed 2026-08-21 -> D06 #37:** `clipdrop.py:5388-5389` `/build` path override.
   Fenced today (`/api/rag` host-only, `:834`); **DR-0003's grants would unfence it**.
7. Commit OpenVault nvidia separately.

## WIP

WIP counts **in-flight**, not open (founder 2026-08-21). In flight: D07 #36, D03 #26.
Queued parents: D06 #37, D08 #38, D04 #22, D05. Never close an epic to free a slot - move
it to queued. No-orphan never overrides the amendment gate.

## Later

- P1 50GB / P2 Meta SIRA / P3 charts / P4 vault-first / P5 Outerbase-Grafana / P6 2GB / P7 NVIDIA default after OV probe

## Demo open

- `tests/RAG/DEMO_RAG.md`, `results/ontology_space_8.json`. Suite 399 pass / 3 fail (Playwright, empty base URL, unrelated).

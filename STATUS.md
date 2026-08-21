# STATUS

**Hard cap: 60 lines.** Older narrative moves to CHANGELOG.md.

## Now

0. **EPIC-D01 #6 and EPIC-D02 #16 closed 2026-08-20 over unfinished work** - founder's
   explicit call, informed. Neither completed. Remainder carried into #31-#35 and
   PARKING_LOT P11-P13 before the close; the closing comments hold the full split of
   shipped vs not. Tickets #9 #10 #13 #14 #15 #17 #18 #19 #20 #21 #25 stay **open**.
1. **#13 messy pack: 0.6937 at n=320**, up from 0.5375. Malformed asks **28% -> 0%**
   (#31 header binder). Journey: 0.5375 -> 0.6219 (banner header + duplicate columns)
   -> 0.6937 (sheet name no longer binds a column). Against F13b's 0.90 per-family
   floor: `out_of_range` 44/44 and `row_range_nocol` 48/48 **meet** it; `filter_agg`
   0.23 and `combined` 0.39 are the open gaps. 50 of 98 failures are abstentions.
   F13 is now split - **F13a** clean corpus (earned, frozen), **F13b** messy (open).
2. **Oracle bench 400/400** on the clean FRTR 00027 across 5 seeds - error bounded at
   **0.75%** (R-0010). The contrast with item 1 is clean workbook vs messy pack.
3. **Verified live this pass, not taken on trust:** #21 numeric KPI over SSE (0.9441,
   `SELECT AVG(OnTimeSLA) FROM Carriers WHERE BaseRate > 1`, Carriers sheet); #15
   reasoning chain over SSE, all checks; #20 Docs originals 7/7 sha256; #14 reveal
   returns `origin: "docs"` on primary50; #25 Settings depth+arch+Save (3 of 4).
4. **D02 works in Python and nowhere else** - `ops_demo_e2e.py` is 32/32 but imports
   `rag.ops_amend` directly (line 25). The six HTTP endpoints have zero coverage and
   `index.html` has zero callers. Gate: #32. Surface: P12.

## Next

0. **#31 header binder** - `frtr_sql_baseline.py:29` takes the first row with >=2
   non-empty cells, so `Messy_RAW` yields columns named `skip` and `-`. Root cause of
   most #13 loss. Fix at the binder (R-0004); clean workbook must stay 400/400 (R-0005).
   Same ticket retains the `sira_max` vs `hybrid_max` comparison that never existed -
   `frtr_cross_latest.json` holds **one** variant.
1. **#32 D02 HTTP gate** - assert the loop where a client calls it (R-0001).
2. **#33 Rebuild ignores saved config** - `depth_default` only stamps a revision label
   at `ingest.py:340`; `architecture` is never read at ingest. Needs a DR.
3. **#34 backfill `docs_path`** - #20 covers new ingests only. Space 8, the demo space,
   is 0/6 and degrades to the `host` or `blob` origin.
4. **#35 production imports from `tests/`** - `rag/answer.py:900` and
   `clipdrop.py:5171`. A deploy without `tests/` loses the xlsx lane silently. Needs a DR.
5. **P13 multilingual** - `sira.py:13` is ASCII-only, so six non-Latin scripts tokenize
   to nothing and `_coverage` returns 1.0, never firing the corrective loop.
   `multilingual_gate.py` is **7/25 and deliberately red**. Do not quiet it (R-0002).
6. **Unrouted, needs `prd-agent`:** `clipdrop.py:5390-5391` lets a caller override
   `paths` on `/build` with arbitrary client-supplied filesystem paths for ingestion.
7. Commit OpenVault nvidia separately.

## WIP

Two epics open against a limit of two - **at** the limit, not under. EPIC-D03 #26 and
EPIC-D04 #22. **D05 is not clear to start**; one of those must close first.

## Later

- P1 50GB / P2 Meta SIRA / P3 charts / P4 vault-first / P5 Outerbase-Grafana / P6 2GB
- AirGPT default to NVIDIA only after OV probe passes (P7)

## Demo open

- `tests/RAG/DEMO_RAG.md`, `results/ontology_space_8.json`, `results/warehouse_hybrid_latest.xlsx`
- Suite: 399 passed, 3 failed (Playwright, empty base URL, unrelated to D01/D02)

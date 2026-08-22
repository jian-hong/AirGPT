# STATUS

**Hard cap: 60 lines.** Older narrative moves to CHANGELOG.md.

## Now

0. **All 16 orphans re-parented 2026-08-21** - no ticket may lack a live parent (founder;
   `DOCUMENT_SYSTEM.md` Tier 6). Closing D01 #6 / D02 #16 orphaned **seventeen**, not the
   five that were noticed. D07 #36: #13 #21 #31. D06 #37: #17 #18 #19 #32 #35. D08 #38:
   #14 #15 #20 #25 #33 #34. #9/#10 parked (P11); #3 exempt repo hygiene.
1. **F13a and F13b BOTH MET: 720/720** - clean 400/400 (5 seeds, <=0.75%), messy
   **320/320** (<=0.94%), from 0.5375. Schema-link 720/720, 0 lucky passes,
   `malformed_ask_rate` 0.0. Four fixes, one class (match without excluding the
   non-target case): banner header, duplicate columns, sheet-name-binds-column,
   short names invisible. **ENGINE number** - the bench calls `sheet_sql` direct.
2. **#21 the SQL lane was off for every founder space** - only the `hybrid_max`
   preset set `hybrid_sql_lane`, and a normal space has no variant, so every ask
   fell through to retrieval. Now default-on; explicit False still honoured so the
   variant A/B survives. `default_space_sql_gate.py` **7/7** asserts where a founder
   stands: no variant, staging dir deleted after ingest (exercises #20), through
   `answer()` -> `lane='sql'` carrying its SQL.
3. **#31 independently verified** - six claims CONFIRMED by a different run, which
   found 3 more defects (stale artifact string, banner substring match, forward-path
   sheet/column collision). All fixed; 720/720 re-measured after. Suite 211 OK.
4. **Verified live:** #15 chain over SSE; #20 Docs 7/7 sha256; #14 reveal
   `origin:"docs"`; #25 Settings 3 of 4. All await a **different-run** close.
5. **D02 works in Python and nowhere else** - `ops_demo_e2e.py` 32/32 but imports
   `rag.ops_amend` direct; six HTTP endpoints uncovered, 0 UI callers. #32 / P12.

## Next

0. **#31 ready to close** - `malformed_ask_rate` now in the artifact and proven to
   move (`malformed_field_gate.py`: 0.4375 pre-rule vs 0.0000 shipped). Still open in
   D07: retained `sira_max` vs `hybrid_max` (`frtr_cross_latest.json` holds **one**).
1. **#32 D02 HTTP gate** - assert the loop where a client calls it (R-0001).
2. **#33 Rebuild ignores saved config** - `depth_default` only stamps a revision
   label (`ingest.py:340`); `architecture` never read at ingest. Needs DR-0006.
3. **#34 backfill `docs_path`** - #20 covers new ingests only; space 8 is 0/6.
4. **#35 production imports from `tests/`** - `rag/answer.py:900` and
   `clipdrop.py:5171`. A deploy without `tests/` loses the xlsx lane silently. Needs a DR.
5. **P13 multilingual** - `sira.py:13` ASCII-only, non-Latin scripts tokenize to
   nothing, `_coverage` returns 1.0. `multilingual_gate.py` **7/25, deliberately
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

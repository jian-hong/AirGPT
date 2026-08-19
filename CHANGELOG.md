# CHANGELOG

Append-only. Never edited, only added to. Newest first.

## 2026-08-20 — #13 rescored at n=320, and two defects that explain the number

- **#13 rescored honestly.** `oracle_bench.py` over the 4 primary50 workbooks, seeds 1-4,
  80 each: value accuracy **172/320 = 0.5375**, schema-link recall **181/320 = 0.5656**.
  This REPLACES the 0.80/1.0/0.80 figure, which was n=10 and bounded nothing (R-0010).
  "Approaching 99%" was never supportable and should not be quoted again.
- Per family: `out_of_range` 44/44 = 1.00 (refusal behaviour is genuinely sound),
  `row_range_nocol` 0.77, `paraphrase` 0.61, `row_range_agg` 0.58, `filter_count` 0.52,
  `combined` 0.16, `filter_agg` 0.12. The largest single failure reason is "no answer
  from the lane" (54 of 148 failures) - abstention, not wrong answers.
- **Header detection picks banner rows.** `tests/RAG/frtr_sql_baseline.py:29` takes the
  first row in the first five with >=2 non-empty cells. On `Messy_RAW` that is the banner
  `['RAW','sheet','—','skip']`, so the real header (row 2) becomes data and the schema
  gains columns literally named `skip` and an em dash. 89 of 320 generated asks (28%) are
  malformed by this; on the 231 well-formed ones accuracy is **0.6017**. Row 2 also
  carries duplicate column names. The bench's own header-drift check reports zero,
  because it compares the loader against the oracle and both pick the banner (R-0007).
- **The product imports its xlsx engine from the tests directory.** `rag/answer.py:900`
  puts `tests/RAG` on `sys.path` at runtime and imports `frtr_sql_baseline`. A deploy
  without `tests/` loses the whole xlsx/KPI lane silently - it returns `None`, with no
  error and no degraded flag (R-0011). Routed to `prd-agent`; likely a decision record.
- Both defects routed, neither implemented - the routing rule in CLAUDE.md is absolute.

## 2026-08-20 — EPIC-D01: the chain reaches the browser, and #20 stops being a claim

- **#15 was invisible in the product.** The chain was built, yielded, and dropped at the
  transport: the SSE handler in `clipdrop.py` enumerated `thinking|meta|citations|delta|
  error|done` with no `reasoning` branch, and rebuilt its `done` payload from a fixed key
  list that omitted it. `index.html` sends `Accept: text/event-stream` on every answer, so
  that handler is the only path a founder takes. Added the branch, the key, and a renderer
  (`.ragreason`, open by default on a refusal or abstention, escaped, collapsed otherwise).
- **The gate had asserted the wrong layer.** `tests/RAG/reasoning_chain_live.py` drove the
  plain JSON handler, which passes the whole dict through — so unit tests, the JSON path,
  and the feature-being-invisible were all simultaneously true. It now drives SSE and parses
  the event stream (R-0001).
- **#25 had the same shape one layer down.** `clipdrop.py` whitelisted depth as
  `basic|high|max|manual`, so a space saved as Adaptive — persisted as `auto`, and sent on
  every ask — was silently coerced to `high`. Saving appeared to work and never took effect.
  Also corrected the Rebuild copy, which omitted the enrich stage.
- **#20 was closed on a false claim.** "Space 8 is 6/6 identical" came from a bench script in
  `stash@{0}`, not the product; production ingest wrote post-extraction text and set no
  `docs_path`, so every `rag/reveal.py` docs lookup fell through. Recovered
  `_retain_docs_original` into `rag/ingest.py` and added `tests/RAG/docs_original_gate.py`,
  which drives real ingest from outside the blob store and asserts sha256 identity plus the
  PK container magic — 7/7. New ingests only; older spaces need a backfill.
- Known red, pre-existing and unrelated: `tests/test_rag_foundation.py
  test_corrective_loop_caps` (2 != 1), identical at `b09e6033`. Left failing rather than
  weakened.
- Corrects the date on the entry below, which was filed as 2026-08-07 in error.

## 2026-08-19 — EPIC-D01 + EPIC-D02: reasoning chains and the ops write path

- **D02 ops amend-confirm** (#17–#19): `rag/ops_amend.py` rewritten to resolve columns
  from the sheet header instead of positionally, match rows honestly rather than
  guessing at the first near-hit, and carry the confirm loop through to a write. A
  spent confirm token can no longer be replayed. Scenario harness
  `tests/RAG/ops_demo_e2e.py` — 32/32, covering reject, refuse, off-rails and the
  confirmed +8% write with its audit stamp. Runbook section added to `DEMO_RAG.md`.
- **D01 reasoning chain** (#15): new `rag/reasoning.py` renders each lane's provenance
  as sentences a founder can check, replacing op codes like `bind_entities`. Every
  answer exit point in `rag/answer.py` now carries one.
- Two chains were reporting work that did not happen. The KPI catalogue's ABSTAIN path
  returned no provenance, so the chain printed "computed from the rows above" on a run
  that deliberately computed nothing; it now carries the abstention and the lane's own
  reason. Policy refusals built their chain without hits, reporting "nothing matched"
  while holding retrieved passages; they now pass the real hits.
- Chain values round through the same helper as the answer text, so a chain no longer
  shows 0.9440740740740741 beside an answer of 0.9441.
- **D01 Settings** (#25): depth and architecture controls were computed into
  `depthOpts`/`archOpts` but never rendered, so Save read elements that did not exist.
  Rendered in `index.html`; `rag/store.py` whitelist accepts `adaptive`/`auto`. Save and
  Rebuild verified over HTTP against a live instance.

## 2026-08-03 — FRTR-Bench Excel RAG smoke

- Harness: `tests/RAG/frtr_eval.py` (+ SQL baseline, Cortex lane). Sanitize materializes formula caches; strips Questions.
- AirGPT RAG: KPI sheet boost in `rag/retrieve.py`; spreadsheet index + small-sheets-first in `rag/ingest.py`.
- Result: hybrid SQL+RAG **6/6 (100%)** on `frtr_0001_quarterly-summary.xlsx`. Full 159 needs XLOOKUP/SUMIFS SQL agent + vision for chart Qs.
- Cortex `/dms/query` confirmed live for SQL-brain demo; OpenVault is not an Excel RAG path.


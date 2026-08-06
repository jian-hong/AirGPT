# CHANGELOG

Append-only. Never edited, only added to. Newest first.

## 2026-08-07 — EPIC-D01 + EPIC-D02: reasoning chains and the ops write path

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


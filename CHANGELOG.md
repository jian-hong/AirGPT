# CHANGELOG

Append-only. Never edited, only added to. Newest first.

## 2026-08-03 — FRTR-Bench Excel RAG smoke

- Harness: `tests/RAG/frtr_eval.py` (+ SQL baseline, Cortex lane). Sanitize materializes formula caches; strips Questions.
- AirGPT RAG: KPI sheet boost in `rag/retrieve.py`; spreadsheet index + small-sheets-first in `rag/ingest.py`.
- Result: hybrid SQL+RAG **6/6 (100%)** on `frtr_0001_quarterly-summary.xlsx`. Full 159 needs XLOOKUP/SUMIFS SQL agent + vision for chart Qs.
- Cortex `/dms/query` confirmed live for SQL-brain demo; OpenVault is not an Excel RAG path.


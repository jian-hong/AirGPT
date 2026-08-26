# Active map

What exists in this repo and where. Update when structure changes, not when state changes
- state lives in STATUS.md.

- `invoke_registry.py` — rules / skills / slash catalog. Product packs:
  `data/skills/` (gitignored). Suite packs: `tests/fixtures/skills/`.
- `openpyxl` and `pandas` are product xlsx deps (`rag/ingest.py`,
  `rag/xlsx_sql.py`) and live in `requirements.txt`. `sqlite-vec` stays opt-in.
- `rag/ingest.py` — `revision_profile` stamps saved architecture on rebuild
  (DR-0006 / #33). `rebuild_source_paths` prefers Docs original over the
  extracted blob; `backfill_docs_originals` fills missing `docs_path` (#34).
- `rag/xlsx_sql.py` — production xlsx loader + SQL-ish KPI answers. Product
  must not import this from `tests/`.
- `rag/sheet_sql.py` — schema-aware filter+aggregate over those frames.
- `rag/answer.py` `_try_hybrid_sql_lane` — wires both into the ask path.
- `tests/RAG/oracle_bench.py --variants sira_max,hybrid_max` — F13 A/B on one
  generated question set; retained `tests/RAG/results/oracle_cross_latest.json`.

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
- `rag/xlsx_orch.py` — F15 / EPIC-D04 AirGPT half: identify ingested xlsx +
  structured Copilot prompt pack + honest DMS handoff/reveal. Does not paste
  or drive Copilot (`paste_owner=pointer`, `cross_check_owner=dms`).
- `rag/sheet_sql.py` — schema-aware filter+aggregate over those frames.
- `rag/answer.py` `_try_hybrid_sql_lane` — wires both into the ask path.
- `tests/RAG/oracle_bench.py --variants sira_max,hybrid_max` — F13 A/B on one
  generated question set; CI smoke `tests/RAG/results/oracle_cross_latest.json`
  (frtr_0001 n=7). Pack: `oracle_cross_primary50_{1..4}.json` + pooled
  `oracle_cross_primary50.json` (n=320, F13b floors on hybrid_max).

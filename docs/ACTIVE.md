# Active map

What exists in this repo and where. Update when structure changes, not when state changes
- state lives in STATUS.md.

- `invoke_registry.py` — rules / skills / slash catalog. Product packs:
  `data/skills/` (gitignored). Suite packs: `tests/fixtures/skills/`.
- `openpyxl` is a product xlsx dep (`rag/ingest.py`, ops, ontology) and lives
  in `requirements.txt`. `sqlite-vec` stays opt-in.
- `rag/xlsx_sql.py` — production xlsx loader + SQL-ish KPI answers. Product
  must not import this from `tests/`.
- `rag/sheet_sql.py` — schema-aware filter+aggregate over those frames.
- `rag/answer.py` `_try_hybrid_sql_lane` — wires both into the ask path.

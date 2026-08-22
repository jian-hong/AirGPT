# Active map

What exists in this repo and where. Update when structure changes, not when state changes
- state lives in STATUS.md.

- `invoke_registry.py` — rules / skills / slash catalog. Product packs:
  `data/skills/` (gitignored). Suite packs: `tests/fixtures/skills/`.
- `openpyxl` and `pandas` are product xlsx deps (`rag/ingest.py`,
  `rag/xlsx_sql.py`) and live in `requirements.txt`. `sqlite-vec` stays opt-in.
- `rag/xlsx_sql.py` — production xlsx loader + SQL-ish KPI answers. Product
  must not import this from `tests/`.
- `rag/sheet_sql.py` — schema-aware filter+aggregate over those frames.
- `rag/answer.py` `_try_hybrid_sql_lane` — wires both into the ask path.

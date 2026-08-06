# STATUS

**Hard cap: 60 lines.** Older narrative moves to CHANGELOG.md.

## Now

1. **Oracle bench** — `tests/RAG/oracle_bench.py`. Grader shares no code with the lane
   (openpyxl by spreadsheet row); questions generated per seed. Scores **value accuracy
   and schema-link recall** separately — a right value off the wrong column is a
   coincidence, not a pass. Found 6 real linking bugs on its first two runs.
2. **Row ranges** — "select row 330 to 660, sum" answers, and states the Excel-row to
   data-row mapping (banner rows make 330 -> 327). No column named -> every numeric one.
3. **SQL lane answers filter+aggregate** (#21) — `rag/sheet_sql.py` resolves against the
   sheet schema; FRTR 00027 `AVG(OnTimeSLA) WHERE BaseRate > 1` = 0.9441, 0 web cites.
2. **Reveal on file cards** (#14) — hover icon; server resolves Docs original → host
   → blob and fails closed. `POST /api/rag/sources/<id>/reveal`.
3. **Docs originals byte-faithful** (#20) — space 8 is 6/6 identical. Verified, was
   already built.
4. **Ops amend-confirm** (D02 #17–#19) — reject/refuse/off-rails all leave the file
   unchanged; confirmed write applies +8% with an audit stamp. Verified end to end.
5. **Recursive clone works** (#3) — orca/superset gitlinks removed, colibri kept.
6. **Ontology-first live** — space 8; artifact `tests/RAG/results/ontology_space_8.json`.

## Next

0. **Schema linking at scale** — `docs/research/terabyte-retrieval.md`. Our schema is
   ~15 columns; published failure rates are measured at 1000+. Next honest measurement
   is the oracle bench against a wide-schema workbook. Then: persist a catalog, make
   linking retrieval rather than substring, move the data layer to Parquet.
1. **#10** ground the Insights sheet in real miss/hit rows (today it is generic prompts).
2. **#13** score the primary-50MB pack — fixtures are ingested (spaces 16 **and** 17,
   duplicate) but no scores are retained.
3. **#15** make the reasoning chain founder-readable; it can now consume #21's SQL
   provenance instead of emitting op codes.
4. **#25** Settings post-create depth/arch + Save + Rebuild (today depth is read-only).
5. **#9** effort x thinking matrix — not started.
6. Push `demo/rag-cross-compare`; commit OpenVault nvidia separately.

## Later

- P1 50GB / P2 Meta SIRA / P3 charts / P4 vault-first / P5 Outerbase·Grafana / P6 2GB
- AirGPT default to NVIDIA only after OV probe passes (P7)

## Demo open

- `tests/RAG/DEMO_RAG.md` (full path)
- `tests/RAG/results/ontology_space_8.json`
- `tests/RAG/results/warehouse_hybrid_latest.xlsx`

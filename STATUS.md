# STATUS

**Hard cap: 60 lines.** Older narrative moves to CHANGELOG.md.

## Now

1. **SQL lane answers filter+aggregate** (#21) — `rag/sheet_sql.py` resolves against the
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

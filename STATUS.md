# STATUS

**Hard cap: 60 lines.** Older narrative moves to CHANGELOG.md.

## Now

1. **Oracle bench 400/400** — `tests/RAG/oracle_bench.py`, 5 seeds x 80 generated Qs.
   Value accuracy **and** schema-link recall both 1.0, 0 lucky passes; error bounded
   at **0.75%** (rule of three, first run at n>=300). Grader shares no code with the
   lane. Found 6 real linking bugs — all linking, none arithmetic.
2. **Row ranges** — "select row 330 to 660, sum" answers, and states the Excel-row to
   data-row mapping (banner rows make 330 -> 327). No column named -> every numeric one.
3. **SQL lane answers filter+aggregate** (#21) — `rag/sheet_sql.py` resolves against the
   sheet schema; FRTR 00027 `AVG(OnTimeSLA) WHERE BaseRate > 1` = 0.9441, 0 web cites.
4. **Reasoning chain is founder-readable** (D01 #15) — `rag/reasoning.py` turns each
   lane's provenance into checkable sentences. Caught two chains that lied: the KPI
   ABSTAIN path claimed "computed from the rows above" having computed nothing, and
   policy refusals reported "nothing matched" while holding passages. Both fixed.
5. **Settings depth + architecture** (D01 #25) — controls were computed but never
   rendered, so Save read absent elements. Rendered; store accepts adaptive/auto.
6. **Reveal on file cards** (#14) — hover icon; server resolves Docs original → host
   → blob and fails closed. `POST /api/rag/sources/<id>/reveal`.
7. **Docs originals byte-faithful** (#20) — the earlier "6/6 identical" claim was
   false: it came from a bench script in `stash@{0}`, not the product, and space 8's
   rows carry no `docs_path`. The writer is now recovered into production ingest
   (`_retain_docs_original`). Gate `tests/RAG/docs_original_gate.py` drives real
   ingest and asserts sha256 identity: **7/7**. Unblocks #14's `docs` origin.
8. **Ops amend-confirm** (D02 #17–#19) — reject/refuse/off-rails all leave the file
   unchanged; confirmed write applies +8% with an audit stamp. Verified end to end.
9. **Recursive clone works** (#3) — orca/superset gitlinks removed, colibri kept.
10. **Ontology-first live** — space 8; artifact `tests/RAG/results/ontology_space_8.json`.

## Next

0. **Schema linking at scale** — `docs/research/terabyte-retrieval.md`. Our schema is
   ~15 columns; published failure rates are measured at 1000+. Next honest measurement
   is the oracle bench against a wide-schema workbook. Then: persist a catalog, make
   linking retrieval rather than substring, move the data layer to Parquet.
1. **#10** ground the Insights sheet in real miss/hit rows (today it is generic prompts).
2. **#13** score the primary-50MB pack — fixtures are ingested (spaces 16 **and** 17,
   duplicate) but no scores are retained.
3. **Backfill `docs_path`** — #20 covers new ingests only. Spaces ingested before it
   (space 8) still have no original; they need a re-ingest or a backfill pass.
4. **#13** scoreboard is in `stash@{0}`, and reads 0.80/1.0/0.80 at n=10. R-0010
   forbids a 99% claim below n=300.
5. **#9** effort x thinking matrix — not started. **#10** Insights sheet — not started.
6. **D02 has no UI** — five endpoints, zero callers in `index.html`. Needs a ticket
   routed through `prd-agent` before anyone builds it.
7. Commit OpenVault nvidia separately.

## Later

- P1 50GB / P2 Meta SIRA / P3 charts / P4 vault-first / P5 Outerbase·Grafana / P6 2GB
- AirGPT default to NVIDIA only after OV probe passes (P7)

## Demo open

- `tests/RAG/DEMO_RAG.md` (full path)
- `tests/RAG/results/ontology_space_8.json`
- `tests/RAG/results/warehouse_hybrid_latest.xlsx`

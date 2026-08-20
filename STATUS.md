# STATUS

**Hard cap: 60 lines.** Older narrative moves to CHANGELOG.md.

## Now

0. **#13 rescored honestly at n=320** — oracle bench over the 4 primary50 workbooks:
   value **0.5375** (172/320), schema-link **0.5656**. The old 0.80/1.0/0.80 was n=10
   and must not be quoted. 89/320 asks (28%) are malformed by the header bug below;
   on the 231 clean ones it is **0.6017**. Worst: `filter_agg` 0.12, `combined` 0.16.
   Best: `out_of_range` 44/44 — refusal is sound. 54 failures are abstentions.
1. **Oracle bench 400/400** on FRTR 00027 — value and schema-link both 1.0, error
   bounded at **0.75%**. Note the contrast with item 0: clean workbook vs messy pack.
2. **Row ranges** + **SQL filter+aggregate** (#21) — `rag/sheet_sql.py` resolves against
   the sheet schema; FRTR 00027 `AVG(OnTimeSLA) WHERE BaseRate > 1` = 0.9441.
3. **Reasoning chain founder-readable and reaching the browser** (D01 #15) —
   `rag/reasoning.py`; chain was dropped at the SSE transport, now streamed + rendered.
   Caught two chains that lied (KPI ABSTAIN, policy refusal). Gate asserts over SSE.
4. **Settings depth + architecture** (D01 #25) — controls rendered; `auto` no longer
   coerced to `high` at the server, so Adaptive actually takes effect.
5. **Docs originals byte-faithful** (#20) — earlier "6/6 identical" was false (bench
   script, not product). Writer recovered into ingest; `docs_original_gate.py` asserts
   sha256 identity **7/7**. Unblocks #14's `docs` origin.
6. **Reveal on file cards** (#14) — resolves Docs → host → blob, fails closed.
7. **Ops amend-confirm** (D02 #17–#19) — reject/refuse/off-rails leave the file
   unchanged; confirmed write applies +8% with an audit stamp. 32/32 end to end.
8. **Ontology-first live** — space 8; **recursive clone** (#3) fixed.

## Next

0. **Schema linking at scale** — `docs/research/terabyte-retrieval.md`. Our schema is
   ~15 columns; published failure rates are measured at 1000+. Next honest measurement
   is the oracle bench against a wide-schema workbook. Then: persist a catalog, make
   linking retrieval rather than substring, move the data layer to Parquet.
1. **Product imports its xlsx engine from `tests/`** — `rag/answer.py:900` puts
   `tests/RAG` on `sys.path` and imports `frtr_sql_baseline`. A deploy without
   `tests/` loses the xlsx lane silently (returns `None`). Needs a decision record.
2. **Header detection picks banner rows** — `frtr_sql_baseline.py:29` takes the first
   row with >=2 non-empty cells, so `Messy_RAW` yields columns named `skip` and `—`.
   Real header (row 2) also has duplicate names. Root cause of most #13 loss.
3. **Non-English asks claim full coverage** — `sira.py:13` is ASCII-only, so six
   non-Latin scripts (Cyrillic too) tokenize to nothing and `_coverage` returns 1.0,
   never firing the corrective loop. English fails safe; the rest fail confidently
   wrong. `multilingual_gate.py` **7/25**, expected red. Fix re-indexes, so it is
   gated on `rag/index_fingerprint.py` (built, wired into oracle_bench).
4. **Backfill `docs_path`** — #20 covers new ingests only. Spaces ingested before it
   (space 8) still have no original; they need a re-ingest or a backfill pass.
5. **#9** effort x thinking matrix — not started. **#10** Insights sheet — not started.
6. **D02 has no UI** — five endpoints, zero callers in `index.html`. Needs a ticket
   routed through `prd-agent` before anyone builds it.
7. Commit OpenVault nvidia separately.

## Later

- P1 50GB / P2 Meta SIRA / P3 charts / P4 vault-first / P5 Outerbase·Grafana / P6 2GB
- AirGPT default to NVIDIA only after OV probe passes (P7)

## Demo open

- `tests/RAG/DEMO_RAG.md`, `results/ontology_space_8.json`, `results/warehouse_hybrid_latest.xlsx`

# STATUS

**Hard cap: 60 lines.** Older narrative moves to CHANGELOG.md.

## Now

1. **EPIC-D01 demo-ready** — branch `demo/rag-cross-compare`. Runbook:
   `tests/RAG/DEMO_RAG.md`.
2. **Scores (retained xlsx/json under `tests/RAG/results/`):**
   - Warehouse hybrid_max **10/10**
   - FRTR 0001 cross **hybrid_max 6/6** (baseline/sira/adaptive 5/6)
   - FRTR SQL batch 8 books **10/44 (0.227)** — patterns expanding; 0001=6/6
   - Edge/injection **target 9/9**; Cortex `:8010` pack=dms **live**
3. Honesty: Cortex-direct, not OpenVault-gated. No exclusion confirm loops.

## Next

1. Open/merge PR for `demo/rag-cross-compare`.
2. Expand SQL patterns for FRTR 0002–0007 (or LLM ingest with `AIRGPT_RAG_EMBED=hash`).
3. Thin #9/#10 effort×thinking if capacity.

## Later

- P1 50GB / P2 Meta SIRA / P3 Excel AI charts / P4 vault-first / P5 Outerbase·Grafana·IDE
- Auto CI-on-every-PR “all benches green” — needs DR; not silent scope widen.

## Tomorrow open these

- `tests/RAG/results/warehouse_hybrid_latest.xlsx`
- `tests/RAG/results/frtr_cross_latest.xlsx`
- `tests/RAG/results/frtr_batch_latest.xlsx`
- `tests/RAG/results/edge_probe_latest.json`
- `tests/RAG/DEMO_RAG.md`

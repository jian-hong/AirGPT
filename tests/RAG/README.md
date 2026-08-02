# AirGPT FRTR RAG bench (EPIC-D01)

**Honesty:** this demo branch uses **Cortex-direct / ai_engine RAG** — **not OpenVault-gated**. OpenVault is secrets/mesh only; do not infer vault custody for full AI on this path.

## Live demo default

**`hybrid_max`** — depth=max + pandas SQL lane + SiRA expand. Best score on `frtr_0001` smoke (6/6). Set for live Q&A:

```http
POST /api/rag/spaces/6/demo-variant
{"variant": "hybrid_max"}
```

List presets (with honesty string): `GET /api/rag/demo-variants`. Switching variants updates space config only — **never** deletes `tests/RAG/results/*`.

## Cross-compare harness

```bash
# Full ingest + all variants (writes JSON + xlsx)
python tests/RAG/frtr_cross_compare.py --workbook frtr_0001_quarterly-summary.xlsx

# Re-score one variant without re-ingest (preserves prior score files)
python tests/RAG/frtr_cross_compare.py --workbook frtr_0001_quarterly-summary.xlsx --variants hybrid_max --eval-only --space-id 6
```

Variants: `baseline_basic`, `sira_high`, `sira_max`, `hybrid_max` (default), `adaptive`.

## Retained artifacts

| File | Purpose |
|------|---------|
| `tests/RAG/results/frtr_cross_latest.json` | Multi-variant scoreboard + spot-check + honesty |
| `tests/RAG/results/frtr_cross_latest.xlsx` | Excel-openable scorebook (Summary / Detail / SpotCheck) |
| `tests/RAG/results/frtr_gold.json` | Extracted gold Q&A |

See also `tests/RAG/FRTR-bench/README.md` for the upstream benchmark.

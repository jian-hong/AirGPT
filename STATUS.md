# STATUS

**Hard cap: 60 lines.** Older narrative moves to CHANGELOG.md.

## Now

1. **F2–F4 YES building** — D01 #13–#15 + D02 ops + OpenVault nvidia (#12).
2. **Ontology-first live** — space 8 entities SKU/Money/…; logic steps on answers;
   artifact `tests/RAG/results/ontology_space_8.json`.
3. **Reveal folder** — `POST /api/rag/reveal-path` opens Explorer on real files.
4. **Messy fixtures** — `tests/RAG/messy/` ~317MB (gitignored); meta in results.
5. **Ops amend-confirm** — identify → yes/no → propose → confirm write (E-0012 tested).
6. **OpenVault nvidia** catalog + `docs/NVIDIA_RAG_EVAL.md` (restart OV to pick up).

## Next

1. Commit/push AirGPT `demo/rag-cross-compare`; commit OpenVault nvidia separately.
2. Ingest messy CSV into a dedicated space + score smoke.
3. Thin UI button for Reveal next to citations if capacity.

## Later

- P1 50GB / P2 Meta SIRA / P3 charts / P4 vault-first / P5 Outerbase·Grafana / P6 2GB
- AirGPT default to NVIDIA only after OV probe passes (P7)

## Demo open

- `tests/RAG/DEMO_RAG.md` (full path)
- `tests/RAG/results/ontology_space_8.json`
- `tests/RAG/results/warehouse_hybrid_latest.xlsx`

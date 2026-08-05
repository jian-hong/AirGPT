# STATUS

**Hard cap: 60 lines.** Older narrative moves to CHANGELOG.md.

## Now

1. **F2–F4 YES building** — D01 #13–#15 + D02 ops + OpenVault nvidia (#12).
2. **Ontology-first live** — space 8 entities SKU/Money/…; logic steps on answers;
   artifact `tests/RAG/results/ontology_space_8.json`.
3. **Reveal folder** — `POST /api/rag/reveal-path` opens Explorer on real files.
4. **Messy GB pack** — `tests/RAG/messy/` ~950MB (gitignored); space **15**
   `messy-gb-bench`; Docs backup 139 files; lite ingest + search 4/4; edge 9/9.
5. **Ops amend-confirm** — identify → yes/no → propose → confirm write (E-0012 tested).
6. **OpenVault nvidia** catalog + `docs/NVIDIA_RAG_EVAL.md` (restart OV to pick up).
7. **F7a+F8a** — establish handshake + 90s LAN cache; LB still **P8**.
8. **F10–F12** — hover reveal on cards; Docs/ originals (#20); Why-this-answer (#15).
   Encrypted custody **P9**.

## Next

1. Commit/push AirGPT `demo/rag-cross-compare`; commit OpenVault nvidia separately.
2. Optional: `--ingest-bulk all` on space 15 (slow embed) or primary50 pack gate.
3. Re-ingest older spaces once to populate Docs/ copies (new ingest only).

## Later

- P1 50GB / P2 Meta SIRA / P3 charts / P4 vault-first / P5 Outerbase·Grafana / P6 2GB
- AirGPT default to NVIDIA only after OV probe passes (P7)
- **F15 Demo-2** — NEEDS-YOU closed; Pointer-primary + Copilot YES; amend #22-24 / DMS #29-32 done; build later

## Demo open

- `tests/RAG/DEMO_RAG.md` (full path)
- `tests/RAG/results/messy_ingest_latest.json` + `messy_reveal_latest.json`
- `tests/RAG/results/ontology_space_8.json`
- `tests/RAG/results/warehouse_hybrid_latest.xlsx`

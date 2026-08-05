# CHANGELOG

Append-only. Never edited, only added to. Newest first.

## 2026-08-03 — Messy ~950MB stress pack ingest + reveal + edge (space 15)

- `gen_messy_fixtures.py --mode stress --target-mb 900` → `tests/RAG/messy/` (~950MB, 36 cols, 800–1000 rows).
- Docs backup first under `data/rag/15/Docs` (139 files); lite ingest + search 4/4; `edge_probe` 9/9.
- Harness: `tests/RAG/messy_ingest_eval.py`; artifacts `messy_ingest_latest.json`, `messy_reveal_latest.json`.

## 2026-08-03 — RAG-BENCH-06 primary ~50MB pack + scoreboard (#13)

- `gen_messy_fixtures.py --mode primary` → four ~12MB unclean xlsx (~50MB) under `tests/RAG/primary50/`.
- `primary50_eval.py` retains sira_max / hybrid_max / adaptive scores (`primary50_cross_latest.*`); hybrid_max 10/10.
- DEMO_RAG: primary pack first; few-hundred-MB stress optional. Warehouse + FRTR 0001 baselines re-proved.

## 2026-08-03 — F16 RAG-BENCH-11 filed as #25

- Epic-agent filed [#25](https://github.com/jian-hong/AirGPT/issues/25) RAG-BENCH-11 under EPIC-D01 #6.
- Not folded into #13 / #21 / #15. STATUS Next + PRD ledger updated with issue URL.
- No product code in this turn.

## 2026-08-03 — F16 Settings depth/arch rebuild (routing only)

- PRD F16: existing RAG Settings need index depth / architecture / adaptive + Rebuild.
- YES under EPIC-D01 as new RAG-BENCH-11 (not amend #13/#21/#15; not PRD amend).
- Honesty: depthOpts/archOpts computed but never rendered; save/rebuild already half-wired.
- Adaptive/auto = space default; chat effort stays query-time.

## 2026-08-03 — F15 Excel-native Copilot wave (routing only)

- PRD F15: multi-part OnTime export+chart fails on RAG; Excel Copilot wins on frtr_00027.
- Wave Demo-2: AirGPT EPIC-D04 (identify+prompt+handoff) + DMS EPIC-016 (Excel drive/extract).
- P3 superseded (not AirGPT chart orchestrator). Distinct from F14/#21 SQL.
- Tickets authorized; build later. NEEDS-YOU: Pointer vs MCP; Copilot dependency.
- Cross-acks: DMS F25, Cortex F2.

## 2026-08-03 — F13 epic amend (routing only, no fixtures/bench yet)

- PRD F13 -> EPIC-D01 #6; amend #13 primary ~50MB / 4×~12MB + SiRA vs hybrid toward ~99%.
- Few-hundred-MB messy stays optional stress; P2 Meta SIRA / P6 2GB parked.
- RAG-BENCH-10 not filed (#13 not overloaded). Docs/reveal remain #20/#14.
- STATUS primary pack target updated; ticket-runner owns execution.

## 2026-08-03 — F7-F9 founder follow-up (routing only, no app code)

- PRD-001 ledger F7 host perf/LB, F8 secure handshake, F9 RAG demo clarity.
- Route: F7a MVP cheap (cache/keepalive/establish) vs F7b **P8** true LB; F8a AirGPT establish vs F8b OpenVault vs F8c park; F9 docs-only on D01.
- No tickets — awaiting founder YES on F7a/F8a epic slice.

## 2026-08-03 — F2-F4 founder YES + tickets filed (no app features)

- Ledger F2-F4 -> YES a/b/c; F5 reveal folder; F6 ontology-first. Wave Demo-1 EPIC-D02 authorized.
- AirGPT: #16 EPIC-D02; #13 RAG-BENCH-06; #14 RAG-BENCH-07; #15 RAG-BENCH-08; #17-19 OPS-DEMO-01..03.
- OpenVault: Netie-AI/OpenVault#12 nvidia catalog+probe. Cortex PRD F1 ack updated for D02 YES.
- Branch split: D01 `demo/rag-cross-compare`; D02 `demo/rag-ops-confirm`.

## 2026-08-03 — PRD F2-F4 intake (no app code)

- PRD-001 ledger F2 messy/2GB demos, F3 governed confirm-ops, F4 NVIDIA/Mistral catalog.
- Route: do not reopen D01 for writes; P6/P7 park; OpenVault+Cortex ledger cross-acks.
- Awaiting founder YES a/b/c before EPIC Agent files tickets.

## 2026-08-03 — FRTR-Bench Excel RAG smoke

- Harness: `tests/RAG/frtr_eval.py` (+ SQL baseline, Cortex lane). Sanitize materializes formula caches; strips Questions.
- AirGPT RAG: KPI sheet boost in `rag/retrieve.py`; spreadsheet index + small-sheets-first in `rag/ingest.py`.
- Result: hybrid SQL+RAG **6/6 (100%)** on `frtr_0001_quarterly-summary.xlsx`. Full 159 needs XLOOKUP/SUMIFS SQL agent + vision for chart Qs.
- Cortex `/dms/query` confirmed live for SQL-brain demo; OpenVault is not an Excel RAG path.


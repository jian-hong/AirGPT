# Parking lot

Deferred work. Every entry needs an unlock condition. IDs never reused.

| ID | Item | Why parked | Unlock condition |
|---|---|---|---|
| P1 | ~50GB multi-workbook ingest ambition | Demo-day needs small sanitized FRTR set; large-corpus ops are not plane-4 product proof | Paying design partner needs that corpus size **and** ingest stays on customer hardware without AirGPT owning plane-1 serving |
| P2 | Full Meta SIRA port (BM25x / Rust, corpus enrichment, QE, LLM pointwise rerank, H100 path) | `rag/sira.py` is inspired only; full port + accelerator path is plane 1 / capital fight Netie refuses | Founder DR accepting a **client-of** SIRA (or upstream dependency) without AirGPT owning serving; no H100 programme inside AirGPT |
| P3 | AI-governed Excel chart-intent pipeline (auto pie for "top 5 sales", re-prompt loop, range pick, violin-by-field graphs) | Founder 2026-08-03: later; tomorrow = strong RAG ingest+retrieve+score first | Cortex PRD epic owns governed chart/export action; AirGPT only surfaces it - after EPIC-D01 demo lands |
| P5 | dbgate / Outerbase / Grafana plug-in sheet+CSV full view + multichart | Demo needs scores+Excel xlsx first; external BI hosts are separate products | Founder picks one thin viewer (embed or deep-link) after EPIC-D01 click-through lands; no AirGPT reimplementation of Grafana |
| P4 | Full vault-first slice of PRD-001 (OpenVault keys + Cortex handoff for all chat/RAG) | Press release TBD; F1 demo uses Cortex-direct exception and must not steal EPIC-001 | Founder completes PRD press release/FAQ and authorizes Mode A slice |
| P6 | ~2GB messy multi-sheet uncleaned raw workbook demos (ingest + insights) | F2 YES covered **sample-messy few-hundred-MB** only (RAG-BENCH-06 #13); 2GB raw remains ops/scale | Paying partner needs 2GB+ corpus on customer hardware; never AirGPT plane-1 |
| P7 | NVIDIA / multi-provider model bake-off inside AirGPT | Custody is OpenVault (plane 2); AirGPT must not invent vault or catalog | OpenVault#12 nvidia catalog+probe lands **and** founder authorizes AirGPT to consume OpenVault-gated routes (ends Cortex-direct demo exception) |
| P8 | F7b true load balancer / multi-worker; F8c mTLS mesh | Owned by EPIC-D03 #26 as out-of-scope; single-worker host path is what the demo needs | EPIC-D03 #26 lands its F7a/F8a slice **and** a design partner needs concurrent host load |
| P9 | F11b encrypted / vault Docs custody | Cited as parked by #6, #14 and #20 but never given a row here; #20 retains originals in the clear under `Docs/` | Founder DR accepting custody of customer originals **and** OpenVault owns the key path (P4/P7 resolved) - AirGPT must not invent a vault |
| P10 | DMS regex standards for workbook field extraction | Cited as parked by #6 and #21; #21 shipped SQL-plan binding against the sheet schema instead | DMS publishes a field-standard the RAG lane can consume **and** a workbook arrives whose schema linking the sheet header cannot resolve |
| P11 | EPIC-D01 thin tickets left unparented at close: #9 effort x thinking matrix, #10 insights sheet surface | Founder closed EPIC-D01 2026-08-20 over both. #9 is not started. #10 is **not** "not started" - `tests/RAG/insights_export.py` implements the sheet and `clipdrop.py:5166` exposes `POST /api/rag/insights-export`, but it has zero UI callers and has never been run to completion (`tests/RAG/results/exports/` does not exist) | `prd-agent` routes them into an epic, **or** the founder confirms the demo ships without an insights surface and both issues are closed with that reason recorded |
| P12 | EPIC-D02 governed loop UI surface | HTTP six endpoints work. Build tab now calls `ragOpsIdentify` (`index.html`); the old "zero callers" claim is stale. Founder click-through identify -> amend -> confirm on a live host is still unproven | Founder drives the Build ops card end to end on a live host, **or** `prd-agent` routes remaining click-through into an epic |
| P13 | Multilingual retrieval: non-English asks report full coverage on unrelated evidence | ASCII tokenizer is **fixed** (CHUNK-02 `unicode_v1`). Own-doc coverage positives now pass (zh/ja/ko/ar). Remaining red: English-only `bge-small-en-v1.5` (gate section 3). Hash-lane section 4 passes. Do not quiet those to green. | Opt-in multilingual embedder (F25d-R) lands **and** section 3 actually passes. Until then the red gate is the forwarding record |

A deliberately red gate is not a passing gate. P13's `multilingual_gate.py` stays red on
purpose; do not skip it, xfail it, or delete it to make a suite green (R-0002).

cite: PRD-001 F1-F6 YES 2026-08-03; sample-messy under #13; OV#12; EPIC-D01 #6 and
EPIC-D02 #16 closed 2026-08-20 over unfinished work, remainder in #31-#35 and P11-P13

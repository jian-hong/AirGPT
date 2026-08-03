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

cite: PRD-001 F1-F6 YES 2026-08-03; sample-messy under #13; OV#12; D02 on demo/rag-ops-confirm

keywords: [RAG, architectures, parsers, contextual retrieval, GraphRAG, auto-ontology, NVIDIA, ontology, foreign key, EPIC-D01, P7, routing]
main_idea: NVIDIA/auto-ontology is a Postgres+NIM text-to-SQL stack, not a document-RAG library. Its ideas (profile columns, infer PK/FK from values) were ported clean-room into rag/ontology.py under #6. New parsers, scale and "whole app" are NEEDS-YOU or parked.

# RAG survey, NVIDIA auto-ontology, and what was routed where

Founder ask 2026-11-12 (cloud session): research every RAG architecture, parsing per
file type, scale, "fork and use" NVIDIA auto ontology, keep building.

## Finding (the defect this closed)

- Expected: #6 clause "ontology from workbook semantics (columns/entities/relations)".
- Actual: `rag/ontology.py` matched 17 English keywords against header text and joined
  on a fixed list of seven column names. A workbook outside that vocabulary reported an
  ontology of "Unknown" entities and no relations. It took the first row as the header,
  cited `SKU` and `Money` in reasoning steps by regex even when neither existed, and kept
  its cache until someone passed `force`.
- Repro (old code): any workbook with non-English headers, or a banner row above the
  header, then `GET /api/rag/spaces/<id>/ontology`.
- Root-cause class: a shipped surface that presents a capability it does not have
  (R-0011), plus first-row-wins (the F21 / F28a class) a third time.
- Invariants: silent fallback is a lie; assert the artifact the user receives; prove a
  gate can fail before trusting it (four mutations each turn `tests/test_rag_ontology.py`
  red).
- Now: keys from uniqueness, relations from value containment (>= 90% of a column's
  distinct values inside another table's unique column; numeric columns also need the
  names to agree), column kind/role/date format, table grain, csv, cross-workbook, cache
  keyed on the source files. Verified on `tests/RAG/warehouse/` (6 workbooks, 11
  relations) through `rag.answer.answer_events`.
- Not verified: the n=320 `hybrid_max` re-score. FRTR-bench is not in this clone. The
  ontology feeds the reasoning chain and the `ontology` event only, no answer value, so
  the score should not move. That is an inference, not a measurement.

## NVIDIA/auto-ontology (verified by reading the repo at v1.2.0)

- Apache-2.0. FastAPI + LangChain/LangGraph + Postgres/pgvector + Next.js + NVIDIA NIM
  for LLM, embeddings and rerank. Ten warehouse connectors, read-only MCP server.
- Builds an ontology from relational database metadata: sampled column profiling, date
  formats, PK/FK and junction-table inference, business terms, then validates generated
  SQL against it (join-path check, literal check, value anchors).
- Use here: ideas only, no model call, no copied code. Running the stack is P7 (NIM,
  custody is OpenVault) and conflicts with PRD section 3 (LangGraph is a second
  orchestrator) and with local-first SQLite.
- Fork: not done. This session's GitHub access is scoped to jian-hong/airgpt.
- Worth porting next, in this order, once routed: join-path check on the SQL lane (a
  fabricated join returns rows and never errors), literal check (near-miss filter value),
  value anchors that name schema rather than data.

## RAG architectures (sourced claims carry a URL; the rest is unverified background)

| Pattern | Index cost | Helps | Verdict for a laptop-local system |
|---|---|---|---|
| Hybrid BM25 + dense, RRF, parent/child | low | default | already shipped |
| Contextual retrieval | 1 LLM call per chunk | chunks that lose their document | deterministic header (file, heading path, sheet) by default; LLM header opt-in |
| Text-to-SQL lane + ontology | schema only | aggregates, filters, joins | shipped for xlsx; validators above are the gap |
| Corrective loop (CRAG-style) | none | noisy retrieval, abstention | one rewrite-and-retry, then abstain |
| RAPTOR, GraphRAG, LightRAG, HippoRAG 2 | LLM per chunk or worse | corpus-wide themes, multi-hop | opt-in only; LazyGraphRAG-style deferral if ever |
| Late chunking, ColBERT | long-context or multi-vector model | cross-chunk reference, ranking | not a laptop default |

- Anthropic contextual retrieval: top-20 retrieval failure 5.7% baseline, minus 35% with
  contextual embeddings, minus 49% adding contextual BM25, minus 67% adding a reranker.
  https://www.anthropic.com/news/contextual-retrieval
- LazyGraphRAG: indexing cost about 0.1% of full GraphRAG.
  https://www.microsoft.com/en-us/research/blog/lazygraphrag/

## Parsing per file type (licences unverified, check before any dependency)

- Light tier, stdlib or already-installed: `zipfile`+XML for docx/pptx, `email`, `ast`,
  `html.parser`, `pypdf`, `openpyxl`/`pandas`. Chunk on structure: heading, slide, sheet,
  function.
- Heavy tier, opt-in only: Docling, OCR (RapidOCR / Tesseract), faster-whisper.
- Licence gate: PyMuPDF and PyMuPDF4LLM are AGPL; MinerU, marker and extract-msg were
  reported as AGPL/GPL. Never bundle; run only if the user installs them.

## Reliability and scale (unverified background)

- Reliability: span-level citations with a post-hoc check that the quoted span exists in
  the cited chunk; a calibrated abstention threshold; a golden set with unanswerable
  questions; retrieval metrics scored without an LLM.
- Scale: content-hash incremental indexing, int8/binary quantisation with full-precision
  re-score, an optional HNSW backend above roughly 200k chunks. 100M chunks is not laptop
  territory.

## Routing (prd-agent run, read-only, against PRD-001 and live GitHub)

| Item | Verdict |
|---|---|
| Research survey | not a build item; this note |
| Fork NVIDIA/auto-ontology | founder YES verbatim; reference fork only; vendoring needs a DR |
| Run the NVIDIA stack | PARKED P7, unlock not met |
| Port its ideas into `rag/ontology.py` | open EPIC-D01 #6, as defect. Built. |
| New parsers, "Claude-like reliable RAG" beyond xlsx | PRD amendment, NEEDS-YOU |
| Scale | PARKED P1 / P6 / P13, unlocks not met |
| "Whole app until done" | not sliceable; no assertion; press release still TBD (P4) |

NEEDS-YOU: authorize a RAG reliability epic whose acceptance is a per-file-type oracle
bench (pdf / docx / pptx / csv / md) with F13b-style floors? Recommended YES, bench first.

Ledger rows for the founder to append to PRD-001 section 7. The ledger in git ends at
F50 while this repo cites up to F89, so these are placeholders, not numbers.

```
| F-NEXT-1 | 2026-11-12 | Claude Code cloud session (founder) | "Research more about RAG each different architecture ... how to parse" | none - not a build item | Research note only; no ticket |
| F-NEXT-2 | 2026-11-12 | same | "auto ontology by nvdiia ( arepo pllease research and fork and use)" - fork | none - estate action | Founder YES verbatim; reference fork only; vendoring needs DR |
| F-NEXT-3 | 2026-11-12 | same | same - run the NVIDIA stack (NIM/Postgres/LangGraph) | PARKED P7 | Unlock not met; conflicts section 3 and local-first SQLite |
| F-NEXT-4 | 2026-11-12 | same | same - use its ideas in AirGPT ontology | OPEN EPIC-D01 #6 (defect; #15 closed over a keyword list) | Built clean-room in rag/ontology.py |
| F-NEXT-5 | 2026-11-12 | same | "different data type file how to parse ... reliable claude like RAG" | none - PRD amendment, NEEDS-YOU | Recommend new epic, per-type oracle bench first |
| F-NEXT-6 | 2026-11-12 | same | "scale" | PARKED P1/P6/P13 | Unlocks not met |
| F-NEXT-7 | 2026-11-12 | same | "whole app should be continue work ... until whole app don" | none - not sliceable | No assertion; P4; WIP limit stands |
```

## Subagent shape

Two agents, isolated context. One Sonnet web survey (5 tool uses; mostly background
knowledge, three sourced claims). One prd-agent routing run on the session model, reading
`Netie-AI/Netie` cloned at `/home/user/netie-ai/netie`. Build and verify ran inline.

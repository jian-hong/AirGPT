# AirGPT RAG Agent — Implementation Plan (Claude Code handoff)

> Status: ready for implementation · Draft 2026-07-23  
> Companion research canvas: workspace canvases `airgpt-rag-agent-product-plan.canvas.tsx`  
> Anchors: `docs/architecture.md`, `docs/memory-layer.md`, `docs/SCALING_POSTGRES_REDIS.md`, `docs/STRATEGY_NEXT_PHASE.md`, `docs/netie-product-architecture.md`  
> **Non-negotiable:** Personal stays local-first (SQLite + vault). Heavy services (Postgres/Redis/Qdrant) are opt-in profiles, never required for chat to work.

---

## 0. One-sentence product

**RAG is a first-class AirGPT agent service under Research:** users create persistent knowledge spaces (RAGs), ingest projects/chats/files, pick a knowledge-depth tier (High / Max), and chat against that corpus with citations, `@` context, and `/` tools — while Netie Cortex / local CortexOS orchestrates the *internal* architecture (hybrid / agentic / graph / modular) from predetermined workflows.

---

## 1. Product ontology (what users see vs what Cortex does)

### 1.1 User-facing entities

| Entity | User language | Meaning |
|--------|---------------|---------|
| **Agents** | Automations + created agents | Existing Cortex catalog (`agent_store` / Cortex page). RAG Agent is one seeded agent *type*. |
| **Default Memory Agent** | Everyday persistent memory | Thin, efficient RAG over chat/project memory (current `memory_index` + vault carry). Always on. Not a heavy corpus builder. |
| **RAG (knowledge space)** | “My RAGs” under Research | Versioned corpus + index profile + chat threads. Persisted. Import/exportable. |
| **RAG chat** | Chat inside a RAG | Continue previous or “New chat” under that RAG. Separate from normal clipboard chat, but can be linked. |
| **Depth tier** | **High** / **Max** | User contract for knowledge depth / compute. Not architecture names. |
| **@ mentions** | `@chat`, `@file`, `@project`, `@rag`, `@memory` | Inject scoped context into the prompt / retrieval filter. |
| **/ commands** | `/rag`, `/ingest`, `/search`, `/cite`, `/trace`, `/agents`, … | Cursor/Claude-style slash actions registered globally. |

### 1.2 Internal (hidden) architecture catalog

Cortex chooses among these; UI never forces users to pick “Graph RAG” vs “Modular RAG”:

| Internal pattern | Research basis | When Cortex picks it |
|------------------|----------------|----------------------|
| **Naive Hybrid RAG** | Dense + sparse → RRF → rerank | Default for High; file/fact lookup |
| **Agentic RAG (Auto-RAG style)** | Iterative retrieve / sufficiency stop | High corrective loop; Max multi-hop |
| **Graph RAG** | Entity–relation graph + local/global search | Max: themes, “what connects X–Y”, corpus-wide |
| **HybridRAG (KG + vector)** | [HybridRAG arXiv:2408.04948](https://arxiv.org/abs/2408.04948) | Max when both semantic + relational needed |
| **Modular RAG** | [Gao et al. arXiv:2407.21059](https://arxiv.org/abs/2407.21059) routing / scheduling / fusion; linear · conditional · branching · looping | Orchestration substrate for all tiers |
| **Multimodal RAG** | [RAG-Anything](https://github.com/HKUDS/RAG-Anything) | PDFs/slides/tables/images when modality flag on |
| **SiRA lexical sidecar** | [facebookresearch/sira](https://github.com/facebookresearch/sira) | Offline index phrases + DF-guarded expansion; file-level search |
| **Auto pipeline search** | [IBM AutoAI RAG](https://www.ibm.com/docs/en/watsonx/saas?topic=generation-automating-rag-pattern-autoai), [Auto-RAG](https://github.com/ictnlp/auto-rag) | Offline profile promotion only — never live free-form architecture invention |

### 1.3 High vs Max (user contract → Cortex routing)

| Tier | User promise | Internal max complexity | Hard caps |
|------|--------------|-------------------------|-----------|
| **High** (default for new RAGs) | Thorough hybrid answer + short evidence check | Modular hybrid + SiRA expansion + ≤1 corrective retrieve | ≤2 retrieval rounds; no global graph unless preclassified; latency budget |
| **Max** | Research-grade multi-hop / corpus synthesis (slower) | Planner → hybrid + file tools → optional KG local/global → synthesis | ≤3 rounds; graph only on entity/global triggers; disclose gaps |
| **Modifier: Multimodal** | Figures/tables/scans | RAG-Anything lane + selected tier | Page/region citations required |

**Standard** (optional third tier for later): one-pass hybrid; can ship as “Fast” later without renaming High/Max.

---

## 2. Current AirGPT reality (do not rewrite blindly)

### 2.1 What already works

| Area | Path | Notes |
|------|------|-------|
| Agent CRUD + runs | `agent_store.py`, `agent_runtime.py`, `clipdrop.py` `/api/agents*` | SQLite `data/agents.db`; SSE tool loop |
| Tools | `agent_tools.py` | vault, memory, fs, git, web, audit |
| Memory (default) | `memory_index.py`, `vault.py`, `docs/memory-layer.md` | SQLite FTS5 + optional Chroma; carry pack |
| Research UI | `research.py`, `index.html` `showResearchPage` | Library only — **no chunk/embed/retrieve** |
| CortexOS RAG prototype | `CortexOS/rag/*`, `CortexOS/api/search.py` | Dense Qdrant + Postgres FTS + RRF + BGE rerank — **listing-shaped**, not generic docs |
| DAG compiler | `CortexOS/fabrication/*`, `execution/dag_runner.py` | Compiler OK; runner only executes subset of node types |
| Soft Cortex sidecar | `cortex_client.py` | Soft-fail; chat works offline |
| OpenIDE `@path` | `index.html`, `agent_runtime.py` `FILE_MENTION_RE` | Path mentions only — not global `@`/`/` |

### 2.2 Explicit gaps this plan closes

1. No RAG knowledge-space product UI  
2. No ingest → chunk → embed → index → retrieve → rerank → cite pipeline for user docs  
3. No High/Max depth routing  
4. No global `@` / `/` registry  
5. No intent detect → open Cortex / RAG Agent  
6. Agent links metadata-only (no A2A orchestration)  
7. Recipes listed, not executed  
8. LangGraph/LangChain advertised in CortexOS engine registry, **not wired**  
9. Redis / Mem0 / Qdrant not in AirGPT personal path  
10. Research uploads not text-extracted  

---

## 3. Dual-agent model (Memory Agent vs RAG Agent)

### 3.1 Default Memory Agent (always-on, efficient)

**Purpose:** Everyday persistent memory — “convert the thing we keep doing in chat into a durable agent you talk to daily.”

| Property | Spec |
|----------|------|
| Seeded name | `Memory` (kind=`memory_default`) |
| Backing | Existing `memory_index` + vault wings + chat ditch/index |
| Chunking | Light: turn/snippet level (already mostly done) |
| Vectors | Local: sqlite-vec (replace Chroma slot per scaling doc); optional |
| Retrieval | FTS → vector → vault keyword → carry pack |
| UX | Memory glass panel + `@memory` + agent in Cortex catalog |
| Cost | Memory-efficient; no graph; no Max pipelines |

**Do not** merge Memory Agent indexes into heavy RAG corpora. Memory is personalization / carry; RAG is authoritative document knowledge.

### 3.2 RAG Agent (Research app)

**Purpose:** Build, persist, chat with, import/export knowledge spaces.

| Property | Spec |
|----------|------|
| Seeded name | `RAG` (kind=`rag_service`) |
| Owns | Knowledge spaces, ingest jobs, index revisions, RAG chats, eval suites |
| Tools | `rag_*` tool family (see §8) |
| Orchestration | Predetermined Modular RAG DAGs; Cortex router picks template |
| Persistence | Local SQLite schema first; Business/opt-in: Postgres + Qdrant + Redis |

---

## 4. Information architecture (UI)

### 4.1 Nav placement

Under **Agents** (alongside Research), add **RAG**:

```
Agents
├── Cortex (all agents / dispatch)     — existing showCortexPage
├── Research                           — existing showResearchPage (papers/drafts)
└── RAG  ← NEW                         — showRagPage()
```

Research remains papers/library. RAG is the knowledge-space product. Cross-link: “Index this paper into a RAG”.

### 4.2 RAG page structure

**L1 — RAG library**

- Grid/list of knowledge spaces user created  
- Actions: Create · Import pack · Rename · Duplicate · Archive · Export  
- Each card: name, source count, last chat, depth default (High/Max), status (indexing/ready/error)

**L2 — Inside a RAG**

Tabs / panes:

1. **Sources** — upload files, upload folder, attach project, attach chats, attach Research papers, link vault rooms  
2. **Build** — depth High/Max, modality toggle, index progress, last eval score, “Rebuild”  
3. **Chats** — previous RAG chats; Continue · New chat  
4. **Trace** — last retrieval traces / citations (debug)  
5. **Settings** — retention, backends profile (Local / Local+Qdrant / Business), export

**Chat composer (inside RAG)**

- Same streaming UX as main chat  
- `@` picker: files in this RAG, prior chats, projects, memory, other RAGs (scoped)  
- `/` picker: slash command registry  
- Depth toggle High | Max on each send (defaults from RAG settings)  
- Citations panel under answer

### 4.3 Intent bridges (chat → Cortex → RAG)

In normal chat / agent loop, add a **lightweight intent classifier** (rules + small LLM) in `ai_engine` / `agent_runtime`:

| Detected intent | Action |
|-----------------|--------|
| Agentic / multi-step tool work | Offer / route to Cortex agent run |
| “Index my project”, “build a knowledge base”, “RAG this folder”, repeated corpus Q&A | Open RAG Agent; create or select knowledge space |
| Everyday recall (“what did we decide”) | Memory Agent / `@memory` — no heavy RAG |

UI: soft handoff chip — “Continue in RAG Agent?” / “Open in Cortex” — never hijack silently.

---

## 5. Storage & compute profiles (local-first law)

Align with `SCALING_POSTGRES_REDIS.md`: **flag picks backend, never feature**.

| Concern | Personal (default) | RAG Local+ (opt-in) | Business |
|---------|--------------------|---------------------|----------|
| Metadata / jobs / chats | SQLite `data/rag.db` | same or Postgres | Postgres |
| Lexical | FTS5 + file-level index | + Postgres tsvector optional | Postgres FTS |
| Vectors | **sqlite-vec** in `rag.db` / memory db | **Qdrant** (Docker/local) | Qdrant or pgvector |
| Cache / queue | in-process + SSD cache dir | **Redis** | Redis |
| Blobs | `data/rag/{ks_id}/` originals + parse artifacts | same / MinIO | S3/MinIO |
| Agent memory | local mem0-shaped API on SQLite | Mem0 OSS → Qdrant | Mem0 + Postgres |
| Graph (Max) | SQLite edge tables or NetworkX artifact | Neo4j/optional later | Postgres AGE or graph store |

**Cache layers (all profiles):**

1. **RAM** — hot query → cited answer (revision+ACL keyed)  
2. **SSD** — embedding cache, parse cache (`data/rag/_cache/`)  
3. **Redis** (opt-in) — job queue, rate limits, semantic cache TTL  

**Never** require Docker for first RAG High answer on a laptop.

---

## 6. Predetermined workflows (exact order — Cortex must not reorder)

### 6.1 Ingest (text / code / md)

```
Authorize → Hash/dedupe → Extract → Normalize → Classify
→ Chunk (parent–child) → Enrich (SiRA phrases, optional)
→ Embed → Index (lexical + dense + file-level)
→ Validate (counts, ACL, embedding dims)
→ Publish revision (atomic) → Notify
```

### 6.2 Ingest (multimodal)

```
Authorize → Parse (RAG-Anything style) → Extract modalities
→ Link layout (page/bbox) → Chunk → Embed modalities
→ Optional graph build → Index → Validate → Publish
```

### 6.3 Query — High

```
Auth → Route(query_class) → Cache check
→ Constrained rewrite / SiRA expand (DF-guarded)
→ ACL filter → Dense retrieve ∥ Sparse retrieve ∥ File-level
→ RRF fuse → Rerank (50–200) → Parent expand
→ Generate grounded → Verify claims → Cite → Trace → Cache
```

Optional: **one** corrective retrieval if sufficiency check fails.

### 6.4 Query — Max

```
Auth → Classify → Plan (typed Modular template)
→ Tool loop: hybrid | file | graph_local | graph_global | multimodal
→ Assess evidence → Refine or stop (≤3)
→ Synthesize → Verify → Cite → Trace
```

### 6.5 Offline Auto-pipeline (IBM AutoAI / Auto-RAG inspired)

```
Golden set → Grid/HPO over {chunk profile, embedder, top-k, fusion, reranker, prompt}
→ Score (Ragas + IR metrics) → Human gate → Promote profile → Never auto-ship without gate
```

---

## 7. Modular RAG operator inventory (implement as DAG nodes)

Map Gao Modular RAG + CortexOS DSL:

| Operator | Node type (extend `dag_runner`) | Notes |
|----------|----------------------------------|-------|
| Router | `rag_route` | Query class → template id |
| Scheduler | `rag_schedule` | continue/halt by sufficiency + budget |
| Retriever dense | `rag_dense` | sqlite-vec / Qdrant |
| Retriever sparse | `rag_sparse` | FTS / BM25 |
| File-level | `rag_file` | SiRA / filename / header index |
| Fuse RRF | `rag_fuse` | Reuse `CortexOS/rag/fuser_rrf.py` logic |
| Rerank | `rag_rerank` | BGE cross-encoder when available |
| Graph local/global | `rag_graph_*` | Max only |
| Generate | `llm_judged` / `rag_generate` | Citation-forced prompt |
| Verify | `rag_verify` | Unsupported-claim detect |
| Emit | `emit` | SSE events + trace |

**Patterns:** linear (High), conditional (route), branching (dense∥sparse∥file), looping (Auto-RAG Max).

**LangGraph/LangChain:** optional adapters behind the same DAG interface (`CortexOS/api/engine_routes.py`). Phase 1: native DAG runner with new node types. Phase 2: LangGraph adapter for marketplace engines. Do not block shipping on LangChain.

---

## 8. API surface (AirGPT `clipdrop.py` + optional CortexOS)

Host-only + auth gates — same as `/api/agents/*`.

### 8.1 Knowledge spaces & sources

```
GET    /api/rag/spaces
POST   /api/rag/spaces                    {name, depth_default, modalities, profile}
PATCH  /api/rag/spaces/{id}               rename, settings
DELETE /api/rag/spaces/{id}               soft archive
POST   /api/rag/spaces/{id}/export        pack zip/json
POST   /api/rag/spaces/import

POST   /api/rag/spaces/{id}/sources       multipart files | folder walk | project_id | chat_ids | research_ids
GET    /api/rag/spaces/{id}/sources
DELETE /api/rag/spaces/{id}/sources/{sid}

POST   /api/rag/spaces/{id}/build         {depth, force_rebuild, graph?}
GET    /api/rag/ingest-jobs/{job_id}
GET    /api/rag/spaces/{id}/revisions
POST   /api/rag/revisions/{rid}/evaluate
POST   /api/rag/revisions/{rid}/promote   human gate
```

### 8.2 Search, answer, chats, memory bridge

```
POST   /api/rag/search                    retrieval only + debug scores
POST   /api/rag/answers                   SSE: plan, citations, tokens, done
GET    /api/rag/traces/{trace_id}

GET    /api/rag/spaces/{id}/chats
POST   /api/rag/spaces/{id}/chats
GET    /api/rag/chats/{cid}/messages

POST   /api/rag/feedback                  {trace_id, rating, citation_issue}

# Slash / mention support
GET    /api/commands                      registry
GET    /api/mentions/suggest?q=&scope=
```

### 8.3 Agent tools (in `agent_tools.py`)

| Tool | Effect |
|------|--------|
| `rag_list_spaces` | List RAGs |
| `rag_ingest` | Queue sources (approval if shared) |
| `rag_search` | Hybrid search + citations |
| `rag_answer` | Full High/Max answer path |
| `rag_build` | Trigger rebuild |
| `rag_trace` | Fetch trace |
| `memory_search` / `memory_add` | Keep; Memory Agent |

---

## 9. Chunking, indexing, SiRA, file-level search

### 9.1 Parent–child chunking (default)

- Split on headings / page / code symbol boundaries  
- **Child** 128–256 tokens → embed for precision  
- **Parent** 600–1000 tokens → return for generation  
- Metadata: `file_id, path, parent_id, page, span, version, project, acl, modality`

### 9.2 SiRA adoption (bounded)

Offline:

1. LLM (or heuristic) generates indexing phrases per section/file  
2. Validate against corpus document frequency (reject absent/generic)  
3. Store phrases in lexical/file index  

Online:

4. Query expansion only with DF-guarded phrases  
5. Weighted lexical + dense; pointwise rerank  

Ship as optional enrich stage — auditable, not free rewrite.

### 9.3 File-level search

Separate index from chunks:

- filename, path tokens, headings, symbols, SiRA phrases  
- Used when query looks like path/API/identifier (`fs_search`-style + RAG file index)  
- Learn from Google file-level patterns: exact match boost, path prefix, recent-open bias (project activity)

---

## 10. `@` and `/` global system

### 10.1 Slash command registry (`commands.py` new)

| Command | Behavior |
|---------|----------|
| `/rag` | Open RAG page / select space |
| `/rag new` | Create knowledge space |
| `/ingest` | Attach files/folder to current RAG |
| `/search` | Retrieval-only |
| `/cite` | Force citation mode |
| `/trace` | Show last trace |
| `/agents` | Open Cortex |
| `/memory` | Open Memory Agent / panel |
| `/depth high\|max` | Set turn depth |

Extensible JSON/YAML registry so marketplace skills can add commands.

### 10.2 Mention resolver (`mentions.py` new)

| Token | Resolves to |
|-------|-------------|
| `@file:path` / `@path` | Existing OpenIDE behavior generalized |
| `@chat:id` / `@chat:title` | Prior chat turns (compressed) |
| `@project:name` | Project wing + indexed files |
| `@rag:name` | Force retrieval scope |
| `@memory` | Memory Agent carry/search |
| `@selection` | UI-highlighted text |

Resolver runs before LLM; injects bounded context + retrieval filters.

---

## 11. CortexOS linkage (what to reuse vs rewrite)

| Reuse | Action |
|-------|--------|
| `CortexOS/rag/fuser_rrf.py` | Port/adapt into AirGPT `rag/fuse.py` (no listing schema) |
| `CortexOS/rag/reranker.py` | Generic chunk rerank |
| `CortexOS/rag/retriever_dense.py` | Parameterize collection = knowledge_space |
| `CortexOS/rag/retriever_sparse.py` | Generic docs FTS |
| `CortexOS/nlp/embedder_bge.py` | Shared embedder facade |
| `CortexOS/memory/store.py` `VectorStore` protocol | Implement sqlite-vec + Qdrant backends |
| `CortexOS/fabrication/dag_compiler.py` | Compile Modular RAG templates |
| `dag_runner.py` | **Extend** node types; parallel layers; tool/A2A stubs |

| Do not | Why |
|--------|-----|
| Wire listing indexer as AirGPT RAG | Wrong schema |
| Require CortexOS online for RAG | Soft-fail; local path must work |
| Let LLM invent new DAG nodes at runtime | Only pick from approved template IDs |

AirGPT modules to add (suggested tree):

```
rag/
  __init__.py
  store.py           # rag.db schema: spaces, sources, chunks, revisions, chats
  ingest.py          # extract/normalize/chunk/enrich
  chunking.py
  sira.py            # phrase enrich + DF guard
  index_local.py     # FTS + sqlite-vec
  index_qdrant.py    # optional
  retrieve.py        # hybrid + file-level
  rerank.py
  graph.py           # Max opt-in
  answer.py          # High/Max pipelines
  evaluate.py        # golden + stress
  export_import.py
  intents.py         # detect → Cortex/RAG
commands.py
mentions.py
```

Wire through `clipdrop.py`, tools in `agent_tools.py`, seed in `research.py` or `agent_runtime.ensure_defaults`.

---

## 12. Evaluation, stress, human gates (ship blockers)

### 12.1 Metrics by stage

| Stage | Metrics |
|-------|---------|
| Ingest | parse success, chunk coverage, dup/revision, ACL inherit, index lag |
| Retrieve | Recall@k, MRR, nDCG, file-level recall, zero-result rate |
| Rerank | ΔnDCG vs hybrid, P95 latency |
| Generate | faithfulness, citation precision/coverage, grounded claim rate |
| Agent | router accuracy, plan validity, rounds, stop reasons |
| Ops | P50/P95 latency, RAM/SSD, cache hit quality, cost/query |

Use Ragas + deterministic IR; local judge model + human audits for promotion.

### 12.2 Stress / security suites

- Identifier-heavy, paraphrase, typo, multilingual, near-dup, contradictory revisions  
- Cross-tenant / revoked doc → zero unauthorized context  
- Concurrent ingest+query; Redis/Qdrant/LLM partial outage → bounded degrade  
- Graph cycles / noisy entities → safe stop  
- Prompt injection in documents cannot change ACL/tool policy  

### 12.3 Human gates

Promote index revision / profile only after:

1. Automated suite green  
2. Spot-check of low-confidence + high-impact answers  
3. Explicit `POST .../promote` actor  

---

## 13. Implementation phases (Claude Code order)

### Phase 0 — Foundation (1–2 days)

- [ ] `rag/store.py` SQLite schema + migrations  
- [ ] Seed RAG + Memory agents  
- [ ] `GET/POST /api/rag/spaces` + minimal library UI shell in `index.html`  
- [ ] Host-only gates in `clipdrop.py`  
- [ ] Unit tests for schema  

### Phase 1 — Local Hybrid High (shippable MVP)

- [ ] Ingest txt/md/code (+ PDF text layer if cheap)  
- [ ] Parent–child chunk + FTS + sqlite-vec (or Chroma bridge until sqlite-vec)  
- [ ] Hybrid retrieve + simple rerank (cross-encoder optional)  
- [ ] `POST /api/rag/answers` SSE with citations  
- [ ] RAG chats (list / continue / new)  
- [ ] Tools: `rag_search`, `rag_ingest`, `rag_list_spaces`  
- [ ] Wire Research upload → optional “Add to RAG”  
- [ ] Golden set of 20 Qs + Recall@5 smoke  

### Phase 2 — Product UX + @ /

- [ ] Full RAG page (Sources / Build / Chats / Trace)  
- [ ] Folder upload + project/chat attach  
- [ ] `commands.py` + `mentions.py` + UI pickers (extend OpenIDE `@`)  
- [ ] Intent detect chips → Cortex / RAG  
- [ ] Export/import packs  
- [ ] Depth High toggle end-to-end  

### Phase 3 — Max + Cortex orchestration

- [ ] Extend `dag_runner` with rag_* nodes  
- [ ] Predetermined High/Max templates  
- [ ] Auto-RAG style sufficiency loop (caps)  
- [ ] SiRA enrich stage  
- [ ] File-level index  
- [ ] Trace UI + feedback → eval dataset  

### Phase 4 — Graph / HybridRAG / Multimodal (opt-in)

- [ ] Entity graph build (offline job)  
- [ ] Graph local/global tools for Max  
- [ ] HybridRAG fusion (vector + KG)  
- [ ] RAG-Anything multimodal lane  
- [ ] Eval gate before default-on  

### Phase 5 — Scale backends + Auto pipeline

- [ ] Qdrant + Redis + Postgres profiles  
- [ ] Mem0 OSS adapter (isolated from corpus)  
- [ ] Offline AutoAI-style profile search  
- [ ] LangGraph adapter (optional engine)  
- [ ] Stress suite + promote API  

### Phase 6 — Hardening

- [ ] Security suite (injection, ACL)  
- [ ] Audit events for ingest/answer/promote  
- [ ] Docs: user guide + `docs/memory-layer.md` update  
- [ ] allcheck.py routes  

---

## 14. File-level change map (for Claude Code)

| File | Change |
|------|--------|
| `rag/*` (new) | Core service |
| `commands.py`, `mentions.py` (new) | Global @ / |
| `clipdrop.py` | Routes + host-only |
| `agent_tools.py` | `rag_*` tools |
| `agent_runtime.py` | Mentions, intent, tool loop |
| `agent_store.py` | kinds `rag_service`, `memory_default` |
| `ai_engine.py` | Optional RAG context inject; intent chips |
| `memory_index.py` | Keep contract; Memory Agent stays here |
| `research.py` | Seed RAG agent; link papers → sources |
| `index.html` | `showRagPage`, nav, pickers, chat |
| `CortexOS/execution/dag_runner.py` | New node types |
| `CortexOS/rag/*` | Generalize or port algorithms |
| `docs/memory-layer.md` | Document dual Memory vs RAG |
| `allcheck.py` | New route probes |
| `requirements.txt` | sqlite-vec; optional qdrant-client, redis |

**Do not** edit `CortexOS/AirGPT/` snapshot as source of truth — root AirGPT only.

---

## 15. Acceptance criteria (MVP = end of Phase 1–2)

1. User creates a RAG, uploads a folder, build completes without Docker.  
2. User chats inside that RAG; answers include file citations.  
3. Previous RAG chats list; continue + new chat work.  
4. `@rag:name` and `/search` work from RAG chat.  
5. Normal chat still works with CortexOS offline.  
6. Memory Agent unchanged for everyday recall.  
7. High depth uses hybrid path; Max path exists with caps (even if graph stubbed).  
8. Host-only + audit on ingest/answer.  
9. Export/import a RAG pack.  
10. Smoke eval Recall@5 on fixture corpus ≥ agreed floor.

---

## 16. Risks & anti-patterns

| Risk | Mitigation |
|------|------------|
| Graph/Max as default → slow + worse | High default; Max opt-in; eval before promote |
| Mixing Mem0 with corpus | Separate stores; memory = untrusted personalization |
| Chroma forever | Replace with sqlite-vec per scaling doc |
| LLM invents pipelines | Template IDs only |
| Silent CortexOS dependency | Soft-fail local path |
| UI architecture jargon | Only High/Max (+ Multimodal toggle) |
| Duplicate Research vs RAG | Research = library; RAG = indexed knowledge product |

---

## 17. Research bibliography (implement against)

1. SiRA — https://github.com/facebookresearch/sira · arXiv:2605.06647  
2. Auto-RAG — https://github.com/ictnlp/auto-rag · arXiv:2411.19443  
3. IBM AutoAI RAG — https://www.ibm.com/docs/en/watsonx/saas?topic=generation-automating-rag-pattern-autoai  
4. RAG-Anything — https://github.com/HKUDS/RAG-Anything  
5. Modular RAG — Gao et al. arXiv:2407.21059  
6. HybridRAG — arXiv:2408.04948  
7. Microsoft GraphRAG — https://microsoft.github.io/graphrag/  
8. Agentic RAG survey — arXiv:2501.09136  
9. Qdrant hybrid/rerank docs · Ragas metrics · Mem0 OSS  

---

## 18. Foundation already landed (Cursor assist loop — 2026-07-23)

Do **not** re-scaffold these; extend them:

| Path | Status |
|------|--------|
| `rag/store.py` | SQLite `data/rag/rag.db` spaces/sources/chunks/FTS/file_index/revisions/jobs/chats/traces |
| `rag/chunking.py` | Parent–child chunking |
| `rag/fuse.py` | Generic RRF (not listing-shaped) |
| `rag/sira.py` | Heuristic phrases + DF guard + constrained expand |
| `rag/ingest.py` | Folder/file ingest → chunk → enrich → index → publish |
| `rag/retrieve.py` | Sparse FTS ∥ dense-lexical stub ∥ file-level → RRF → parent expand → traces |
| `rag/answer.py` | Extractive grounded answer + citations (LLM optional) |
| `rag/agents.py` | Seeds `Memory` + `RAG` agents |
| `rag/intents.py` | Soft chips: rag / cortex / memory |
| `commands.py` / `mentions.py` | Slash + @ registry |
| `agent_tools.py` | `rag_list_spaces`, `rag_ingest`, `rag_search`, `rag_answer` |
| `clipdrop.py` | Host-only `/api/rag/*`, `/api/commands`, `/api/mentions/suggest` |
| `tests/test_rag_foundation.py` | Offline ingest/search/answer/intent tests |

**Also landed (loop tick 1 — 2026-07-23):**
- Agents → RAG nav + full `showRagPage` (library, sources/build/chats/trace, `/search`, depth, SSE chat)
- `POST /api/rag/answers` SSE stream (`Accept: text/event-stream`)
- `rag/embed.py` + `rag/vectors.py` — dense index: sqlite-vec if installed, else hash-embed blob cosine; soft-fail to lexical
- Default embedder is **hash** (offline). Opt-in real models: `AIRGPT_RAG_EMBED=bge` (avoids surprise HF downloads)
- `GET /api/rag/vectors` status; Build tab shows backend; UI LLM toggle for grounded `ai_engine.chat_text`
- `test_recall_at5_smoke` golden Recall@5 ≥ 0.8

**MVP verified (parallel Claude session — browser E2E):** create space → ingest `D:/AirGPT/docs` (16 sources) → new chat → SSE answer with citations grounded in real files. Unit 6/6. Contained route smoke 11/11. No commit yet (await user).

**Loop tick 2 — true grounded LLM streaming (2026-07-23):**
- `rag.answer.answer_events()` — retrieve once → meta → citations → live `delta*` from `ai_engine._standard_llm_stream` (grounded system/user, no vault mix-in) when `use_llm=True`; extractive chunked otherwise; soft-fail to extractive
- `clipdrop._handle_rag_answer_stream` consumes `answer_events` (no post-hoc slice-of-full-answer)
- UI shows `thinking` events in RAG composer

**Claude / loop next:** SiRA LLM enrich stage, Max DAG nodes, `@`/`/` pickers polish, export/import packs, Research→Add-to-RAG.

## 19. Immediate Claude Code start prompt (copy)

```
Implement AirGPT RAG Agent Phase 0+1 per docs/RAG_AGENT_IMPLEMENTATION_PLAN.md.

Constraints:
- Local-first: SQLite + FTS + sqlite-vec (or Chroma bridge); no Docker required.
- Seed agents: Memory (memory_default) and RAG (rag_service).
- Add rag/ package, /api/rag/* routes in clipdrop.py (host-only), minimal showRagPage UI.
- Parent–child chunk → hybrid retrieve → cite in SSE answers.
- Do not break memory_index / normal chat / Cortex soft-fail.
- Reuse algorithms from CortexOS/rag (RRF, rerank) but generic chunk schema.
- Skip graph/Qdrant/Redis until Phase 4–5.
- Add allcheck probes + a tiny fixture corpus test.
```

---

*End of handoff plan. Visual overview: canvas `airgpt-rag-agent-product-plan.canvas.tsx`.*

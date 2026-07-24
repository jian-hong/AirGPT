# AirGPT roadmap (P2–P5)

Personal local AirGPT stays free / open-source path (BYOK). Online Pro and Business governance are the paid tiers — do not paywall local clipboard/chat.

## Locked licensing

| Tier | Price stance | What ships |
|------|----------------|------------|
| **Personal** | Free local / OSS-path | Clipboard, WiFi, tunnel, BYOK AI, session share QR |
| **Business** | License | Admin, IP allowlist, Cortex governance, audit export |
| **Online Pro** | Expensive hosted (~$200/mo target in P3) | Hosted keys, managed DB, Stripe entitlement |

## Phase 2 — Memory + local models + OpenVault readiness

- Project memory wings (MemPalace-inspired) on top of vault
- `vLLM` OpenAI-compatible provider in `ai_engine.py`
- OpenVault / NVMe health hooks as config only (no Phison hardware dependency)
- **Hub panel** — Coherent Access graph, join codes, per-peer ACL, disconnect history
- **Agents IA** — All Agents + Research under Agents; Marketplace meta categories
- **OSS template research** — `docs/templates-research.md` (patterns only)

## Phase 2.5 — OpenIDE + OpenForge + Cortex agentic (2026-07)

- **OpenIDE**: Monaco workspace, path-jailed FS, Cursor SDK bridge (`cursor_bridge.py`)
- **OpenForge**: chat-to-chip design API (`openforge_chip.py`) — integrate full Netie ngspice pipeline next
- **Cortex**: multi-step tool loop, Thinking modes, orchestrator worker (`cortex_orchestrator.py`)
- See `parkinglot.markdown` for remaining checklist

## Phase 3 — Paid online Personal

- Activate Stripe on `control_plane` (kill stubs in `NEXT_UPDATE.md`)
- Bundle: managed Postgres/Supabase, Resend, hosted API keys
- Self-hosted SKU remains BYOK + local DB

## Phase 4 — Enterprise audit + scale

- K8s split: AirGPT API + optional vLLM GPU
- Connectors: SLURM / VMware / enterprise DB audit export
- Masked data layer before any cloud sync
- Ontology-lite: Asset, Agent, Run, MemoryWing

## Phase 5 — Vertex-style companions

- Forward-deployed QC / predictive maintenance companions
- AirGPT/Cortex orchestrates + audits; edge inference stays external

## Shipped 2026-07-24 — agent surfaces, Routines, methodology skills

- **Dedicated agent surfaces**: clicking a built agent opens its own page or a focused chat, never a blocking prompt. RAG, Research, and a new Vertex edge-AI page (camera + stream + process) each route from `agentSurface`.
- **Routines page** (`showRoutinesPage`): simple recurring tasks (daily/weekly ingest) that need no dedicated agent app. Scalable, editable cards that play image, video, and music with words. Local store now; real scheduling ties to the orchestrator next.
- **Methodology skills** in `data/skills/`: `build-recon`, `cortex-agent-design`, `agent-window-builder`, `verify-no-fabrication`, `coop-editing`, `web-research`, `routine-design`. These capture how to research, design an agent, build an agent window, and verify without fabrication, so the Cortex engine can turn a few-shot prompt into a working agent or app.
- **Cortex home** trimmed: fewer, shorter suggestion chips that build the agent on click; "vault" wording is now "memory storage"; compact chrome on short viewports.

### Routines and skills — next
- Wire routine cadence to the orchestrator so daily/weekly routines actually run and ingest.
- A "create agent in Cortex" flow that reads the `cortex-agent-design` skill and scaffolds tools + prompt + surface from one prompt.
- Vertex streaming backbone (Kafka to PyFlink) and an MJPEG/WebSocket live endpoint on the QC service.

## Explicit deferrals (see `NEXT_UPDATE.md`)

- Full online Personal AI without BYOK (until Stripe live)
- Bundling Netie Cortex into the EXE
- Vector RAG / Qdrant / Mem0 cloud

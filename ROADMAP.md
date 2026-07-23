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

## Explicit deferrals (see `NEXT_UPDATE.md`)

- Full online Personal AI without BYOK (until Stripe live)
- Bundling Netie Cortex into the EXE
- Vector RAG / Qdrant / Mem0 cloud

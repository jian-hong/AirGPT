# AirGPT business / company platform readiness

Local-first product with optional cloud BYOK. Strong GPU/RAM host serves;
phones and weak PCs join the same chat over LAN or tunnel.

## Product surfaces (in-app)

| Surface | Status | Notes |
|---------|--------|-------|
| Chat + projects | Live | AirGPT UI |
| **Hub (Coherent Access)** | Live | Host graph, team codes, QR share, per-peer ACL |
| Cortex agents + audit | Live | Soft-fail DMS sidecar |
| Model Marketplace | Live | Fit-gated HF catalog, install/serve bind |
| Hosting panel | Live | vLLM / Colibri base URL health |
| Usage panel | Live | Local token ledger (personal) |
| MemPalace-style wings | Live | `data/vault/{project}/rooms/{topic}/` |
| Billing & invoices UI | Stub / roadmap | Mirror Cursor Spending/Usage patterns |
| Admin CRM | Partial | `admin.html` + control plane |
| Company marketing site | Live | Merged into netie.ai/airgpt — see `docs/netie-product-architecture.md` |

## Inference stack

1. **Cortex** orchestrates — never replaced by Open WebUI / OpenClaw.
2. **vLLM** — primary GPU OpenAI `/v1` (FP8/INT8 KV). RTX 4070 (~12GB): 7B–8B (+ tight 14B AWQ).
3. **Colibri** — optional disk MoE (`third_party/colibri`). GLM-5.2 ~370GB disk + ~25GB RAM. `scripts/colibri_prepare.ps1`.
4. **KV compression** — prefer engine-side (vLLM quant / Colibri MLA cache). Research: RotorQuant, SpectralQuant, KVTC, AWQ. Do not reimplement TurboQuant in AirGPT.
5. **mem0** — deferred for synced user memory.

## Security & audit (company)

- Local `audit.jsonl` + optional Cortex ledger
- Auth tokens, session ACL (view/post), Business mode hard-block when DMS required
- Sandbox layer: agent tools audited; no silent shell exfil
- Access policy / license SKU gates for tunnel & AI

## Billing / CRM (prepare)

Personal panel fields (UI already sketches Usage):
- Plan, included usage %, API usage, on-demand toggle (default Disabled)
- Spend chart by model, export CSV later
- Invoices: Stripe hooks exist as stubs in env (`STRIPE_*`)

Admin:
- Members, usage by seat, spend caps, audit verify
- Marketplace allow-list for Business tenants

## API map (engine)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/models/probe` | Hardware + tier |
| GET | `/api/marketplace` | Catalog + fit |
| POST | `/api/marketplace/override` | Declare GPU/RAM |
| POST | `/api/marketplace/install` | Queue install |
| POST | `/api/marketplace/serve` | Bind base URL into env.local |
| GET | `/api/hosting` | vLLM/Colibri health |
| GET | `/api/usage` | Token/spend ledger |
| POST | `/api/usage` | Append usage event |
| POST | `/api/memory/drawer` | Project wing write |

## Host collaboration story

1. Host machine: Marketplace → Install fitting model → Serve (writes `VLLM_BASE_URL` or `COLIBRI_BASE_URL`).
2. Host starts vLLM or `coli serve`.
3. Guests open LAN/tunnel URL (phone / weak PC) — chat only; inference stays on host.
4. If host has ≥25GB RAM + 370GB NVMe, Colibri GLM-5.2 can be the offline frontier path.

## Verify checklist

- [ ] `GET /api/marketplace` returns fit reasons for this PC
- [ ] Declare 4070 override if `nvidia-smi` missing
- [ ] Colibri cloned under `third_party/colibri`
- [ ] `coli_prepare.ps1` without `-DownloadWeights` prints serve recipe
- [ ] Serving binds env and `/api/hosting` flips live when server up
- [ ] Audit events fire on install/serve

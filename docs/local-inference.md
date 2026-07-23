# Local inference backends (Cortex orchestrated)

AirGPT keeps **Cortex** as the product brain (agents, DMS gate, vault memory, UI, audit).
Inference engines are **swappable backends**, never the product surface.

| Layer | Owns | Must not |
|-------|------|----------|
| **Cortex** | Agents, tool policy, vault, DMS gate, usage audit, UI | Leak keys, sidecar secrets, or raw tool dumps |
| **Serve backends** | Token generation only (OpenAI-compatible `/v1`) | Talk to clients or store product state |
| **Cloud BYOK** | Explicit user keys in `env.local` | Appear in agent SSE / logs (`cortex_runtime` redacts) |

In-app: **Marketplace**, **Hosting**, **Usage** under Platform.

```http
GET  /api/models/probe
GET  /api/profile
GET  /api/marketplace          # curated + profile-filtered (not full HF)
POST /api/marketplace/override {"ram_gb":36,"vram_gb":12,"gpu_name":"RTX 4070"}
POST /api/marketplace/install  {"item_id":"qwen2.5-1.5b-gguf"}
POST /api/marketplace/trial    {"item_id":"..."}  # generate → verify → delete
POST /api/marketplace/serve    {"item_id":"..."}
GET  /api/hosting
GET  /api/cortex/isolation
```

## Product posture

- Sell **management + auditable governance** (local-first; cloud access hidden behind policy).
- Guests join over LAN/tunnel; host can require IP approval (`access_policy`).
- Local CoT / tool-calling stays in Cortex; backends only complete tokens.
- Cortex isolation: `CORTEX_LOCAL_ONLY=1` locks cloud; `safe_tool_result` redacts secrets.

## Profile ladder (auto-detect)

| Profile | Hardware | Serving |
|---------|----------|---------|
| `cloud_only` | <8GB RAM / no headroom | BYOK only |
| `cpu_gguf` | No NVIDIA, ≥8GB RAM | llama.cpp / GGUF (current no-GPU laptop) |
| `vllm_small` | ~8–16GB VRAM | AWQ/FP8 7–8B |
| `vllm_mid` | ≥20GB VRAM | Larger instruct |
| `colibri_disk` | ≥25GB RAM + large NVMe | Disk-streamed MoE (optional) |

Marketplace shows **suitable-only** by default. Trial path: download → probe tokens → quality check vs strong model → delete on fail.

## TurboQuant (KV cache — stack with GGUF)

TurboQuant does **not** replace weight quants. Pair Q4_K_M (or similar) GGUF with KV compression for long context on low VRAM:

```text
llama-server -m model.gguf -fa on -c 16384 \
  --cache-type-k turbo3 --cache-type-v turbo3
```

- Best impact: dense models, 4K–32K context, 8–24GB GPUs.
- Track ggml-org/llama.cpp discussion #20969 / turboquant_plus forks until mainline.
- Wire as optional serve flag when GPU host is ready (deferred optimizer in `serve_profile`).

## vLLM (preferred GPU host)

RTX 4070 (~12GB): low-effort 7B–8B AWQ/FP8. Soft-fail to BYOK when offline.
Marketplace → Serve sets `VLLM_BASE_URL` in `env.local`.

## Colibri (optional disk MoE)

Vendored at `third_party/colibri`. ~25GB RAM + ~370GB NVMe to run GLM-class MoE.
Learn from it (stream/cache, soft-fail tiers) — do **not** fork a second product engine.

## Open-source UI learnings (build on, stay light)

| Source | Steal | Skip |
|--------|-------|------|
| Open WebUI | Clean chat + Ollama-style local bind | Heavy plugin zoo |
| LibreChat | Multi-endpoint + token controls | Full ChatGPT clone bloat |
| AnythingLLM | Workspace ↔ docs as DB | Desktop-only path |
| LocalAI | OpenAI-compatible drop-in | Bundle every modality day-one |
| OpenHands / Langflow | Agent/tool UX patterns | Node-editor as default |

AirGPT stays: clipboard + LAN/tunnel + Cortex governance + curated marketplace.

## Memory

`project_wing` drawers: `data/vault/{project}/rooms/{topic}/`

## Business / billing

See [business-platform.md](business-platform.md).

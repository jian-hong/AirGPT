# AirGPT architecture — light product, strong governance

## What we sell

**Auditable management software** for local-first AI: marketplace, hosting, memory,
Cortex agents, usage, and Business safety. Inference engines (vLLM, Colibri, GGUF,
cloud BYOK) are **backends** — swappable. The product value is orchestration +
governance, not shipping a second Open WebUI.

## Learnings we take (without bloating)

| Source | Keep | Skip |
|--------|------|------|
| **Colibri** | Stream what does not fit RAM; soft-fail tiers; never silent precision change; OpenAI serve | Embedding 370GB engine in EXE |
| **vLLM** | PagedAttention, FP8/INT8 KV, `/v1` API | Replacing AirGPT UI |
| **Open WebUI / LibreChat** | Multi-user + clean chat UX cues | Heavy plugin ecosystems as default |
| **AnythingLLM** | Doc → memory workspace idea → our vault wings | Second vector product UI |
| **LocalAI** | Drop-in OpenAI compatibility | Full multimedia stack in-process |
| **OpenHands / Langflow** | Tool-calling / agent patterns | Node editors as P1 |

## Runtime layers

```
UI (index.html)  →  clipdrop API  →  Cortex agents + DMS gate
                                  →  ai_engine provider chain
                                       ├─ local OpenAI (vLLM / GGUF / Colibri)
                                       └─ cloud BYOK (soft-fail)
                                  →  vault / project_wing memory
```

## No-GPU laptop (current)

Profile `cpu_gguf`: Marketplace shows **only suitable** small GGUF models.
Trial: bind serve → generate tokens → optional cloud judge → delete on fail.
Later GPU host: declare override or auto-detect → vLLM / Colibri appear.

## Cortex no-leak

- `cortex_runtime.py`: redact secrets from agent SSE / tool dumps
- Sidecar never receives API keys — only gated text + audit events
- `CORTEX_LOCAL_ONLY=1` in env.local for stricter local posture
- `GET /api/cortex/isolation` for status

## Tool calling (Claude-like direction)

Agent runtime already: vault_read → session_summarize → LLM draft → vault_write,
all audited. Next: expand tool schemas + structured function-call loop when local
GGUF/vLLM supports tools.

## Optimizers

`GET /api/profile` lists recommended optimizers (huggingface_hub, llama-cpp-python,
vllm, autoawq). `POST /api/optimizers/install` defaults to **dry_run**.

## Platform Hub (Coherent Access)

- **Host** = laptop that initialized workspace + serves inference
- **Guest(Team)** = short join code (Teams-style)
- **Guest(QR)** = session share + workspace QR
- Access levels: read-only, read-write, use host AI, use own AI, limited
- Personal: current session roster; Business: audit history + token-by-peer trace
- Module: `hub.py` — peers, join codes, ACL, disconnect events

## Agents IA

- **All Agents** under Agents nav → Cortex page (dispatch, runs, pending)
- **Research** under Agents (not Platform)
- Marketplace meta: LLM | Agents | Skills | Tools & Apps

## Download readiness checklist

1. Auto profile detects laptop
2. Marketplace filters suitable models
3. Install / Serve / Trial paths audited
4. Weak clients join strong host chat via Hub
5. Business docs: `docs/business-platform.md`
6. OSS patterns: `docs/templates-research.md`

## Scaling path (design)

Personal stays SQLite/local (default, untouched). Business scale path:
Postgres + Redis + sqlite-vec→pgvector — see [SCALING_POSTGRES_REDIS.md](SCALING_POSTGRES_REDIS.md).

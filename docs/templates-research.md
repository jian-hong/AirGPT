# OSS template research — steal patterns, do not fork

Updated 2026-07. AirGPT stays a **light orchestration product**; these repos supply UX and architecture cues only.

## Template matrix

| Repo | Steal for AirGPT | Skip |
|------|------------------|------|
| [LibreChat](https://github.com/danny-avila/LibreChat) | Agents + MCP, usage tracking, team auth, conversation branching | MongoDB + MeiliSearch stack |
| [Open WebUI](https://github.com/open-webui/open-webui) | Multi-user join UX, model picker polish, Pipelines middleware | Plugin zoo / replace our UI |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | Workspace/doc → vault wings, desktop→self-host path | Second vector product UI |
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) | Agent dispatch, tool loop, human approve gates | Full IDE agent as P1 |
| [LocalAI](https://github.com/mudler/LocalAI) | OpenAI drop-in serve compatibility | Multimedia in-process |
| [LobeChat](https://github.com/lobehub/lobe-chat) | Marketplace meta-category UX | Heavy plugin ecosystem |
| Colibri / vLLM / Netie Cortex | Runtime backends only (already in tree) | Embed engines in EXE |

## AirGPT-specific surfaces (this sprint)

| Surface | Pattern source | Our implementation |
|---------|----------------|-------------------|
| **Hub** | LibreChat team join + Open WebUI device roster | `hub.py` + Platform Hub page |
| **All Agents** | OpenHands dispatch | Cortex page + agent store |
| **Marketplace meta** | LobeChat category tabs | LLM / Agents / Skills / Tools & Apps |
| **Memory wings** | AnythingLLM workspaces | `memory_index.py` + vault rooms |
| **OpenIDE** | Cursor / OpenHands FS tools | Monaco + path jail + approve writes |

## Deploy-ready references (clone for patterns, not vendoring)

- **Chat + agents:** `danny-avila/LibreChat` — docker-compose quick start
- **Local models:** `open-webui/open-webui` — single-container Ollama front door
- **Doc RAG:** `Mintplex-Labs/anything-llm` — workspace + LanceDB
- **Code agents:** `All-Hands-AI/OpenHands` — tool execution loop
- **OpenAI shim:** `mudler/LocalAI` — drop-in `/v1`
- **Netie stack:** `Netie-AI/Cortex` (dms-v2 sidecar), `Netie-AI/OpenVault`, `Netie-AI/Vertex`

## Explicit deferrals

See `NEXT_UPDATE.md`: Stripe, hosted Personal AI, Qdrant/mem0 cloud, Cortex-in-EXE.

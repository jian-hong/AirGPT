# Prompt layers — Context engineering for OpenIDE agents

OpenIDE agent runs assemble context in **layers**, not one flat prompt dump.
This is the S5 contract: *smallest high-signal token set* under an attention budget
([Anthropic — Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)).

## Layer order (stable → volatile)

| Layer | Source | Notes |
|-------|--------|-------|
| **Instructions** | `.airgpt/rules.md` or `AGENTS.md` + skill pack | Right altitude: concrete heuristics, not brittle if-else or vague vibes |
| **Tools** | `agent_tools.tool_schemas` — minimal viable set | Prefer lean schemas; avoid overlapping tools |
| **Examples** | (optional) few canonical shots | Not a laundry list of edge cases |
| **State** | Git fingerprint (`branch` / `head` / dirty) | Cheap workspace orientation |
| **Memory** | `memory_index` carry pack + `.airgpt/NOTES.md` | Notes live *outside* the window and are re-injected |
| **Retrieval** | Vault / web snippets, `@file` mentions | Prefer JIT identifiers when possible |
| **Messages** | Tool-loop history | Compacted first (tool-result clearing + head summary) |

Rendered with tagged sections (`<instructions>`, `<tool_guidance>`, …) by
`context_engineering.assemble_context`.

## Code map

| Piece | Path |
|-------|------|
| Local assembler | `D:\AirGPT\context_engineering\` |
| Agent wiring | `D:\AirGPT\agent_runtime.py` (`_assemble_agent_prompt`) |
| Cortex engine (canonical) | `D:\Cortex\CortexOS\context_engineering\` |
| Cortex HTTP | `POST /api/context/assemble` · `/compact` · `/notes` |
| Ponytail | Uses assembler for warehouse prefetch budgets |
| Engine optimizer flag | `context_engineering` in `CortexOS/engine/registry.py` |

## Long-horizon techniques

1. **Compaction** — when blocks exceed ~5k chars, clear stale tool results and collapse the head.
2. **Structured notes** — deep runs append a short summary to `.airgpt/NOTES.md`.
3. **Sub-agents** — Deep mode ≤2 children; each returns a distilled result into the parent loop (isolation of search context).

## Rules of thumb

- Treat context as a **finite attention budget**, not infinite storage.
- Prefetch only hot state (fingerprint, NOTES); load file bodies via tools / `@mentions`.
- After tool calls, feed **lean** results back (ok / path / preview / error) — never full file bodies.

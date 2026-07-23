# Claude Code — Latest Features (mid-2026)

**Research date:** 2026-07-19 · **CLI window:** ≈v2.1.195 → v2.1.212  
**Sources:** [code.claude.com/docs](https://code.claude.com/docs), weekly digests · synthesized by [Claude Code research](b831f8a2-fd5b-4df2-a283-920854a2686d)

## Six primitives

| Primitive | Role | AirGPT / Cortex analogue |
|-----------|------|---------------------------|
| **CLAUDE.md** | Project memory | `AGENTS.md` + vault + Netie Memory Protocol |
| **Skills** (`SKILL.md`) | Reusable procedures; slash + auto-invoke | Marketplace Skills + skill packs |
| **Subagents** | Isolated context; background by default (≥2.1.198) | Cursor Task + Cortex agents |
| **Hooks** | Deterministic lifecycle (PreToolUse = policy) | audit gates, approve_write |
| **Plugins** | Bundle skills + hooks + MCP | Marketplace Tools & Apps |
| **MCP** | External tools; ToolSearch lazy schemas | planned Cortex MCP client UI |

## Orchestration surfaces

| Approach | Coordination | Use |
|----------|--------------|-----|
| Subagents | Hub-and-spoke in one session | Side research |
| Agent view (`claude agents`) | Many full background sessions | Parallel bugs/PRs |
| Agent teams | Lead + teammates (experimental) | Debate / collab |
| Dynamic workflows | JS orchestration (research preview) | Large audits |

Also: worktrees, `/batch` → N PRs, Artifacts (live MCP connectors ≥2.1.209), Chrome GA, Sonnet 5 default.

## Cursor vs Claude (for hub UX)

- **Cursor:** tiled Agents Window + in-IDE canvases.
- **Claude Desktop:** server dropdown + `autoPort` + shareable artifacts.
- **AirGPT blend:** sessions sidebar + press-to-activate rails (`apps_registry.json`) + research/canvas panels — not chat walls.

## Patterns adopted

1. One port per app; activate = idempotent open-or-start.
2. Research in side panels / canvases, not main chat dumps.
3. Background workers; peek vs attach; soft-cap fan-out.
4. Policy in hooks; guidance in skills; isolation in subagents.

## AirGPT invoke analogue (landed)

`invoke_registry.py` is the Cursor/Claude-style hub:

- **Rules** (passive) — `.airgpt/rules.md` or `AGENTS.md`, always injected into Cortex agent system prompts.
- **Skills** (active) — `data/skills/*.md` via `/skill <pack>` (or `/skill-<pack>`); `GET /api/cortex/invoke` catalogs packs + slash + agents.
- **Subagents** — Deep mode `subagent_dispatch` / `/subagent` queues child runs (≤2); SSE `subagent_start` / `subagent_done`. Nested UI cards still open.
- **Cortex engine** — `CortexOS/engine/registry.specs()` exposes `"invoke": ["rules","skills","slash","subagents"]` (soft; local load never requires CortexOS online).

## Docs

- https://code.claude.com/docs/en/whats-new · https://code.claude.com/docs/en/sub-agents · https://code.claude.com/docs/en/artifacts · https://code.claude.com/docs/en/mcp

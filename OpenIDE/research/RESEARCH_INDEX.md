# OpenIDE Research Index — Superset + Orca scrape

**Date:** 2026-07-23  
**Goal:** Clone + fully inventory UI/features from peer ADEs, map gaps vs OpenIDE + Cortex, hand unfinished work to Claude Code.

## Clones

| Repo | Path | License | Status |
|------|------|---------|--------|
| [stablyai/orca](https://github.com/stablyai/orca) | `research/orca/` | **MIT** | Full clone OK (~9814 files) |
| [superset-sh/superset](https://github.com/superset-sh/superset) | `research/superset/` | **Elastic License 2.0** | Full clone OK after `core.longpaths` (~6331 files) |

### License law (do not violate)

- **Orca (MIT):** May study, adapt, reimplement, and attribute. Prefer clean reimplementation of protocols into OpenIDE/AirGPT branding.
- **Superset (ELv2):** Research + UI/UX *behavior* inspiration only. Do **not** copy substantial source, do **not** rehost as managed service with their feature set, do **not** strip notices. Reimplement patterns from scratch under AirGPT/OpenIDE.

## Companion docs (this folder)

| File | Purpose |
|------|---------|
| `SCRAP_ORCA.md` | Orca feature/UI/architecture inventory + mobile pairing (summary) |
| `SCRAP_SUPERSET.md` | Superset feature/UI/architecture inventory (summary) |
| `GAP_OPENIDE_CORTEX.md` | What OpenIDE + `D:\Cortex` already have vs missing (summary) |
| `CLAUDE_CODE_HANDOFF.md` | Prioritized unimplemented backlog for Claude Code |
| `SUBAGENT_SCRAP_ORCA_FULL.md` | Full Orca explore dump (pairing, RPC allowlist, settings IA) |
| `SUBAGENT_GAP_OPENIDE_CORTEX.md` | Full OpenIDE+Cortex gap dump (APIs, serial orchestrator truth) |
| `SUBAGENT_SCRAP_SUPERSET_FULL.md` | Full Superset explore dump (when subagent finishes) |

## Critical truth from gap scrape

- OpenIDE agent brain today = **AirGPT in-process** (`agent_runtime` + serial `cortex_orchestrator`), **not** `D:\Cortex` tool loop.
- `D:\Cortex` = CortexOS sidecar (soft-fail `:8010`) for DMS/engine — must **wire** OpenIDE→Cortex for “run native Cortex at insane speed.”
- OpenIDE APIs are **host-only** — phone cannot drive IDE until capability-token remote unlock.
- Terminal is allowlisted exec, **not** real PTY/splits.
- Plan/Debug/Multitask UI modes are mostly **thinking-mode aliases**, not true parallel fleet.

## Product north star (user intent)

1. **OpenIDE main job** = run native **Netie Cortex** (`D:\Cortex`) at high speed + synchrony (parallel agents / worktrees like Orca).
2. **Become the next Orca** = parallel ADE: worktrees, agent fleet, terminal splits, mobile remote steer, settings depth.
3. **Phone remote control** = OpenIDE host + companion app (or Orca-compatible pairing host) so phone can connect/control/improve the IDE.
4. **Window logic** = one logical window per app/repo context; easy navigate; open new window / open in repo; IDE sync across surfaces.
5. **Cursor Agent + Claude Code parity** = composer, agent modes, Rules/Skills/Subagents, Settings/Preferences, agent timeline.

## Subagents

| Agent | Status | Output |
|-------|--------|--------|
| [OpenIDE+Cortex map](1553fe22-5b95-4bed-97c0-5db8c5118dea) | Done | `SUBAGENT_GAP_OPENIDE_CORTEX.md` |
| [Orca scrape](2b159c0f-e91e-490f-b5b0-3c510ef5a72c) | Done | `SUBAGENT_SCRAP_ORCA_FULL.md` |
| [Superset scrape](4ca383f2-8c3a-4fb5-bf45-55c2564bfad6) | Done | `SUBAGENT_SCRAP_SUPERSET_FULL.md` |

All three scrapes complete. Claude Code entry: `CLAUDE_CODE_HANDOFF.md`.

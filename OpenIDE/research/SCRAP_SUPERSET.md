# SCRAP — Superset (superset-sh/superset)

**Clone:** `D:\AirGPT\OpenIDE\research\superset`  
**License:** **Elastic License 2.0** — behavior inspiration only; no substantial code copy into OpenIDE product.  
**Tagline:** Code Editor for the AI Agents Era — orchestrate Claude Code / Codex / CLI agents in parallel worktrees.

---

## 1. Product summary

Bun + Turbo monorepo:

| App / package | Role |
|---------------|------|
| `apps/desktop` | Electron desktop ADE (TanStack routes, huge renderer) |
| `apps/mobile` | iOS companion (AGENTS.md: iOS-only for now) |
| `apps/relay` | Remote reachability |
| `apps/api` / `apps/web` / `apps/admin` / `apps/marketing` / `apps/docs` | Cloud/org/docs surfaces |
| `apps/streams` / `electric-proxy` | Live sync |
| `packages/host-service` | Local host daemon |
| `packages/pty-daemon` | Terminal daemon |
| `packages/panes` | Pane layout model |
| `packages/chat` | Agent chat / slash commands |
| `packages/session-protocol` | Session wire protocol |
| `packages/workspace-fs` / `workspace-client` | Workspace FS |
| `packages/port-scanner` | Per-worktree ports |
| `packages/mcp` / `mcp-v2` | MCP |
| `packages/sdk` / `cli` | External reach (CLI/SDK/MCP) |

---

## 2. Feature wall (README)

| Feature | Behavior to mirror (reimplement) |
|---------|----------------------------------|
| **Parallel Workspaces** | 10+ agents, each worktree+branch+terminal+env; compare/merge |
| **Agent Monitoring** | Sidebar status, completion chimes, dock badges on attention |
| **Built-in Terminal** | Tabs, infinite splits, presets, persistent sessions; ⌘I rich prompt + @files |
| **Built-in Diff Viewer** | Inspect/comment/edit agent diffs; commit/push |
| **In-App Browser & Ports** | Preview per worktree; auto port detect |
| **Automations** | Scheduled agent sessions |
| **Remote Workspaces** | Connect other machines; desktop/CLI/phone; wake host command |
| **Command Palette** | Jump workspace/action/setting |
| **Open-in-editor handoff** | One-click to external editor/terminal |
| **CLI / SDK / MCP reach** | Same workspaces from outside the GUI |

---

## 3. Desktop UI map (settings + dashboard)

### Settings routes (`apps/desktop/.../routes/_authenticated/settings/`)

account, agents, api-keys, appearance, behavior, billing, experimental, git, hooks, hosts, integrations, keyboard, links, members, models, organization, permissions, presets, project(s), ringtones, security, team(s), terminal, v2-project, …

### Dashboard routes (`.../_authenticated/_dashboard/`)

automations, project, tasks, workspace(s), v2-workspace(s), …

### Agent UX patterns (from AGENTS.md)

- `ask_user` tool → interactive overlay (never plain-text questions)
- Shared `.agents/commands` + `.agents/skills` as source of truth across Claude/Codex/Cursor/OpenCode
- Workspace = git worktree isolation (not VS Code multi-root metaphor)

---

## 4. Remote + mobile

- Remote hosts/members in org settings (hosts UI)
- Mobile iOS app reaches workspaces via relay/host-service
- Wake offline hosts with custom command
- OpenIDE should expose: **Host Service** on AirGPT LAN + optional relay, **phone app** listing Cortex agent runs

ELv2 note: do not fork/rebrand Superset as our hosted product; implement our own host-service inspired by the *shape*.

---

## 5. Window / single-instance lessons

From CDP verification rules in AGENTS.md:

- Multiple desktop instances can diverge — always target correct worktree/renderer
- Pane/file switch + remount lifecycle matter
- OpenIDE should: bind one Electron/browser window per workspace root; focus-on-open; sync Open Tabs across Agents|IDE panes

---

## 6. Scrap checklist → OpenIDE

### P0

1. Worktree-per-agent isolation model (match Orca P0)
2. Agent monitoring chrome (status, chimes/toasts, badge)
3. Rich composer (@file, multiline, modes Ask/Agent/Plan)
4. Diff viewer that is a first-class pane (not only git summary)

### P1

5. Terminal tabs/splits/presets + session persistence
6. Port scanner + preview browser per worktree
7. Full Settings IA (mirror categories above under OpenIDE branding)
8. Command palette
9. Remote host + phone reach (AirGPT wifi / P2P already partial)

### P2

10. Automations
11. Org/teams/billing-like account surfaces (only if multi-user Netie needs them)
12. Hooks / presets / ringtones polish
13. MCP v2 + SDK external control of OpenIDE workspaces

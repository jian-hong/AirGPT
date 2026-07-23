# Superset Research Scrape — OpenIDE Learning Inventory

**Source:** `D:\AirGPT\OpenIDE\research\superset` (clone of https://github.com/superset-sh/superset)  
**License:** Elastic License 2.0 (ELv2) — conceptual port only; do not copy assets/code.  
**Scope:** Research only.

---

## 1. Product summary

**Superset** = “The Code Editor for AI Agents.”

- Orchestrates CLI coding agents (Claude Code, Codex, Cursor Agent, Amp, Gemini, OpenCode, Pi, Copilot, Mistral Vibe, Kimi, Droid, Polygraph, Mastracode, + custom) across **isolated git worktrees**.
- Surfaces: **Desktop (Electron)**, **CLI**, **TypeScript SDK** (`@superset_sh/sdk`), **MCP server**, **iOS mobile** (in progress), **relay** for remote hosts.
- Stack: **Bun + Turbo monorepo**, Electron + React + Vite + Tailwind, tRPC, Drizzle, Neon Postgres + **Electric** sync, Hono services.
- Model: **local-first host-service** owns files/terminals/ports/agents; cloud API + Electric sync org metadata; **relay** tunnels remote clients to host-service.
- OS today: **macOS**; Windows/Linux untested.

**Apps:** `apps/desktop`, `apps/mobile`, `apps/relay`, `apps/api`, `apps/web`, `apps/electric-proxy`, `apps/docs`, `apps/marketing`, `apps/admin`, `apps/streams`, `apps/discord-triage`.

**Key packages:** `host-service`, `host-client`, `pty-daemon`, `panes`, `session-protocol`, `workspace-client`, `workspace-fs`, `port-scanner`, `local-db`, `db`, `shared`, `chat`, `mcp`/`mcp-v2`, `sdk`, `cli`, `auth`, `trpc`, `ui`.

---

## 2. Feature wall (README + docs) → how it works + source paths

| Feature | How it works | Key paths |
|--------|----------------|-----------|
| **Parallel workspaces** | One workspace ≈ one branch/worktree; own dir, terminals, ports. Create from new/existing branch, PR, or import worktrees. ⌘N modal. | `packages/host-service/src/workspaces/`, `.../workspace-creation/`, `apps/desktop/.../NewWorkspaceModal/`, `.../DashboardNewWorkspaceModal/`, `.../_dashboard/v2-workspaces/`, docs: `workspaces.mdx` |
| **Agent monitoring** | Sidebar working indicators, completion chimes, dock badges; V2 optional inline agent rows. | `apps/desktop/.../v2-notifications/`, `WorkspaceRunIndicator/`, `StatusIndicator/`, `main/lib/notifications/`, Settings → Ringtones |
| **Built-in terminal** | Tabs, infinite splits, presets, PTY daemon persistence across restarts; ⌘I rich prompt (@files). Env: `SUPERSET_*`. | `packages/pty-daemon/`, `host-service/src/terminal/`, `apps/desktop/.../TerminalPane/`, `screens/.../TabsContent/Terminal/`, Settings → Terminal |
| **Diff viewer** | Stage/commit/push/PR; split/unified; focus mode; line comments → agent; edit-in-place. | `.../DiffPane/`, `.../ChangesContent/`, `.../ChangesView/`, `host-service` git/PR routers, docs: `diff-viewer.mdx` |
| **In-app browser & ports** | Per-workspace port scan; open in browser pane; DevTools pane. Remote ports via host. | `packages/port-scanner/`, `host-service/src/ports/`, `.../BrowserPane/`, `.../PortsList/`, `DashboardSidebarPortsList/`, docs: `browser.mdx`, `ports.mdx` |
| **Automations** | Cron/RRule scheduled agent runs on a host+project; creates workspace or attaches; CLI too. | `apps/desktop/.../_dashboard/automations/`, cloud/API automation tables, docs: `automations.mdx` |
| **Remote workspaces** | Host registers with relay; clients filter Device → remote host; full UX proxied. | `apps/relay/`, `host-service/src/tunnel/`, Settings → Security/Hosts, docs: `remote-workspaces.mdx` |
| **Command palette** | Search workspaces/actions/settings/open-in. | `apps/desktop/src/renderer/commandPalette/` (modules: actions, addProject, navigation, openIn, settings, workspace) |
| **Model picker & custom agents** | Launch-time model/effort; Settings → Agents; custom agent icons. | `packages/shared/src/builtin-terminal-agents.ts`, `agent-*.ts`, Settings → Agents/Models |
| **Setup/teardown scripts** | `.superset/config.json` setup/teardown/run per project/worktree. | Project settings `V2ScriptsEditor`, docs: `setup-teardown-scripts.mdx` |
| **Terminal presets** | Saved agent/shell layouts; one-keystroke. | Settings → Terminal presets, `V2PresetsBar`, docs: `terminal-presets.mdx` |
| **Slack & Linear** | Spin workspaces from issues/messages. | Settings → Integrations, docs: `use-with-linear.mdx`, Tasks routes |
| **Open in IDE** | ⌘O → Cursor/VS Code/Zed/Windsurf/JetBrains/etc. | `OpenInButton/`, `useOpenInExternalEditor`, docs: `use-with-ide.mdx` |
| **Custom themes** | Import theme JSON. | Settings → Appearance, docs: `custom-themes.mdx` |
| **Keyboard shortcuts** | Fully remappable (⌘/). | Settings → Keyboard, `renderer/hotkeys/` |
| **BYO providers** | OpenRouter, Bedrock, Vertex, AI Gateway. | Settings → Models/Integrations, docs: `providers.mdx` |
| **Built-in chat** | Chat pane; tool approvals; plan review; ACP sessions. | `packages/chat/`, `session-protocol/`, `.../ChatPane/`, ACP in host-service |
| **CLI / SDK / MCP** | Same host/cloud surface programmatically. | `packages/cli/`, `packages/sdk/`, `packages/mcp*`, docs under `cli/`, `sdk/`, `mcp.mdx` |
| **Mobile (iOS)** | Monitor/chat/diff/files against remote hosts via Electric + relay. | `apps/mobile/` (Expo), iOS-only per AGENTS.md |

---

## 3. Architecture map

```
┌─────────────┐   JWT    ┌──────────────┐  WS tunnel  ┌─────────────────┐
│ Desktop /   │─────────▶│ apps/relay   │◀────────────│ host-service    │
│ Mobile / CLI│  HTTP    │ (Fly)        │  proxy HTTP │ (per org, local)│
└──────┬──────┘          └──────┬───────┘             └────────┬────────┘
       │                        │                              │
       │ Electric (org data)    │ directory (Redis)            │ worktrees,
       ▼                        ▼                              │ PTY, ports,
┌──────────────┐         ┌──────────────┐                      │ git, agents
│ Neon + API   │◀────────│electric-proxy│                      ▼
│ apps/api     │         │ (CF Worker)  │              git worktree dirs
└──────────────┘         └──────────────┘
```

### Desktop renderer routes (TanStack Router)

| Route group | Paths |
|-------------|--------|
| Auth | `/sign-in`, `/create-organization` |
| Onboarding | `/_authenticated/onboarding`, `.../project` |
| Dashboard | `/_authenticated/_dashboard/...` — `workspaces`, `workspace/$id` (v1), `v2-workspaces`, `v2-workspace/$id`, `tasks`, `tasks/$taskId`, `tasks/pr/$prNumber`, `tasks/issue/$issueNumber`, `project/$projectId`, `automations`, `automations/$automationId` |
| Settings | `/_authenticated/settings/...` (see §6–7) |

V2 workspace is the primary product surface: pane layout via `@superset/panes`, host tRPC via `WorkspaceTrpcProvider` / `@superset/workspace-client`.

### Host-service (`packages/host-service`)

Local Hono + tRPC + SQLite; **no Electron coupling** (tested). Owns:

- Workspaces / worktree create-delete-cleanup  
- Terminal + PTY daemon sessions  
- Ports, filesystem, git, GitHub/PR  
- Agents / terminal-agent bindings / ACP sessions / chat runtime  
- Tunnel client → relay  
- Event bus / git watcher / workers  

Routers under `packages/host-service/src/trpc/router/` (workspace*, terminal*, agents, ports, filesystem, git, github, chat, acp-sessions, settings, host, …).

Desktop starts host-services for known orgs at boot (`apps/desktop/src/main/index.ts`).

### Worktree model

- Project = registered repo on a host.  
- Workspace = isolated worktree + branch metadata (local-db + host db + optional cloud sync).  
- Scripts from `.superset/config.json`.  
- Branch prefix / worktree base dir at user, host, and project levels.

### Agent adapters

Not separate process adapters — **terminal agent definitions** + launch command builders:

- Catalog: `packages/shared/src/builtin-terminal-agents.ts` (+ `agent-command.ts`, `agent-launch*.ts`, `agent-settings.ts`, `agent-models.ts`, `agent-custom.ts`)  
- Host persistence/store: `packages/host-service/src/terminal-agents/`  
- Chat/ACP: `packages/chat`, `packages/session-protocol`, host `runtime/acp-sessions`, `runtime/chat`  
- Desktop orchestration: `renderer/lib/agent-session-orchestrator/`

### Electric / sync

- Cloud tables (orgs, projects, hosts, chat sessions, automations, …) via Neon.  
- `apps/electric-proxy`: JWT-gated Electric shape proxy with org `WHERE` clauses.  
- Desktop/mobile: TanStack DB collections + `useLiveQuery` (cache-first rule in AGENTS.md).  
- Host-local state stays on the machine; relay for live host ops.

---

## 4. Remote + mobile

### How a phone / other client reaches workspaces

1. User signs into Superset org (OAuth / API key).  
2. A machine runs **host-service** (`superset start --daemon` or desktop Security toggle).  
3. Host opens **WSS `/tunnel?hostId&token`** to relay; relay stores directory ownership and proxies `/hosts/:routingKey/*` → host localhost.  
4. Clients call host via **`@superset/host-client`** `createHostTransport({ getRelayUrl, getToken })` → `GET/POST …/hosts/:routingKey/trpc/...` and WS streams with token query param.  
5. Mobile also uses Electric collections for list/metadata; workspace ops go through host when online.

Auth: JWT verified against auth JWKS (`apps/relay/src/auth.ts`); host access checked (`access.ts`). Headless: `SUPERSET_API_KEY` + `--org`.

Pairing/access grant: **Settings → Hosts → Add member** (not a QR pairing code — org membership + host ACL).

Mobile capabilities (`apps/mobile`):

- Home: host/project filter, session list, new chat, attachments  
- Workspace: index, chat (+ ACP chat), diff, files-changed, file, jump-to-file, commits, line-comment, finish-review  
- Settings: account, organization, hosts, billing  
- iOS-only Expo app

### Extension points for OpenIDE as a third-party IDE host

Conceptual compatibility (no ELv2 copy):

| Layer | What to implement |
|-------|-------------------|
| **Host HTTP API** | Local service exposing workspace/terminal/port/agent ops; bind `127.0.0.1`; optional relay registration |
| **Transport** | Same shape as `HostClientConfig`: relay base URL + JWT + `/hosts/:id/trpc/*` + stream URLs |
| **Session protocol** | Message envelopes for chat/ACP streaming (`session-protocol`) |
| **Auth** | Org JWT / API keys; host member ACL |
| **Worktree contract** | Create/list/delete worktrees; expose cwd + env to agents |
| **CLI/SDK/MCP** | Optional thin clients talking to the same host |

OpenIDE can either (a) speak a **compatible host+relay protocol** so Superset mobile/CLI could target it, or (b) **mirror the product behaviors** with its own protocol — prefer (b) for license safety unless intentionally interop’ing.

---

## 5. Window / multi-window / single-instance

| Pattern | Behavior | Paths |
|---------|----------|--------|
| **Single instance** | `app.requestSingleInstanceLock()`; secondary exits 0 | `apps/desktop/src/main/index.ts`, `lib/electron-app/factories/app/instance.ts` |
| **Second-instance** | Focus main window; process deep-link argv | `main/index.ts` `second-instance` → `focusMainWindow()` |
| **One BrowserWindow** | `currentWindow` singleton; IPC handler singleton (macOS reopen) | `main/windows/main.ts` |
| **Window state** | Persist bounds; force-repaint hack for GPU | `main/lib/window-state` |
| **Protocol** | `setAsDefaultProtocolClient`; custom `superset-icon` / `superset-font` | `main/index.ts` |
| **Open-in-editor** | Shell out to preferred editor (not new Electron windows) | OpenIn components / `useOpenInExternalEditor` |
| **No duplicate workspace windows** | Workspaces are **tabs/routes inside one window**, not separate Electron windows; focus existing terminal/chat panes instead of duplicating | `focusTerminalPane`, tab store dedupe |
| **Dev multi-instance** | `setup.local.sh` distinct app identity/ports so installed + worktree builds coexist | root README / DEVELOPMENT.md |

---

## 6. Settings / Preferences taxonomy

**Store sections** (`renderer/stores/settings-state.ts`):  
`account` | `organization` | `teams` | `appearance` | `ringtones` | `keyboard` | `behavior` | `git` | `agents` | `terminal` | `links` | `models` | `experimental` | `integrations` | `billing` | `apikeys` | `permissions` | `security` | `project` | `hosts`

**Folders under** `apps/desktop/src/renderer/routes/_authenticated/settings/`:

`account`, `agents`, `api-keys`, `appearance`, `behavior`, `billing`, `components`, `experimental`, `git`, `hooks`, `hosts`, `integrations`, `keyboard`, `links`, `members`, `models`, `organization`, `permissions`, `presets`, `project`, `projects`, `ringtones`, `security`, `team`, `teams`, `terminal`, `utils`, `v2-project`

**Searchable setting items** (from `settings-search.ts` — full list):

- **Account:** Profile, Sign Out  
- **Organization:** Logo, Name, Slug, ID, Team Members, Invite, Pending Invitations  
- **Teams:** Teams list (+ team detail routes)  
- **Appearance:** Theme, Markdown style, Custom themes, Editor font, Terminal font  
- **Ringtones:** Notification sound  
- **Keyboard:** Shortcuts  
- **Behavior:** Confirm quit, File open mode, Resource monitor, Open links in-app  
- **Git:** Delete local branch on remove, Branch prefix, Worktree location  
- **Agents:** Enabled agents, Commands, Task prompt templates  
- **Terminal:** Presets, Quick-add templates, Terminal daemon, Background memory, Link behavior  
- **Links:** File / URL / Sidebar file rows / Ports click behavior  
- **Models:** Anthropic auth, OpenAI auth  
- **Experimental:** Superset V2 toggle, V1→V2 migration, Inline workspace ports, Workspace agents  
- **Integrations:** Linear, GitHub, Slack  
- **Billing:** Current plan, All plans, Usage limits  
- **Project:** Name, Path, Scripts, Branch prefix, Worktree location, Import worktrees, Env vars  
- **API keys:** List, Generate  
- **Permissions:** Full Disk Access, Accessibility, Microphone, Automation (Apple Events), Local Network  
- **Security:** Allow remote via relay  
- **Hosts:** Members, Worktree location, Grant access, (delete host / related)

---

## 7. UI component / route inventory

### Dashboard (`_authenticated/_dashboard`)

| Area | Role | Paths |
|------|------|--------|
| Layout / TopBar / Sidebar | Device filter, nav, ports list | `layout.tsx`, `components/DashboardSidebar/`, `TopBar/` |
| Workspaces list (v1/v2) | Browse/filter workspaces | `workspaces/`, `v2-workspaces/` |
| Workspace detail v1 | Legacy workspace UX | `workspace/$workspaceId/` + `screens/main/.../WorkspaceView/` |
| Workspace detail v2 | Pane IDE | `v2-workspace/$workspaceId/` |
| Tasks | Linear/GitHub task board | `tasks/` |
| Automations | Schedule CRUD + runs | `automations/` |
| Project | Project dashboard | `project/$projectId/` |
| Modals | New workspace, add repo, template gallery, V1 import | `components/DashboardNewWorkspaceModal/`, `AddRepositoryModals/`, `TemplateGalleryModal/`, `V1ImportModal/` |

### V2 workspace panes (`usePaneRegistry/components/`)

| Pane | Data | Role |
|------|------|------|
| TerminalPane | `terminalId` | Agent/shell PTY |
| ChatPane | `sessionId` + launchConfig | Built-in chat |
| BrowserPane | `url` | In-app preview |
| FilePane | path + editor/diff/preview | File edit/view |
| DiffPane | path + focus | Review |
| CommentPane | PR comment thread | Review comments |
| DevtoolsPane | target browser pane | Webview DevTools |

Sidebar tabs: Files, Changes/Review (+ PR actions). Supporting: presets bar, background terminals, run button, notification indicators, empty/offline/host-incompatible states.

### Legacy WorkspaceView (`screens/main/components/`)

`WorkspaceSidebar` (list, ports, sections), `WorkspaceView` → `ContentView` (tabs: Terminal, Chat, Browser, Comment, FileViewer, DevTools), `RightSidebar` (Files + Changes), `WorkspacesListView`, CommandPalette, SettingsButton.

### Command palette modules

`actions`, `addProject`, `navigation`, `openIn`, `settings`, `workspace` — under `renderer/commandPalette/modules/`.

### Mobile routes

- `(home)/` — index, filter, new-chat, attachments  
- `workspace/[id]/` — chat, acp chat, diff, files-changed, file, jump-to-file, commits, line-comment, finish-review  
- `settings/` — account, organization, hosts, billing  

---

## 8. Scrap checklist for OpenIDE (behaviors only)

### P0 — Core agent IDE loop

1. **Worktree-per-task isolation** — create/list/delete workspaces without checkout thrash.  
2. **Parallel agent runs** — multiple workspaces/agents visible with status.  
3. **Persistent terminal sessions** — survive IDE restart (daemon or equivalent).  
4. **Host-service split** — UI ≠ process owner of PTY/git/ports (headless-capable).  
5. **Single-instance Electron** + deep-link focus (no duplicate app instances fighting).  
6. **Agent adapter catalog** — pluggable CLI agents with command/prompt templates.  
7. **Sidebar agent/workspace monitoring** + completion notification sound/badge.  
8. **Diff review in-app** — stage/commit/push/PR without leaving.  
9. **Open-in-external-editor** handoff (Cursor/VS Code/etc.).  
10. **Command palette** for workspace + action jump.

### P1 — Differentiation / multi-surface

11. **Port detection + in-app browser preview** per workspace.  
12. **Pane system** — terminal/chat/diff/browser/file splits & tabs.  
13. **Terminal presets / layout templates**.  
14. **Setup/teardown/run scripts** per project.  
15. **Remote host model** — register machine, ACL members, wake/offline handling.  
16. **Relay-like tunnel** (or SSH equivalent) so phone/other clients reach host.  
17. **Mobile monitoring** — chat + diff + file list against remote host.  
18. **Automations / scheduled agent runs**.  
19. **Settings taxonomy** — agents, terminal, links click-behavior, git/worktree location, permissions, security/expose.  
20. **Integrations** — GitHub PR status in sidebar; Linear/Slack task → workspace.  
21. **MCP + CLI + SDK** surfaces on the same host API.  
22. **Built-in chat** with tool approval / plan review (not only raw TUI).

### P2 — Polish / scale

23. Custom themes, remappable shortcuts, ringtones.  
24. Resource monitor (CPU/RAM per workspace/session).  
25. Inline sidebar ports/agents experimental toggles.  
26. Branch ahead/behind + PR CI hover cards.  
27. Diff focus mode, line comments → agent.  
28. Background terminal parking / memory caps.  
29. Org/teams/hosts/billing multi-tenant UX.  
30. V1→V2-style migration paths if OpenIDE evolves data models.  
31. Provider BYO (Bedrock/Vertex/OpenRouter).  
32. Dev multi-worktree identity (run several IDE builds side-by-side).

---

## Package quick-reference (for OpenIDE mapping)

| Package | Role for OpenIDE |
|---------|------------------|
| `host-service` | Canonical “machine brain” API design |
| `host-client` | How any client (desktop/mobile/node) talks to a host |
| `pty-daemon` | Session persistence design |
| `panes` | Generic split/tab layout engine |
| `session-protocol` | Chat/ACP streaming contract |
| `shared` agent-* | Agent definition / launch semantics |
| `port-scanner` | Dev-server discovery |
| `workspace-client` / `workspace-fs` | Remote FS + workspace RPC |
| `relay` | Multi-device connectivity pattern |
| `electric-proxy` + `local-db`/`db` | Offline-first sync vs host-local truth |

---

**Bottom line for OpenIDE:** Treat Superset as a **behavior reference** for worktree-centric multi-agent orchestration with a **local host-service + optional remote tunnel + sync layer**. Reimplement concepts under OpenIDE’s own license/architecture; do not copy ELv2 source or assets.
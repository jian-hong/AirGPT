# Orca Research Scrape — OpenIDE Learning Inventory

**Source:** `D:\AirGPT\OpenIDE\research\orca` (clone of https://github.com/stablyai/orca)  
**Version observed:** `1.4.151-rc.1` (`package.json`)  
**License:** MIT  
**Scope:** Research only — no code edits.

---

## 1. Product summary

**Orca** is an **Agent Development Environment (ADE)** — marketed as “The AI Orchestrator for 100x builders.” It runs **CLI coding agents** (Codex, Claude Code, OpenCode, Pi, Cursor CLI, Grok, Copilot, and ~30+ others) **side-by-side**, each typically in an **isolated git worktree**, with one desktop surface for terminals, files, review, browser, tasks, and orchestration.

| Surface | What it is |
|--------|------------|
| **Desktop** | Electron app (macOS / Windows / Linux). Main process + preload + React renderer. Packaged via electron-builder. |
| **Mobile companion** | React Native / Expo app (`mobile/`). iOS App Store + TestFlight; Android APK. Pairs to desktop over LAN WebSocket or cloud **Relay**. |
| **Web client** | Bundled static web UI served from the runtime WebSocket server; pairs with `scope: 'runtime'`. |
| **VPS / headless** | `orca serve` — runtime without desktop window; auto-Xvfb on Linux; same WS pairing on port **6768** (docs: `docs/reference/headless-linux-server.md`). |
| **CLI** | `orca` / `orca-ide` (Linux) — worktrees, terminals, browser automation, orchestration, skills, computer-use. |

**Positioning for OpenIDE:** Orca is not a fork of VS Code; it embeds Monaco + xterm + Chromium browser panes and treats **parallel agent worktrees + remote phone control** as the product core.

---

## 2. Feature wall — complete list

### README feature wall (primary)

| Feature | How it works | Key paths |
|--------|----------------|-----------|
| **Mobile Companion** | Phone pairs via QR (`orca://pair?code=…`). Desktop hosts encrypted WebSocket RPC (port 6768 packaged / 6769 dev). Phone lists worktrees, streams terminal output, sends input/follow-ups, gets completion notifications. Modes: LAN (`local-only`) or **Anywhere** via cloud Relay (needs signed-in desktop). | `mobile/`; `src/main/ipc/mobile.ts`; `src/main/runtime/runtime-rpc.ts`; `src/main/runtime/rpc/ws-transport.ts`; `src/renderer/src/components/mobile/`; `src/renderer/src/components/settings/MobilePane.tsx` |
| **Parallel Worktrees** | Fan one prompt across N agents; each agent gets its own git worktree; compare/merge winner. Creation UI + sidebar cards; sleep/activate lifecycle. | `src/main/runtime/rpc/methods/worktree.ts`; `src/renderer/src/components/worktree-creation/`; `src/renderer/src/components/sidebar/`; `src/main/git/` |
| **Terminal Splits** | Ghostty-class xterm + WebGL, infinite splits, scrollback that survives restarts; main-owned PTY state. | `src/main/pty/`; `src/main/ghostty/`; `src/renderer/src/components/terminal/`; `src/renderer/src/components/terminal-pane/`; `docs/terminal-*.md` |
| **Design Mode** | Click UI in embedded Chromium → HTML/CSS + cropped screenshot injected into agent prompt. | `src/main/browser/`; `src/renderer/src/components/browser-pane/`; CLI `browser.*` RPC methods |
| **GitHub & Linear (native)** | In-app PRs/issues/boards; open worktree from task; review without context switch. Also GitLab, Jira, Azure DevOps, Bitbucket, Gitea modules in main. | `src/main/github/`; `src/main/linear/`; `src/main/gitlab/`; `src/main/jira/`; `src/renderer/src/components/TaskPage.tsx`; `src/renderer/src/components/github*`; Linear issue workspace components |
| **SSH Worktrees** | Agents/files/git/terminals on remote hosts; auto-reconnect; port forwarding. Separate from mobile Relay — uses `src/relay` SSH execution relay. | `src/main/ssh/`; `src/relay/` (pty/fs/git handlers); Settings `SshPane` |
| **Annotate AI Diffs** | Line comments on diffs → shipped back to agent; review/edit/commit in-app. | `src/renderer/src/components/diff-comments/`; source-control + review right-sidebar panels |
| **Drag Files to Agents** | Monaco editor + autosave; drag files/images into agent prompts. | `src/renderer/src/components/editor/`; `src/renderer/src/components/right-sidebar/FileExplorer*`; clipboard image upload RPCs |
| **Orca CLI** | Agents script Orca: `worktree create`, `snapshot`, `click`, `fill`, orchestration, skills. Talks to running runtime via discovery files + RPC. | `src/cli/`; `src/cli/specs/`; skills `orca-cli` |

### “Also in the box” (README)

| Feature | How it works | Key paths |
|--------|----------------|-----------|
| **Quick open (Cmd+J)** | Cross-search worktrees, files, agents, commands, settings nav. | `src/renderer/src/components/cmd-j/`; `QuickOpen.tsx`; `WorktreeJumpPalette.tsx` |
| **Account switcher & usage** | Claude/Codex/OpenCode/Grok/etc. multi-account + rate-limit meters; hot-swap. | `src/main/claude-accounts/`; `codex-accounts/`; `*-usage/`; Settings `AccountsPane` |
| **Rich repo previews** | Markdown (TipTap), images, PDFs in workspace. | editor/markdown components; `pdfjs-dist` |
| **Computer Use** | Native OS automation (click/type/apps) via platform natives + RPC. | `native/computer-use-*`; `src/main/computer/`; Settings `ComputerUsePane`; skill `computer-use` |
| **Notifications & unread** | Desktop + mobile push when agent finishes / needs attention; mark unread. | `src/main` notifications; `mobile/src/notifications/`; Settings `NotificationsPane`; RPC `notifications.*` |

### Additional major capabilities (codebase, beyond README wall)

| Feature | How it works | Key paths |
|--------|----------------|-----------|
| **Orchestration** | Multi-agent DAG: task-create, dispatch/inject, ask/reply, gates, worker_done. Experimental flag. | `src/main/runtime/orchestration/`; RPC `orchestration.*`; skill `skills/orchestration`; Settings `OrchestrationPane` |
| **Automations** | Scheduled/triggered agent workflows. | `src/main/automations/`; `AutomationsPage`; RPC `automation.*` |
| **Native Chat** | Non-TUI chat UI with Codex/Claude parity experiments. | `src/main/native-chat/`; `src/renderer/src/components/native-chat/`; RPC `nativeChat.*` |
| **Mobile Emulator** | Android emulator streaming/control for agents. | `src/main/emulator/`; `emulator-pane/`; Settings `MobileEmulatorSettingsPane`; docs `android-emulation*.md` |
| **Floating Workspace** | Global floating terminal/browser/markdown tabs. | `floating-terminal/`; Settings `FloatingWorkspacePane` |
| **WSL / Windows project runtime** | Prefer WSL or native for project shells. | Settings General + Repository panes; `src/main` WSL CLI registration |
| **Ephemeral VMs** | Experimental disposable VM recipes. | Settings `EphemeralVmsPane`; CLI `vm` |
| **Skills system** | Bundled agent skills (CLI guides stubs + full guides served by binary). | `skills/`; `skill-guides/`; `skill-stubs/`; RPC `skills.discover` |
| **AI Vault / session history** | Resume past agent sessions. | `src/main/ai-vault/`; right-sidebar `AiVaultPanel`; RPC `aiVault.*` |
| **Feature Wall / onboarding** | First-run tour + setup checklist. | `feature-wall/`; Settings setup-guide |
| **Dictation / Voice** | On-device STT (sherpa-onnx). | `src/main/speech/`; Settings `VoicePane`; mobile voice settings |
| **Remote Orca Servers** | Pair desktop/web to another `orca serve` runtime (Beta). | Settings `RuntimeEnvironmentsPane` / `servers`; web runtime client |
| **Agent Teams (Claude)** | Tmux-compat + prepareLaunch for agent teams in native panes. | RPC `agentTeams.*` |
| **Source Control AI** | AI commit messages / PR fields; action recipes. | Git settings; `git.generateCommitMessage` etc. |
| **Dashboard popout** | Optional second BrowserWindow for agent dashboard (singleton). | `src/main/window/dashboard-popout-window.ts` |
| **Pet / star-nag / telemetry** | Soft engagement + PostHog telemetry with opt-out. | `pet/`; `star-nag/`; Privacy settings |

---

## 3. Architecture map

```
orca/
├── src/
│   ├── main/          # Electron main: runtime, PTY, agents, SSH, IPC, windows
│   ├── preload/       # contextBridge API (window.api.*)
│   ├── renderer/src/  # React UI (Zustand store, components)
│   ├── relay/         # SSH remote host relay (fs/git/pty over socket) — NOT mobile cloud relay
│   ├── cli/           # orca CLI → runtime RPC
│   ├── shared/        # types, pairing, protocol version, agent catalogs
│   └── types/
├── mobile/            # Expo RN companion (own Metro bundle)
├── native/            # computer-use + macOS notification-status + windows-cli-launcher
├── skills/ + skill-guides/ + skill-stubs/
├── docs/              # mostly internal design notes + headless guide
└── orca.yaml          # THIS REPO’s setup script only (not a host plugin schema)
```

### Process / layers

| Layer | Role |
|-------|------|
| **Main** (`src/main`) | Owns PTYs, worktrees, git, SSH, browser profiles, device registry, E2EE keys, `OrcaRuntimeRpcServer`, Electron windows/tray/menu. Huge domain folders per agent (`claude/`, `codex/`, `opencode/`, `pi/`, …). |
| **Preload** | Thin IPC façade: `mobile:*`, filesystem, settings, pty, etc. (`src/preload/index.ts`, `api-types.ts`). |
| **Renderer** | Single-window SPA: `TopLevelView` switches content; Zustand slices under `src/renderer/src/store/`. |
| **Runtime RPC** | Unified API for CLI, mobile, web, remote servers. Method registry: `src/main/runtime/rpc/methods/`. Transports: Unix socket (local CLI) + WebSocket (remote/mobile/web). |
| **Relay (SSH)** | `src/relay` — remote filesystem/git/pty when workspace host is SSH. |
| **Mobile Relay (cloud)** | `src/main/runtime/relay/` — broker for phone↔desktop when not on LAN (`DesktopRelayService`, invite/resume credentials). |

### How agents are spawned

1. User picks a **TuiAgent** (`src/shared/types.ts` — claude, codex, opencode, pi, cursor, …).
2. Worktree created/activated (`worktree.create` / `worktree.activate`).
3. Terminal tab created; agent launched via **`terminal.createAgentSession` / `terminal.ensureAgentSession`** (host-authority RPC) or local PTY spawn with agent CLI + args from `agent-session-option-catalog` / `agent-session-option-launch.ts`.
4. Detection of running/idle state via **OSC titles** + process recognition (`src/shared/agent-detection.ts`, `agent-process-recognition.ts`).
5. Hooks for Claude/Codex/Cursor install into agent hook endpoints (`src/main/agent-hooks/`, discovery file `agent-hooks/endpoint.env`).

Agents are **not** an internal LLM SDK — they are **external CLIs in PTYs**, orchestrated by Orca.

### IPC & state sync (desktop ↔ mobile)

| Mechanism | Purpose |
|-----------|---------|
| Electron IPC | Renderer ↔ main for local UI (`mobile:getPairingQR`, settings, etc.). |
| WebSocket + E2EE | Phone/web/CLI remote → `OrcaRuntimeRpcServer` (`ws-transport.ts`, `e2ee-channel.ts`, v2 framing). |
| Device registry | Tokens persisted under canonical userData; scopes `mobile` \| `runtime`. |
| Allowlist | Mobile tokens only call `MOBILE_RPC_METHOD_ALLOWLIST` methods (`runtime-rpc.ts`). |
| Streaming | `terminal.subscribe`, `notifications.subscribe`, `session.tabs.subscribe`, `browser.screencast`, `runtime.clientEvents.subscribe`. |
| Capabilities | `status.get` advertises `RUNTIME_CAPABILITIES` + protocol version (`src/shared/protocol-version.ts`). |

---

## 4. Mobile remote control — deep dive

### Connection modes

1. **Local / LAN** — Desktop listens `ws://0.0.0.0:6768` (packaged) or **6769** (dev). QR embeds LAN/Tailscale IP chosen in Settings → Mobile.
2. **Relay / Anywhere** — Pairing offer includes `relay: { directorUrl, cellUrl, inviteToken, … }`. Phone dials cloud cell; desktop maintains broker session (`DesktopRelayService`). Requires signed-in desktop; else UI forces local-only.
3. **Headless serve** — Same WS stack; `orca serve --port 6768 --pairing-address <reachable-ip>`.

### Pairing protocol (exact)

**URL:** `orca://pair?code=<base64url-json>`  
**Schema** (`src/shared/mobile-relay-pairing-offer.ts`):

```ts
{
  v: 2,                    // PAIRING_OFFER_VERSION
  endpoint: string,        // e.g. ws://192.168.x.x:6768
  deviceToken: string,     // bearer credential
  publicKeyB64: string,    // desktop Curve25519 public key (pinned)
  scope?: 'mobile' | 'runtime',
  relay?: {                // optional; mobile-only
    v: 1,
    directorUrl, cellUrl,  // HTTPS origins
    assignmentEpoch,
    relayHostId,           // base64url 16
    inviteToken,           // base64url 43
    inviteExpiresAt,       // ≤ 10 min
    e2eeFraming: 2
  }
}
```

**Desktop minting:** IPC `mobile:getPairingQR` → `createMobilePairingOffer` (scope mobile) or `mobile:getRuntimePairingUrl` (scope runtime + webClientUrl).

**Mobile decode:** `mobile/src/transport/pairing.ts` (mirrors `src/shared/pairing.ts` for Hermes).

### Auth / crypto handshake

1. TCP/WS connect to endpoint.
2. E2EE channel: `awaiting_hello` → key exchange → `e2ee_auth` with `deviceToken` → `ready` (`e2ee-channel.ts`, tweetnacl; v2 key schedule modules).
3. Pre-auth timeout 10s; unpaired auth failures throttle + notify desktop to re-pair.
4. Protocol compat: `RUNTIME_PROTOCOL_VERSION = 3`, mobile `MOBILE_PROTOCOL_VERSION = 3`, min compatible 2. Hard-block UI: `ProtocolBlockScreen.tsx`.

### Exact modules (desktop)

| Concern | Path |
|---------|------|
| IPC pairing UI API | `src/main/ipc/mobile.ts` |
| RPC server + offers | `src/main/runtime/runtime-rpc.ts` |
| WS transport | `src/main/runtime/rpc/ws-transport.ts` |
| E2EE | `src/main/runtime/rpc/e2ee-*.ts`, `mobile-e2ee-v2-*` |
| Device registry | under `src/main/runtime/` (device-registry) |
| Mobile allowlist gate | `MOBILE_RPC_METHOD_ALLOWLIST` in `runtime-rpc.ts` |
| Cloud relay | `src/main/runtime/relay/desktop-relay-service.ts`, `relay-session-broker.ts` |
| Firewall (Windows) | `src/main/runtime/windows-mobile-firewall.ts` |
| Pairing encode | `src/shared/pairing.ts`, `mobile-relay-pairing-offer.ts` |
| Settings UI | `MobilePane.tsx`, `MobilePairingQrSection.tsx`, `MobilePage.tsx` |

### Exact modules (mobile)

| Concern | Path |
|---------|------|
| Screens | `mobile/app/` (pair-scan, pair-confirm, `h/[hostId]/session`, tasks, files, PR, review, …) |
| Transport | `mobile/src/transport/` (rpc-client, pairing, relay*, e2ee, host-store) |
| Session UX | `mobile/src/session/` |
| Terminal WebView | `mobile/src/terminal/` |

### What the phone can do (from allowlist + routes)

- **Steer agents:** `terminal.send`, create/ensure agent sessions, split/list/focus/close tabs, quick commands, restore fit.
- **Observe:** live `terminal.subscribe` multiplex stream; agent status; worktree list/activate/create/sleep/rm.
- **Notifications:** `notifications.subscribe` / missed-since.
- **Source control / review:** large `git.*`, `github.*`, `gitlab.*`, Linear, hosted review.
- **Files:** browse/read/preview, open diffs, limited writes (artifacts).
- **Browser remote:** screencast + click/goto/back/forward/reload/viewport.
- **Accounts:** list/select Claude & Codex; subscribe usage.
- **Dictation, clipboard images, native chat subscribe, SSH connect state, markdown tabs, AI vault resume.**

Not full desktop parity — **no** unrestricted computer-use / many admin RPCs unless `scope: 'runtime'`.

### How OpenIDE could be recognized as a peer / host

**There is no third-party “app id” plugin API.** Recognition is **protocol compatibility**:

| Extension point | Implication for OpenIDE |
|-----------------|-------------------------|
| **Implement runtime WS server** | Speak same pairing offer + E2EE + `status.get` capabilities → official mobile app / `orca` CLI / web client can attach. Must implement enough of `ALL_RPC_METHODS` (or subset) and advertise matching `RUNTIME_PROTOCOL_VERSION` / capabilities. |
| **Act as runtime client** | Mint/consume `orca://pair` with `scope: 'runtime'` against Orca desktop/`orca serve` — OpenIDE becomes another remote client (like web), not a host. |
| **Act as mobile client** | Same as phone: encode offer, E2EE auth, only use allowlisted methods — OpenIDE phone UI against Orca host. |
| **`MOBILE_RPC_METHOD_ALLOWLIST`** | If OpenIDE is a host wanting Orca’s mobile app: must allowlist every method the mobile app calls (CI-enforced in Orca via scanning `mobile/`). |
| **Capabilities flags** | Soft feature gates (`terminal.quick-commands.v1`, `aiVault.v1`, …) — advertise only what you implement. |
| **Custom scheme** | Deep link host must be `orca://pair` for stock mobile QR flow — changing scheme breaks App Store app unless OpenIDE ships its own companion. |
| **Relay** | Cloud Relay is Orca-cloud-specific (signed-in director/cell URLs). LAN pairing is the open path; Anywhere requires their broker or your own relay implementing `mobile-relay-phone-protocol.ts`. |
| **`orca.yaml`** | **Not** a peer schema — only project setup scripts for Orca’s own repo (`scripts.setup`). Do not treat as host registration. |
| **Device scope** | `mobile` = restricted; `runtime` = full RPC (dangerous if leaked). Choose deliberately. |

**Practical OpenIDE strategies (conceptual):**  
**(A)** Reimplement companion protocol as OpenIDE host + own mobile app (cleanest product ownership).  
**(B)** Pair OpenIDE as `runtime` client into Orca for orchestration handoff.  
**(C)** Do **not** “hack” Orca recognition — there is nothing to flip except speaking the wire protocol.

---

## 5. Window / workspace UX

| Behavior | Detail | Paths |
|----------|--------|-------|
| **Single-instance** | `requestSingleInstanceLock` after userData path config; second launch focuses existing window. Prevents clobbering `orca-runtime.json` + hook endpoint files. Dev can skip; macOS bypass env exists. | `src/main/startup/single-instance-lock.ts` |
| **Main window** | One primary `BrowserWindow`; bounds/maximize persisted. | `createMainWindow.ts` |
| **Second-instance / activate** | Routed through serve desktop activation gate (headless won’t pop UI incorrectly). | `index.ts`, `focus-existing-window.ts` |
| **Dashboard popout** | Optional singleton companion window; focus-if-exists. | `dashboard-popout-window.ts` |
| **Open repo** | Sidebar `AddRepoDialog` flows: clone, create, nested import, remote host, server start. | `components/sidebar/AddRepo*` |
| **Multi-host workspace** | Local + SSH + remote Orca servers; `workspaceHostScope` / host order in persisted UI. | `PersistedUIState` in `types.ts` |
| **Navigation** | `TopLevelView`: `terminal` \| `settings` \| `tasks` \| `activity` \| `automations` \| `space` \| `skills` \| `mobile`. Sidebar hidden on settings/activity/space/skills. | `App.tsx`, `store/slices/ui.ts` |
| **Worktree sync** | Runtime graph sync local ↔ remote hosts; sleep/activate; sort order. | `sync-runtime-graph.ts`, worktree RPCs |
| **Persistence** | Settings + UI patches via IPC; activeView has dedicated tiny preference write. | `App.tsx` unload/persist comments |

---

## 6. Settings / Preferences / Skills taxonomy

### Settings nav groups (`useSettingsNavigationMetadata.ts`)

**Capabilities:** Agents · AI Provider Accounts · Orchestration · Linear (if connected) · Computer Use · Voice  

**Setup:** Onboarding checklist · General · Integrations · Mobile  

**Workflows:** Git & Source Control · Task Sources · Terminal · Quick Commands · Browser · Mobile Emulator · Floating Workspace  

**Interface:** Appearance · Input & Editing · Notifications · Shortcuts · Stats & Usage  

**Remote:** SSH Hosts · Remote Orca Servers (Beta)  

**Security:** macOS Permissions · Privacy & Telemetry  

**Advanced:** Advanced · Dev Tools (dev only) · Experimental  

**Repositories:** one nav row per project (`repo-{id}`) with host-scoped overrides  

### Notable setting domains (panes)

Agents defaults/commands · account switching · orchestration skill install · Linear skill · computer-use enablement · voice models · workspace directory · updates · remote server updates · GitHub/GitLab/Linear/Jira/Bitbucket cards · mobile pairing mode (automatic/local-only) + QR + paired devices + Windows firewall · git base refs / attribution / AI commit · task provider visibility · terminal shell/theme/WebGL/scrollback/Ghostty+Warp import · quick commands · browser home/cookies/profiles · emulator · floating workspace · appearance/zoom/sidebars/status bar · notifications/sounds · keybindings file · SSH targets · runtime environments · privacy/telemetry · experimental flags (orchestration, native chat, ephemeral VMs, dashboard popout, …)

### Skills (bundled)

| Skill | Purpose |
|-------|---------|
| `orchestration` | Multi-agent DAG / ask-reply / gates |
| `orca-cli` | Drive Orca from agent via CLI |
| `computer-use` | Desktop UI automation |
| `orca-linear` / `linear-tickets` | Linear from agents |
| `orca-emulator` / `orca-emulator-android` | Emulator control |
| `orca-per-workspace-env` | Per-workspace env |

Stubs in `skills/*/SKILL.md` defer to `orca skills get <name>` for version-matched guides (`skill-guides/`).

### `orca.yaml` (repo root)

Only:

```yaml
scripts:
  setup: |
    node config/scripts/run-internal-dev-setup.mjs
    pnpm install
```

**Not** a peer/host recognition config.

---

## 7. UI component inventory (major surfaces)

### Top-level views / routes (`App.tsx` lazy)

| View | Component path |
|------|----------------|
| Landing (no repos) | `components/Landing.tsx` |
| Terminal / workbench | `Terminal.tsx` + terminal-pane / tab-bar / floating-terminal |
| Tasks | `TaskPage.tsx` |
| Automations | `automations/AutomationsPage.tsx` |
| Activity | `activity/ActivityPrototypePage.tsx` |
| Settings | `settings/Settings.tsx` |
| Skills | `skills/SkillsPage.tsx` |
| Workspace Space | `workspace-space/WorkspaceSpacePage.tsx` |
| Mobile marketing/pairing page | `mobile/MobilePage.tsx` |

### Chrome

| Surface | Path |
|---------|------|
| Left worktree sidebar | `components/sidebar/` |
| Right sidebar (files/SC/PR/AI vault) | `components/right-sidebar/` |
| Tab bar / tab groups | `tab-bar/`, `tab-group/` |
| Status bar | `status-bar/` |
| Cmd+J palette | `cmd-j/`, `QuickOpen.tsx` |
| Feature wall modal | `feature-wall/FeatureWallModal.tsx` |
| Notifications UI | `notifications/` |
| Onboarding | `onboarding/` |
| Dashboard | `dashboard/`, `dashboard-popout/` |

### Domain panels

| Domain | Paths |
|--------|-------|
| Browser / Design Mode | `browser-pane/` |
| Emulator | `emulator-pane/` |
| Editor / markdown | `editor/` |
| Source control | `source-control/` + right-sidebar commit/checks |
| Diff annotate | `diff-comments/` |
| Native chat | `native-chat/` |
| GitHub projects | `github-project/` |
| Linear/Jira workspaces | `LinearIssueWorkspace.tsx`, `JiraIssueWorkspace.tsx`, dialogs |
| New workspace composer | `NewWorkspaceComposerModal.tsx`, `new-workspace/` |
| Ports | `ports/` |
| Dictation | `dictation/` |
| Settings (all panes) | `settings/*Pane.tsx` (~40 panes) |
| UI primitives | `components/ui/` (shadcn) |

### Mobile app routes (`mobile/app`)

Home hosts · pair / pair-scan / pair-confirm · settings (+ terminal/voice/browser/native-chat) · `h/[hostId]/` index, accounts, tasks, session, files, history, PR, review, source-control, agent-history · notifications · troubleshoot · about · onboarding.

### Web client

`src/renderer/src/web/` — `WebConnect.tsx`, `web-pairing.ts`, `web-runtime-client.ts`, E2EE for browser runtime access.

---

## 8. Scrap checklist for OpenIDE (behaviors to reimplement)

> Conceptual port only — do **not** copy proprietary cloud Relay infra, icons, App Store binaries, or branded assets. Orca is MIT for code patterns, but product/cloud pieces still need independent implementation.

### P0 — Core ADE differentiators

1. **Parallel worktree agent fan-out** — create N isolated worktrees, launch chosen CLI agents, compare outcomes, merge winner.  
2. **Agent-as-PTY model** — treat Cursor/Codex/Claude CLIs as first-class launch targets with status from titles/processes.  
3. **Unified runtime RPC** — one method registry for UI/CLI/remote clients; capability negotiation.  
4. **Mobile (or tablet) companion remote control** — pairing QR, encrypted WS, terminal subscribe/send, completion notifications, follow-ups.  
5. **Single-instance + discovery files** — avoid duplicate runtimes corrupting RPC/hook endpoints.  
6. **Terminal splits + durable scrollback** — multi-pane agent visibility is the job-to-be-done.

### P1 — High leverage product surfaces

7. **Tasks hub** (GitHub/Linear/GitLab) → “open as worktree.”  
8. **Annotate diffs → send to agent** review loop.  
9. **Design Mode** (element pick → prompt context).  
10. **SSH/remote workspaces** with reconnect (own relay design OK).  
11. **Account/usage switcher** for multi-subscription builders.  
12. **Quick open** across worktrees/agents/settings.  
13. **Notifications + unread agent threads.**  
14. **Settings taxonomy** grouped Capabilities / Workflows / Remote / per-repo.  
15. **Headless serve** for VPS “always-on agent host.”

### P2 — Differentiation / later

16. **Orchestration skill** (DAG, gates, worker_done) — optional advanced layer.  
17. **Computer Use** OS automation.  
18. **Mobile emulator** for agent QA.  
19. **Floating global workspace** tabs.  
20. **Automations** scheduler.  
21. **AI Vault** session resume.  
22. **Cloud Relay “Anywhere”** pairing — only if OpenIDE wants off-LAN phone control (build own broker; don’t depend on Orca’s).  
23. **Web runtime client** pairing sibling to mobile.  
24. **Feature wall / onboarding checklist** patterns.  
25. **Bundled skills** that teach agents how to drive the IDE via CLI.

### Explicit non-goals / legal-product caution

- Do not clone Orca App Store companion and retarget it; ship OpenIDE’s own client or implement host protocol carefully.  
- Do not spoof `orca://` in production unless intentionally interoperating and documenting that dependency.  
- Prefer **reimplementing behaviors** (pairing offer shape, E2EE, allowlists, worktree UX) over copying UI chrome/assets.

---

## Appendix — Protocol constants cheat sheet

| Constant | Value / note |
|----------|----------------|
| Packaged WS port | **6768** |
| Dev WS port | **6769** |
| Pairing URL | `orca://pair?code=…` |
| Offer version | **2** |
| Runtime/mobile protocol | **3** (min compatible **2**) |
| Device scopes | `mobile` (allowlisted) · `runtime` (full) |
| Connection modes | `automatic` (Relay) · `local-only` |
| E2EE | Curve25519 + framing v2 |

---

**Bottom line for OpenIDE:** Steal the *architecture* — worktree-isolated parallel agents, versioned encrypted runtime RPC, phone-as-remote-control, and task→worktree workflows. Treat Orca’s mobile Relay and App Store client as reference, not drop-in peers, unless you deliberately implement their wire protocol end-to-end.
# SCRAP — Orca (stablyai/orca)

**Clone:** `D:\AirGPT\OpenIDE\research\orca`  
**Version seen:** `1.4.151-rc.1` (`package.json`)  
**License:** MIT  
**Tagline:** ADE for a fleet of parallel agents. Desktop + mobile + VPS. Run Codex / Claude Code / OpenCode / Pi with your own subscription.

---

## 1. Product summary

Electron + Vite desktop IDE (`electron.vite.config.ts`) with:

- `src/main` — Electron main (worktrees, PTY, agents, SSH, relay, window, IPC)
- `src/preload` — bridge
- `src/renderer` — React 19 UI (sidebar, terminal, browser, settings, mobile pairing UI)
- `src/relay` — mobile relay cell/director
- `src/cli` — `orca` CLI
- `src/shared` — pairing + remote-runtime contracts
- `mobile/` — React Native / Expo companion (iOS App Store + Android APK)
- `native/` — computer-use + notification helpers per OS
- `skills/` + `skill-guides/` + `skill-stubs/` — bundled skills

---

## 2. Feature wall (behaviors to reimplement in OpenIDE)

| Feature | Behavior | Key paths |
|---------|----------|-----------|
| **Mobile Companion** | Pair phone → monitor/steer agents, notifications, follow-ups from anywhere | `src/shared/pairing.ts`, `mobile-relay-*`, `src/relay`, `mobile/`, renderer `components/mobile` |
| **Parallel Worktrees** | Fan one prompt across N agents, each isolated git worktree; compare/merge winner | `src/main/repo-worktrees.ts`, `worktree-create-*.ts`, `components/worktree-creation` |
| **Terminal Splits** | Ghostty-class xterm WebGL, infinite splits, scrollback survives restart | `components/terminal*`, `src/main/pty*`, native xterm patches |
| **Design Mode** | Click Chromium UI → HTML/CSS + crop into agent prompt | `components/browser-pane`, design-mode docs |
| **GitHub & Linear native** | PRs/issues/boards in-app; open worktree from task | `components/github*`, `linear*`, `src/main/linear`, `github` |
| **SSH Worktrees** | Agents on remote box; edit/git/term; auto-reconnect + port forward | `src/main/ssh`, `src/shared/remote-runtime-*` |
| **Annotate AI Diffs** | Comment on agent diffs in-app | `components/diff-comments`, source-control |
| **Automations** | Scheduled / headless agent runs | `components/automations`, `headless-automation-*` |
| **Quick Open / Jump** | File + worktree jump palettes | `QuickOpen.tsx`, `WorktreeJumpPalette.tsx` |
| **Dashboard / Popout** | Multi-client navigation, popout windows | `dashboard*`, `popout.tsx`, `src/main/window` |
| **Ports / Emulator** | Port detection + floating mobile emulator tab | `components/ports`, `emulator-pane` |
| **Skills / Profiles** | Skills UI + orca-profiles | `components/skills`, `orca-profiles` |
| **Dictation / Speech** | Voice input | `components/dictation`, `src/main/speech` |
| **Multi-provider agents** | Claude, Codex, OpenCode, Pi, Kimi, Grok, Hermes, … | `src/main/{claude,codex,opencode,pi,kimi,grok,…}` |

---

## 3. Mobile remote control (critical for “phone controls IDE”)

### Pairing deep link

```
orca://pair?code=<base64url(JSON PairingOffer)>
```

Schema (`PAIRING_OFFER_VERSION = 2`) in `src/shared/mobile-relay-pairing-offer.ts`:

- `endpoint`, `deviceToken`, `publicKeyB64` (Curve25519)
- optional `scope`: `mobile` | `runtime`
- optional `relay`: directorUrl, cellUrl, assignmentEpoch, relayHostId, inviteToken, inviteExpiresAt (≤10m), `e2eeFraming: 2`

Encode/decode: `src/shared/pairing.ts`.

### Relay phone protocol

- `src/shared/mobile-relay-phone-protocol.ts` — `relay-hello` (invite/resume), `relay-moved`
- E2EE v2 contracts: `mobile-e2ee-v2-contract.ts`
- Connection modes: `mobile-pairing-connection-mode.ts`
- Close codes: `mobile-relay-close-codes.ts`

### OpenIDE strategy (legal + product)

1. **Preferred:** Implement **OpenIDE Companion** protocol (`openide://pair` / `netie://pair`) mirroring Orca’s MIT contracts under our brand — own relay or LAN WebSocket to AirGPT host.
2. **Interop (optional later):** Host an Orca-compatible pairing offer so stock Orca mobile can attach *if* we speak their relay+E2EE — MIT allows protocol reimplementation; do **not** spoof App Store identity / trademarks. Advertise as “OpenIDE host” in pairing metadata.
3. Phone capabilities to ship: list agents, status dots, send follow-up, approve/deny, notifications on need-attention, open worktree summary, basic terminal tail.

---

## 4. Window / navigation patterns

From main modules + renderer:

- Dedicated `src/main/window` — multi-window / popout
- `popout.tsx` + `dashboard-popout` — detach surfaces
- Active view persistence: `active-view-preference.ts`
- Single-serialize persistence: `persistence-single-serialize*`
- External editor handoff: `external-editor-launch.ts`
- Multi-client navigation e2e scripts exist — treat as reference for “IDE sync”

**OpenIDE rule to adopt:** One primary window per bound workspace root; secondary popouts for terminal/diff/browser only; opening same repo focuses existing window (no duplicate).

---

## 5. Settings taxonomy (renderer `components/settings` + main)

Expect categories (confirm in subagent merge): Appearance, Terminal, Agents/Models, Keybindings, Network/SSH, Mobile pairing, Skills, Source control, Notifications, Profiles, Experimental, Telemetry.

---

## 6. UI component inventory (top-level)

`src/renderer/src/components/`: activity, agent, automations, browser-pane, cmd-j, dashboard, dictation, diff-comments, editor, emulator-pane, floating-terminal, github, gitlab, linear, mobile, native-chat, network, new-workspace, notifications, ports, repo, right-sidebar, settings, sidebar, skills, source-control, status-bar, tab-bar, tab-group, terminal*, workspace-*, worktree-creation, QuickOpen, WorktreeJumpPalette, Landing, TaskPage, PullRequestPage, …

---

## 7. Scrap checklist → OpenIDE (priority)

### P0 — become “next Orca” core

1. Parallel git worktrees per agent run (Cortex-backed)
2. Agent fleet sidebar with live status + need-attention
3. Composer fan-out (1 prompt → N worktree agents)
4. Mobile pairing host + companion (or LAN control plane reuse of AirGPT wifi)
5. Window focus / single-instance-per-repo

### P1 — daily ADE power

6. Terminal splits + persistent scrollback
7. In-app diff annotate + commit/PR (extend existing Create PR)
8. Command palette / Quick Open / Worktree jump
9. Settings depth (Cursor-like + agent providers)
10. Ports + preview browser pane

### P2 — parity / polish

11. Design Mode / browser element → prompt
12. SSH / remote runtime worktrees
13. Automations / scheduled agents
14. Linear/GitHub boards in-app
15. Dictation, skills marketplace UI

# OpenIDE — WORK

Active slices. Prefer landing work in this folder (`ui/` + Python modules).

## Landed (baseline)

- [x] Package isolation: `OpenIDE/` + root shims
- [x] Density pass: compact New Agent, nested repo agents, `+` = New Agent
- [x] Create PR hidden until dirty
- [x] Open Tabs sync + runs persist localStorage
- [x] Settings Cursor-like shell (Rules / Skills / Subagents) — still wired from root Settings UI
- [x] **Create-App Magic** — `POST /api/openide/scaffold` + empty-state CTA + auto Cortex seed
- [x] **OpenVault Key Vault** — OpenFree + BYOK + CLI (`GH_TOKEN`) + OpenShip deploy cards
- [x] **OpenVault mesh** — bridge to `D:\OpenVault` (:5000) handshake + connect-pack; Keys → Connect / OpenIDE Vault button
- [x] Prompt-trend advice injected into scaffold seeds
- [x] Run CTA / empty-state contrast polish; Enter to Run; Keys in header

## Next

**S4 — GitHub + netie.ai**
- [ ] Harden clone destination under netie.ai workspace convention
- [ ] Push-help after auth (never type credentials — key_vault law)
- [ ] Detect pasted repo URLs in composer

**S5 — Research → implement**
- [ ] Prompt layers doc (Rules → Skill → Git FP → Tools)
- [ ] Token / tool-loop timing coalescing
- [ ] Tool-calling schema parity vs Cursor Agents

**Create-App follow-ups**
- [ ] In-shell path modal (replace remaining `prompt()` for Browse/New folder)
- [ ] Auto-start preview server after scaffold + Browser tab
- [ ] Playwright: Create app → scaffold files → Keys → Run
- [ ] OpenShip one-tap deploy from Changes rail

**UI polish**
- [ ] Nested subagent timeline cards
- [ ] Persist repo→agent map beyond localStorage
- [ ] Canvas files as Open Tabs when opened from agent
- [ ] Further visual renew vs Claude Code / Cursor once density is daily-usable

**Tests**
- [x] Pytest: scaffold static template + key vault CLI/OpenShip
- [ ] Playwright: Settings → create skill → catalog lists it

## Runtime revive (2026-07-23)

- [x] **Root cause empty app / stuck syncing:** OpenIDE JS was injected *mid* main `<script>`, so `layoutComposerChrome` ran before definition and aborted boot (`Local · syncing…` forever).
- [x] Fix: one continuous main script; load `/OpenIDE/ui/openide.js` **after** boot IIFE.
- [x] Recents header aligned with Platform/Agents (shared label padding + side-scroll inset).
- [x] Edge hotzone no longer steals clicks when sidebar expanded.

**Backend was not dead** — `/api/health`, sessions, history all responded; UI never finished `bootApp`.

Lag was **not** OpenIDE isolation corruption. Fixed hot paths:

- [x] Hide Projects vault under Recents (home shows Recents only)
- [x] `/api/wait` no longer runs PowerShell LAN diagnostics every poll
- [x] Skip `register_device` SQLite writes on wait/static/OpenIDE assets
- [x] OpenIDE: light fingerprint on open; full `git_summary` deferred to Git/Changes
- [x] Boot: parallel `pullHistory` + `loadVaultTree`
- [x] Expand `SKIP_DIRS` (research, CortexOS, .cursor, …); search_files respects it

### Native rewrite (later — not day-one)

Full Rust/Go/TS rewrite of AirGPT is **out of band**. Prefer targeted natives after Python hot paths are smooth:

| Candidate | Why |
|-----------|-----|
| Rust git status/diff (gitoxide) | Privacy-local + no subprocess tax |
| Go static + `/api/wait` edge | Concurrent poll without GIL |
| TS OpenIDE shell (Vite) | Split 500KB `index.html` |

Scaffold only when stress tests show Python still bound after the above.

Run: `python OpenIDE/tests/test_lag_hotspots.py`
- OpenVault Key Vault = one place for keys/CLIs/deploy; OpenVault memory (`vault.py`) stays separate

# CLAUDE CODE HANDOFF — OpenIDE ← Orca/Superset scrape

**Date:** 2026-07-23  
**Repo roots:** `D:\AirGPT` (host) · `D:\AirGPT\OpenIDE` (IDE surface) · `D:\Cortex` (brain)  
**Research clones:** `D:\AirGPT\OpenIDE\research\{orca,superset}`  
**Read first:** `research/RESEARCH_INDEX.md`, `SCRAP_ORCA.md`, `SCRAP_SUPERSET.md`, `GAP_OPENIDE_CORTEX.md`, `OpenIDE/WORK.md`, `D:\Cortex\CURSOR_HANDOFF.md`

## License constraints

- **Orca = MIT** → may adapt protocol/UI patterns with attribution; rebrand as OpenIDE/Netie.
- **Superset = ELv2** → **reimplement behaviors only**; no substantial code copy; no managed rehost of their feature set.

## Mission

Make **OpenIDE** the ADE that runs **native Netie Cortex (`D:\Cortex`)** at high parallel speed, matching Orca/Superset UX for fleet agents, then add phone remote control.

### Architecture truth (do not skip)

Today OpenIDE Run uses **AirGPT in-process** `agent_runtime` + **serial** `cortex_orchestrator` (3s tick, one `_active_run_id`). Native CortexOS is only a soft-fail sidecar via `cortex_client`. **Wave 1 must wire OpenIDE→Cortex as the real brain** (or explicitly promote AirGPT orchestrator into Cortex packs) — not pretend the sidecar already is the loop.

Do **not** invent a third orchestrator — extend surviving orchestrator + Cortex gates (see dual-brain plan).

---

## Implementation waves (do in order)

## Wave 0b — Wire native Cortex as OpenIDE brain (BLOCKING for “insane speed”)

**Truth:** OpenIDE Run → `agent_runtime` (AirGPT). `D:\Cortex` is soft-fail sidecar only.

Tasks:

1. Define OpenIDE backend mode `cortex_native` that routes tool loop / packs through CortexOS (`cortex_client` hardened, not 1.5s soft-fail for IDE runs)
2. Parallel run slots in orchestrator (replace single `_active_run_id` serial drain) — Fleet mode
3. Sync barriers + event bus so OpenIDE UI gets live multi-agent timeline (not localStorage-only)
4. Keep Assist=0 / Deep≤2 defaults; Fleet = explicit opt-in for N worktrees

Without Wave 0b, Waves 1–3 are UI theater.

**Outcome:** One prompt can fan out to N Cortex agents, each in an isolated git worktree under the bound workspace; sidebar shows live status; write gate still Cortex.

Tasks:

1. `workspace_api`: `create_agent_worktree(run_id)`, `list_worktrees`, `remove_worktree` (git worktree add/remove; Windows longpaths aware)
2. `cortex_orchestrator`: parallel queue (bounded concurrency), sync barrier for “all children done”, respect Assist=0 / Deep≤2 laws — add explicit **Fleet** mode for N>2 with user opt-in
3. OpenIDE UI: fleet sidebar status dots, need-attention toast, nested timeline cards (WORK.md polish)
4. Persist repo→agent map beyond localStorage (SQLite via `agent_store` or Cortex ops DB)

Tests: unit worktree create/remove; orchestrator fan-out with fake backend; no credential auto-type.

### Wave 2 — Window logic (P0)

1. Single-instance-per-workspace-root: opening same repo focuses existing OpenIDE session
2. “Open new window” = new browser/Electron window with independent workspace bind
3. Sync Open Tabs + active agent across Agents|IDE panes (BroadcastChannel or host WS)
4. Easy navigate: recent workspaces, open in repo, jump to running agent

### Wave 3 — Mobile companion host (P0/P1)

1. Implement `openide://pair` (or `netie://pair`) pairing offer inspired by Orca MIT `PairingOffer` v2
2. LAN-first WebSocket on AirGPT (reuse wifi auth) — phone: list runs, send follow-up, approve writes, notifications
3. Optional: Orca-protocol-compatible mode behind flag (speak their schemas) — advertise OpenIDE host name; **do not** spoof Orca trademarks
4. Scaffold Expo/RN app under `OpenIDE/mobile/` or `AirGPT/mobile/` (MIT lessons from `research/orca/mobile`)

### Wave 4 — ADE chrome (P1)

1. Terminal splits + session persistence (extend `terminal_pty`; study Orca xterm patches conceptually)
2. First-class Diff pane (comment stubs OK initially) + Create PR already exists
3. Command palette + Quick Open + Worktree jump
4. Ports scanner + preview per worktree (Superset/Orca behavior)
5. Settings IA expansion: Agents, Models, Terminal, Keyboard, Git, Hosts/Mobile, Notifications, Experimental — keep Cursor Rules/Skills/Subagents panels

### Wave 5 — Cortex “insane sync” (P1)

1. Token/tool-loop timing coalescing (WORK S5)
2. Tool-calling schema parity vs Cursor Agents
3. Lifecycle hooks: beforeSubmit / afterResponse / subagentStart (dual-brain plan)
4. Stress bench: N parallel worktree agents on `D:\Cortex` demo pack — publish ev/s + latency

### Wave 6 — Parity nice-to-haves (P2)

Automations, SSH worktrees, Design Mode, in-app GitHub/Linear boards, dictation, MCP/SDK external workspace control.

---

## Superset deep-scrape deltas (fold into Waves 1–4)

From `SUBAGENT_SCRAP_SUPERSET_FULL.md` (ELv2 — behaviors only):

- **Host-service split:** UI ≠ owner of PTY/git/ports — map to AirGPT daemon + `D:\Cortex` (OpenIDE host API)
- **Single BrowserWindow + `requestSingleInstanceLock`** — workspaces are tabs/routes, not duplicate Electron windows
- **Remote = JWT + relay tunnel + host ACL** (not QR); OpenIDE should prefer Orca-style QR for phone + optional host ACL later
- **Pane registry:** Terminal / Chat / Browser / File / Diff / Comment / Devtools — mirror in OpenIDE right-rail
- **Settings IA:** account→hosts/security full taxonomy already listed in SCRAP_SUPERSET + full dump §6
- **P0 checklist in dump §8** aligns with Waves 0b–2; add **pty-daemon persistence** and **open-in-external-editor** to Wave 4 if missing

Prefer **mirror behaviors with OpenIDE protocol** over speaking Superset relay wire format (license safety).

---

## Acceptance (Wave 1–3)

- [ ] Fan-out 3 worktree agents from one OpenIDE prompt; merge winner manually
- [ ] Same repo open focuses existing window
- [ ] Phone on LAN pairs and can send follow-up + see run status
- [ ] Cortex still sole write gate; Assist/Deep laws hold unless Fleet opted in
- [ ] Scrap docs remain the source of feature checklist

---

## File touch map (expected)

| Area | Files |
|------|--------|
| Worktrees | `OpenIDE/workspace_api.py`, new `OpenIDE/worktree_fleet.py` |
| Orchestrator | `AirGPT/cortex_orchestrator.py`, `agent_store.py`, Cortex hooks as needed |
| UI | `OpenIDE/ui/openide.js`, `openide.css` |
| Pairing | new `OpenIDE/remote_pairing.py`, routes in `clipdrop.py` / `hub.py` |
| Settings | root Settings modal panels (index.html + JS) — migrate gradually into OpenIDE |
| Tests | `OpenIDE/tests/`, AirGPT pytest |

---

## Reference paths (scrap)

- Orca pairing: `research/orca/src/shared/pairing.ts`, `mobile-relay-pairing-offer.ts`
- Orca worktrees: `research/orca/src/main/repo-worktrees.ts`, `worktree-create-*.ts`
- Orca UI: `research/orca/src/renderer/src/components/*`
- Superset settings IA: `research/superset/apps/desktop/src/renderer/routes/_authenticated/settings/*`
- Superset packages: `host-service`, `pty-daemon`, `panes`, `session-protocol`, `port-scanner`

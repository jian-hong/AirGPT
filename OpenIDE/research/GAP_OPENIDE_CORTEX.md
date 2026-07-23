# GAP — OpenIDE + Cortex vs Orca/Superset/Cursor/Claude Code

**OpenIDE:** `D:\AirGPT\OpenIDE` (UI + workspace/bridge/pty)  
**Host:** `D:\AirGPT` (Settings shell, agents APIs, wifi/P2P)  
**Brain:** `D:\Cortex` (Netie Cortex / CortexOS + packs)

---

## 1. What OpenIDE already has (landed)

From `WORK.md` + `ui/openide.js` + Python modules:

| Area | Status | Notes |
|------|--------|-------|
| Agents \| IDE shell | ✅ | Density pass, rails, glass menus |
| New Agent / nested repo agents | ✅ | `+` = New Agent; localStorage runs |
| Composer + modes | ✅ partial | Ask / Agent / Plan-ish via think modes; @mention picker |
| Open Tabs sync | ✅ | localStorage |
| Create PR (when dirty) | ✅ | Hidden until dirty |
| Git fingerprint / branch checkout | ✅ | `workspace_api` |
| File tree + open file | ✅ | Path-jailed FS |
| Terminal allowlist | ✅ | `terminal_pty` (not Ghostty-class splits) |
| Cursor / local / cloud backends | ✅ partial | `cursor_bridge` + Cortex runs |
| Write approval gate | ✅ | Cortex write gate |
| Settings Cursor-like (Rules/Skills/Subagents) | ✅ shell | Still rooted in AirGPT Settings modal |
| Preview / app chips | ✅ thin | Basic preview URL load |
| Package isolation | ✅ | OpenIDE folder + root shims |

### Explicit laws already coded

- Assist = 0 subagents; Deep ≤ 2; children don’t recurse (`WORK.md`)
- Local-first; Cortex = brain / write gate
- Never auto-type credentials

---

## 2. Cortex speed / synchrony (honest)

**Shipped useful pieces**

- AirGPT `cortex_orchestrator.py`: thinking modes, queued runs, subagent meta, worker thread
- CortexOS engine registry, memory plane, DAG runner (**limited fan-out**), S0 streams ~380 ev/s stress
- Dual-brain plan: governance on `main`, engine capabilities land gate-by-gate (`ENGINE_SDK_DUAL_BRAIN_PLAN`)
- O1 ontology registry PASS (2026-07-23)

**Not yet “insane parallel ADE”**

- No worktree-per-agent isolation in OpenIDE↔Cortex path
- No fan-out composer (1 prompt → N isolated Cortex agents)
- DAG fan-out limited; “don’t build a third orchestrator” watch-item
- Parallel / side agents called out as future property of surviving orchestrator
- Token/tool-loop coalescing still on OpenIDE WORK S5

**Target architecture for “next Orca”**

```
Phone / OpenIDE UI
    → AirGPT control plane (auth, wifi, pairing)
        → OpenIDE workspace manager (worktrees, windows, tabs)
            → Cortex orchestrator (parallel runs, sync barriers, write gate)
                → D:\Cortex packs/tools/ontology
```

---

## 3. Remote / mobile today

| Piece | Exists? | Gap |
|-------|---------|-----|
| AirGPT LAN / wifi_access | ✅ | Laptop↔phone on same WiFi for chat/drop — not ADE agent steer |
| P2P drop HTML | ✅ | File drop, not agent control |
| Orca-compatible pairing | ❌ | Need `openide://pair` + relay/E2EE or LAN WS |
| Companion mobile app | ❌ | Build Netie/OpenIDE app or adapt Orca mobile (MIT) under our brand |
| Host wake / remote workspaces | ❌ | |

**Extra truth** (`SUBAGENT_GAP_OPENIDE_CORTEX.md`): OpenIDE APIs are **host-only** — phone/LAN guests cannot drive IDE. Orchestrator is serial (one `_active_run_id`, 3s tick). `runOpenIDEAgent` forces `backend='local'`. `terminal_pty` is allowlisted exec, not interactive PTY. Multitask ≠ parallel fleet. `apps_hub.already_running` is for hosted apps only, not OpenIDE windows.

---

## 4. Window / multi-window

| Need | Status |
|------|--------|
| Single window per repo / focus existing | ❌ not implemented |
| Open new window | ❌ (browser tab only) |
| Open in repo (nested agent) | ✅ partial (`newOpenIDECortexRun(repoPath)`) |
| Popout terminal/diff/browser | ❌ |
| Cross-surface IDE sync (tabs/agents) | ❌ beyond localStorage |

---

## 5. Settings / Preferences gap vs Superset+Orca+Cursor

OpenIDE/AirGPT Settings has Cursor-like nav shell for Rules / Skills / Subagents.

**Missing depth (from Superset settings IA + Orca):**

agents, models, api-keys, appearance, behavior, git, hooks, hosts, integrations, keyboard, terminal presets, permissions, presets, ringtones/notifications, security, experimental, mobile pairing, SSH/remote, worktree location, automations.

---

## 6. Master NOT YET IMPLEMENTED (for Claude Code)

See `CLAUDE_CODE_HANDOFF.md` for prioritized backlog. Summary buckets:

1. **Worktree fleet + parallel Cortex**
2. **Mobile companion + pairing host**
3. **Window manager / single-instance**
4. **Terminal splits + persistence**
5. **Diff pane + annotate**
6. **Command palette / Quick Open**
7. **Ports + preview browser**
8. **Settings IA expansion**
9. **Automations**
10. **SSH/remote hosts**
11. **Design Mode**
12. **Cortex sync barriers / coalescing / fan-out**

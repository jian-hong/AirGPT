# OpenIDE + Cortex — Current-state inventory (gap analysis)

**Verdict:** OpenIDE is a **browser-embedded Agents|IDE shell** inside AirGPT (`D:\AirGPT`), not a native Electron IDE. Agent “brain” for OpenIDE runs **in-process** via `agent_runtime.py` / `cortex_orchestrator.py`. Native **`D:\Cortex`** is a separate CortexOS/DMS sidecar Soft-polled by `cortex_client.py` — not the OpenIDE tool loop. “Insane speed & synchrony” is only partially present (parallel git fingerprint, ≤2 queued subagents, serial 3s worker).

---

## 1. OpenIDE UI surfaces

**Source of truth:** `D:\AirGPT\OpenIDE\ui\openide.js` (~1362 lines), `openide.css` (~296 lines)  
**Host hooks:** `D:\AirGPT\index.html` — CSS `<link href="/OpenIDE/ui/openide.css"/>`, script `<script src="/OpenIDE/ui/openide.js">`, nav `#navOpenIDE` → `showWorkspace('openide')` → `showOpenIDEPage()`, `#openideIdeBtn` → `openOpenIDERightRail()`, Esc/`popstate` → `exitOpenIDE()`.

| Surface | Status | Key symbols |
|--------|--------|-------------|
| **Boot morph** | **Exists** | `openideMorphPlay` / `openideMorphDone` |
| **Mode shell** | **Exists** | `setOpenIDEMode`, `body.openide-mode`, `#openide` history |
| **Agents \| IDE toggle** | **Exists** | `setOpenIDEView('agents'\|'editor')`, `openide-view-*` CSS |
| **Left: Agents / Repos** | **Exists** | `renderOpenIDERepos`, `newOpenIDECortexRun`, runs in `localStorage` (`airgpt_oide_runs`) |
| **Left: Files / Git** | **Exists** (IDE view) | `openideTab`, `refreshOpenIDETree`, `loadOpenIDEGitBundle` |
| **Center: transcript + composer** | **Exists** | `#openideTranscript`, `#openidePrompt`, `runOpenIDEAgent` |
| **Composer modes** (Plan / Debug / Ask / Multitask) | **Thin alias** — only flips Cortex thinking mode + toast | `setOideMode` |
| **Model tier / think** | **Exists** (shared AirGPT globals) | `setOideModelTier`, `toggleOideThink` |
| **Cortex chip** | **Exists** | `toggleOpenIDECortex` → Assist/Deep/Idle via `/api/cortex/settings` |
| **Open Tabs** | **Exists** (local) | `syncOpenIDEAgentTabs`, Agent + file/browser tabs; **no durable server map** |
| **Right rail: Browser / Changes / Terminal / Files** | **Exists** | `openideWorkTab`; right rail starts **always collapsed**; open via **IDE ↗** |
| **Monaco editor** | **Partial** | CDN Monaco on file open; else `<pre>` fallback (`openIDEFile`) |
| **Terminal** | **Exists but not real PTY** | allowlisted `subprocess` via `/api/terminal/exec` |
| **Git panel + Create PR** | **Exists** | `loadOpenIDEGitBundle`, `openideCreatePR` → `gh pr create --fill`; PR btn only when dirty |
| **Write approve gate** | **Exists** | `renderOpenIDEApproval`, `approveOpenIDEWrite` / `rejectOpenIDEWrite` |
| **@ mentions** | **Exists** | `openideMentionPicker` → `/api/fs/find` |
| **/ skills** | **Partial** | placeholder text; arm via Settings `pendingSkillPack`; full slash UX elsewhere in AirGPT |
| **Settings** | **Host modal, not OpenIDE-owned** | `#settingsModal` in `index.html`; OpenIDE gear opens **invoke** panel |
| **Remote / phone sync of OpenIDE** | **Blocked by design** | host-only API prefixes in `clipdrop.py` |
| **Window management (native multi-window)** | **Not in product** | only SPA mode + rail collapse |

**Research-only (not product):** `D:\AirGPT\OpenIDE\research\superset\`, `research\orca\` — Electron/desktop reference clones for gap study.

---

## 2. OpenIDE APIs

Routed from `D:\AirGPT\clipdrop.py`; modules live in `D:\AirGPT\OpenIDE\` (root shims re-export).

### `workspace_api.py`
| Endpoint / capability | Function |
|----------------------|----------|
| `GET /api/workspace` | `get_workspace` |
| `POST /api/workspace/open` | `open_workspace` |
| `GET /api/fs/tree` | `list_tree` (lazy, skips heavy dirs) |
| `GET /api/fs/read` | `read_file` |
| `GET /api/fs/find` | `find_paths` |
| `POST /api/fs/write` / `patch` | `write_file` / `patch_file` (`apply` gate) |
| `POST /api/fs/checkpoint` | `checkpoint_create` |
| `GET /api/git/fingerprint` | `fingerprint` (**ThreadPoolExecutor**, 3s cache) |
| `GET /api/git/summary` | `git_summary` (parallel status+diff) |
| `GET /api/git/branches` · `POST /api/git/checkout` | `list_branches` / `checkout_branch` |
| Rules text | `rules_text` → `.airgpt/rules.md` or `AGENTS.md` via `invoke_registry` |

Also: `search_files`, `glob_paths` (used by agent tools).

### `cursor_bridge.py`
| Endpoint / capability | Function |
|----------------------|----------|
| `GET/POST /api/openide/backend` | `get_backend` / `set_backend` (`local` \| `cursor_local` \| `cursor_cloud`) |
| `GET /api/openide/last-run` | `last_run_info` |
| `GET /api/openide/ready` | Key Vault readiness + backend |
| Stream events | `run_cursor_events` (needs `CURSOR_API_KEY` + `cursor-sdk`) |
| Deep-link | `open_in_cursor_uri` / UI `openInCursor` |

**Note:** OpenIDE Run currently **forces `backend='local'`** in `runOpenIDEAgent` — Cursor SDK path exists in runtime but UI doesn’t select it on Run.

### `terminal_pty.py` (name oversells)
| Endpoint | Function |
|----------|----------|
| `GET /api/terminal/session` | `start_session` (in-memory session log, **not** a PTY) |
| `POST /api/terminal/exec` | `run_command` / `exec_in_session` |
| Allowlist | python/npm/node/pytest/cargo/go/git/gh …; no shell metacharacters; no `git push --force` |

### Agent / Cortex (shared, not OpenIDE-package)
- `POST /api/agents/{id}/run` → SSE from `agent_runtime.run_agent_events`
- `/api/cortex/settings|queue|pending|recipes|isolation|invoke`
- `/api/invoke/skills|rules` → `invoke_registry`

**Security:** all of the above are **host-only** (`_HOST_ONLY_PREFIXES` in `clipdrop.py`). Phone/LAN guests cannot drive OpenIDE.

---

## 3. Cortex run path

### Two “Cortex” layers (do not conflate)

```
OpenIDE UI
    │ SSE POST /api/agents/{id}/run
    ▼
AirGPT in-process brain
  agent_runtime.run_agent_events
  cortex_orchestrator (queue + serial worker)
  cortex_runtime (redact / isolation_status)
  agent_tools.TOOLS
    │ optional soft-fail HTTP
    ▼
D:\Cortex CortexOS sidecar (:8010)
  cortex_client.health / engine_* / secure_message / ledger
```

### AirGPT brain (what OpenIDE actually uses)
| File | Role |
|------|------|
| `D:\AirGPT\agent_runtime.py` | Multi-step tool loop; Thinking modes; write preview; `subagent_dispatch` |
| `D:\AirGPT\cortex_orchestrator.py` | Settings; `queue_run`; **single** `_active_run_id`; daemon tick **every 3s**; recipes JSON under `data/openforge/recipes` |
| `D:\AirGPT\cortex_runtime.py` | Secret redaction; `cortex_cloud_allowed`; isolation status |
| `D:\AirGPT\cortex_client.py` | Soft-fail client to CortexOS `:8010` (1.5s timeouts, 5s poller) |
| `D:\AirGPT\agent_tools.py` | Audited tool registry |
| `D:\AirGPT\invoke_registry.py` | Rules/skills catalog |

**Run path detail (`run_agent_events`):**
1. Idle → `deterministic_tick` only (memory thin + audit spotcheck), no LLM  
2. `cursor_local` / `cursor_cloud` → `cursor_bridge.run_cursor_events`  
3. Else local loop: inject rules + skill + memory + git fingerprint + `@file` → LLM JSON tool calls → tools → optional write_preview  
4. Deep parent may add `subagent_dispatch` (cap **2**); children **never recurse**; spawn = `queue_run(is_subagent=True)` then immediate `subagent_done: queued` (worker drains later, serially)

**Multitask UI:** queues one Cortex job **and** runs primary SSE — not true parallel agent orchestration.

### Native `D:\Cortex` (sidecar / DMS platform)
| Doc / area | State relevant to agents |
|------------|--------------------------|
| `ARCHITECTURE.md` | Honest: DAG **partial** (no Temporal, limited fan-out); WASM scaffold; A2A planned |
| `STATUS.md` (2026-07-23) | DMS F1–F7 shipped; O1 ontology; next O2; `@agent` chat dispatch still open |
| `CORTEX_COMPLETE_PLAN.md` | Deploy/security/RAG roadmap — platform, not OpenIDE |
| `AGENTS.md` | DMS subagent dispatch roles — not AirGPT OpenIDE |
| `netie/` | Import alias → `CortexOS.*` |
| `CortexOS/execution/dag_runner.py` | `run_dag` — **sequential** flatten of layered order (layers compiled but executed one node at a time) |
| `CortexOS/api/sidecar_routes.py` | Exact routes AirGPT `cortex_client` expects |

### What already exists for “speed & synchrony”
| Capability | Reality |
|------------|---------|
| Parallel git probes | `fingerprint` / `git_summary` ThreadPoolExecutor |
| Soft-fail sidecar | Short timeouts so chat doesn’t stall if CortexOS down |
| Subagent fan-out | Deep ≤2, **queued**, drained **one-at-a-time** by orchestrator |
| Token budgets | `token_budget` / `max_steps` in settings (defaults 1200 / 8) |
| Lean tool context | Truncated tool results back into loop |
| True parallel agents / shared timeline sync | **No** |
| Durable DAG / Temporal / parallel layer exec | **No** (ARCHITECTURE: partial; `run_dag` serial) |
| Streaming tool-call protocol parity with Cursor | JSON-in-text loop, not native function-calling |

`docs/STRATEGY_NEXT_PHASE.md` still lists **recipe DAG executor, MCP client** as parked relative to product ambition (subagents exist in minimal form now).

---

## 4. Window / multi-window / single-instance

| Concern | Current state |
|---------|---------------|
| Native multi-window IDE | **Not implemented** in product (research Electron code under `OpenIDE/research/superset` only) |
| OpenIDE “windows” | Single browser document; Agents vs IDE layout; collapsible rails; `#openide` history |
| Focus / open-in-repo | `openIDEWorkspace(path)`, recents `airgpt_ws_recents`, repo groups in left rail — **same SPA**, not OS windows |
| One-window-per-app | `apps_hub.probe` / `already_running` for **Hosted apps** registry — not OpenIDE window policy |
| Cross-tab sync of agent state | Runs/tabs in **localStorage** only; no BroadcastChannel / server session sync |
| Remote OpenIDE attach | Explicitly deferred (host-only APIs; “capability token later”) |

---

## 5. Settings / Preferences / Rules / Skills / Subagents

**Shell:** Cursor-like left nav in `#settingsModal` (`index.html`).

| Panel | Implemented? |
|-------|----------------|
| General / Profile / Appearance / Plan | **Yes** (local prefs, passcode, themes, license) |
| Agents | **Yes** — create + list via `/api/agents` |
| Models / Key Vault | **Yes** — BYOK fields + Key Vault modal |
| Git & PRs | **Thin** — links to OpenIDE + `gh auth status` |
| **Rules, Skills, Subagents** | **Yes (core)** — load/save rules & skills via `/api/invoke/*` + `/api/cortex/invoke`; Arm skill → `pendingSkillPack`; subagent UI is docs + locked “cap 2” checkbox |
| Tools & MCPs | **Stub** — static tool names; “MCP client UI is parked” |
| Hooks | **Docs-only panel** — describes approve/path jail/audit (no hook editor) |
| Browser & Network | **Redirect** to Connect/Tunnel |
| Indexing | **Redirect** to RAG / Memory |
| Beta | OpenForge + invoke probe |

**Backend:** `invoke_registry.list_skills|load_skill|save_skill|rules_context|save_rules|catalog`.

---

## 6. Remote / mobile control

| Piece | Path | What it is |
|-------|------|------------|
| LAN chat host | `clipdrop.py` port **8765** | Clipboard/chat over LAN/tunnel |
| WiFi helpers | `wifi_access.py` | mDNS `airgpt.local`, connect methods, diagnostics — **chat access**, not IDE remote control |
| Phone UI | `body.phone-client` in `index.html` | Compact composer for mobile **chat** |
| P2P photos | `p2p-drop.html` (`/p2p`, `/p2p-drop.html`) | Room-code photo drop — **not** IDE control |
| Hub peers / ACL | `/api/hub/peers/*` | Named peers, kick, rename |
| OpenIDE from phone | **Denied** | Host-only FS/terminal/agents/cortex |
| Orca-like remote IDE / SSH daemon / worktree remote | **Not in product** (only in `research/orca`) |

---

## 7. Explicit NOT YET IMPLEMENTED (vs modern Cursor / Claude Code / Orca-class)

Concrete gaps vs a Cursor-like + Claude Code agent IDE:

1. **Native desktop shell** — no Electron/main process, single-instance lock, OS multi-window, or “one window per repo”
2. **Real PTY / interactive terminal** — allowlisted batch commands only; no shell, splits, OSC7, session attach
3. **Full editor IDE** — Monaco CDN optional; no LSP, multi-file tabs persistence server-side, diffs editor, debugger, search UI beyond tree
4. **Background agent sessions as first-class** — UI runs are localStorage; orchestrator is serial 3s poll; no peek/attach, Agent teams, worktree-isolated agents
5. **True parallel multi-agent synchrony** — Multitask/Plan/Debug are thinking-mode aliases; subagents queue then wait; no shared live timeline cards (WORK.md still lists nested subagent timeline)
6. **Native tool-calling / schema parity** — JSON-in-text loop vs Cursor/Claude structured tools; WORK.md S5 still open
7. **MCP client + marketplace plugins as IDE primitives** — Settings panel admits parked; no ToolSearch
8. **Hooks editor / PreToolUse scripting** — policy hardcoded (approve_write, path jail, redact)
9. **Skills auto-invoke / rich `/` command palette in OpenIDE** — Settings arm + prompt placeholder; not Claude-style slash+auto
10. **Continue/resume for local Cortex** — Continue mostly Cursor `run_id`; local SSE runs don’t resume mid-loop statefully
11. **Cursor SDK as default OpenIDE path** — bridge exists; Run hardcodes `local`
12. **Remote IDE control from phone** — intentionally blocked; no capability-token remote OpenIDE
13. **Cloud Agents / Composer cloud UX** — optional `cursor_cloud` only if key+remote+SDK
14. **Durable recipe DAG executor wired to OpenIDE** — recipes list/default JSON exist; worker does not execute recipe DAGs as primary path
15. **CortexOS parallel DAG / Temporal / WASM sandbox** — documented partial/scaffold
16. **Codebase indexing inside OpenIDE** — RAG is separate AirGPT surface; no IDE-native semantic index panel
17. **Canvas / Artifacts as Open Tabs** — WORK.md still unchecked
18. **GitHub clone/auth polish under netie.ai** — WORK.md S4 open; clone via `gh`/`git` allowlist only
19. **Cross-window settings sync / focus-on-notification** — N/A without multi-window
20. **Orca remote daemon / WSL / SSH session model** — research docs only

---

### Quick “exists vs stub” cheat sheet

| Area | Exists | Stub / thin / research |
|------|--------|------------------------|
| Agents UI + Run + approve writes | ✓ | |
| IDE Files/Git/Browser/Terminal panes | ✓ | Terminal ≠ PTY; Monaco partial |
| Settings Rules/Skills | ✓ | MCP/Hooks UI stub |
| Subagents | ✓ queue ≤2 Deep | No parallel sync UI |
| Cursor bridge | ✓ module | Not used by default Run |
| WiFi / phone / P2P | ✓ for chat | Not OpenIDE remote |
| Native CortexOS | ✓ DMS/engine | Not OpenIDE brain |
| Superset/Orca multi-window | | Research trees only |

**Primary product docs:** `D:\AirGPT\OpenIDE\README.md`, `WORK.md`, `D:\AirGPT\docs\openforge.md`, `docs\STRATEGY_NEXT_PHASE.md`, `D:\Cortex\ARCHITECTURE.md`, `STATUS.md`.
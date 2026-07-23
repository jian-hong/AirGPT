# AirGPT Parking Lot — Master Build Order

> Updated: 2026-07-17 (OpenIDE Agents Surface plan) · See `docs/openforge.md` and `NEXT_UPDATE.md`

## Product map (locked)

| Surface | Role |
|---------|------|
| **Moat** | Clipboard ↔ chat ↔ phone, tunnel/LAN/P2P |
| **Cortex** | Agentic brain · Thinking modes Idle/Assist/Deep |
| **OpenIDE** | Chat → code · Monaco · Cursor SDK optional · human approve writes |
| **OpenForge** | Chat → chip · honest ngspice smoke · Netie-AI/OpenForge |

## Build phases

| Phase | Status | Focus |
|-------|--------|-------|
| 0 Honesty + naming | **shipped** | Nav split, parking lot, Connect path, Beta badges |
| 1 Cortex platform | **hardened** | Tool loop + nested JSON parse, thinking modes, queue worker claim/finish, @agent |
| 2 Chat + memory | **shipped** | Message queue, regen/edit hooks, memory tools |
| 3 OpenIDE | **hardened** | FS jail, Monaco, write_preview approve, @file picker, git panel |
| 4 Terminal + git | **hardened** | argv allowlist (no shell=True / no python -c), git status/diff APIs |
| 5 OpenForge chip | **honest** | Template + real ngspice smoke when installed; no fake "gated" |
| 6 Marketplace + moat | **partial** | auto-serve API, PWA manifest, spotlight hotkey |
| 7 Steal remainder | **partial** | Research upload, Usage CSV |
| 8 Business | **partial** | Admin exists; Stripe still deferred |
| 9 OpenIDE Agents Surface | **in progress** | **Source of truth → `OpenIDE/`** (Cursor-clone IA; see OpenIDE Cursor clone section) |
| 10 Launch + netie.ai merge | **in progress** | Scroll download dock · AirGPT+Space installer · shared Netie account · legal SSOT |

---

## Reality-check fixes (2026-07-16)

Critical bugs found by audit subagents and fixed this session:

- [x] Apply Patch no longer writes agent prose to disk — `write_preview` SSE + Approve → `/api/fs/patch|write`
- [x] Cortex queue worker claims run_id and finishes that row (no infinite duplicate runs)
- [x] Terminal allowlist: `shell=False`, block `python -c`, git subcommand allowlist
- [x] Tool-call parser: brace-balanced JSON (nested `params` work)
- [x] OpenForge honesty: `simulation_gated` only after ngspice smoke succeeds
- [x] cursor_bridge aligned to Cursor SDK message shape (`message.message.content`)
- [x] OpenIDE git panel + `@file` picker + event-delegated tree (no broken onclick paths)
- [x] Cortex Runs + Pending tabs
- [x] `allcheck.py` covers workspace / cortex / openide / openforge / agents

---

## Moat (keep sacred)

- [x] Connect path chooser (Tunnel / LAN / Hotspot)
- [ ] P2P fully integrated into Connect flow
- [ ] Clipboard large-image edge cases hardened
- [x] Spotlight hotkey (Ctrl+Shift+Space)
- [x] PWA manifest.json
- [ ] `/api/info` timeout under slow tunnel diag

## Naming / IA

- [x] OpenForge → chat-to-chip workspace
- [x] OpenIDE → code workspace
- [x] Cortex → agentic brain (sidebar + top tab)
- [x] Beta badges: Hosting, Research, Usage

## Cortex (exceed Open WebUI)

- [x] Native multi-step tool loop (nested JSON parse)
- [x] Wire web_search + session summarize into loop
- [x] Load skill_pack per agent
- [x] Thinking modes: Idle / Assist / Deep
- [x] Queued runs + background worker (claim/finish fixed)
- [x] In-chat `@agent` dispatch
- [x] Agent memory tools (add/search/forget)
- [x] Run history UI in Cortex panel
- [x] Pending queue visible in Cortex panel
- [ ] Checklist / recipe DAG engine (recipes file seeded; no executor yet)
- [x] Human gates UI (OpenIDE approve_write; Cortex still preview-first)
- [ ] MCP client UI
- [ ] OpenVertex verify second hop
- [ ] Channels-lite shared session

## OpenIDE (Cursor-like) — Phase 3 hardened core

- [x] Workspace bind + path jail FS APIs
- [x] File tree + editor (Monaco CDN) — dispose on reopen
- [x] Chat-to-code agent panel + SSE
- [x] Structured write_preview + Approve / Reject
- [x] Checkpoint API
- [x] cursor-sdk bridge module + backend switcher
- [x] Open in Cursor escape hatch
- [x] Terminal exec (hardened allowlist)
- [x] Git panel UI (`/api/git/status`, `/api/git/diff`)
- [x] `@file` mention picker (`/api/fs/find`)
- [ ] Repomix index button in UI
- [ ] Monaco DiffEditor widget (nice-to-have)

---

## Phase 9 — OpenIDE Agents Surface (stronger version)

> **Problem:** Today's OpenIDE is a full-page Monaco block that replaces Home chat.
> Pressing Build → OpenIDE should leave Home and enter a **dedicated Agents workspace**
> (Cursor Agents window tone), not a cramped three-column tool page.

### Product thesis

**OpenIDE = Cortex-governed Agents workspace with IDE dual-mode.**

| Layer | Owns |
|-------|------|
| **Cortex** | Brain: Idle/Assist/Deep, tool loop, queue, vault, audit, approve_write |
| **OpenIDE shell** | Surface: Agents timeline + IDE panels + brand morph entry |
| **cursor-sdk** | Optional executor (`cursor_local` / `cursor_cloud`) — never replaces Cortex gates |
| **Netie mark** | Governance brand in OpenIDE topbar (square geometry locked) |

Home stays clipboard/chat moat. Cortex top-tab stays agent-brain admin.
OpenIDE is the **builder runtime** where agents *act on a workspace*.

### Entry morph (press OpenIDE)

Do **not** instantly swap `#chat` HTML. Play overlay, then mount the surface.

| Beat | ms | Motion |
|------|-----|--------|
| 0 | 0 | Clone `#navOpenIDE` icon → fixed overlay at source rect |
| 1 | 0–420 | Morph expand to viewport center (ease-out-cubic), mild scale 1→~4.2 |
| 2 | 420–680 | Soft liquid-glass splash (radial frost pulse, ≤12% opacity, no purple) |
| 3 | 560–820 | Wordmark **"OpenIDE"** fades under logo (DM Sans 600) |
| 4 | 820–1400 | Logo + name FLIP up into topbar brand slot |
| 5 | 1400–1600 | Settle: Netie liquid-glass square replaces triangle mountain; `#appTitle` → OpenIDE; dim Home chrome |
| 6 | 1600+ | Reveal Agents Surface; remove overlay |

**Skip path:** `prefers-reduced-motion` → instant brand swap + surface mount (≤80ms).

**Files:** `index.html` (CSS keyframes + `playOpenIDEEntryMorph()`), assets under `video-assets/01-logos/netie/`.

### Brand lock (topbar)

- Replace `.brand-mark` mountain SVG with **Netie square-in-square** geometry from `netie-mark.svg`
- Rebuild **white** stroke + inner square as **liquid glass** (frost fill, soft rim highlight, translucent core) — geometry unchanged
- Title: **OpenIDE** (subtitle/status can stay Offline/Local · Free)
- Leaving OpenIDE (Home / Cortex / other nav) restores AirGPT triangle mark + "AirGPT"

### Mode switcher — Agents | IDE

Reuse `.workspace-switch` pattern (Home | Cortex):

```
[ Agents | IDE ]
```

| Mode | Left | Center | Right |
|------|------|--------|-------|
| **Agents** | Runs / pinned workspaces / agent list | Agent timeline (thoughts · tools · status · Continue) | Changes / Canvas / Approve stack |
| **IDE** | Files · Git (existing) | Monaco + `@file` composer | Diff Approve + terminal |

Bottom composer shared: project chip · prompt · Thinking mode · backend (`local` / `cursor_local` / `cursor_cloud`) · Multitask toggle.

### Feature map — Cursor Agents → AirGPT ports

| Cursor Agents cue | AirGPT port | Cortex theory |
|-------------------|-------------|---------------|
| Thought blocks ("Thought for Ns") | Map SSE `thinking` → collapsible Thought row | Assist/Deep emit thinking; Idle = deterministic tick only |
| Tool / finish rows | Map `tool` / `write_preview` / `done` | `agent_runtime` + `safe_tool_result` redaction |
| Continue working | Resume same `run_id` / `Agent.resume` when cursor backend | `cortex_orchestrator` queue + claim/finish |
| Multitask | Queue parallel runs (cap by Thinking mode) | Assist: 1 active; Deep: N≤3 queued; Idle: no dispatch |
| Model / backend picker | Existing `#openideBackend` + Cortex mode select | `AGENT_BACKEND` + `cursor_bridge.py` |
| Changes tab | Approve/Reject stack (already `write_preview`) | Human gate before disk |
| Canvas / doc pane | Right pane markdown/plan preview (read-only first) | Vault / session summary inject |
| Subagents | `subagent_dispatch` + `/subagent` queue; SSE `subagent_start`/`done` live (Deep ≤2; Assist 0). Nested timeline cards still open | Recipes DAG (still open) + `invoke_registry` |
| MCP tools | Parked until MCP client UI | Same allowlist / path jail |

**Landed (2026-07-23) — Unified Invoke:** `invoke_registry.py` (rules / skills / slash catalog), rules always inject into `agent_runtime`, `/skill` + `/rules` + `/subagent` in composer, `GET /api/cortex/invoke`, Cortex engine `specs().invoke` flag. Nested Agents Window cards for subagents still parked.

### Backend wiring (no new product brain)

**Keep:** `agent_runtime.run_agent_events`, `cursor_bridge.run_cursor_events`, path jail, approve APIs.

**Add / enrich SSE types for Agents UI:**

| Event | Purpose |
|-------|---------|
| `thinking` | Already — add optional `ms` duration |
| `tool` | Already — UI: name + truncated safe result |
| `write_preview` | Already — right pane Changes |
| `status` | Timeline header |
| `subagent_start` / `subagent_done` | **Live** (events emitted; nested timeline cards still P1) |
| `mcp_call` | P2 — when MCP client lands |

**Touch points:**

- `index.html` — morph, Agents Surface layout, Agents|IDE switch, timeline renderer
- `cursor_bridge.py` — richer message types (tool/thinking if SDK exposes); keep approve path local
- `agent_runtime.py` — duration on thinking; optional subagent yield
- `cortex_orchestrator.py` — multitask queue depth by Thinking mode
- `clipdrop.py` — only if new SSE fields need API docs

**Concrete sketches (illustrative, not final code):**

`agent_runtime.py` — gate the cursor backends through the same redaction + write_preview path instead of the current raw passthrough (today `run_agent_events` at the `backend in ("cursor_local","cursor_cloud")` branch just re-yields `cursor_bridge` events verbatim):

```python
if backend in ("cursor_local", "cursor_cloud"):
    import cursor_bridge, workspace_api
    cwd = workspace_api.get_workspace().get("root") or ""
    t0 = time.monotonic()
    for ev in cursor_bridge.run_cursor_events(prompt, cwd=cwd, backend=backend, model=model):
        if ev["type"] == "thinking":
            ev["ms"] = int((time.monotonic() - t0) * 1000)
        if ev["type"] in ("fs_write", "fs_patch") and require_approval:
            yield _write_preview_event(ev["type"], ev.get("params", {}), ev, run_id=run_id)
            continue  # never let a cursor-side write land without the same gate as local tools
        yield ev
```

`cursor_bridge.py` — accept `model` instead of the hardcoded `"composer-2.5"`, and stop collapsing every block into `token`:

```python
def run_cursor_events(prompt, *, cwd="", backend="", model="composer-2.5") -> Iterator[dict]:
    ...
    kwargs = {"model": model, "api_key": api_key}
    ...
    for message in run.messages():
        btype = getattr(message, "type", None)
        if btype == "tool_call":
            yield {"type": "tool_call", "name": message.tool_name, "params": message.params}
        elif btype == "tool_result":
            yield {"type": "tool", "name": message.tool_name, "result": message.result}
        elif btype == "thinking":
            yield {"type": "thinking", "text": message.text}
        elif btype == "subagent_start":
            yield {"type": "subagent_start", "id": message.id, "name": message.name}
        elif btype == "subagent_done":
            yield {"type": "subagent_done", "id": message.id}
        # ...existing assistant/text handling stays
```

`cortex_orchestrator.py` — swap the single `_active_run_id` lock for a capacity keyed by Thinking mode (Idle: 0, Assist: 1, Deep: ≤3):

```python
MAX_CONCURRENT = {"idle": 0, "assist": 1, "deep": 3}
_active_run_ids: set[int] = set()

def _worker_tick() -> None:
    settings = get_settings()
    cap = MAX_CONCURRENT.get(settings["thinking_mode"], 1)
    if len(_active_run_ids) >= cap:
        return
    ...  # claim next pending run_id, add to _active_run_ids, spawn a thread, discard on finish
```

`index.html` — SSE event → timeline row map (new types are additive, existing `thinking`/`tool`/`write_preview`/`status`/`done`/`error` keep working unchanged):

```js
const TIMELINE_ROW = {
  thinking:'thought', tool:'tool', tool_call:'tool-call', write_preview:'changes-card',
  subagent_start:'subagent-open', subagent_done:'subagent-close', mcp_call:'mcp-row',
  status:'header', done:'footer', error:'error'
};
```

### Asset work

- [ ] `netie-mark-glass.svg` — square geometry + liquid-glass white (lock in `01-logos/netie/LOCKED/`)
- [ ] OpenIDE wordmark lockup for morph beat 3
- [ ] Optional OpenIDE nav icon = glass square (family with Netie) — keep Build section label "OpenIDE"

**Technical note — two renders, one geometry.** `backdrop-filter` only frosts real DOM content behind it; a flat `<img>`/raster export of an SVG cannot sample the page behind itself. Ship both from the same `viewBox 0 0 512 512` source:

1. **Live render** (topbar + morph clone) — inline the square-in-square as a CSS `clip-path` (outer frame path + inner square path, scaled from the 512 grid) on a real `div.brand-mark-glass` with `backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate))` + a soft inset highlight gradient. This is what actually looks "liquid glass" over the animated topbar background.
2. **Baked fallback** (`netie-mark-glass.svg`, used for favicon/OG/anywhere a live DOM layer isn't available) — simulate frost with layered semi-transparent white fills + `feGaussianBlur` + a diagonal `linearGradient` rim highlight, since it can't sample anything behind it.

Keep the outer frame stroke ratio and inner square size identical to `netie-mark.svg` (locked geometry) in both renders — only the fill treatment changes.

### Checklist — Phase 9

**P0 — ship the surface**

- [ ] Entry morph overlay (beats 0–6) + reduced-motion skip
- [ ] Topbar: Netie glass mark + OpenIDE title while in surface; restore on exit
- [ ] Agents \| IDE `workspace-switch` sibling (do not remove Home \| Cortex)
- [ ] Agents mode: 3-pane shell (list · timeline · Changes)
- [ ] Wire existing SSE → timeline Thought / Tool / Done rows
- [ ] Changes pane = Approve / Reject (`write_preview` path unchanged)
- [ ] IDE mode embeds current Monaco / tree / terminal (no feature regression)
- [ ] **Governance parity:** wrap `cursor_local` / `cursor_cloud` through redaction + `write_preview` (today cursor backends bypass approve gate in `agent_runtime.py` ~209–225)

**P1 — stronger agents**

- [ ] Continue working (resume run / follow-up prompt on same session)
- [ ] Multitask toggle → orchestrator queue depth
- [ ] Thought duration badges
- [ ] Monaco DiffEditor in Changes (nice)
- [ ] `subagent_*` SSE + nested timeline cards
- [ ] cursor_bridge: surface tool/thinking blocks when SDK provides them
- [ ] Persist backend on `agent_runs` + show badge on timeline/Runs
- [ ] Idle-mode Pending hint (“queue frozen — leave Idle”)
- [ ] Recipe step executor (reuse `agent_tools` + `approve_write` gates)

**P2 — ecosystem**

- [ ] MCP client UI in Agents tools strip
- [ ] Canvas publish / share plan pane
- [ ] Recipe DAG executor driving OpenIDE checklists
- [ ] Repomix index button

### Explicit non-goals (Phase 9)

- Do not replace Cortex with Cursor cloud as the product brain
- Do not remove path jail or Approve/Reject
- Do not morph from VS Code activity-bar "build" icon — morph from **sidebar Build → OpenIDE**
- Do not invent aviation / purple AI chrome
- Do not block Home forever inside OpenIDE — exit restores AirGPT brand + Home chat

---

## OpenIDE Settings — Cursor left-nav clone (2026-07-23)

> Spec canvas: `canvases/openide-settings-cursor.canvas.tsx`
> Research: Cursor 2.4/2.5 Skills+Subagents+Customize; Claude Code CLAUDE.md / skills / bg subagents.

### Landed
- [x] Settings shell: left nav (General · Profile · Appearance · Plan · Agents · Models · Git · **Rules, Skills, Subagents** · Tools · Hooks · Network · Indexing · Beta)
- [x] Create Rule → `POST /api/invoke/rules` → `.airgpt/rules.md` or `AGENTS.md`
- [x] Create Skill → `POST /api/invoke/skills` → `data/skills/<id>.md` + Arm `/skill`
- [x] Create Agent → `POST /api/agents` with skill_pack
- [x] Gear / Settings opens Cursor-like Settings (OpenIDE opens invoke panel)
- [x] Privacy: local-first (no Cursor-style cloud training share)

### Still open
- [ ] Playwright smoke: Settings → create skill → catalog lists it
- [ ] MCP enable/disable UI (client still parked)
- [ ] Hooks editor for `.airgpt/hooks.json`
- [ ] Worktrees / Cloud Agents sections (N/A local — keep stub)
- [ ] Auto-help wizard: “describe workflow → draft skill” LLM assist

> Spec canvas: `canvases/openide-cursor-clone.canvas.tsx` (pretty TSX · open on right of OpenIDE).
> Differentiator: **fully free** + **Cortex Engine** (host models / free APIs). Same agent UX logic as Cursor.
> **Code source of truth:** [`OpenIDE/`](OpenIDE/) — UI in `OpenIDE/ui/`, backend modules + `WORK.md` there; root shims only.

### Landed (S0–S3 partial)

- [x] Remove composer clutter: `@` / Help / Keys buttons
- [x] Agents | IDE toggle (was Cortex | IDE)
- [x] **New Agent** button + empty-state CTAs: Browse · New folder · GitHub · Auto repos
- [x] New Agent stays highlighted until workspace bound / run starts
- [x] Left **Repositories** group from recents + Add folder
- [x] Right rail: **Open Tabs** + **On {repo}** · Changes · Browser · Terminal · Files · IDE ↗
- [x] Runs inject git `branch@head` + Cortex invoke hint; `skill_pack` + Multitask queue; `subagent_*` transcript lines
- [x] Unified invoke already landed (`invoke_registry`, `/api/cortex/invoke`)
- [x] **Density pass**: compact New Agent empty · repo nested agents · header/`repo` `+` = New Agent (not add path) · Create PR hidden until dirty · Open Tabs sync · runs persist localStorage

### Still open (slice carefully)

**S4 — GitHub + netie.ai**
- [ ] Harden clone destination under netie.ai workspace convention
- [ ] Push-help flow after auth (never type credentials — key_vault law)
- [ ] Link detection when user pastes repo URL in composer

**S5 — Research → parking then implement**
- [ ] Prompt engineering layers (Rules → Skill → Git FP → Tools) doc + tune
- [ ] Load / token budget / tool-loop timing coalescing
- [ ] API request scheduling for orchestrator + multitask depth
- [ ] Tool-calling schema parity checklist vs Cursor Agents

**UI polish**
- [ ] Nested subagent timeline cards (events live; cards open)
- [ ] Persist repo→agent map beyond localStorage recents
- [ ] Canvas files appear as Open Tabs when opened from agent
- [ ] Further visual renew vs Claude Code (fonts/chrome) once density feels right in daily use

### Implementation order

1. ~~S0 IA chrome~~  
2. ~~S1 repos sidebar~~  
3. ~~S2 right rail~~  
4. ~~S3 Cortex wire (partial)~~  
5. S4 GitHub/netie.ai  
6. S5 research docs + timing  
7. Nested cards / MCP  

### Explicit non-goals (Phase 9)

- Do not replace Cortex with Cursor cloud as the product brain
- Do not remove path jail or Approve/Reject
- Do not morph from VS Code activity-bar "build" icon — morph from **sidebar Build → OpenIDE**
- Do not invent aviation / purple AI chrome
- Do not block Home forever inside OpenIDE — exit restores AirGPT brand + Home chat

### Legacy morph / brand order (still open)

1. Assets: liquid-glass Netie mark SVG  
2. Morph + brand swap (no layout change yet)  
3. Timeline renderer polish on existing SSE  
4. Monaco DiffEditor in Changes  
5. Nested subagent cards + MCP  

### Demo capture note

Video checklist: capture morph once @1440p60 (uncut), then Agents timeline + Approve, then Agents↔IDE toggle — for Higgsfield underlays keep screens as **real UI** only.

## OpenForge (chat-to-chip)

- [x] Design API + netlist + SVG schematic
- [x] Marketplace module enables pipeline
- [x] Honest ngspice smoke gate (when installed)
- [ ] Vendor Netie-AI/OpenForge full ngspice AC/transient metrics
- [ ] Cortex-driven design iteration recipes

## Chat UX

- [x] Message queue while streaming
- [x] Cancel / stop (existing stream abort)
- [x] Regenerate / edit helpers
- [ ] Markdown LaTeX polish
- [ ] Multi-model compare / arena
- [ ] Notes pane
- [ ] `#` doc inject in composer

## Marketplace / Hosting

- [x] auto-serve API (`/api/marketplace/auto-serve`)
- [x] Hub panel — Coherent Access graph, team join codes, per-peer ACL
- [x] Marketplace meta tabs — LLM / Agents / Skills / Tools & Apps
- [x] Colibri runtime on Hosting only (not Marketplace LLM card)
- [x] Apps hub — press-to-activate peers (`apps_registry.json` / `/api/apps`) unique ports
- [x] LTX-2 video generator (mock + cloud + local hooks) · `/api/video/*` · sidebar Video
- [ ] Job progress UI polish
- [x] Usage CSV export
- [ ] One-click GGUF auto-start process manager
- [ ] Clone Lightricks/LTX-2 into `third_party/LTX-2` + GPU distilled smoke
- [ ] Wire `LTX_API_KEY` cloud path on a real account

## Research / Memory

- [x] Research paper upload UI
- [ ] PDF parse pipeline
- [x] Memory tools in agent runtime

## Business / Admin

- [ ] Admin CRM completion
- [ ] RBAC / groups
- [ ] Filters / PII pipes
- [ ] Encrypted backup
- [ ] Stripe (deferred in NEXT_UPDATE)

## Explicitly deferred

- Hosted Personal AI without BYOK
- Qdrant / mem0 cloud
- Full Cortex DMS in EXE
- Always-on reasoner KG DB
- K8s / Redis multi-node
- Video calls

## Port registry (locked — do not collide)

| App | Port |
|-----|------|
| AirGPT | 8765 |
| DMS v1 UI | 3000 |
| Cortex / DMS v2 | **8010** |
| vLLM | 8001 |
| Colibri | 8002 |
| LTX-2 | 8020 |
| Ollama | 11434 |
| SGLang | 30000 |
| Qdrant | 6333 |
| Scroll World | 8801 |

Source of truth: `apps_registry.json`.

## Cortex Nav Slices (2026-07-22)

| Slice | Status | What |
|------|--------|------|
| **P0** | **Done** | Settings waitlist/license `.side-search` inputs vertically centered; license/waitlist buttons height-matched |
| **1** | **Done** | OpenIDE Cortex agent window — Folder/Branch/Modes/tiers, IDE↗ open-only, local backend |
| **2** | **Done** | OpenIDE auto-collapse app left sidebar; logo click/hover back to AirGPT |
| **3** | **Done** | Drop +New chat; Chats=smart new chat; Search+Day beside Chats; Home\|Cortex top; hide Chats/Projects on Cortex select **or hover** Agents/Cortex |
| **4** | **Done** | Section label Agents; Cortex=agent chat+hints; View more under Apps → catalog |
| **5** | **Done** | Catalog/view-only pages hide composer; clipboard/chat containers stay isolated |
| **6** | **Done** | Settings/Connect toggles right panel collapse |

**Padding polish (2026-07-22 audit):** side-nav top spacing, workspace-switch, chats-row icons, nav-label gaps, cortex-agent-home, settings field/license/waitlist button heights.

**Parked (old Slice 1 follow-ups):** repos filter, marketplace scrape, subagent popup, auto-checkpoint.

## Next session prompt

> Keep Apps hub + LTX-2 green. Smoke Cortex Nav Slices 2–6 (sidebar, OpenIDE collapse, Agents catalog). Optional: clone LTX-2 locally and smoke distilled on RTX 4070; set `CORTEX_API_URL=http://127.0.0.1:8010` in env.local.

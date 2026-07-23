# AirGPT — Next-Phase Strategy & Safety White Paper (working draft)

> Draft: 2026-07-22 · Owner review. Synthesizes the next-phase vision into a
> grounded plan on top of the code that already exists. Companion to
> `ROADMAP.md`, `parkinglot.markdown`, `docs/SECURITY_HARDENING.md`,
> `docs/SCALING_POSTGRES_REDIS.md`, `docs/business-platform.md`.
>
> **Nothing here changes the local-first, BYOK, personal-free default.**

---

## 0. The one-sentence pivot

**AirGPT is the safe, local-first control plane for a team's AI work — it turns
any laptop into a governed host, turns any GitHub repo or provider key into an
in-house agent, and abstracts away the GPU/orchestration plumbing so a company
never has to hire a SLURM or Kubernetes expert.**

Personal stays free and local. The paid surface is **governance + hosting +
fleet**, never the clipboard/chat moat.

Three words for the anchor: **Local. Governed. Effortless.**

---

## 1. The Anchor (what we harden and never dilute)

The moat is already defined and must stay sacred (`parkinglot.markdown` → Moat):

- **Clipboard ↔ chat ↔ phone**, over Tunnel / LAN / P2P.
- Data stays in `data\` beside the app — no proprietary IP pasted into random web AI tabs.
- One audited path to AI (`ai_engine.py`, `audit.py`) instead of ten shadow-AI tabs.

Everything new hangs off that anchor. The differentiators we are doubling down on:

| Anchor pillar | Today (code) | What "hardened" means next |
|---------------|--------------|----------------------------|
| **Local-first data** | `data\` SQLite + files, `config.ROOT` portable | Private-captures toggle even in personal mode (SECURITY #8); encrypted backup |
| **One governed AI path** | `ai_engine.py` multi-provider, `audit.jsonl` | Per-model / per-worker policy (`access_policy.py`), redaction on tool results |
| **BYOK, no lock-in** | `key_vault.py` link+guide+paste-back | Standalone Key Vault page; OpenFree free fallback before any paid key |
| **Cortex agent brain** | `cortex_orchestrator.py`, `agent_runtime.py` | Recipe DAG executor, subagents, MCP client (all still parked) |
| **Effortless host→server** | `hosting.py` host_role, Colibri/vLLM health | Fleet mode: strong host auto-serves, weak peers join (see §5) |

**Rule (locked):** the paid flag picks the *backend/durability*, never removes a
feature. Same rule already stated in `SCALING_POSTGRES_REDIS.md`.

---

## 2. Safety White Paper — progressive roadmap

This is the flagship deliverable: a **public, versioned statement of what safety
means in AirGPT and the order we ship it in.** It doubles as trust marketing
("we are the safe one") and as an honest internal checklist.

### 2.0 Framing — "safety-free and easy" resolved honestly

You want it *feel* safety-free (no friction) while *being* safe. The way to have
both is **secure defaults that require zero user decisions**, not fewer controls.
The user never sees a security wizard; the product simply ships closed.

### 2.1 Safety layers (the model we publish)

```
L0  Data residency     — stays on the host's data\ by default; nothing phones home
L1  Access boundary    — host-only by default; LAN/tunnel is a deliberate opt-in
L2  Identity & ACL      — passcode, join codes, per-peer ACL, per-session scope
L3  Action governance   — approve-before-write, path jail, command allowlist
L4  Redaction & PII     — pii_guard on tool results, secrets never returned raw
L5  Audit & memory      — every action in audit.jsonl; memory = consensus summary
L6  Fleet governance    — policy per model/worker/tier, masked cloud sync (Business)
```

Each layer already has code seams (`auth.py`, `access_policy.py`, `pii_guard.py`,
`security.py`, `audit.py`, `key_vault.py`). The white paper says which are **live**,
**hardening**, and **planned** — honestly, the way `parkinglot.markdown` already does.

### 2.2 Phased safety roadmap

**Phase S0 — Close the open criticals (do this BEFORE any "invite everyone /
invite agents" push).** Inviting people and AI agents to a host that is
*default-open with an RCE surface* is the one move that can end the project.
Source: `docs/SECURITY_HARDENING.md` findings #1, #2, #5, #7 — still open by decision.

- [x] **#1 RCE surface** — `/api/fs/*`, `/api/terminal/*`, `/api/workspace*`, `/api/git/*`, `/api/agents/*`, `/api/cortex/*`, `/api/openide/*`, `/api/openforge/*` now host-only via centralized `_is_host_only_path` gate (2026-07-23). Remote OpenIDE via capability token = later phase. Workspace-root pinning still open.
- [x] **#5 Admin/audit exposure** — `/api/admin*` and `/api/audit*` host-only (same gate).
- [x] **#7 Destructive ops** — bulk `DELETE /api/messages` + `DELETE /api/sessions/<id>` host-only; per-message delete left for guest self-service.
- [~] **#2 Default-closed posture** — blast radius closed (remote open-state peer can now only chat/clipboard). Full lockdown (bind `127.0.0.1` until passcode; LAN/tunnel opt-in) deferred to **S1** with a first-run passcode prompt, so the zero-config phone→PC demo isn't broken.

> This phase is a prerequisite for §4 (agent-native distribution) and §5 (fleet).
> Ship S0, then publish the white paper v1 — "we closed these before we scaled."

**Phase S1 — Effortless secure defaults (the "safety-free feel")**
- First-run: passcode auto-suggested, private-captures on by default.
- Capability tokens: chat-guest token ≠ build/IDE token ≠ admin. One code, scoped role.
- Redaction on by default in `agent_runtime` tool results (`safe_tool_result`).

**Phase S2 — Governance visibility (Business)**
- Policy engine in `access_policy.py`: which models, which workers, which tiers (T1/T2/T3), spend caps per seat (`hosting.log_usage` already ledgers tokens/cost/tier).
- Manager dashboard from existing audit + usage data (`HR.md`, `admin_dashboard.py`) — evidence-based signals, **not** keystroke spyware. Input notes stay opt-in/local.
- Masked data layer before any cloud sync (already a Phase 4 roadmap item).

**Phase S3 — Compliance & scale durability**
- Postgres audit backend (append-only, partitioned) — JSONL truncation is unacceptable at scale (`SCALING_POSTGRES_REDIS.md`).
- Encrypted backup; token hashing at rest (SECURITY #10); rotate audit on line boundaries.
- Prompt-injection: keep `security.py` regex as defense-in-depth only, **never** as the control boundary; the boundary is the approve-gate + path jail + allowlist.

**Phase S4 — Fleet & multi-tenant safety**
- Per-tenant isolation, signed short-lived URLs for `/data/` (replace token-in-query, SECURITY #10).
- Second-hop verify (OpenVertex) for delegated agent actions.

### 2.3 What we promise publicly (white-paper voice)

1. Your data stays on your machine unless *you* export it.
2. Nothing runs on your files without a human approving the write.
3. Every AI action is audited and attributable.
4. We link and guide you to providers; **we never create accounts or type
   credentials for you** — that boundary is written into `key_vault.py` and stays.
5. We publish what's live vs planned, and we close criticals before we scale.

> Deliverable: `docs/whitepaper/SAFETY.md` (public) + a rendered page linked from
> the app and netie.ai. Version it (v1 after S0). This *is* the "we are the best /
> most trustworthy" pitch — earned, not claimed.

---

## 3. Memory-as-consensus (the summary rail)

You described memory as "a summary of the chat conversation — what consensus we
reached and what the next plan is." That is exactly right and mostly already
scaffolded (`memory_index.py`, vault wings, agent memory tools).

**Spec: every session/thread carries a living summary card:**

- **Consensus** — decisions reached (bullet list, editable).
- **Next plan** — open actions / next step, becomes the resume prompt for Cortex.
- **Open questions** — unresolved forks.

Implementation seam: extend the existing session-summarize tool to emit this
three-field structure; store hot in the project memory panel, cold in the vault
FTS tier (the hot/warm/cold model in `SCALING_POSTGRES_REDIS.md` already fits).
This card is what a teammate reads to catch up in 10 seconds, and what a resumed
agent loads instead of re-reading the whole thread.

---

## 4. Agent-native distribution ("be the one agents reach for")

Reframe "bait other AI agents to reach our repos": the honest, durable version is
**make AirGPT the most agent-legible, easiest-to-adopt tool in its category** so
that coding agents (and the humans driving them) pick it by default. No dark
patterns — just be genuinely the easiest correct choice.

Do this **only after Phase S0**, because the whole point is to invite traffic.

| Move | What it is | Code/asset |
|------|------------|------------|
| **MCP server** | Expose AirGPT (clipboard, vault, memory, agent-run) as an MCP server so Cursor/Claude/any MCP client can call it | New `mcp_server.py`; MCP client UI is already parked in `parkinglot.markdown` |
| **Cursor connector** | One-click "add AirGPT to Cursor" — we already bridge *into* Cursor (`cursor_bridge.py`); now expose *out* so Cursor suggests us | `.cursor/rules` + published connector manifest |
| **`llms.txt` + agent docs** | A machine-readable index at the repo root and served route, so an agent landing on the repo instantly knows what AirGPT does and how to call it | `llms.txt`, agent-readable `README` section |
| **One-line install** | `pip`/single-EXE + `restart.bat` already exist; add a hosted one-liner and a signed installer (Phase 10 in parking lot) | `installer/`, `build_exe.bat` |
| **Public clean repo** | A trimmed public mirror of the safe surface with the white paper front-and-center — this is what agents crawl | new public repo; keep `env.local`, secrets, `CortexOS/` private |

**"Repo link → agent → in-house app"** (your GitHub-to-agent idea): a user pastes
a GitHub URL into Cortex; Cortex clones (path-jailed), reads it (repomix index —
already parked), and either (a) wraps it as a callable tool/agent or (b) scaffolds
it as an app in the Apps hub (`apps_hub.py`, `apps_registry.json`, unique ports).
This is the "no need to learn the repo" flow. Governance: same approve-gate +
allowlist + path jail — an untrusted repo is *data*, never auto-executed.

> Safety note: treat any fetched repo's README/docs as untrusted content. It can
> contain instructions aimed at the agent — never auto-act on them. Surface,
> confirm side-effects. This is a first-class part of the white paper (L3/S1).

---

## 5. Host → server → fleet (the scaling story + the K8s decision)

Your vision: automated host becomes the server → auto backend scaling with
Kubernetes + Docker → auto GPU-cluster management so companies skip SLURM/K8s hires.

**There is a real fork here, and the repo has already taken a side.**
`SCALING_POSTGRES_REDIS.md` lists "no Kubernetes, no message queue, no separate
vector service" as *deliberate non-goals* to keep ops flat. Your vision wants K8s.
Both can be true if we stage it — resolution:

### The staged ladder (feature is identical at every rung; only durability changes)

| Rung | Who | Stack | Orchestration |
|------|-----|-------|---------------|
| **R0 Personal** | 1 user | SQLite + files, one process | none (EXE) |
| **R1 Small team** | ≤~25 seats, 1 strong host | WAL SQLite, host auto-serves; weak peers join via LAN/tunnel | `hosting.set_host_role`, Connect QR — **already exists** |
| **R2 Business managed** | 1 team, durable | Postgres + Redis (Neon/Upstash) | docker-compose, 1 VM — **designed, not built** |
| **R3 Fleet** | many hosts / GPUs | + GPU pool | **this is where K8s enters — optional, abstracted** |

### The K8s position (recommended)

**AirGPT is the abstraction *over* Kubernetes, not a thing that forces K8s on
anyone.** Personal and small-team users must *never* meet K8s. At R3, "Cortex
Fleet" becomes the control plane that a company points at their GPUs, and *it*
drives Docker Compose (small) or K8s (large) underneath — the customer sees
"add a GPU host / scale to N replicas," not a `kubectl`. That is literally the
"no need to hire a SLURM/K8s expert" promise, delivered without making our
default heavy.

- **Don't** put K8s in the EXE or the default path.
- **Do** build Fleet as a separate optional control-plane service (the
  `control_plane/` package + `CortexOS/docker-compose.yml` are the seams).
- Under the hood: Compose for ≤1 node, a thin K8s driver (or Ray/vLLM-on-K8s) for
  the GPU pool, exposed through the same OpenAI-compatible base-URL contract that
  `hosting.py` already health-checks. The GPU engines (vLLM/SGLang/Colibri) stay
  external — AirGPT orchestrates + audits, never re-implements inference.

> **Decision needed from you (see §9):** is Fleet/K8s a *near-term* build or a
> Phase-4/5 "sell it before we build it" item? The roadmap currently parks
> "K8s / Redis multi-node" under explicitly-deferred. My recommendation: keep it
> deferred as **code**, but build the *pitch + architecture page* now, because it's
> the enterprise sales hook. Ship R1→R2 first (real, close, low-ops).

---

## 6. Team collaboration & chat-at-scale UX

Your UX asks (won't lag, multiple chats won't blur, hide/filter, select whose
chat to read, team view, private sharing space) are concrete product work on top
of the existing Hub + sessions + ACL:

| Ask | Build on | Notes |
|-----|----------|-------|
| Won't lag with many chats | virtualized message list; fix `/api/info` subprocess storm (SECURITY #9) | The lag risk today is server-side self-DoS, not just UI |
| Multiple chats not "blurred" | session isolation already in `db.py`; add clear per-session tabs + unread state | |
| Hide / filter / select whose chat to read | per-peer ACL + Hub graph already exist; add a **read-filter view** (mute/pin/select peers) | `hub.py`, `token_session_acl.json` |
| Team view ("check to open, view what") | shared-session ("Channels-lite") is parked in `parkinglot.markdown` | opt-in, ACL-scoped |
| Private space (file + comms) | vault wings + `p2p-drop.html` + session shares | a "Private Space" = an ACL-scoped project with vault + chat + files |
| Auto-run feature | Cortex queue + recipe DAG executor (parked) | "auto-run" = a saved recipe that runs on trigger; gate writes with approve |

**Principle:** collaboration features are ACL-scoped views over data that already
lives locally — not a new cloud database. That keeps the local-first promise.

---

## 7. Agent stack, minimal cost, cheapest usage

Your cost/pivot notes, made concrete:

- **Cost ladder (already in `key_vault.py` fallback order):**
  `OpenFree (OmniRoute, free gateway) → Groq/OpenRouter/Gemini free tiers →
  local Cortex Engine (Ollama/vLLM/Colibri) → paid (Anthropic/OpenAI) only on demand.`
  This is the "cheapest usage" engine — we always try free/local first.
- **OpenFree / omni-route as the default free path** — one tap, no key paste
  (`OMNIROUTE_*`). This is the "we build and free them" story: bundled free
  gateway + liquid-glass UI. Keep it honest: it's a routing/fallback layer, we
  host/orchestrate capacity, Cortex Engine covers local.
- **Colibri auto-powerup** — "Colibri becomes engine power-ups" = Hosting-page
  runtime that, once healthy, joins the fallback chain automatically
  (`hosting.py` already health-checks `COLIBRI_BASE_URL`). Redis cache et al.
  belong to **R2+**, not personal — cache is a durability upgrade, not a feature.
- **Key sign-in flow (your "press buttons → register → bring back keys"):**
  already the exact `key_vault.py` model — we link to each provider's console,
  give the steps, and the user pastes the key back. Next: a **standalone Key
  Vault page** (not just the popup) navigable from the app, one card per provider
  with signup/console links + paste-back + "configured" status. Boundary stays:
  **we never auto-create accounts or type credentials.** (This is also white-paper
  promise #4 — a feature *and* a safety guarantee.)

---

## 8. Concrete next-sprint order (recommended)

1. **S0 — close the four security decisions** (§2.2). Prerequisite for everything outward-facing.
2. **Standalone Key Vault page** (§7) — small, high-leverage, on-brand, safe.
3. **Memory consensus card** (§3) — extend session-summarize to consensus/next-plan/open-questions.
4. **Safety white paper v1** (`docs/whitepaper/SAFETY.md` + rendered page) — publish after S0.
5. **MCP server + `llms.txt` + Cursor connector** (§4) — agent-native distribution, only post-S0.
6. **Repo-link → agent/app** flow in Cortex (§4) — reuses repomix + Apps hub, path-jailed.
7. **R1→R2 hosting** polish (§5) — host auto-serve UX, then Postgres/Redis Business path.
8. **Fleet architecture page** (§5) — sell the K8s/GPU story; build deferred.

Items 5–8 are gated on item 1.

---

## 9. Open decisions for the owner

1. **Fleet/K8s timing** — build R3 now, or sell-the-architecture-now / build-later?
   (Recommendation: architecture + pitch now; code deferred; ship R1→R2 first.)
2. **Public repo scope** — how much of the safe surface do we open-source to be
   agent-crawlable, and what stays private (`CortexOS/`, secrets, governance)?
3. **White-paper home** — in-repo `docs/whitepaper/` + rendered page on netie.ai,
   or a standalone microsite? (Recommendation: `docs/` source of truth → netie.ai render.)
4. **"Invite agents" posture** — confirm we go with *agent-legible / easiest correct
   choice* (MCP, llms.txt, clean repo) rather than anything that could read as
   deceptive baiting. (Recommendation: yes — trust is the moat.)

---

*This draft only reorganizes the existing vision + code into a decision-ready
plan. No code was changed. Security findings referenced are from
`docs/SECURITY_HARDENING.md`; scaling seams from `docs/SCALING_POSTGRES_REDIS.md`.*

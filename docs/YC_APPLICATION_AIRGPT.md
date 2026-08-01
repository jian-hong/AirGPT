# YC Fall — AirGPT application draft (Track A + Multiplayer AI)

**Pivot:** AirGPT is the product. Netie Space is a sibling front door, not the company story.  
**OpenVault** is the custody / route / ship layer that makes small software and shared agents safe.  
**Cortex** is the orchestration brain (can stay named lightly in copy as “the agent engine”).

**Thesis (say this before every form answer):**

> AirGPT turns any laptop into a multiplayer AI host — one live agent room your team can join by QR — and OpenVault is the cloud layer for the small software that room ships: keys, health, route/fallback, access, and one-click deploy under the same permissions.

---

## 0. One-liner (company / product)

**AirGPT is the Google Docs moment for AI agents: one shared live session, host-controlled access, local memory as system of record — and OpenVault makes whatever the team builds as easy to ship and share as a Doc.**

Shorter:

**Multiplayer agents on your laptop. Small software that ships with the same permissions.**

---

## 1. What are you building? (YC form)

We are building **AirGPT** — a local-first host for team AI work — and **OpenVault**, the companion control plane that holds keys, routes models, gates deploy, and ships the tiny tools agents build.

Most AI products are single-player chat tabs. AirGPT is the opposite: a **host machine** that teammates join over tunnel QR (phone, iPad, laptop). Everyone drops into the **same live agent session**, watches it work, redirects it, and hands work off — like crowding around one colleague, not forwarding a thousand private ChatGPT threads.

The same access model that governs the chat (**Read only / Use Host AI / Use Own AI / Can edit**) governs the **projects and shipped tools**. That is how we answer two YC RFS at once:

| RFS | AirGPT + OpenVault answer |
|-----|---------------------------|
| **Multiplayer AI** (Epstein) | One room, one agent, many humans. Presence, ACL Hub, token ledger, emergency AI cut-off. Share by QR — not a read-only transcript link. |
| **Cloud for Small Software** (Koomen) | Agents already make purpose-built tools trivial to *build*. OpenVault deletes Big Cloud complexity for *deploy + share*: encrypted Key Vault, FreeRoute auto-fallback, API health / access resolve, FreeBuild ship, same ACL as the chat. |

We started this as a weak-worker automation stack: clipboard ↔ chat ↔ phone sync, audited local AI instead of shadow ChatGPT tabs. The product insight is larger: **the host is the unit of collaboration**, and **custody (OpenVault) is the unit of trust**.

---

## 2. Problem

### Multiplayer AI
Teams already collaborate on docs, designs, and tickets. AI is still solitary. You prompt alone; the best “share” is a frozen transcript. Long-running agents (hours → weeks) make solo threads worse — the work needs watchers, interruptors, and handoffs.

### Cloud for Small Software
Agents can now build personal / team tools in an afternoon. Incumbent clouds (AWS/Azure) were designed for Big Software: many users, ops teams, IAM sprawl. Small software needs Google-Doc simplicity: share, permission, and ship without a platform engineering department. Auth, customize-the-runtime, and “let nontechnical people share arbitrary code safely” are still unsolved.

### Why both in one product
Small software without multiplayer is a private toy. Multiplayer agents without a ship path leave the team stuck in chat. **The conversation and the artefact must share one permission surface.**

---

## 3. Solution — how AirGPT + OpenVault fit

```
Teammate scans QR
        ↓
   AirGPT Host (laptop)     ← multiplayer room, Hub ACL, local memory, audit
        ↓ asks
   Cortex (agent brain)     ← dual-brain reason/verify, RAG, orchestration
        ↓ resolve / keys / may I?
   OpenVault                ← Key Vault · FreeRoute fallback · access route · health · FreeBuild ship
        ↓
   Shipped small tool       ← same Read only / Host AI / Own AI / Edit ACL
```

### Multiplayer surfaces (AirGPT)
- **Live shared sessions** — long-poll sync; a teammate’s message lands in the open chat (no refresh).
- **QR join** — tunnel QR for phone/iPad/laptop; project/session share with ACL defaulting to **Read only**.
- **Coherent Access Hub** — host + peers, join codes, kick, rename; who is on Host AI vs BYOK; usage/tokens.
- **Host controls** — who may watch, type, spend host tokens, bring own keys, edit files; emergency **Cut all AI**.
- **Hosting / Workforce Observatory** — auditable who did what; business admin dual view of workforce AI + governed engine.

### Small-software / custody surfaces (OpenVault)
- **Encrypted Key Vault** — keys, secrets, accounts; reveal is intentional + audited (no second vault).
- **Access routing** — `/api/access/resolve`: *where does this live, who owns it, may this caller go* — returns location + gate verdict, **never** memory content (memory stays with the brain).
- **FreeRoute (OpenFree)** — local free-tier cascade before paid APIs; soft-fail to cloud if sidecar down.
- **Health / observe / slots** — laptop inventory, path hotspots, model slots acknowledged — so a weak host knows what it can actually run.
- **FreeBuild ship** — sync → detect framework → build → ship/share under the same ACL popover.
- **Mesh** — OpenVault ↔ AirGPT ↔ Cortex as one local mesh, not ten SaaS tabs.

---

## 4. Dual brain + persistent local memory (system of record)

**Dual brain (product meaning, not metaphor):**
1. **Reasoner path** — plan / build / act (Cortex orchestration + Max tier).
2. **Verifier path** — second pass that checks accuracy, first principles, and policy before writes leave the gate.

Together with OpenVault’s gate, this is how personal automation becomes **company-safe**: the agent can move fast, but custody + verify decide what may leave the machine or hit a provider.

**Persistent memory as way of record:**
- Default residency: everything beside the app in `data\` (SQLite + FTS, vault wings, carry-pack hot snippets).
- Chat + project memory indexed locally; DSA-style context compaction keeps the live window sane without discarding the archive.
- `audit.jsonl` — append-only who/what/when (foundation for Workforce Observatory).
- OpenVault **routes** to memory; it does **not** become a second memory store. Gathering all the data into one dual-brain system means: **AirGPT/Cortex hold the record; OpenVault holds the keys and the permission to touch it.**

That split is the unlock for “personal dual brain that is still enterprise-real”: local truth, auditable access, shareable sessions — without pasting IP into random web AI.

---

## 5. Why now

- Agents finally build real tools and run long tasks — collaboration and deploy become the bottlenecks, not codegen.
- Laptops are powerful enough to host a team room; tunnel QR removes corporate Wi‑Fi pain.
- Teams reject shadow AI; they need BYOK, local-first, and a kill switch.
- Big clouds will not delete complexity for one-to-ten-user tools; a small-software cloud can.

---

## 6. Who wants this first

1. **Small eng/ops teams** already crowding on one problem (RFQ packs, VDML sheets, sprint tools).
2. **Founders / PMs** who want agents to build internal widgets and share them like Docs.
3. **Security-conscious companies** that want Host AI vs Own AI, token ledgers, and emergency cut-off — not another ChatGPT seat.

Beachhead: **the host laptop of a tech lead** → invite 3–12 peers by QR → ship one internal tool through OpenVault.

---

## 7. Paste-ready YC answers

### Describe what your company does in 50 characters or less
`Multiplayer AI host + cloud for small software`

### What is your company going to make? (~500 chars)
AirGPT is a local-first multiplayer AI host: teammates join one live agent session by QR, with host ACL (read-only / host AI / own AI / edit), usage ledger, and emergency cut-off. OpenVault is the custody layer—encrypted keys, free-route fallback, API health/access gates, and one-click ship—so the tiny tools agents build share like a Google Doc under the same permissions. Memory and audit stay on the host as the system of record; dual-brain reason+verify keeps work fast and governed.

### What is the problem? / Why does it need to be solved now?
AI work is still single-player while real work is multiplayer; long-running agents make private threads worse. At the same time agents make “small software” trivial to build but still hard to deploy and share safely. Teams need one room for humans+agents and a cloud that deletes Big Software complexity for tools with a handful of users—auth, keys, route fallback, and ship included.

### How do you know people need this? (founder-market)
I built AirGPT to automate my own weak-worker workflow—clipboard, phone sync, local audited AI instead of ten shadow tabs—then found the same pattern every team needs: shared agent sessions, host permissions, and a place to ship the bespoke tools agents generate. Live sync and Hub ACL already run on a real host; the remaining work is making multiplayer and ship unmistakable on camera and in the product.

### What’s new about your approach?
1. **Host-as-product**, not another cloud chat tab.  
2. **Same ACL for chat, project, and shipped app.**  
3. **OpenVault custody split** — resolve location + gate, never duplicate memory.  
4. **FreeRoute fallback + BYOK** so a weak host still works without a platform team.  
5. **Local memory + audit as system of record**, dual-brain reason/verify for trustworthy automation.

### How will you make money?
Personal host stays free/local. Paid surface is **governance + hosting + fleet**: Host AI tokens, business audit/Workforce Observatory, OpenVault ship/host tiers, and team seats — never locking the clipboard/chat moat behind a paywall.

---

## 8. Honest demo truth (do not overclaim in the interview)

| Claim | Status |
|-------|--------|
| Same-session live multiplayer chat | **Works today** (`/api/wait`) |
| Session share + QR + ACL levels | **Works today** |
| Hub peers / join / ACL | **Works today** (UI being simplified to one Edit Access control) |
| Presence avatars / author chips | **Plumbing exists; pixels in build queue** |
| Emergency AI lockdown | **Must ship before film** |
| Hub Demo Mode drill-down | **Data ~90% there; surface in build queue** |
| OpenVault handshake | **Works**; sync→detect→ship thin path in build queue |
| FreeRoute / Key Vault / access resolve / audit | **Real in OpenVault + AirGPT** |
| Dual-brain Max tier / local memory index | **Real** |

Never show an unlabelled fake production URL. Label simulated ship targets.

---

## 9. Elevator (30 seconds)

“ChatGPT is Word in 2005 — powerful, alone. We’re building the Google Docs of agents. AirGPT turns your laptop into a host: teammates scan a QR, join the same live agent, and you control who can watch, spend your tokens, or bring their own keys. When the agent builds a tiny internal tool, OpenVault ships it under the same permissions — keys, health, free-route fallback, one-click deploy. Local memory and audit stay the system of record. Multiplayer AI and a cloud for small software are the same product.”

---

## 10. What to de-emphasize vs older Netie Space pitch

| Old emphasis | New emphasis |
|--------------|--------------|
| Netie Space as the product | **AirGPT host** as the product |
| File-named desktop chat UI | **Multiplayer room + Hub + QR** |
| Generic “governance brain” | **OpenVault custody + FreeBuild ship** |
| Vague dual brain | **Reason + verify + local memory SoR + Workforce Observatory** |
| AWS-scale story | **Small software share-like-a-Doc** |

Netie remains the company/brand umbrella if useful; the application product is **AirGPT + OpenVault**.

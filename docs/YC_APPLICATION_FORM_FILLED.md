# YC Fall 2026 — final paste-ready application (technical pass)

**Product:** AirGPT (multiplayer AI host) · OpenVault (custody, routing, ship) · Cortex (agent runtime).
**Company:** Netie.AI · sole founder · MVP delivery, landing page, and the whole ecosystem built solo.
**Rules:** name the mechanism, not the marketing. Nothing claimed as shipped that the code does not enforce.

Answers are plain text — paste straight into the form.

---

## Founders

### Who writes code, or does other technical work on your product? Was any of it done by a non-founder?

All of it is mine. I am the sole technical founder and the only committer across
the three repos — AirGPT (host server, UI, retrieval rail, audit), OpenVault (key
vault, route cascade, access gate, ship), Cortex (agent runtime, packs,
compliance engine). I also build the landing page and everything else Netie
ships. No contractor, employee, or agency has written a line of it.

I run Claude Code and Cursor as coding agents against contracts I write first.
PRODUCT_ROLES.md pins the boundaries they are not allowed to cross — brains go to
Cortex, keys and the leave-machine gate go to OpenVault, AirGPT stays the host
shell — and the two locks under it are "no second key vault, no third
orchestrator." Agents implement inside those contracts; I write the contracts,
review every diff, and own every merge.

The decisions that determine whether this is safe are mine and not generated: the
host-only API boundary that refuses host-capable routes to remote peers even when
they hold a valid chat token; the five-level access model; source authority
tiering, so the assistant's own past answers can be retrieved but can never
become a citation; and the custody split that keeps OpenVault answering "where is
it, who owns it, may this caller reach it" without ever returning the content.

### Are you looking for a cofounder?

Yes. Finding people who share the vision is the hard part; I am actively looking
for three specific profiles, not general help.

1. Technical cofounder — strong systems engineering plus real ML depth, reads
   papers, and can own the hard subsystems: multiplayer session sync, hybrid
   retrieval and reranking, model routing and fallback, and the fleet control
   plane that comes next.
2. GTM cofounder — can run several agents in parallel and still hold a coherent
   pipeline; converts a live demo into forward-deployed accounts across SEA.
3. Marketing lead — strong prompt engineering, intermediate-to-advanced After
   Effects, drawing ability a plus; owns the product film and the launch surface.

Hard filter for all three: calm under parallel agent load and a large open todo
surface, because that is exactly what building this way feels like.

### Founder video (required — the form will not submit without it)

One minute, under 100 MB, spoken not read:

- 0:00–0:10 — Who I am. Kuala Lumpur, solo technical founder, three repos.
- 0:10–0:25 — Problem: AI is single-player, and the small tools agents build are
  trivial to make and nearly impossible to share safely.
- 0:25–0:45 — Product: my laptop is the host. A teammate scans a QR and is inside
  the same live session. I choose one of five access levels for them — including
  letting them spend my provider key through my audited path, or bring their own.
  OpenVault ships what we build under that same permission.
- 0:45–0:55 — Status, honestly: runs on my machines daily, MVP install end of
  August 2026, revenue zero, users zero.
- 0:55–1:00 — Why YC: this is the two RFS, and I want the cofounder and the
  distribution.

---

## Company

### Company name
Netie.AI

### Describe what your company does in 50 characters or less.
Multiplayer AI host + cloud for small software

(46 characters.)

### Company URL
https://netie.ai

### Demo (≤3 min, ≤100 MB)
Three real beats, in order: (1) two browsers in one session — a phone message
lands live with the sender's presence chip, no refresh; (2) the access Hub —
move a peer from Use Host AI to Use Own AI, then open their per-peer ledger
(tokens today and this week, cost, model split, real prompts) and jump into the
exact message; (3) Key Vault plus the OpenVault handshake, then share by QR. No
unlabelled production URL.

### Please provide a link to the product
Leave blank until the MVP install exists. netie.ai is the company site, not the
product, and putting it here reads as a live product that is not there yet.

### What is your company going to make?

Netie.AI makes AirGPT, a local-first multiplayer AI host, and OpenVault, the
custody and ship layer for the small software those sessions produce. Cortex is
the agent runtime underneath both.

**What AirGPT is.** A Python host process on port 8765 that turns any laptop into
a room. A teammate scans a Cloudflare quick-tunnel QR from a phone, iPad, or
another laptop and is inside the same live session — no VPN, no firewall rule, no
account, and it works on corporate Wi-Fi that blocks device-to-device traffic.
Delivery is a long-poll: a peer's message appears in your open chat without a
refresh, and because every poll doubles as a presence heartbeat, the roster of
who is here and who is typing costs no websocket and no second timer.

**Access is five explicit levels, not a share toggle.** Read only · read-write ·
use host AI · use own AI · limited. "Use host AI" is the one that matters
commercially: the peer spends the host's provider key through the host's audited
path — they never see or hold the key, every call is ledgered against them, and
the host can see exactly what they spent it on. "Use own AI" is BYOK inside the
same room, so a contractor can join without touching your quota. Every peer has a
real activity record: tokens today and this week, cost, per-model split, actual
prompts, and a jump straight into the message in its session. Underneath, a
separate host-only boundary refuses filesystem, git, agent-execution, and audit
routes to any remote caller — including one holding a valid chat token — and a
device allowlist gates LAN and phone peers by capability.

**The local store is the system of record, not a cache.** Chat, files, and memory
live in a folder beside the app: SQLite with FTS5 lexical search plus a dense
vector rail whose backend is profile-selected and soft-fails to local, combined
by reciprocal-rank fusion and then reranked. Retrieval is hardened where it
actually breaks: goals are extracted entity-first, a token-overlap gate runs
before anything is ingested or cited, and every source carries an authority tier.
Documents and fetched pages can be evidence; past conversation is retrievable but
can never be cited — because on 26 July the engine cited its own earlier
fabrication back to me from a chat transcript, and a model quoting its own guess
is indistinguishable from grounding. Everything writes to an append-only audit
log.

**OpenVault is custody and ship.** Encrypted key vault and secrets, with an
env-scan path that imports keys already scattered across a machine and returns
masks only. FreeRoute cascades keyless free tiers through a local
OpenAI-compatible gateway on loopback before any paid key, and soft-fails to the
cloud cascade if the sidecar is down. Access resolve answers where a thing lives,
who owns it, and whether this caller may reach it — and returns a location and a
verdict, never the content, which is what keeps it from quietly becoming a second
memory store. Control writes are dry-run by default. FreeBuild does sync, detect
the framework, build, ship. Cortex adds the runtime: pack loader, a compliance
engine over YAML rules, engine registry, memory plane, DAG runner, and watcher
agents that detect, draft, and stop for approval.

**What we are going to build is the part I am most confident about.** The staged
ladder is already designed and the seams are in the code. R0 is one person on
SQLite. R1 is a team of up to about twenty-five on one strong host that
auto-serves while weak peers join by QR — that runs today. R2 is a durable
managed backend, Postgres and Redis behind one Compose file. R3 is Fleet: a
company points the control plane at its own GPUs and gets "add a host, scale to N
replicas" instead of kubectl. AirGPT becomes the abstraction over Kubernetes, not
a product that forces it on anyone — Compose underneath for a single node, a thin
K8s driver for a real pool, with vLLM/SGLang-class engines staying external
behind the same OpenAI-compatible base URL the host already health-checks. We
orchestrate and audit inference; we never re-implement it. The locked rule at
every rung: the paid tier changes durability, never removes a feature. Alongside
it, hardware honesty — the host profiles the machine and only offers models it
can actually run, and a trial path downloads, probes real tokens, checks quality
against a strong model, and deletes on failure, so a weak laptop is a supported
configuration rather than a bad experience.

This answers two of your Fall 2026 RFS with one mechanism. Multiplayer AI: one
room, one agent, many humans, host-controlled, joined by QR instead of a
read-only transcript. A cloud for small software: agents already make bespoke
tools trivial to build, and OpenVault removes the AWS/Azure surface around
deploying and sharing them. The reason those are one product and not two is that
a tool is only safely shareable if the permission set in the conversation follows
it into the artefact. That is the whole thesis: one permission surface, from chat
to project to shipped tool.

### Where do you live now, and where would the company be based after YC?
Kuala Lumpur, Malaysia / San Francisco, United States of America

### Explain your decision regarding location.

I live in Kuala Lumpur and would base the company in San Francisco after YC.

The gap I am building into is SEA forward deployment. Malaysian and regional
manufacturing, logistics, and service companies run real operational workflows
that need bespoke internal tools, and have no platform team to build or operate
them — the exact profile that cannot absorb an AWS-shaped answer. That is where
my domain knowledge came from and it stays my first design input and first
deployment ground.

The company still has to be built in San Francisco. Talent density for the hard
parts — session sync, retrieval, routing, the security model, and the fleet
control plane — is there and is not here, and so is the density of design
partners who will push the product harder than my own daily use does. So: San
Francisco for the company and the team, KL as the lower-burn build base and the
proving ground for forward deployment into ASEAN. Build in SF, prove in SEA,
scale from both.

---

## Progress

### How far along are you?

MVP, running on my machines and used every day.

Working today: live same-session sync with presence and per-message authorship;
join by tunnel QR from phone, iPad, or laptop with no network setup; five access
levels (read only, read-write, use host AI, use own AI, limited) enforced
server-side, with join codes, rename, and kick; per-peer ledger — tokens today
and this week, cost, per-model split, real prompts, and a jump into the exact
message; one single access control reused for chat, peer, and project, so a
permission is granted the same way everywhere. Local memory as system of record:
SQLite plus FTS5 and a dense vector rail, reciprocal-rank fusion, reranking,
entity-first goal extraction, a token-overlap gate before ingest or citation,
authority tiers that stop past model output being cited as fact, and an
append-only audit log. Security: host-capable routes are refused to remote peers
even with a valid chat token, and LAN/phone peers are gated by a capability
allowlist. OpenVault is meshed and real — encrypted vault, env-scan import,
free-tier gateway cascade with budget snapshot, access resolve, deploy gates,
sync/detect/build/ship backend, dry-run-by-default control. Cortex runs as the
engine sidecar with goals, routines, queue, and run history driven from the host.

In build for the MVP install: the Hub drill-down drawer (backend complete, UI
not), the live app card that shows a tool the agent just built running inside the
room, project share QR, and the one-shot OpenVault ship UI.

Precise about one thing so nobody discovers it in a demo: emergency AI cut-off
has state, an API, and a UI treatment, but it does not yet gate the AI path. It
is visual until I wire enforcement, and I will not present it as more than that.

Public install target: end of August 2026. Users: none outside me. Revenue: $0.

### How long have each of you been working on this? How much of that has been full-time?

Solo, so this is just me. About 12 months of research and requirement gathering —
local inference, Windows workforce workflows, warehouse and logistics operations,
governance — and about 4 months building AirGPT, OpenVault, and Cortex full-time,
plus the landing page and everything else Netie needs.

### What tech stack are you using, or planning to use? Include AI models and AI coding tools you use.

AirGPT host: Python HTTP server on 8765, portable from any folder, no install
ceremony. SQLite with FTS5 for lexical retrieval plus a dense vector rail
(sqlite-vec locally, profile-selected alternates for business, soft-failing back
to local rather than erroring), fused by reciprocal-rank fusion and reranked;
semantic cache; source authority tiering at ingest. Single-page HTML/JS UI, no
framework. Cloudflare quick tunnel for QR join. Append-only JSONL audit.

Cortex (agent runtime, port 8010): pack loader, YAML-rule compliance engine,
engine registry, memory plane, DAG runner, DuckDB/DuckLake for the data-heavy
packs, watcher agents on a detect-draft-approve loop.

OpenVault (control plane, port 5000): Python with uv. Encrypted key vault and
secrets, env-scan and masked import, FreeRoute free-tier cascade through a local
OpenAI-compatible gateway on loopback 20128, health and path observation, access
resolve, FreeBuild ship and deploy gates, local mesh into Cortex and AirGPT,
dry-run-by-default control writes.

Models: bring-your-own-key across providers (Anthropic, OpenAI, Gemini, Groq,
OpenRouter) behind the vault cascade, with the free-tier gateway tried first and
a soft-fail to cloud. Local inference is profile-gated by real hardware —
cloud-only, CPU GGUF via llama.cpp, small and mid vLLM tiers, disk-streamed MoE
for large-RAM machines — with KV-cache quantisation stacked on weight quants for
long context on small VRAM. Model trials download, generate, quality-check
against a strong model, and delete on failure. Serving backends only produce
tokens behind an OpenAI-compatible /v1; they never hold product state. A hosted
Netie Engine is the paid path for teams that do not want to run any of this.

AI coding tools: Claude Code (Opus) and Cursor, working against contracts I write
first. I own architecture, review, and merges.

### Are people using your product?

No.

I use it full-time and people who have seen it asked to install it, but nobody
outside the founding team runs it on their own machine yet, and founder usage is
not traction. That changes with the MVP install at the end of August.

### When will you have a version people can use?

Public installable host by end of August 2026. Free: the local host, clipboard
and phone sync, chat, local memory, retrieval, and the audit log — permanently.
Payment starts only when a team opts into hosted Netie models, team governance
and audit, or hosted ship. The rule I hold myself to is that a paid flag selects
the backend and the durability, never removes a feature.

### Do you have revenue?

No.

### Applying with the same idea as a previous batch?

First application, first idea. No prior YC application and no pivot to explain.

### Incubator / accelerator

None. Not participating in and not committed to any incubator, accelerator, or
pre-accelerator.

---

## Idea

### Why did you pick this idea? Do you have domain expertise? How do you know people need it?

It started as my own problem. I work on Windows across a laptop and a phone with
material I cannot paste into a public chat site. I wanted AI that stayed on my
machine and left an audit trail, a phone that could hand a photo to the laptop
without going through a third-party uploader, and — the part that turned it into
a company — teammates who could interrupt the same agent instead of each forking
a private thread and mailing screenshots around.

Domain expertise is that I built every layer, so I know precisely where this gets
hard rather than where it looks hard. The host-only boundary, because a valid
chat token must not equal filesystem access. Authority tiering, because I watched
the engine cite its own fabricated answer back to me out of an indexed chat
transcript and had to make "retrievable" and "citable" two different privileges.
The custody split, because the moment OpenVault returns content instead of a
location and a verdict, it becomes a second copy of your data to defend.
Separately, the Cortex work was built against real warehouse and logistics SME
operations, which is where I learned that the tools these teams need are small,
specific, and completely unshippable through a normal cloud.

How I know people need it: today the evidence is qualitative and consistent, not
quantitative, and I am not going to invent a survey around it. Every demo lands
on the same two moments — a port they control, and a QR that puts a second person
inside the same live session — and people ask to install it. The measurable
version arrives with the install: weekly active hosts, share of sessions with
more than one participant, and tools shipped through OpenVault. If
multi-participant sessions do not outnumber solo ones within a month of launch,
the multiplayer thesis is wrong and I will say so rather than re-frame it.

### Who are your competitors? What do you understand about your business that they don't?

ChatGPT and Claude are the best single-player experiences and will stay that;
their sharing primitive is a frozen transcript. Cursor and the coding agents own
the individual builder and stop at the repository. AWS and Azure are built for
software with many users, and their complexity is the honest price of that scale
— they have no reason to serve a tool with four users. The "ChatGPT for teams"
wrappers sell cloud seats: your data leaves, the permissions are theirs, and
there is no kill switch you own.

What I understand that they do not:

The host is the unit of collaboration, not the account. Someone's machine already
holds the files, the context, and the trust. Make that machine the room and
sharing collapses into a QR instead of a migration.

The conversation and the artefact must share one permission surface. Everyone
else treats "who can see this chat" and "who can run this tool" as two separate
products with two separate models. That gap is exactly why nontechnical people
cannot safely share arbitrary code, and closing it is what makes small software
shippable at all.

Custody is separable from memory. Location, ownership, and permission are one
service; content is another. Nobody selling seats will build that split, because
their business requires holding the content.

Retrievable is not citable. Every RAG product I have used will happily quote a
model's own earlier output back as evidence. Tiering source authority at ingest
is a small piece of code and the difference between a memory that compounds
knowledge and one that compounds error.

And cheap-first is a feature. Free tiers cascade before any paid key, own-key is
a first-class access level, and hardware profiling means a weak laptop is a
supported configuration. That is unsellable for anyone optimising cloud seats,
and it is exactly what a forward-deployed SEA account needs.

### How do or will you make money? How much could you make?

Layered. The personal host stays free and local permanently — that is the moat
and it never goes behind a paywall. Revenue comes from the governance and hosting
layer: hosted Netie model access for teams that do not want to manage keys or
GPUs, per-seat team governance (access levels, ledger, audit, workforce
visibility), and OpenVault hosting and ship tiers for the tools those teams
build. Fleet is the enterprise line above it: a company points the control plane
at its own GPUs and skips hiring a Kubernetes or SLURM specialist.

Best estimate, stated as a planning target and not a forecast: roughly 200 paid
seats at $30–50 per seat per month in the first year after launch is about
$72k–$120k ARR, or the same figure from far fewer seats at higher governance ACV
in forward-deployed accounts. The metric that actually compounds is not seats but
tools shipped and governed per team — a team running fifteen bespoke tools
through one gate is a structurally different account from one running a single
chat room. I will report real conversion after the free host ships rather than
defend a model built on nothing.

### If you had any other ideas you considered applying with, please list them.

Netie DMS — an operations data layer for garages and warehouses. These sites run
on paper, WhatsApp photos, and one person's memory: stock in and out, job cards,
parts, damage, and dimensions get typed twice or not at all, and the errors
surface weeks later at reconciliation. Netie DMS captures at the point of work
(photo, scan, voice, or form), extracts and classifies automatically with PII
handled before anything reaches a model, writes to a governed ledger with
row-level access and an audit trail, and turns retrieval into a plain question
instead of a spreadsheet hunt. Watcher agents run the loop end to end — detect,
draft, and hold for approval — so the human is in the loop only for judgment: a
low-confidence extraction or an exception. The runtime already exists in Cortex
(warehouse capture, dimensioning, classification, compliance gate, lakehouse
ingest and pipelines, approval-gated agents). It is a vertical on the same
governed stack, not a separate company.

[TO FILL — one line each to follow]: Netie Space · Netie Pointer · Netie Cortex ·
Netie Forge · Netie Talkie · Netie RUMA · Netie Cikgu

---

## Equity

### Have you formed ANY legal entity yet?
Yes

### Please list all legal entities you have and in what state or country each was formed.

One: a Malaysian sole proprietorship registered through SSM's ezBiz, which I
opened recently to operate legitimately while building. It is a sole
proprietorship, so it has no share capital and no shareholders — there is no cap
table to disclose and no prior entity, subsidiary, or pre-pivot company anywhere.
If accepted I will incorporate a Delaware C-Corp as the parent and keep or wind
down the Malaysian registration as YC's counsel prefers.

### Please describe the breakdown of the equity ownership in percentages.

Jian Hong Oo, Founder and CEO — 100%. No cofounders, no employees, no outside
stockholders, no advisors holding equity, no options granted, no SAFEs or
convertibles outstanding. The option pool gets created at C-Corp incorporation.

### Have you taken any investment yet?
No

### Are you currently fundraising?
No

### Relevant details about your current fundraise
Not fundraising. Applying to YC; open to standard post-YC financing after the
batch.

---

## Curious

### What convinced you to apply to Y Combinator?

Two of your Fall 2026 Requests for Startups describe what I was already building.
Multiplayer AI is the room — one live agent session a team joins, watches, and
redirects together, rather than a read-only transcript. The cloud for small
software is the other half — agents make bespoke tools trivial to build, and
deploying and sharing them safely is still the wall. I had already concluded
these are one problem, because a tool is only shareable if the permission from
the conversation follows it into the artefact. Nobody encouraged me to apply and
I have not attended a YC event; the RFS naming the exact gap is what convinced
me.

### How did you hear about Y Combinator?
Instagram.

### Batch preference
Fall 2026

---

## Before you submit

- [ ] Founder video attached — this is the only thing currently blocking submit
- [ ] Demo attached, or the field left empty
- [ ] Product link left blank until the install exists
- [ ] Users = No · Revenue = No
- [ ] Other-ideas list completed with your seven one-liners
- [ ] Spelling pass on anything retyped by hand

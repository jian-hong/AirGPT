# AirGPT — YC "Multiplayer AI" film + build queue

**Target:** YC RFS *Multiplayer AI*. One 2:35 film. Cold open (0:00–0:20) is the teaser cut; the rest is the product demo.

**Thesis sentence** (say it out loud before every edit decision):

> Every other AI tool gives your team a thousand private threads. AirGPT gives you one room — one agent, everyone in it, and a host who controls who touches what.

---

## 1. Truth table — status after YC demo build (2026-07-28)

**Paste-ready gen prompts:** [VIDEO_YC_PROMPTS.md](./VIDEO_YC_PROMPTS.md)  
**Recorders:** `video-assets/scripts/record_act{1,2,3,4,6}*.py` (require `demo_mock`)

| Item | Status | Note |
|------|--------|------|
| P0-1 Presence + authorship | **DONE** | `presence.py` + `#presenceStack` + author chips + typing; film with `record_act1_interrupt.py` (2 contexts) |
| P0-2 Cut all AI | **MOCK UI DONE** | `access_policy.ai_lockdown` + Hub button + red bar via `/api/wait` — **does not gate AI providers** (film-only) |
| P0-3 Hub Demo + drill-down | **DONE** | Demo mode grid, state colours, peer drawer, `GET /api/hub/peers/<ip>/activity`, View chat → `#msg-N` |
| P1-4 Edit access | **DONE** | `ui/multiplayer_demo.js` — 3 radios + Can edit → existing ACL enum |
| P1-5 Project share QR | **DONE** | Share on project header; default read-only |
| P1-6 OpenVault one-shot | **DONE** | `sync` / `detect` (reads `package.json`) / `build` / `ship` with **Simulated target** |
| P2 Motion on filmed surfaces | **DONE** | Hub nodes + access pop + drawer + presence springs via `Motion` |

### Still true without new code

| Beat | Where |
|------|-------|
| Live cross-device chat | `/api/wait` long-poll |
| Session share QR | `shareSession()` |
| Demo seed peers (expanded to 9 + limited) | `seed_demo_mock.py` + `start_demo_mock.bat` |

### Must be built before Cursor can record

~~Superseded — build queue shipped.~~ Act 1 still needs a **live** two-browser take (do not fake). Re-seed before recording: `python seed_demo_mock.py --reset`.

---

<details><summary>Original P0 build specs (archived)</summary>

**P0-1 · Presence + authorship — half a day**

The plumbing is multiplayer; the pixels are single-player. `messages` already stores `device_ip` and `device_name` ([db.py:45](../db.py)), but `renderMsg()` ([index.html:11974](../index.html)) only uses it to decide left/right alignment. Nothing tells you *who* is in the room.

Without this, the 0:15 interrupt shot reads as the host talking to itself, and a YC partner will read it as fake.

Build:
- `GET /api/presence?session_id=N` → live members (touch on each `/api/wait`, 30s TTL). Reuse `hub.touch_peer`.
- Avatar stack in the chat header — initials on a coloured disc, `Motion.springTo` in with the `snappy` preset, greyscale when idle.
- Author chip above every non-`me` bubble: `Jordan · Eng`.
- System line: `— Jordan Lee joined this chat` on first message from a new peer.
- `POST /api/presence/typing` + a three-dot chip under the avatar stack.

Acceptance: two browsers, same session, second sends a message → first shows the avatar, the typing chip, the author chip, and the system line, with zero manual refresh.

---

**P0-2 · Emergency AI cut-off — half a day**

~~Real kill-switch deferred.~~ Shipped as **mock UI** for Act 4 film only — see [VIDEO_YC_PROMPTS.md](./VIDEO_YC_PROMPTS.md).

</details>

---

**P0-3 · Hub Demo Mode + peer drill-down — 1 day** *(shipped — kept for history)*

Act 3 is the differentiator, and 90% of the data already exists — it just has no surface.

Build:
- `GET /api/hub/peers/<ip>/activity` — one join across three existing sources: `hub.get_hub_snapshot` (identity, ACL), `hosting.usage_summary` filtered by `user`/`ip` (tokens, model, cost, `session_id`), `db.device_activity_stats` + `db.list_hub_events` (sessions, connect history). Return recent prompts with `session_id` + `message_id`.
- Top-right **Demo mode** toggle on the Hub → replaces the 4-slot radial layout with a responsive grid of *all* peers. State colour: green live · amber idle · grey offline · **red limited/over-quota**.
- Click a peer → right drawer (`Motion.springTo`, `sheet` preset):
  - identity + access level
  - **AI source**: `Host AI (netie-engine)` or `Own key (BYOK · anthropic)` — the sharpest single frame in the film
  - tokens today / this week, cost, model split
  - last 5 prompts, each a row with a quality signal
  - **View chat →** deep-links to that exact message: `openSession(session_id)` then scroll+flash `#msg-<id>`
- Deep-link needs `id="msg-${m.id}"` added in `renderMsg()`. It isn't there.

Acceptance: from the Hub grid, three clicks lands you inside Jordan's actual chat at the actual message, with no typing.

---

**P1-4 · Collapse access levels into one control — 2 hours**

Today the Hub shows a raw `<select>` of five enum names and a `⋯` menu of five `Set: …` buttons ([index.html:6296](../index.html), [index.html:6320](../index.html)). It reads as a database column, not a product.

Replace with one **Edit access** button per node → popover, three big rows + one toggle:

```
  ○ Read only            can watch, cannot type      (default)
  ○ Use Host AI          spends your tokens
  ○ Use Own AI           brings their own key
  [ ] Can edit project files
```

Maps to the existing enum — `read_only`, `use_host_ai`, `use_own_ai`, and the checkbox flips `read_write`/`limited`. Same `POST /api/hub/peers/<ip>/acl` endpoint, zero backend work.

---

**P1-5 · Project-level share QR — half a day**

Session share exists; project share does not. `renderProjects()` ([index.html:10608](../index.html)) cards carry no share affordance.

Build: share button on the project card → same modal shape as `shareSession`, plus an access toggle above the QR that **defaults to Read only**. Mint at project scope using the `auth.issue_session_share` pattern.

The "default read only" default is a line you can say out loud in the film. Say it.

---

**P1-6 · OpenVault one-shot: sync → detect → build → ship → share — 1 day**

Today `OpenShip` is a token row in the key vault ([key_vault.py:199](../key_vault.py)) and OpenVault has a handshake endpoint. No pipeline.

Build the thin-but-real path:
- `POST /api/openvault/sync` — copy the project dir to `D:\OpenVault\apps\<name>`, stream progress lines.
- `GET /api/openvault/detect` — **actually read `package.json`**. If `next` is a dependency, return `{"framework":"Next.js","build":"next build","port":3000}`. A real detector on one real file is honest and costs 20 lines; a hardcoded string is a lie that a YC partner will ask about.
- `POST /api/openvault/build` — run the detected build, stream output.
- `POST /api/openvault/ship` — returns the deploy URL. **If the EC2 target is not real, the UI must say `Simulated target`** in small type on screen. Do not put a fake AWS domain on camera without that label — one screenshot of a fabricated production URL is worse than showing a localhost port.
- Ship result panel → **Share** → the same access popover from P1-4.

---

**P2-7 · Adopt the motion layer — ongoing, do the four surfaces the camera sees**

`ui/motion.js` and `ui/apple.css` are written and loaded but essentially unadopted — the app still runs 91 CSS transitions. Springs are catchable mid-flight; transitions are not. On a 60fps screen recording the difference is the entire perceived quality of the product.

Do exactly these four before recording:
1. Hub peer nodes entering — stagger 40ms, `snappy`.
2. Peer drawer — `sheet`, opened and dismissed by drag in the recording so the catch is visible.
3. Lockdown wash — 220ms desaturate, everything else freezes for 400ms of true stillness.
4. Presence avatars — `snappy`, scale 0.6→1.

---

### Build queue summary

| # | Item | Est | Blocks |
|---|------|-----|--------|
| P0-1 | Presence + authorship | 0.5d | Act 1 |
| P0-2 | Emergency AI cut-off | 0.5d | Act 4 |
| P0-3 | Hub demo mode + drill-down | 1.0d | Act 3 |
| P1-4 | One access control | 2h | Acts 2, 3, 6 |
| P1-5 | Project share QR | 0.5d | Act 2 |
| P1-6 | OpenVault one-shot | 1.0d | Act 6 |
| P2-7 | Motion on 4 surfaces | 0.5d | All app acts |

**≈ 4.5 focused days.** Nothing here is speculative — every item extends a surface that already exists.

---

## 2. The film — 2:35, eight acts

Legend: **[GEN]** generated plate (LTX-2 / Higgsfield) · **[REC]** screen recording · **[COMP]** composited in Premiere/Motion.

| # | Time | Act | Source |
|---|------|-----|--------|
| 0 | 0:00–0:05 | QR shuffle → Team Collaboration mesh | GEN |
| 1 | 0:05–0:20 | The interrupt — two humans, one agent | REC + COMP |
| 2 | 0:20–0:48 | Projects · invite · QR with access | REC |
| 3 | 0:48–1:20 | The Hub — who's in, whose AI, what it cost | REC |
| 4 | 1:20–1:38 | Cut all AI | REC + COMP |
| 5 | 1:38–1:52 | Cleared — the room goes back to work | GEN + REC |
| 6 | 1:52–2:16 | OpenVault — sync, detect, ship, share | REC |
| 7 | 2:16–2:35 | Three devices → logo | GEN + REC |

---

### Act 0 · 0:00–0:05 — QR shuffle → mesh

**0:00–0:03** — QR codes shuffling like a dealt deck, each on a different surface: brushed aluminium, a glass meeting-room wall, an iPad, a whiteboard, a lanyard badge. Cuts land on the beat, 6 codes/sec, accelerating.

**0:03–0:05** — Shuffle collapses into one QR. It dissolves into typography: **TEAM COLLABORATION**, letters landing one at a time. Then the letters resolve into nodes — laptops, a server, a database — and light-carrying wires connect them, data pulsing along the links.

- VO: *"A QR code is all you need —"* (0:00) → *"— for your whole team to work with one AI."* (0:03)
- SFX: card-shuffle riffle, low sub-bass swell, single clean chime on the final QR.

### Act 1 · 0:05–0:20 — the interrupt

The money shot. Everything else is support.

**0:05–0:08** — Push in on the AirGPT chat bar. Whole UI tilted ~45° in Z, floating in black, then rotating to flat-on as we arrive. Type: `Sup Netie! Prepare a slideshow for today's 4pm meeting.` Netie's thinking chain opens; memory chips light up as it orchestrates.

**0:08–0:15** — The agent works. Calendar wires in: *4:00pm — Mr Tan, Vitron — forward-deployment collaboration.* Slides assemble from real vault notes. Ken Burns across the thinking pane.

**0:15–0:20** — **The reverse.** Tape-stop / reversed-cymbal riser, picture stutters back 6 frames, and a second person's message lands **in the same chat**:

> **Jordan · Eng** — *Hey Netie, complete the VDML sheet referencing the RFQ, FCM and PO from NMD?*

Presence avatar springs into the header. Netie: *"Sure — picking that up in parallel."* Both tasks run in one thread.

- VO: *"Someone else on your team can just… walk in."* (0:16)
- On-screen title, small, lower-left: `Same session. Same agent. No new thread.`

> **Recording note:** film this for real, two machines, one session. Do not fake it in post. The whole submission rests on this shot being genuine.

### Act 2 · 0:20–0:48 — projects, invite, access

- **0:20–0:28** Projects page. Cards breathe in on a spring. Open *Vitron — Forward Deployment*.
- **0:28–0:36** Invite: **Share** → QR modal. Cursor deliberately rests on the access toggle, already reading **Read only**. VO: *"Sharing defaults to read-only. You raise it on purpose, never by accident."*
- **0:36–0:44** Phone scans. Split screen: iPhone joins on the right, host Hub on the left gains a node in the same frame. **One take, one camera, no cut** — the simultaneity is the proof.
- **0:44–0:48** Host lifts them to **Use Host AI** from the new popover. Node turns green.

### Act 3 · 0:48–1:20 — the Hub

- **0:48–0:54** Hub page. Host at centre, peers around it, wires alive.
- **0:54–1:00** Top-right **Demo mode**. Grid expands to ~12 machines. Colours read instantly: green live, amber idle, grey off, red limited.
- **1:00–1:08** Click a red one. Drawer springs in. VO: *"You can see who's in, what they asked, whose AI they spent, and what it cost."*
- **1:08–1:14** Hold on the AI-source row: **Own key · BYOK** vs **Host AI · netie-engine**. Then the token bar.
- **1:14–1:20** Click a prompt → **View chat →** → lands inside that exact chat at that exact message, which flashes once.

### Act 4 · 1:20–1:38 — cut all AI

- **1:20–1:26** A prompt appears in the drill-down that shouldn't be there. Push in. Music drops out — leave one bar of near-silence.
- **1:26–1:32** Host hits **Cut all AI · everyone**. Red wash. Every node desaturates. Banner: `AI disabled · 4 sessions frozen`. Peer screens: red bar, input dead. **Total silence, 1.5 seconds.** Do not score this.
- **1:32–1:38** VO, quiet: *"One host. One button. Everything stops — and nothing is lost."*

### Act 5 · 1:38–1:52 — cleared

- **1:38–1:42** Green **Cleared**. Colour floods back. Music re-enters underneath.
- **1:42–1:52** Office cutaways: people looking up, a small cheer, back to keyboards. Screens fill with prompts and builds. Shots begin shrinking into rounded rectangles.

### Act 6 · 1:52–2:16 — OpenVault one-shot

- **1:52–1:58** Project → **Ship**. `Syncing to OpenVault…` progress streams real file counts.
- **1:58–2:04** `Detected: Next.js` — with the `package.json` line that proved it visible beside the badge. **Build** streams real output.
- **2:04–2:10** **Ship** → URL appears. Small type under it, honest: `Simulated target`.
- **2:10–2:16** **Share** → the same access popover. Read only → Use Host AI → Can edit. Same control as Act 2. VO: *"One control, everywhere. That's the whole idea."*

### Act 7 · 2:16–2:35 — devices, then the mark

- **2:16–2:24** All the rounded rectangles compress toward centre and collapse into a single point of light.
- **2:24–2:31** Light unfolds into three devices, side by side: MacBook, iPad, iPhone — same session live on all three, the same message arriving on each at the same instant.
- **2:31–2:35** Devices fade. **AirGPT** wordmark, then **by NETIE.AI** with the bounce-dot mark. Black.
- VO close: *"AirGPT. Multiplayer by default."*

---

## 3. Generation prompts

### 3A · LTX-2 / Higgsfield plates

House style, prepend to every plate:

> Cinematic product film, anamorphic 2.39:1 framing inside a 16:9 frame, shallow depth of field, deep matte-black background, cool neutral grade with a single warm practical, subtle film grain, no text artefacts, no watermark, no UI mockups, no人物 faces in focus.

Universal negative:

> `blurry, low resolution, warped text, gibberish letters, extra fingers, distorted hands, watermark, logo artefacts, oversaturated, HDR halo, jitter, morphing geometry, subtitles, captions`

---

**PLATE 01 — QR shuffle · 3s · 24fps**

> A rapid shuffle of black-and-white QR codes, each printed on a different real surface — brushed aluminium laptop lid, frosted glass meeting-room wall, an iPad screen, a dry-erase whiteboard, a fabric lanyard badge. The codes cut past camera like a riffled deck of cards, six per second, accelerating. Macro lens, extremely shallow focus, specular highlights raking across each surface as it passes. Deep black void behind. Cool white key light from upper left, single warm amber practical far background. Camera locked, subjects moving. High-contrast monochrome with a faint cyan cast.

**PLATE 02 — QR dissolves to mesh · 2s**

> A single QR code holds centre frame, then its black modules detach and drift apart into three dimensions, becoming a constellation of glowing nodes suspended in black. Thin light-filaments draw themselves between the nodes, and pulses of bright data travel along the filaments from node to node. Slow dolly-in, 24mm, gentle parallax. The mesh reads as laptops, a server rack, and a database, abstracted to pure geometry. Cool white and pale cyan emissive light, no ambient fill. Volumetric haze.

**PLATE 03 — the reverse riser · 1.5s**

> Abstract visual tape-stop: a field of horizontal light-streaks snaps backwards, chromatic aberration splitting into red and cyan fringes at the edges, one frame of scan-line tear, then everything settles instantly to stillness. Pure black background, streaks in cool white. Violent motion resolving to perfect calm.

**PLATE 04 — lockdown wash · 2s**

> A network of glowing white nodes and connecting filaments, seen from slightly above. In one beat every filament drains from white to deep crimson and the nodes desaturate to cold grey, the light dying outward from centre like a power cut travelling down a grid. Then absolute stillness — no drift, no pulse, no flicker. Deep black background. Ominous, controlled, not chaotic.

**PLATE 05 — cleared · 2s**

> The same grey network reilluminating: a single green pulse from the centre node travels outward along every filament, and as it passes, colour and motion return. Warm white light blooming back into cool geometry. Relief, exhale, forward momentum. Slow dolly out.

**PLATE 06 — compression to a point · 3s**

> Two dozen small rounded-rectangle screens, each glowing with abstract interface light, floating in black space. They drift inward and compress toward the centre with accelerating momentum, overlapping and shrinking until they collapse into one intense point of white light, which holds for half a second and then blooms. Motion-blurred trails, anamorphic horizontal flare on the bloom. Camera slowly pushing in throughout.

**PLATE 07 — devices unfold · 3s**

> A single point of white light in black space unfolds into three devices arranged side by side — an open laptop, a tablet on a stand, a phone — all screens facing camera, all glowing with the same soft interface light. Studio product photography, floating with no visible surface, soft top key and cool rim light. Slow orbit of ten degrees, shallow depth of field with focus resting on the tablet at centre.

> **Screens must be composited, not generated.** Generate these plates with **dark blank screens**, then track in the real recordings in Premiere. Every video model produces illegible garbage UI, and garbage UI in a YC demo is fatal.

---

### 3B · Cursor build prompts

One per build item. Paste as-is; each is scoped to files that exist.

**BUILD 1 — presence + authorship**

```
AirGPT: make a shared chat session visibly multiplayer.

Live message delivery already works via the /api/wait long-poll in index.html
(syncLoop, ~line 12867). Messages already carry device_ip and device_name
(db.py schema ~line 45). Nothing surfaces this in the UI. Add:

1. Backend, clipdrop.py:
   - GET  /api/presence?session_id=N -> {members:[{name,ip,icon,last_seen,typing}]}
   - POST /api/presence/typing {session_id, typing:bool}
   Track in memory, 30s TTL. Reuse hub.touch_peer for identity/icon.
   Touch presence on every /api/wait so no extra client polling is needed —
   return a "presence" key in the /api/wait response instead.

2. Frontend, index.html:
   - Avatar stack in the chat header: initials on a coloured disc, colour hashed
     from device_name. Greyscale at 45% opacity when last_seen > 60s.
     Enter with Motion.springTo, preset 'snappy', scale 0.6 -> 1, stagger 40ms.
   - In renderMsg() (~line 11974): when a non-AI message's device_name differs
     from the local device, render an author chip above the bubble showing the
     name. Also add id="msg-${m.id}" to the bubble element — a later feature
     deep-links to it.
   - System line "— {name} joined this chat" on a peer's first message in a session.
   - Typing chip (three animated dots) under the avatar stack.

Constraints: no new dependencies, no build step, keep the single-file index.html
structure, match surrounding code style.

Done when: two browsers on the same session — the second sends a message and the
first shows avatar, author chip, and system line with no manual refresh.
```

**BUILD 2 — emergency AI cut-off**

```
AirGPT: add a host-only emergency AI lockdown.

No such feature exists today (grep for panic/emergency/lockdown/kill-switch
returns nothing).

1. hub.py: set_lockdown(on: bool, reason: str = "") and get_lockdown().
   Persist to data/access_policy.json under key "ai_lockdown"
   {on, reason, by, started_at}. Log a hub_event on both edges.

2. clipdrop.py: POST /api/hub/lockdown {on, reason} — host-verified only.
   Include lockdown state in /api/info and in the /api/wait response.

3. Gate every AI entry point: ai_engine.py and agent_runtime.py return
   {"ok": false, "error": "ai_lockdown", "by": host} before any provider call.
   Nothing may be dropped or corrupted — in-flight work is saved as-is.

4. index.html:
   - Hub page: one wide destructive button "Cut all AI · everyone" with a
     confirm sheet.
   - When on: --danger wash over the page, every hub node desaturates
     (220ms), sticky banner "AI disabled · N sessions frozen · mm:ss".
   - Peer view: red bar "Host disabled AI. Your work is saved." Chat input
     disabled but never cleared.
   - Clearing restores both sides without a reload.

Done when: lockdown on -> a peer's send returns ai_lockdown and the peer's red
bar appears within 2s. Off -> both sides recover, no reload, no data lost.
```

**BUILD 3 — Hub demo mode + peer drill-down**

```
AirGPT: add Demo mode and per-peer drill-down to the Coherent Access Hub.

All the data exists; there is no surface for it.

1. clipdrop.py: GET /api/hub/peers/<ip>/activity, joining three existing sources:
   - hub.get_hub_snapshot()        -> identity, access_level, join_method
   - hosting.usage_summary()       -> filter events by user/ip; tokens, cost,
                                      model split, session_id
   - db.device_activity_stats() + db.list_hub_events() -> sessions, history
   Return: {peer, ai_source:"host"|"own", tokens_today, tokens_week, cost,
            by_model[], recent_prompts:[{text, session_id, message_id, ts, model}]}
   ai_source derives from access_level: use_own_ai -> "own", else "host".

2. index.html, renderHubPage() (~line 6273):
   - Top-right "Demo mode" toggle. On: replace the 4-slot radial layout
     (slots tl/tr/bl/br) with a responsive grid of ALL peers.
   - State colour: green online, amber idle >5min, grey offline,
     red access_level==='limited' or over quota.
   - Click a peer -> right drawer via Motion.springTo preset 'sheet', drag to
     dismiss. Drawer shows: identity, access level, AI SOURCE as a large
     prominent row ("Host AI · netie-engine" vs "Own key · BYOK"), token bar,
     cost, and the last 5 prompts.
   - Each prompt row has "View chat →" that calls openSession(session_id), then
     scrolls to #msg-<message_id> and flashes it once.

Done when: from the Hub grid, three clicks land inside a peer's real chat at the
exact message, with no typing.
```

**BUILD 4 — one access control**

```
AirGPT: replace the raw ACL enum UI with a single access control.

Today renderHubPage() shows a <select> of five enum values (~line 6296) and
hubPeerMenu() offers five "Set: ..." buttons (~line 6320). It reads as a
database column.

Replace both with one "Edit access" button per node opening a popover:

    ( ) Read only        can watch, cannot type      [default]
    ( ) Use Host AI      spends your tokens
    ( ) Use Own AI       brings their own key
    [ ] Can edit project files

Mapping to the existing enum: read_only / use_host_ai / use_own_ai; the
checkbox toggles read_write vs limited. Keep POST /api/hub/peers/<ip>/acl
unchanged — this is UI only. Reuse the same component for project share and
deploy share so all three surfaces are identical.

Popover animates with Motion.springTo, preset 'snappy'.
```

**BUILD 5 — project share QR**

```
AirGPT: add project-level sharing with a QR and an access toggle.

Session sharing exists — shareSession() at index.html ~line 11172, backed by
auth.issue_session_share (auth.py ~line 391). Project cards, rendered by
renderProjects() (~line 10608), have no share affordance.

1. auth.py: issue_project_share(project_key, acl) following the session-share
   pattern; redeem_project_share() alongside redeem_session_share.
2. clipdrop.py: POST /api/projects/<key>/share {acl} -> {share_url, token}.
3. index.html: share button on each project card -> modal with QR + copied link,
   and the BUILD 4 access popover above the QR, DEFAULTING TO READ ONLY.
   Changing the toggle re-mints the token.

Done when: scanning the QR on a phone opens the project read-only, and raising
access to Use Host AI on the host lets that phone prompt.
```

**BUILD 6 — OpenVault one-shot**

```
AirGPT: build the sync -> detect -> build -> ship -> share pipeline to OpenVault.

Today only the handshake exists: kvConnectOpenVault() at index.html ~line 13808
-> POST /api/openvault/connect. OpenShip is only a key-vault token row
(key_vault.py ~line 199).

Add to OpenIDE/openvault_bridge.py + clipdrop.py routes:
  POST /api/openvault/sync   {project} -> copy to D:\OpenVault\apps\<name>,
                                stream real file counts over SSE
  GET  /api/openvault/detect {project} -> READ package.json for real. If "next"
                                is a dependency return
                                {framework:"Next.js", build:"next build", port:3000}.
                                Also handle vite, cra, plain node. Do NOT hardcode.
  POST /api/openvault/build  -> run the detected build, stream stdout
  POST /api/openvault/ship   -> return {url, simulated: true|false}

index.html: a "Ship" button on the project card opening a stepper —
Sync / Detect / Build / Ship — each step streaming live output, then a result
panel with the URL and a Share button reusing the BUILD 4 access popover.

IMPORTANT: when ship returns simulated:true, the UI must render "Simulated
target" under the URL. This is going on camera; a fabricated production URL
with no label is not acceptable.
```

**BUILD 7 — motion on the four filmed surfaces**

```
AirGPT: adopt ui/motion.js on the four surfaces the demo camera sees.

ui/motion.js and ui/apple.css are loaded but essentially unadopted — the app
still runs 91 CSS transitions, which cannot be caught mid-flight.

1. Hub peer nodes entering: Motion.springTo, preset 'snappy', 40ms stagger.
2. Peer drawer: preset 'sheet', drag-to-dismiss inheriting release velocity.
3. Lockdown wash: 220ms desaturate, then 400ms of enforced stillness — cancel
   every other running animation for that window.
4. Presence avatars: preset 'snappy', scale 0.6 -> 1.

Respect prefers-reduced-motion via the existing helper in motion.js.
Change nothing else.
```

---

### 3C · Cursor recording prompts

Every session starts with:

```powershell
cd D:\AirGPT
.\start_demo_mock.bat
(Invoke-RestMethod http://127.0.0.1:8765/api/info).demo_mock   # must be True
```

**REC-A · the interrupt (Act 1)** — the one that must be genuine.

```
Record AirGPT's two-person interrupt, 1920x1080 60fps, into
video-assets/03-demo-clips/multiplayer/.

Setup: DEMO MOCK profile. Two browser contexts — HOST (127.0.0.1:8765) and
PEER (joined by QR as "Jordan Lee · Eng"), same session, both visible.

Beats, one continuous take:
 1. HOST types "Sup Netie! Prepare a slideshow for today's 4pm meeting."
 2. Let the thinking chain and memory orchestration play out fully. Do not cut.
 3. At ~7s, PEER types "Hey Netie, complete the VDML sheet referencing the RFQ,
    FCM and PO from NMD?" and sends.
 4. Hold 4s on the HOST screen while the presence avatar springs in, the author
    chip renders, and Netie acknowledges both tasks.

Capture HOST full-frame; capture PEER separately for the picture-in-picture.
Do not cut between them — the simultaneity is the entire point.
Deliver: host.mp4, peer.mp4, and a synced side-by-side.
```

**REC-B · Hub + demo mode + drill-down (Act 3)**

```
Record the Coherent Access Hub, 1920x1080 60fps.

 1. Open Hub. Hold 2s on the radial graph.
 2. Toggle Demo mode. Hold 2s while the grid springs in.
 3. Click a RED (limited) peer. Let the drawer spring fully open.
 4. Hold 3s on the AI-source row, then 2s on the token bar.
 5. Click the third prompt -> "View chat →". Let it land and flash.

Move the cursor slowly and deliberately — this is being slowed to 0.8x in the
edit. Never move while an animation is still settling.
```

**REC-C · lockdown (Act 4)**

```
Record the emergency AI cut-off, 1920x1080 60fps, THREE screens simultaneously:
HOST + two PEER devices.

 1. All three active, prompts mid-flight.
 2. HOST: "Cut all AI · everyone" -> confirm.
 3. Hold 4 FULL SECONDS on the red state. Do not move the cursor. The stillness
    is the shot.
 4. Clear it. Hold 3s on the recovery.

Deliver all three angles, frame-synced.
```

**REC-D · share + phone join (Act 2)** and **REC-E · OpenVault ship (Act 6)** follow the same shape: one continuous take, host and phone in one frame for the join, slow deliberate cursor, hold on every settle.

---

### 3D · Assembly (Premiere / Motion / Raylight)

- **Timeline:** 2.39:1 letterbox for GEN plates; full 16:9 for REC. Cutting between them is a deliberate rhythm, not an accident — the film breathes wide, then goes flat-on for product.
- **Screen recordings:** 0.8x speed everywhere except the lockdown (1.0x) and the interrupt (1.0x). Nothing else should feel real-time.
- **Grade:** match REC to GEN — lift blacks 3%, cool the mids, one warm accent.
- **Colour meaning is fixed and must never break:** cyan = live · amber = idle · grey = offline · red = restricted or stopped · green = cleared.
- **Audio:** one music bed, three states — build (0:00–1:20), silence (1:26–1:32), release (1:38–end). The silence is the most important sound design decision in the film. Protect it in the mix.
- **Titles:** only four in the whole film, all lower-left, all small:
  `Same session. Same agent. No new thread.` ·
  `Read-only by default.` ·
  `One host. One button.` ·
  `Multiplayer by default.`

---

## 4. Capture hygiene

- [ ] `/api/info.demo_mock === true` on **every** machine in frame, verified on camera before the take
- [ ] No Settings or key-vault panel ever visible — `env.local` holds live keys
- [ ] Tunnel URLs are ephemeral public links; do not linger on them
- [ ] Mock forces LAN `10.10.20.42` — confirm no real IP or hostname is on screen
- [ ] Re-seed with `python seed_demo_mock.py --reset` between takes if chats get messy
- [ ] Every clip named `*_MOCK_*`
- [ ] Any simulated deploy target is labelled **on screen**

---

## 5. Order of operations

1. **Build P0-1, P0-2, P1-4** (1.25 days) — unlocks Acts 1, 2, 4, the emotional spine.
2. **Record REC-A immediately.** It is the submission. Everything else supports it.
3. **Build P0-3, P2-7** (1.5 days) → record REC-B, REC-C.
4. **Build P1-5, P1-6** (1.5 days) → record REC-D, REC-E.
5. **Generate plates 01–07** in parallel with all of the above — they need no code.
6. Assemble. Cut to 2:35. Then cut it to 2:00 and see if it got better. It usually does.

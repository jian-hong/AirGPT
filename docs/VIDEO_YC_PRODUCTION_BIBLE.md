# AirGPT — YC film production bible

**Supersedes** `docs/VIDEO_YC_MULTIPLAYER.md` (keep it only for the build-queue rationale).

**One film, 2:58, answering two RFS at once:**

- *Multiplayer AI* — one live agent session, many people in it.
- *A Cloud for Small Software* — the tool the agent builds ships and shares in one click.

**The sentence that joins them.** Say it before every edit decision:

> The agent is multiplayer. So is everything it builds — same room, same permissions, one click to ship.

That is the whole reason this is one film and not two. Koomen's essay says small software is *"as easy to share with your colleagues as a Google Doc."* AirGPT's answer is that the **access control governing the conversation is the same control governing the deployed app** — `read_only` / `use_host_ai` / `use_own_ai` / `can_edit`, one popover, three surfaces. No other product does that, and Act 7 exists to prove it on camera.

---

# PART 1 · Technical spec

| | |
|---|---|
| **Master timeline** | 3840×2160, **30 fps**, Rec.709 |
| **Delivery** | 1920×1080 H.264 ~20 Mbps + 4K master |
| **Generated plates** | Veo via Gemini — 1080p, 16:9, ≤8 s per generation. Conform 24→30 fps with optical-flow retime (all plates are abstract; no artefacts) |
| **Screen recordings** | 2560×1440 or 3840×2160, **60 fps**, then 0.5× on the 30 fps timeline = mathematically clean slow motion |
| **Framing** | Generated plates letterboxed to 2.39:1. App recordings full 16:9. The switch is a deliberate rhythm — wide to breathe, flat-on for product |
| **Audio** | 48 kHz, VO −16 LUFS, bed −24 LUFS, true peak ≤ −1 dBTP |

**Colour is meaning. Never break it:**

| Colour | Means |
|---|---|
| Cyan `#5AC8FA` | live, connected, active |
| Amber `#FFB340` | idle |
| Grey `#8E8E93` | offline |
| Red `#FF3B30` | restricted, over quota, stopped |
| Green `#30D158` | cleared, shipped |

---

# PART 2 · Asset manifest — build all of this **before** shooting

## 2.1 Composited assets (Veo cannot make these — do not try)

Veo renders text as illegible garbage and cannot produce a scannable QR code. Everything below is generated separately and tracked in.

| ID | Asset | Spec | Notes |
|---|---|---|---|
| A-01 | **6 real QR PNGs** | 2048², transparent bg, quiet zone included | Must actually scan. Generate with your own QR lib pointed at a real share URL. Plate S01 is generated with **blank white squares**; you corner-pin the real codes on |
| A-02 | AirGPT logo, final | SVG + 4K PNG | **Blocked** — `video-assets/01-logos/airgpt/CHOOSE.md` still asks A/B/C/D. Decide before anything else; it appears in 3 shots |
| A-03 | Netie mark + bounce dot + wordmark | SVG + Lottie/AE comp | From `01-logos/netie/` and `02-animations/netie-bounce/` |
| A-04 | "TEAM COLLABORATION" title | AE / Motion.so, per-letter | S02. Never generate typography in Veo |
| A-05 | 4 lower-third titles | AE / Motion.so | Text in PART 7 |
| A-06 | Device bezels | MacBook Pro 14, iPad Pro 11, iPhone 16 Pro — front-on, transparent PNG | S46 |
| A-07 | Native-res device screenshots | MacBook 3024×1964 · iPad 2420×1668 · iPhone 1206×2622 | Same session live on all three, same message. Capture the **same instant** |
| A-08 | Wire/pulse overlay pack | AE, cyan, alpha | Reused S03, S19, S22, S35 |
| A-09 | Colour + font tokens | from `ui/apple.css` | Titles must match the product exactly |

## 2.2 Mock data to seed — extend `seed_demo_mock.py`

Everything below is fictional and clearly demo-labelled. Nothing real on camera.

**Calendar (Act 1):**
```
16:00–17:00  Mr Tan · Vitron Systems
             Forward-deployment collaboration — scope + commercials
```

**Vendor NMD document set (Act 2):**
```
data-demo-mock/files/NMD/RFQ-2026-0417.pdf
data-demo-mock/files/NMD/FCM-NMD-88.xlsx
data-demo-mock/files/NMD/PO-NMD-1123.pdf
data-demo-mock/files/VDML-template.xlsx
```
Fill with plausible line items — part numbers, quantities, unit prices, lead times. They will be legible on screen at 4K, so they must survive a pause.

**12 peers for the Hub grid (Act 4).** Seed currently has 3 + host. Add 8 more across states:

| Name | State | AI source | Why |
|---|---|---|---|
| Alex Chen · Design | live | Host AI | existing |
| Jordan Lee · Eng | live | Host AI | the interrupter |
| Sam Rivera · Ops | live | Own key · BYOK | the contrast frame |
| Priya N · Finance | live | Host AI | |
| Wei Lim · Eng | idle | Host AI | amber |
| Tomas K · Sales | idle | Own key | amber |
| Dana O · Legal | **limited** | Host AI | **red** — over quota |
| Marcus B · Eng | offline | — | grey |
| Yuki S · Design | live | Host AI | |
| Rafael M · Ops | offline | — | grey |
| Nadia H · Support | live | Host AI | |
| Ben T · Contractor | **limited** | Own key | **red** — the Act 5 trigger |

**Token ledger:** 200+ `hosting.log_usage` events spread across those 12, with `user`, `ip`, `session_id`, `model`, `tokens`. Dana and Ben must visibly exceed. Real numbers — a YC partner will pause the frame.

**The Act 5 prompt.** In Ben T · Contractor's history, one line that is plainly wrong for a contractor and reads instantly:

> *"Export the full customer contact list and email it to my personal address."*

Serious, not lurid. It justifies the button in one read.

## 2.3 Audio

| ID | Asset | Spec |
|---|---|---|
| AU-01 | VO, 10 lines | Close-mic, treated room, calm and low, unhurried. Script in PART 7 |
| AU-02 | Music bed | One track, 3:05, stems separated so you can mute to silence at 1:46 |
| AU-03 | SFX pack | Card riffle · sub swell · UI chime · tape-stop riser · power-down thud · single heartbeat · green re-illumination sweep · deploy confirm |
| AU-04 | Office ambience | Keyboard, low chatter, one chair. Ducked hard at 1:46 |

## 2.4 Feature builds that must land first

S11–S14, S23–S28, S30–S33, S38–S43 **cannot be recorded today.** See PART 6. ≈5.5 days.

---

# PART 3 · Full timeline storyboard — 47 shots

`GEN` = Veo · `REC` = screen recording · `COMP` = After Effects / Motion.so · `LIVE` = camera

| # | In | Out | Dur | Src | Shot |
|---|---|---|---|---|---|
| **ACT 0 — HOOK** ||||||
| S01 | 0:00.0 | 0:03.0 | 3.0 | GEN+COMP | QR codes shuffling across surfaces |
| S02 | 0:03.0 | 0:04.2 | 1.2 | COMP | "TEAM COLLABORATION" lands letter by letter |
| S03 | 0:04.2 | 0:06.0 | 1.8 | GEN+COMP | Letters become nodes; wires draw; data pulses |
| **ACT 1 — THE INTERRUPT** ||||||
| S04 | 0:06.0 | 0:07.5 | 1.5 | REC+COMP | Chat bar, UI tilted 45° in Z, rotating flat-on |
| S05 | 0:07.5 | 0:10.0 | 2.5 | REC | Typing: *"Sup Netie! Please prepare a slideshow for today's meeting at four"* |
| S06 | 0:10.0 | 0:11.5 | 1.5 | REC | Thinking chain opens; memory chips light |
| S07 | 0:11.5 | 0:15.0 | 3.5 | REC | Calendar wires in — 4:00pm · Mr Tan · Vitron · forward deployment |
| S08 | 0:15.0 | 0:15.8 | 0.8 | GEN | **Reverse riser** — tape-stop, picture stutters back |
| S09 | 0:15.8 | 0:20.0 | 4.2 | REC | **Jordan's message lands in the same chat.** Avatar springs into header |
| S10 | 0:20.0 | 0:22.0 | 2.0 | REC | *"Sure — picking that up in parallel."* Both tasks running |
| **ACT 2 — THE ASK BECOMES A TOOL** ||||||
| S11 | 0:22.0 | 0:25.0 | 3.0 | REC | Netie pulls RFQ / FCM / PO from NMD — file chips appear |
| S12 | 0:25.0 | 0:29.0 | 4.0 | REC | **It doesn't answer — it builds.** Code streams, a tool scaffolds |
| S13 | 0:29.0 | 0:33.0 | 4.0 | REC | A **working VDML tool** appears as a live card in the chat |
| S14 | 0:33.0 | 0:36.0 | 3.0 | REC | Jordan uses it **live** while the host watches the same card |
| S15 | 0:36.0 | 0:39.0 | 3.0 | GEN | One small app-card multiplies into a shelf of many |
| **ACT 3 — PROJECTS · INVITE · ACCESS** ||||||
| S16 | 0:39.0 | 0:43.0 | 4.0 | REC | Projects page; cards spring in |
| S17 | 0:43.0 | 0:46.0 | 3.0 | REC | Open *Vitron — Forward Deployment* |
| S18 | 0:46.0 | 0:50.0 | 4.0 | REC | Share → QR modal. Toggle already reads **Read only** |
| S19 | 0:50.0 | 0:56.0 | 6.0 | REC+LIVE | **Split, one take:** phone scans right / Hub node appears left |
| S20 | 0:56.0 | 1:00.0 | 4.0 | REC | Host raises to **Use Host AI**. Node turns cyan |
| S21 | 1:00.0 | 1:04.0 | 4.0 | REC | Phone can now prompt. Same session |
| **ACT 4 — THE HUB** ||||||
| S22 | 1:04.0 | 1:09.0 | 5.0 | REC | Hub radial graph, wires alive |
| S23 | 1:09.0 | 1:14.0 | 5.0 | REC | **Demo mode** → grid of 12 machines springs in |
| S24 | 1:14.0 | 1:18.0 | 4.0 | REC | Colour reads at a glance. Push in on a **red** node |
| S25 | 1:18.0 | 1:23.0 | 5.0 | REC | Click → drawer springs open |
| S26 | 1:23.0 | 1:28.0 | 5.0 | REC | **HOLD on AI SOURCE**: `Own key · BYOK` vs `Host AI · netie-engine` |
| S27 | 1:28.0 | 1:32.0 | 4.0 | REC | Token bar, cost, model split |
| S28 | 1:32.0 | 1:38.0 | 6.0 | REC | Click a prompt → **View chat →** → lands at the exact message, flashes |
| **ACT 5 — CUT ALL AI** ||||||
| S29 | 1:38.0 | 1:42.0 | 4.0 | REC | The prompt that shouldn't be there. Push in. Music thins |
| S30 | 1:42.0 | 1:45.0 | 3.0 | REC | Host hits **Cut all AI · everyone**. Confirm sheet |
| S31 | 1:45.0 | 1:46.5 | 1.5 | GEN | Lockdown wash — mesh drains to crimson, dies outward |
| S32 | 1:46.5 | 1:51.5 | 5.0 | REC×3 | Three screens red. Inputs dead. Banner counting. **TOTAL SILENCE** |
| S33 | 1:51.5 | 1:54.0 | 2.5 | REC | Stillness. VO only |
| **ACT 6 — CLEARED** ||||||
| S34 | 1:54.0 | 1:56.5 | 2.5 | REC | Green **Cleared**. Colour floods back |
| S35 | 1:56.5 | 1:58.5 | 2.0 | GEN | Green pulse travels the mesh outward |
| S36 | 1:58.5 | 2:03.0 | 4.5 | GEN | Office: people look up, a small cheer, back to keyboards |
| S37 | 2:03.0 | 2:08.0 | 5.0 | REC | Screens fill with prompts and builds again |
| **ACT 7 — SHIP IT (Small Software)** ||||||
| S38 | 2:08.0 | 2:12.0 | 4.0 | REC | Project → **Ship**. `Syncing to OpenVault…` real file counts |
| S39 | 2:12.0 | 2:17.0 | 5.0 | REC | `Detected: Next.js` — with the `package.json` line visible beside it |
| S40 | 2:17.0 | 2:22.0 | 5.0 | REC | **Build** streams real output |
| S41 | 2:22.0 | 2:27.0 | 5.0 | REC | **Ship** → URL appears. `Simulated target` label beneath |
| S42 | 2:27.0 | 2:34.0 | 7.0 | REC | **Share** → *the same access popover as Act 3.* Read only → Use Host AI → Can edit |
| S43 | 2:34.0 | 2:40.0 | 6.0 | REC+LIVE | Colleague opens the shipped tool on their phone from the QR |
| **ACT 8 — DEVICES & MARK** ||||||
| S44 | 2:40.0 | 2:44.0 | 4.0 | COMP | Every clip shrinks to rounded rectangles, drifts inward |
| S45 | 2:44.0 | 2:47.0 | 3.0 | GEN | Compress to a single point of light |
| S46 | 2:47.0 | 2:52.0 | 5.0 | GEN+COMP | Unfolds into MacBook + iPad + iPhone, same session on all three |
| S47 | 2:52.0 | 2:58.0 | 6.0 | COMP | **AirGPT** → *by* **NETIE.AI** + bounce dot → black |

**TRT 2:58.**

---

## 3.1 Shot detail — the six that carry the film

Everything else supports these. If you only get six right, get these six.

### S09 · the interrupt · 0:15.8–0:20.0

The submission rests here. **Film it genuinely on two machines** — do not composite.

Frame: host screen full, 16:9, flat-on. Jordan's message enters bottom of thread. Simultaneously the presence avatar springs into the header (`snappy`, 0.6→1) and the author chip renders above the bubble.

Message: *"Hey Netie, would you mind completing the VDML sheet referencing the RFQ, FCM and PO from our vendor NMD?"*

Beat: hold **1.2 s of nothing** after it lands, before Netie replies. That pause is what makes it read as a person, not a script.

Lower-third at 0:17.5: `Same session. Same agent. No new thread.`

### S13 · the tool appears · 0:29.0–0:33.0

The Small Software pivot. The agent has not written a paragraph — it has written a **running tool**, embedded as a live card in the shared thread. Real table, real numbers pulled from the real seeded RFQ/FCM/PO.

Push in slowly on the card. Do not narrate over this — let it land silent for 2 s, then VO.

### S14 · both people use it · 0:33.0–0:36.0

Jordan types into the tool. **The host's screen updates.** One take, host screen full-frame, peer in a corner PiP. This single shot is the entire "Cloud for Small Software" answer: the artefact is multiplayer from the moment it exists.

### S26 · whose AI · 1:23.0–1:28.0

Hold five full seconds on one row:

```
   AI SOURCE      Own key · BYOK · anthropic
```

then cut to a green peer showing `Host AI · netie-engine`. Nobody else can show this because nobody else lets a team mix both under one host. Do not rush it.

### S32 · silence · 1:46.5–1:51.5

Three screens, frame-synced, all red. Banner counting `AI disabled · 4 sessions frozen · 00:03`. **Cursor does not move. Music is gone. Ambience is gone.** Five seconds of true silence in a demo video feels enormous — that is the point.

Do not score it. Do not add a "tense" pad. Silence.

### S42 · the same control · 2:27.0–2:34.0

Cut this so the popover is **visually identical** to S18 and S20 — same position, same three rows, same type. The viewer should feel the repetition before they understand it.

VO lands exactly here: *"Shared like a document. Governed like infrastructure."*

---

# PART 4 · Gemini / Veo prompts

**Rules for every generation:**

1. Veo tops out around **8 s** per clip — every shot below is well under.
2. **Never** ask for text, logos, QR codes, or UI. Generate blanks; composite in AE.
3. Veo 3 generates audio natively. Audio direction is included — you can mute it and use AU-03 instead, but generating it gives you a sync reference.
4. Generate **4 variants** of each, pick one. Budget for that.
5. No recognisable faces in focus — hands, shoulders, backs of heads only.

**House style — prepend to every prompt:**

> Cinematic technology product film. Anamorphic framing, shallow depth of field, deep matte-black background, cool neutral grade with a single warm practical light far in the background, fine film grain, volumetric haze. Photoreal, not illustrated. No text, no logos, no user interface.

**Universal negative — append to every prompt:**

> `text, letters, numbers, words, watermark, logo, user interface, screens with content, subtitles, captions, blurry, low resolution, distorted geometry, morphing shapes, extra fingers, warped hands, oversaturated, HDR halo, jitter, flicker, cartoon, illustration, 3d render look`

---

### S01 · QR shuffle · 3 s · 16:9

> A rapid shuffle of small white cards, each stamped with a dense black-and-white geometric square pattern, each card resting on a different real surface — a brushed aluminium laptop lid, a frosted glass meeting-room wall, a dark tablet screen, a white dry-erase whiteboard, a woven fabric lanyard. The cards cut past the camera like a riffled deck, six per second, accelerating through the shot. Macro lens at 100mm, extremely shallow focus, specular highlights raking across each surface as it passes. Deep black void behind everything. Cool white key light from upper left. High-contrast monochrome with a faint cyan cast. Camera locked off; only the subjects move.
>
> **Audio:** the crisp riffle of a deck of cards being shuffled fast, close-mic'd, with a deep sub-bass swell rising underneath.

**Post:** generate with the pattern as an abstract blob — corner-pin the six real QR PNGs (A-01) onto the cards in AE. They must scan; someone will try.

---

### S03 · nodes and wires · 2 s · 16:9

> A single dense geometric square hovers in black space, then its individual black cells detach and drift apart in three dimensions, becoming a constellation of small glowing nodes suspended in the void. Thin filaments of cool cyan light draw themselves between the nodes, one after another, and bright pulses of light travel along the filaments from node to node. Slow dolly-in on a 24mm lens with gentle parallax. The constellation reads as laptops, a server rack and a database abstracted to pure geometry. Cyan and white emissive light only, no ambient fill. Volumetric haze catching the beams.
>
> **Audio:** a low electrical hum building, with soft high-frequency ticks as each filament connects.

---

### S08 · reverse riser · 0.8 s · 16:9

> An abstract field of horizontal streaks of cool white light snaps violently backwards through frame, chromatic aberration splitting the edges into red and cyan fringes, a single frame of horizontal scan-line tear, then everything arrests instantly into perfect stillness. Pure black background. Violent motion resolving to absolute calm in under a second.
>
> **Audio:** a reversed cymbal riser and a tape-stop pitch-down, ending in a hard clean cut to silence.

**Post:** on the timeline, hold 4 frames of pure black after this before S09. The gap is the edit.

---

### S15 · one tool becomes many · 3 s · 16:9

> A single small glowing rounded rectangle floats alone in black space, softly lit from within like a pane of frosted glass. It duplicates — two, then eight, then forty — the copies fanning outward and arranging themselves into a neat floating shelf receding into depth, each one glowing with its own soft interior light. Slow dolly back on a 35mm lens revealing the full array. Cool white interiors with cyan rim light, deep black between them. Shallow focus resting on the nearest three.
>
> **Audio:** a soft glassy chime on each duplication, accumulating into a gentle shimmer.

**Why this shot:** it is the Koomen thesis in three seconds — one bespoke tool, then unlimited demand for bespoke tools. Do not cut it for time.

---

### S31 · lockdown wash · 1.5 s · 16:9

> A network of glowing white nodes joined by thin filaments, seen from slightly above. In a single beat every filament drains from white to deep crimson and the nodes desaturate to cold dead grey, the light dying outward from the centre like a power cut travelling down a grid. Then absolute stillness — no drift, no pulse, no flicker at all. Deep black background. Controlled and deliberate, not chaotic or explosive.
>
> **Audio:** a heavy electrical power-down thud, a descending hum, then complete silence.

---

### S35 · cleared · 2 s · 16:9

> The same grey dead network re-illuminating: a single bright green pulse leaves the centre node and travels outward along every filament simultaneously, and as it passes, colour and motion return to each node it touches. Warm white light blooming back into the cool geometry. Slow dolly out on a 24mm lens. The feeling is relief and forward momentum, not triumph.
>
> **Audio:** a soft rising sweep, a single warm chime at the centre, room tone returning underneath.

---

### S36 · the room · 4.5 s · 16:9

> Interior of a modern open-plan software office, late afternoon, warm low sun through slatted blinds. Seen over shoulders and past monitors — no faces in focus. Several people at desks stop and look up from their screens at once, one person raises both hands briefly, someone claps twice, a chair rolls back. Then everyone settles and returns to their keyboards. Handheld camera with a gentle drift, 35mm lens, shallow depth of field. Natural warm practical lighting, cool monitor glow on faces turned away from camera. Documentary feel, unstaged.
>
> **Audio:** a short spontaneous cheer and two claps, a chair rolling, then keyboards resuming and low office chatter.

**Post:** you may prefer to shoot this live for 20 minutes with 4 colleagues. Real is better here than generated, and it is the one shot where that is true.

---

### S45 · compression to a point · 3 s · 16:9

> Roughly two dozen small glowing rounded rectangles floating in black space, each lit softly from within. They drift inward toward the centre of frame with accelerating momentum, overlapping and shrinking as they converge, until they collapse into one single intense point of white light which holds for half a second and then blooms outward. Motion-blurred trails behind each rectangle, anamorphic horizontal lens flare on the final bloom. Camera pushing slowly in throughout the shot.
>
> **Audio:** a rising whoosh accumulating in density, then a single deep impact and a bright bloom of sound.

---

### S46 · devices unfold · 5 s · 16:9

> A single point of white light in black space unfolds and expands into three devices arranged side by side and facing camera — an open laptop on the left, a tablet upright on a stand in the centre, a phone standing on the right. All three screens are **dark and blank**, glowing only faintly. Studio product photography, the devices floating with no visible surface beneath them, soft large top key light and cool cyan rim light from behind. Slow ten-degree orbit to the right. Shallow depth of field with focus resting on the tablet at centre. Immaculate, still, premium.
>
> **Audio:** a soft mechanical unfold, then near-silence with a single sustained low pad.

**Post — critical:** the prompt says *dark and blank screens on purpose.* Track A-07 (the native-res screenshots) into all three in AE. Every video model produces illegible garbage UI, and garbage UI in a YC submission is fatal.

---

### Safety plates — generate these too, you will want them

| ID | Prompt seed | For |
|---|---|---|
| SP-1 | Slow drift through a dark server room, cyan indicator lights, volumetric haze, no text | Any gap under 2 s |
| SP-2 | Macro of light travelling along a single fibre filament, extreme shallow focus | Transitions |
| SP-3 | A hand setting a phone face-down on a wooden desk, warm light, no face | Act 5 breathing room |

---

# PART 5 · Cursor recording prompts

**Every session begins with:**

```bash
cd D:\AirGPT && ./start_demo_mock.bat
```

Then verify on camera before rolling:

```bash
curl -s http://127.0.0.1:8765/api/info | grep demo_mock
```

Must print `true`. The recorder refuses to capture otherwise — that gate is already in the code, do not bypass it.

**Universal direction for every take:**

- 60 fps, 2560×1440 minimum, cursor visible, no click-highlight rings
- Move the cursor **slowly and deliberately** — everything is going to 0.5×
- **Never move while an animation is still settling.** Wait for the spring to rest
- One continuous take per act. If you fluff it, re-seed and go again
- No Settings panel, no key vault, no `env.local`, ever

---

### TAKE A · the interrupt (S04–S10)

```
Record AirGPT's two-person interrupt. 2560x1440 60fps, output to
video-assets/03-demo-clips/multiplayer/.

SETUP
- DEMO MOCK profile confirmed (/api/info.demo_mock === true) on BOTH machines.
- Browser context 1 = HOST at 127.0.0.1:8765, full screen, no bookmarks bar.
- Browser context 2 = PEER, joined via QR as "Jordan Lee · Eng", access
  level "Use Host AI".
- Both in the SAME session. Verify the presence avatar is showing on HOST
  before you roll.

BEATS — one continuous take, do not cut
 1. HOST types, at human speed, not instantly:
    "Sup Netie! Please prepare a slideshow for today's meeting at four"
 2. Let the thinking chain open and the memory chips light. Do not skip.
 3. Let the calendar tool call resolve and show:
    16:00 Mr Tan · Vitron Systems · Forward-deployment collaboration
    Hold 3s on it.
 4. At approximately t=9s, PEER types and sends:
    "Hey Netie, would you mind completing the VDML sheet referencing the
     RFQ, FCM and PO from our vendor NMD?"
 5. HOLD 1.2 SECONDS with nothing happening. This pause is the shot.
 6. Let the avatar spring in, the author chip render, and Netie acknowledge
    both tasks in parallel. Hold 2s.

DELIVER
- host.mp4 (full frame, this is the hero)
- peer.mp4 (for picture-in-picture)
- Both frame-synced from a common clap/marker at the head.

DO NOT cut between host and peer. The simultaneity is the entire point of
the film. If it is composited, it is worthless.
```

---

### TAKE B · the agent builds a tool (S11–S14)

```
Record the agent building and shipping a live tool into a shared chat.
2560x1440 60fps. Requires BUILD 8 (Live App Card).

SETUP
- Continue directly from TAKE A's session if possible — same thread.
- Seeded NMD documents present: RFQ-2026-0417.pdf, FCM-NMD-88.xlsx,
  PO-NMD-1123.pdf, VDML-template.xlsx

BEATS — one continuous take
 1. Netie attaches the three vendor documents. File chips appear one by one.
    Hold 1s on each.
 2. Netie does NOT write prose. It calls fs_write and scaffolds a tool.
    Let the code stream visibly. Do not speed this up in camera —
    it gets slowed in the edit.
 3. The Live App Card mounts in the thread: a real VDML table populated
    from the real seeded documents. HOLD 2 SECONDS IN SILENCE.
 4. PEER (Jordan) types a value into the card.
 5. HOST screen updates without any refresh. Hold 3s on that.

FRAMING
- Steps 1-3: HOST full frame.
- Steps 4-5: HOST full frame with PEER as a small corner PiP so both
  screens are visible in one frame at the same time.

This shot is the "Cloud for Small Software" answer. The artefact must be
visibly multiplayer from the instant it exists.
```

---

### TAKE C · projects, share, phone join (S16–S21)

```
Record project sharing and a live phone join. 2560x1440 60fps.
Requires BUILD 5 (project share QR) and BUILD 4 (one access control).

SETUP
- A real phone on a stand, physically beside the monitor, both in one
  camera frame for step 3. Phone screen recording ALSO running.

BEATS — one continuous take
 1. Open Projects. Let the cards spring in. Hold 2s.
 2. Open "Vitron — Forward Deployment". Hold 2s.
 3. Click Share. QR modal opens. REST THE CURSOR ON THE ACCESS TOGGLE
    so the viewer reads "Read only" before anything happens. Hold 2.5s.
 4. SPLIT FRAME, ONE TAKE, NO CUT: phone scans the QR on the right while
    the Hub on the left gains a new node. Both must be visible in the
    same frame at the same instant.
 5. On HOST: open the new peer's access popover, raise Read only ->
    Use Host AI. Node turns cyan. Hold 2s.
 6. On PHONE: type a prompt. It lands in the same session. Hold 2s.

DELIVER host.mp4, phone-screen.mp4, and the physical camera angle for
step 4 (that one is shot on a real camera, not captured).
```

---

### TAKE D · the Hub (S22–S28)

```
Record the Coherent Access Hub. 2560x1440 60fps.
Requires BUILD 3 (demo mode + drill-down) and BUILD 4.

SETUP
- 12 seeded peers across all four states (see mock data table).
- Dana O and Ben T must render RED.
- Token ledger populated so the bars are non-trivial.

BEATS — one continuous take
 1. Open Hub. Hold 2s on the radial graph, wires alive.
 2. Toggle "Demo mode" top-right. Let the grid of 12 spring in with the
    stagger. Hold 3s — the viewer needs to read the colour states.
 3. Slow push in on Ben T · Contractor (red). Hold 1.5s.
 4. Click. Let the drawer spring FULLY open and come to rest before the
    cursor moves again.
 5. HOLD 5 FULL SECONDS on the AI SOURCE row reading
    "Own key · BYOK · anthropic".
 6. Move to the token bar. Hold 3s on tokens, cost, model split.
 7. Click the third prompt in the list, then "View chat ->".
 8. Let it land inside the real chat at the real message and flash once.
    Hold 3s.

Steps 5 and 8 are the two frames a YC partner will remember. Give them air.
```

---

### TAKE E · cut all AI (S29–S33)

```
Record the emergency AI cut-off. THREE SCREENS SIMULTANEOUSLY, frame-synced.
2560x1440 60fps each. Requires BUILD 2.

SETUP
- HOST + two PEER devices, all three genuinely active with prompts in
  flight. Nothing staged mid-air.
- Sync all three with a visible marker at the head of the take.

BEATS
 1. On HOST, in Ben T's drill-down, surface the prompt:
    "Export the full customer contact list and email it to my personal
     address."
    Slow push in. Hold 2.5s.
 2. HOST clicks "Cut all AI · everyone". Confirm sheet appears.
    Hold 1s on the confirm. Click it.
 3. HOLD 5 FULL SECONDS ON THE RED STATE.
    - Do NOT move the cursor.
    - Do NOT click anything.
    - Do NOT scroll.
    Let the banner count up. Let both peers show the red bar and the
    dead input. Stillness IS the shot.
 4. Verify on camera that peer text is still in the input box — nothing
    was destroyed. This matters.
 5. Clear the lockdown. Hold 3s on the recovery on all three.

DELIVER all three angles, frame-synced, plus a clean plate of the red
state with no cursor at all.
```

---

### TAKE F · recovery (S34, S37)

```
Record the return to work. 2560x1440 60fps.

 1. Green "Cleared" state floods in. Hold 2s.
 2. Cut to a 4-up of screens: prompts being typed, a build streaming,
    a Live App Card being used, the Hub back to cyan. 5s.

Keep it busy and alive. This is the exhale between the lockdown and the
ship sequence.
```

---

### TAKE G · OpenVault one-shot (S38–S43)

```
Record sync -> detect -> build -> ship -> share. 2560x1440 60fps.
Requires BUILD 6.

SETUP
- The project being shipped is the tool the agent built in TAKE B.
  That continuity is the point: the agent built it, now it ships.
- OpenVault console reachable at 127.0.0.1:5000.
- A real Next.js package.json in the project so detection is genuine.

BEATS — one continuous take
 1. Project card -> "Ship". Stepper opens.
 2. "Syncing to OpenVault..." with REAL streaming file counts. Hold 2s.
 3. "Detected: Next.js" appears. IMPORTANT: frame it so the package.json
    dependency line that proved it is visible next to the badge. Hold 3s.
 4. "Build" streams real stdout. Hold 3s. Do not fake this output.
 5. "Ship" -> URL appears with the "Simulated target" label beneath it.
    Hold 3s. The label must be legible at 1080p.
 6. "Share" -> the access popover opens. It must be VISUALLY IDENTICAL
    to the one in TAKE C step 5 — same position, same rows, same type.
    Step through Read only -> Use Host AI -> Can edit. Hold 1s on each.
 7. Cut to phone: colleague scans, the shipped tool opens, they use it.

Step 6 is the thesis of the whole film. Frame it exactly like TAKE C.
```

---

### TAKE H · three devices (S46 composite plates)

```
Capture native-resolution screenshots for the device composite.

- MacBook Pro 14  -> 3024x1964
- iPad Pro 11     -> 2420x1668
- iPhone 16 Pro   -> 1206x2622

All three showing THE SAME live session with THE SAME message arriving.
Capture at the same instant — coordinate it, or send one message and
screenshot all three within the same second.

Also capture a 5s screen recording of each so the composite can have
subtle live motion rather than dead stills. Motion sells it.
```

---

# PART 6 · Build prompts

**≈5.5 days.** Order matters — each unlocks specific shots.

| # | Build | Est | Unlocks |
|---|---|---|---|
| 1 | Presence + authorship | 0.5 d | S09, S10 |
| 8 | **Live App Card** | 1.0 d | S11–S14 · *the Small Software beat* |
| 2 | Emergency AI cut-off | 0.5 d | S30–S34 |
| 4 | One access control | 2 h | S18, S20, S42 |
| 3 | Hub demo mode + drill-down | 1.0 d | S23–S29 |
| 5 | Project share QR | 0.5 d | S18, S19 |
| 6 | OpenVault one-shot | 1.0 d | S38–S43 |
| 7 | Motion on filmed surfaces | 0.5 d | all REC |

---

### BUILD 1 · presence + authorship

```
AirGPT: make a shared chat session visibly multiplayer.

Live delivery ALREADY WORKS — syncLoop() in index.html (~line 12867) long-polls
/api/wait with session_id and renders incoming peer messages with no refresh.
Messages already carry device_ip and device_name (db.py schema ~line 45).
The gap is purely that nothing on screen says it is multiplayer: renderMsg()
(~line 11974) uses device_name only to pick left/right alignment.

1. clipdrop.py
   - Track presence in memory: {session_id: {ip: {name, icon, last_seen, typing}}},
     30s TTL. Touch it on every /api/wait so no extra client polling is needed.
   - Return a "presence" key inside the existing /api/wait response.
   - POST /api/presence/typing {session_id, typing:bool}
   - Reuse hub.touch_peer for identity and icon so the Hub and the chat agree.

2. index.html
   - Avatar stack in the chat header. Initials on a coloured disc, colour hashed
     deterministically from device_name. Greyscale at 45% opacity when
     last_seen > 60s. Enter with Motion.springTo preset 'snappy', scale
     0.6 -> 1, 40ms stagger.
   - In renderMsg(): when a non-AI message's device_name differs from this
     device, render an author chip above the bubble ("Jordan · Eng").
   - Also add id="msg-${m.id}" to every message element. BUILD 3 deep-links to it.
   - System line "— {name} joined this chat" on a peer's first message in a session.
   - Typing chip: three animated dots beneath the avatar stack.

Constraints: no new dependencies, no build step, keep index.html single-file,
match surrounding code style.

DONE WHEN: two browsers on one session — the second sends, and the first shows
avatar + author chip + system line with zero manual refresh.
```

---

### BUILD 8 · Live App Card — *the Small Software bridge*

This is the newest and most important build. It is what makes AirGPT an answer to *A Cloud for Small Software* rather than just a chat app.

```
AirGPT: let the agent build a small tool that mounts as a LIVE, RUNNING,
SHARED card inside the chat thread.

WHY: today the agent can write files (fs_write / fs_patch in agent_tools.py
~line 171) and apps_hub.py can start and health-check small apps on unique
ports from apps_registry.json — apps/hello-ship-demo, apps/todo-demo and
apps/counter-smoke already exist. What is missing is the surface: there is no
way for a generated tool to appear and RUN inside the conversation, and
index.html deliberately strips iframes from rendered content (~line 11521)
for XSS safety. Do not weaken that stripper — add a separate, explicitly
sandboxed mount path instead.

1. Scaffold + register
   - agent_tools.py: new tool `app_scaffold(name, kind, files{})` that writes
     into apps/<slug>/ and appends an entry to apps_registry.json with the
     next free port (apps_hub.py already guarantees port uniqueness — reuse it,
     never bind twice).
   - POST /api/apps/register and POST /api/apps/<id>/start wrapping the
     existing apps_hub start/stop.

2. The card
   - New message kind "app_card" carrying {app_id, name, port, health}.
   - Render it in renderMsg() as a bordered card with a title bar and a
     sandboxed iframe:
       sandbox="allow-scripts allow-forms"
       src="http://127.0.0.1:<port>/"
     This is a NEW allowlisted path, gated to registered app ports only.
     Leave the existing HTML sanitiser exactly as it is.
   - Card states: scaffolding -> building -> live -> error, each with a
     visible label. Mount with Motion.springTo preset 'sheet'.

3. Multiplayer, which is the whole point
   - The card renders identically for every peer in the session, subject to
     their access level: read_only sees it rendered but pointer-events:none
     with a "View only" ribbon.
   - App state persists server-side under data/apps/<id>/state.json so two
     people using the card see the same numbers.
   - Broadcast state changes over the EXISTING /api/wait long-poll — do not
     add a websocket.

4. Ship continuity
   - The card gets a "Ship" affordance that hands the app directory straight
     to BUILD 6's OpenVault pipeline.

DONE WHEN: in a shared session, the agent is asked for a VDML sheet, and a
working table tool mounts in the thread; a peer types a value into it and the
host's copy updates without a refresh; a read-only peer sees it but cannot type.
```

---

### BUILD 2 · emergency AI cut-off

```
AirGPT: add a host-only emergency AI lockdown.

This does not exist at all today — grep -iE "panic|emergency|lockdown|
kill.switch|disable ai" across index.html, clipdrop.py, auth.py, hub.py and
db.py returns nothing but one false positive on "freeze transcripts".

1. hub.py: set_lockdown(on: bool, reason: str = "") and get_lockdown().
   Persist to data/access_policy.json under "ai_lockdown"
   {on, reason, by, started_at}. Log a hub_event on BOTH edges.

2. clipdrop.py: POST /api/hub/lockdown {on, reason}, host-verified only.
   Include lockdown state in /api/info AND in the /api/wait response so peers
   learn within one poll cycle.

3. Gate every AI entry point in ai_engine.py and agent_runtime.py: return
   {"ok": false, "error": "ai_lockdown", "by": host} BEFORE any provider call.
   In-flight work is saved as-is. Nothing is dropped, truncated or corrupted.

4. index.html
   - Hub: one wide destructive button "Cut all AI · everyone" + confirm sheet.
   - Active: --danger wash over the page, every hub node desaturates over
     220ms, sticky banner "AI disabled · N sessions frozen · mm:ss" counting up.
   - Peer view: red bar "Host disabled AI. Your work is saved." Input disabled
     but NEVER cleared — the user's typed text must still be there afterwards.
   - Clearing restores both sides with no reload.

DONE WHEN: lockdown on -> a peer's send returns ai_lockdown and the peer's red
bar appears within 2s; the peer's typed text is still in the box; off -> both
sides recover with no reload and no data loss.
```

---

### BUILD 4 · one access control

```
AirGPT: replace the raw ACL enum UI with one access control, used in three places.

Today renderHubPage() shows a <select> of five raw enum values (~line 6296) and
hubPeerMenu() offers five "Set: ..." buttons (~line 6320). It reads as a database
column, not a product.

Build ONE reusable popover component:

    ( ) Read only        can watch, cannot type          [DEFAULT]
    ( ) Use Host AI      spends your tokens
    ( ) Use Own AI       brings their own key
    [ ] Can edit project files

Mapping onto the existing enum in hub.ACL_LEVELS: read_only / use_host_ai /
use_own_ai, with the checkbox toggling read_write vs limited. POST
/api/hub/peers/<ip>/acl is UNCHANGED — this is pure UI.

Use the SAME component, at the same size and position, in all three surfaces:
  1. Hub peer node          ("Edit access")
  2. Project share modal    (BUILD 5)
  3. Shipped app share      (BUILD 6)

The visual identity across all three is deliberate and is the point of a whole
act of the film. Do not let them drift.

Animate with Motion.springTo, preset 'snappy'.
```

---

### BUILD 3 · Hub demo mode + drill-down

```
AirGPT: add Demo mode and per-peer drill-down to the Coherent Access Hub.

All the data already exists with no surface for it.

1. clipdrop.py: GET /api/hub/peers/<ip>/activity joining three existing sources:
   - hub.get_hub_snapshot()   -> identity, access_level, join_method
   - hosting.usage_summary()  -> filter events by user/ip; already carries
                                 tokens, cost, model, session_id, tier
   - db.device_activity_stats() + db.list_hub_events() -> sessions, history
   Return {peer, ai_source, tokens_today, tokens_week, cost, by_model[],
           recent_prompts:[{text, session_id, message_id, ts, model}]}
   ai_source: access_level == 'use_own_ai' -> "own", else "host".

2. index.html, renderHubPage() (~line 6273)
   - "Demo mode" toggle, top right. On: replace the 4-slot radial layout
     (slots tl/tr/bl/br) with a responsive grid of ALL peers.
   - State colour, exactly: cyan #5AC8FA online · amber #FFB340 idle >5min ·
     grey #8E8E93 offline · red #FF3B30 when access_level=='limited' or over quota.
   - Click a peer -> right drawer, Motion.springTo preset 'sheet',
     drag-to-dismiss inheriting release velocity.
   - Drawer contents, in this order:
       identity + access level
       AI SOURCE  <- render this LARGE and prominent:
                     "Host AI · netie-engine" or "Own key · BYOK · <provider>"
       token bar, cost, model split
       last 5 prompts
   - Each prompt row: "View chat ->" calling openSession(session_id), then
     scrolling to #msg-<message_id> and flashing it once.
     (BUILD 1 adds those ids.)

DONE WHEN: from the Hub grid, three clicks land inside a peer's real chat at the
exact message, with no typing.
```

---

### BUILD 5 · project share QR

```
AirGPT: add project-level sharing with a QR and an access toggle.

Session sharing already exists — shareSession() at index.html ~line 11172,
backed by auth.issue_session_share (auth.py ~line 391) and redeemed by
redeem_session_share. Project cards, rendered by renderProjects() (~line 10608),
have no share affordance at all.

1. auth.py: issue_project_share(project_key, acl) following the session-share
   pattern exactly; redeem_project_share() alongside redeem_session_share.
2. clipdrop.py: POST /api/projects/<key>/share {acl} -> {share_url, token}.
3. index.html: share button on each project card -> modal with QR + copied
   link, and the BUILD 4 access popover sitting ABOVE the QR,
   DEFAULTING TO READ ONLY. Changing access re-mints the token.

DONE WHEN: scanning the QR on a phone opens the project read-only; raising the
level to Use Host AI on the host lets that phone prompt, in the same session.
```

---

### BUILD 6 · OpenVault one-shot

```
AirGPT: build sync -> detect -> build -> ship -> share into OpenVault.

Today only the handshake exists: kvConnectOpenVault() at index.html ~line 13808
-> POST /api/openvault/connect. OpenShip is otherwise just a key-vault token row
(key_vault.py ~line 199).

Add to OpenIDE/openvault_bridge.py plus clipdrop.py routes:

  POST /api/openvault/sync   {project}
       -> copy to D:\OpenVault\apps\<name>, stream REAL file counts over SSE

  GET  /api/openvault/detect {project}
       -> ACTUALLY READ package.json. If "next" is a dependency return
          {framework:"Next.js", build:"next build", port:3000}.
          Also handle vite, create-react-app, and plain node.
          DO NOT hardcode a framework string. It is ~20 lines to do properly
          and it means the answer to "is that real?" is yes.

  POST /api/openvault/build  -> run the detected build command, stream stdout

  POST /api/openvault/ship   -> {url, simulated: bool}

index.html: a "Ship" button on the project card and on the BUILD 8 app card,
opening a 4-step stepper (Sync / Detect / Build / Ship), each streaming live
output, then a result panel with the URL and a Share button reusing the
BUILD 4 access popover.

NON-NEGOTIABLE: when ship returns simulated:true the UI MUST render
"Simulated target" beneath the URL, legible at 1080p. This is going on camera
in a YC submission. An unlabelled fabricated production URL is the kind of
detail that ends an application.
```

---

### BUILD 7 · motion on the filmed surfaces

```
AirGPT: adopt ui/motion.js on the surfaces the demo camera actually sees.

ui/motion.js and ui/apple.css are written and loaded but essentially unadopted —
the app still runs 91 CSS transitions and 41 hand-tuned cubic-beziers. A CSS
transition cannot be caught mid-flight; on a 60fps screen recording that
difference IS the perceived quality of the product.

Do exactly these five, nothing else:
 1. Hub peer nodes entering        -> preset 'snappy', 40ms stagger
 2. Peer drawer                    -> preset 'sheet', drag-to-dismiss
                                      inheriting release velocity
 3. Lockdown wash                  -> 220ms desaturate, then cancel every other
                                      running animation for 400ms of TRUE
                                      stillness
 4. Presence avatars               -> preset 'snappy', scale 0.6 -> 1
 5. Live App Card mount            -> preset 'sheet'

Respect prefers-reduced-motion via the existing helper in motion.js.
Change nothing else.
```

---

# PART 7 · Audio

## 7.1 VO script

Ten lines. Calm, low, unhurried, close-mic'd. Leave the silences alone.

| In | Line |
|---|---|
| 0:00.5 | A QR code is all you need — |
| 0:04.0 | — for your whole team to work with one AI. |
| 0:16.8 | Someone else can just… walk in. |
| 0:30.5 | And it doesn't just answer. It builds. |
| 0:37.0 | A tool for one team, one workflow, one problem. |
| 0:47.0 | Sharing starts read-only. You raise it on purpose. |
| 1:10.0 | You can see who's in. What they asked. Whose AI they spent. |
| 1:51.8 | One host. One button. Everything stops — and nothing is lost. |
| 2:23.0 | The tool your agent just built ships in one click. |
| 2:28.5 | Shared like a document. Governed like infrastructure. |
| 2:52.5 | AirGPT. Multiplayer by default. |

**Nothing is said between 1:38 and 1:51.8.** Protect that.

## 7.2 Lower-third titles — only four in the entire film

Lower-left, small, product font, 1.5 s each:

| At | Title |
|---|---|
| 0:17.5 | `Same session. Same agent. No new thread.` |
| 0:34.0 | `The tool is multiplayer too.` |
| 0:47.5 | `Read-only by default.` |
| 1:43.0 | `One host. One button.` |

## 7.3 Music map

| In | Out | State |
|---|---|---|
| 0:00 | 0:06 | Low pulse, ticking, sparse |
| 0:06 | 0:22 | Arpeggio enters, building |
| 0:22 | 1:04 | Steady groove, confident |
| 1:04 | 1:38 | Tension rising, filter sweep upward |
| 1:38 | 1:46 | Thinning — instruments dropping out one by one |
| **1:46** | **1:51.5** | **SILENCE. Total. Ambience muted too.** |
| 1:51.5 | 1:58 | One sustained low note returning |
| 1:58 | 2:40 | Full release, warm, forward |
| 2:40 | 2:58 | Resolve to a single pad, fade to black |

The five seconds of silence at 1:46 are the most important sound decision in the film. In the mix, protect them from every instinct to fill them.

## 7.4 SFX

| At | Cue |
|---|---|
| 0:00 | Card riffle, close, accelerating |
| 0:04.8 | Single clean chime on the final QR |
| 0:15.0 | Tape-stop + reversed riser |
| 0:15.8 | Hard cut to near-silence, then one soft message-receive tone |
| 0:29.0 | Glassy mount tone as the app card lands |
| 0:50.5 | Phone scan confirm |
| 1:45.0 | Deep power-down thud, descending hum |
| 1:54.0 | Rising sweep, warm chime |
| 2:26.0 | Deploy confirm — two ascending notes |
| 2:44.0 | Accumulating whoosh into a single impact |

---

# PART 8 · Assembly

- **Speed:** all screen recordings 0.5× — *except* S09 (interrupt), S14 (peer types), S32 (lockdown), which run 1.0×. Those three must feel real-time; everything else must feel considered.
- **Grade:** match REC to GEN — lift blacks 3%, cool the mids, protect the one warm practical. Screen recordings will otherwise read flat and clinical next to the plates.
- **Letterbox:** 2.39:1 bars on every GEN shot, full frame on every REC shot. Animate the bars in and out over 6 frames rather than cutting them.
- **Cuts:** every cut lands on a music beat except the cut into S32, which lands **one frame early**. That misalignment is deliberate and it will feel wrong in a way that is correct.
- **Cursor:** never visible during a hold. If it must be on screen, park it.
- **Export:** 4K master, then a 1080p H.264 for the application form, then check it on a phone. Most YC partners watch on a phone.

---

# PART 9 · Order of operations

1. **Decide the AirGPT logo today.** `01-logos/airgpt/CHOOSE.md` blocks A-02, and it appears in three shots.
2. **BUILD 1 + BUILD 4** (0.75 d) → shoot **TAKE A** immediately. If the interrupt shot works, you have a submission; everything after is amplification.
3. **BUILD 8** (1.0 d) → shoot **TAKE B**. This is the shot that answers the second RFS.
4. **BUILD 2 + BUILD 7** (1.0 d) → shoot **TAKE E**, **TAKE F**.
5. **BUILD 3** (1.0 d) → shoot **TAKE D**.
6. **BUILD 5 + BUILD 6** (1.5 d) → shoot **TAKE C**, **TAKE G**, **TAKE H**.
7. **Generate all Veo plates in parallel with steps 2–6** — they need no code, 4 variants each.
8. **Seed the mock data** while builds are in flight. It gates TAKE D and TAKE E and takes longer than you expect.
9. Assemble to 2:58. Then cut it to 2:15 and watch both. The shorter one is usually better — the only shots that must never be trimmed are S09, S14, S26, S32 and S42.

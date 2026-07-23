# AirGPT — Higgsfield Marketing Video Production Plan
**Series:** 4 videos (Hero Film, Moat Spotlight, Builder Spotlight, 3× Social Verticals)
**Product:** AirGPT — local-first AI clipboard, chat, and phone-to-PC sync (paired with Netie for governance)
**Prepared for:** Video connector — Higgsfield generation + edit assembly
**Version:** v1.0

---

# 0. STYLE LOCK (applies to every video — do not deviate)

## 0.1 Color grade
- Canvas: near-black `#0a0a0a`. Blacks anchored at IRE 2 — never crushed to 0, never lifted above 5%.
- One show LUT for everything: `AIRGPT_SHOW_LUT_v1.cube` — Rec.709, global desaturation to ~88%, gentle S-curve, +3% halation on speculars only. Applied in edit, never baked into plates.
- Accent discipline: **white** is the only kinetic/type accent. **Green `#3dd68c`** appears ONLY at success/confirmation moments (connect tick, Approve, "landed in chat"). Green on screen = something worked. Never use green decoratively.
- Temperature: neutral-cool (5600K bias) for product sections; a single warm shift (4300K) allowed only in the Business/Netie close of Video 1.

## 0.2 Typography
- Titles / kinetic type: **DM Sans**, weight 600, tracking −1%, white, sentence case. Max 6 words per card.
- Labels, timecodes, kickers, captions: **IBM Plex Mono**, weight 400, ALL CAPS, 60% white, letterspaced +8%.
- Type animation: 180ms ease (cubic-bezier 0.2, 0, 0, 1), opacity + 8px Y-rise. No bounces, no per-letter cascades, no typewriter except the AI-stream moments where it mirrors real UI behavior.

## 0.3 Motion language
- All UI/type moves: 180ms eased. All camera plate moves: slow (≤10% frame travel per second).
- Average scene length 1.5–2.5s. The ONE exception: the hero result shot in each video holds longer (2.4–3.2s) with near-silence before it.
- Transitions vocabulary (only these): hard cut on beat, whip pan, match cut, glass morph (frosted blur cross-dissolve, 8–12 frames), dip-to-black (hero setup only).

## 0.4 Forbidden looks (reject any Higgsfield output containing these)
- Purple/magenta "AI fog", particle swarms, neural-network node graphs, glowing brains, humanoid robots.
- Any invented / hallucinated UI, fake dashboards, fake text on screens. Screens in generated plates must be dark, blank, or bokeh'd out — real UI is composited later.
- Lens-flare abuse, cyberpunk neon streets, stock "hacker" imagery, emoji, aviation imagery (AirGPT is NOT aviation — reject planes/cockpits if the model drifts on the name).
- Excessive camera shake, speed-ramped whooshy drone spam, watermarked stock texture.

## 0.5 Audio signature
- **"AI acts" sound** (mandatory on every analysis/stream/agent moment): soft granular glass shimmer, 300–600ms, layered over a sub-tick at −20 LUFS. Same sample library across all 4 videos. Name it `SFX_AI_ACTS_v1.wav` and reuse.
- UI ticks: short, dry, −18 LUFS. Success tick (green moments): slightly pitched-up variant, `SFX_TICK_OK.wav`.
- Near-silence rule: 0.6–1.0s duck to −30 LUFS room tone immediately before each hero result.
- Loudness targets: −14 LUFS integrated (social), −16 LUFS (hero/spots), true peak −1 dBTP.

## 0.6 Brand mark
- Geometric triangle mark: always rendered as etched/frosted glass with a single white light sweep. Never spinning, never 3D-extruded chrome.

---

# VIDEO 1 — BRAND HERO FILM

## 1. Title / runtime / aspect / use case
- **Title:** *AirGPT — Your Work Stays Yours*
- **Runtime:** 70.0s
- **Aspect:** 16:9, 3840×2160 master (safe-crop 1:1 center for feed re-use)
- **Use case:** Website hero, YouTube pre-roll, launch post pinned video, sales-deck opener.

## 2. One-line creative thesis
Shadow AI and phone-hell are the villain; AirGPT is the calm, local, audited machine that ends both — proven live with the phone→PC clipboard loop, then widened to engineers and the business.

## 3 + 4. Beat sheet with per-shot Higgsfield prompts
Legend: `HF` = Higgsfield-generated plate. `UI` = real screen capture, full-frame or comped (no generation). Every HF prompt: subject / camera move (ONE) / lens / lighting / grade / duration / motion intensity.

| # | TC (s) | Dur | Shot | Source |
|---|--------|-----|------|--------|
| S01 | 0.0–2.2 | 2.2 | ECU: phone glow reflected in a worker's glasses, dark office | HF |
| S02 | 2.2–4.2 | 2.0 | Top-down: cluttered desk, face-down phone buzzing, laptop half-open | HF |
| S03 | 4.2–6.2 | 2.0 | Night office exterior through glass, dozens of blue monitor glows | HF |
| S04 | 6.2–7.4 | 1.2 | Hard black. Type card #1 | Type |
| S05 | 7.4–9.4 | 2.0 | Triangle brand mark, light sweep on etched glass — **drop at 8.0** | HF + logo comp |
| S06 | 9.4–12.0 | 2.6 | **REAL UI:** main Liquid Glass chat, idle then cursor into input | UI |
| S07 | 12.0–14.0 | 2.0 | **REAL UI:** Connect screen, Tunnel QR displayed | UI |
| S08 | 14.0–16.0 | 2.0 | Hands raise phone to laptop screen to scan (screen dark in plate) | HF (phone screen comped) |
| S09 | 16.0–18.2 | 2.2 | **REAL UI (phone capture):** Send to PC tap on a photo | UI |
| S10 | 18.2–18.8 | 0.6 | Near-silence beat: black with faint frosted texture | Type/plate |
| S11 | 18.8–21.4 | 2.6 | **HERO — REAL UI:** photo lands in AirGPT chat, green confirmation | UI |
| S12 | 21.4–23.8 | 2.4 | **REAL UI:** clipboard chip → Copy to Notepad → paste in Notepad | UI |
| S13 | 23.8–26.2 | 2.4 | **REAL UI:** copy from Windows back → appears in chat. Loop closed | UI |
| S14 | 26.2–27.6 | 1.4 | Breath: macro laptop hinge / desk texture, calm | HF |
| S15 | 27.6–30.6 | 3.0 | **REAL UI:** engineering diagram pasted → AI screenshot analysis streams | UI |
| S16 | 30.6–31.8 | 1.2 | **REAL UI:** Memory panel quick cut | UI |
| S17 | 31.8–33.0 | 1.2 | **REAL UI:** Projects hub quick cut | UI |
| S18 | 33.0–34.8 | 1.8 | Type card #2 on black glass texture | Type |
| S19 | 34.8–37.2 | 2.4 | **REAL UI:** Cortex — Thinking Idle → Assist → Deep | UI (prism underlay HF) |
| S20 | 37.2–39.4 | 2.2 | **REAL UI:** Vault Summarizer run + Audit trail lines | UI |
| S21 | 39.4–41.8 | 2.4 | **REAL UI:** OpenIDE — proposed write, Approve (green) | UI |
| S22 | 41.8–44.6 | 2.8 | **REAL UI:** OpenForge — chat → schematic renders | UI |
| S23 | 44.6–46.8 | 2.2 | **REAL UI:** Marketplace "Fits / Can't fit" + Hosting glance (2 fast cuts) | UI |
| S24 | 46.8–48.6 | 1.8 | Glass-morph mood shift: wide office at dawn, laptops closed, calm | HF |
| S25 | 48.6–52.0 | 3.4 | **REAL UI:** Business Admin dual-brain — Workforce Observatory + Netie | UI |
| S26 | 52.0–54.6 | 2.6 | Single closed laptop on clean desk, morning light — "it stays here" | HF |
| S27 | 54.6–57.6 | 3.0 | Recap montage: 3× 1.0s re-hits (S11 land, S15 stream, S22 schematic) | UI |
| S28 | 57.6–60.6 | 3.0 | Type card #3 | Type |
| S29 | 60.6–66.0 | 5.4 | End card: triangle mark, wordmark, tagline, CTA | Logo comp |
| S30 | 66.0–70.0 | 4.0 | Hold end card, audio tail resolves to silence | — |

### Higgsfield prompts (HF shots only)

**S01 — `HF_V1_S01_glasses-reflection`**
- Subject: extreme close-up of a person's eyeglasses in a dark office at night, a small bright smartphone-shaped glow reflected in the lens, face mostly in shadow, no readable screen content
- Camera move: slow push-in
- Lens: 100mm macro, f/2.0, shallow DOF
- Lighting: single cool practical from below-left (phone as source), 5600K, deep shadows
- Grade: near-black, desaturated, no color cast
- Duration: 3s (trim to 2.2)
- Motion intensity: low

**S02 — `HF_V1_S02_desk-overhead`**
- Subject: top-down overhead of a cluttered office desk at night — face-down smartphone with edge glow pulsing, half-open dark laptop, scattered cables and sticky notes, coffee cup
- Camera move: slow lateral truck left
- Lens: 35mm, f/4
- Lighting: dim overhead office fluorescent falloff plus phone edge glow, moody
- Grade: cold, near-black shadows, muted midtones
- Duration: 3s (trim to 2.0)
- Motion intensity: low

**S03 — `HF_V1_S03_office-glow`**
- Subject: nighttime open-plan office seen through a floor-to-ceiling glass wall, rows of empty desks, many monitors glowing cold blue in the dark, slight interior haze, no readable screens
- Camera move: slow dolly right along the glass
- Lens: 24mm, f/2.8
- Lighting: monitor glow only, cold blue-white, heavy negative fill
- Grade: desaturated, blacks anchored, slight halation on the glows
- Duration: 3s (trim to 2.0)
- Motion intensity: low

**S05 — `HF_V1_S05_triangle-sweep`**
- Subject: a minimalist geometric triangle etched into dark frosted glass, a single thin white light sweep traveling across the etch, pure black background, subtle glass grain
- Camera move: static (light does the motion)
- Lens: 85mm macro, f/5.6
- Lighting: single hard white sweep, everything else black
- Grade: monochrome, high micro-contrast, no color
- Duration: 3s (trim to 2.0)
- Motion intensity: low
- Note: final logo lockup is a design comp on top; the HF plate is texture/energy only.

**S08 — `HF_V1_S08_phone-scan`**
- Subject: over-the-shoulder close-up of hands raising a smartphone toward a dark laptop screen as if scanning something, office at night, phone screen dark/blank, laptop screen dark
- Camera move: slow arc right around the hands
- Lens: 50mm, f/2.2
- Lighting: soft key from laptop direction, cool, rim from window
- Grade: near-black, neutral
- Duration: 3s (trim to 2.0)
- Motion intensity: medium
- Note: both screens replaced in comp (laptop = real QR capture, phone = real camera-scan capture).

**S14 — `HF_V1_S14_hinge-macro`**
- Subject: macro of a matte-black laptop hinge and aluminum edge on a clean dark desk, tiny dust motes in a soft beam of light, calm and precise
- Camera move: slow tilt up
- Lens: 100mm macro, f/2.8
- Lighting: single soft beam, cool white
- Grade: neutral, deep blacks
- Duration: 2s (use 1.4)
- Motion intensity: low

**S19 underlay — `HF_V1_S19_prism`**
- Subject: a small frosted-glass prism slowly refracting a thin band of white light on a black surface, abstract, elegant, no color spectrum rainbow — white light only
- Camera move: slow orbital left
- Lens: 85mm macro, f/4
- Lighting: single white beam through prism
- Grade: monochrome
- Duration: 4s (loops under S19 at 15% opacity behind UI)
- Motion intensity: low

**S24 — `HF_V1_S24_dawn-office`**
- Subject: wide calm open-plan office at dawn, warm low sun through windows, all laptops closed on tidy desks, no people, serene and orderly
- Camera move: slow push-in down the center aisle
- Lens: 32mm, f/4
- Lighting: warm natural dawn (4300K), soft
- Grade: gently warm, still near-black in shadow corners
- Duration: 3s (trim to 1.8)
- Motion intensity: low

**S26 — `HF_V1_S26_laptop-closed`**
- Subject: a single closed dark laptop centered on a clean wooden desk, morning side-light, a smartphone resting beside it screen-down, absolute stillness
- Camera move: slow push-in
- Lens: 50mm, f/2.8
- Lighting: soft warm window key, cool fill
- Grade: warm-neutral, calm
- Duration: 3s (trim to 2.6)
- Motion intensity: low

## 5. VO script + on-screen text
**VO (169 words, calm confident read, ~145 wpm — fits 70s with pauses):**

> (0.0) Every day, company work walks out the door. Pasted into random AI tabs. Photographed and emailed to yourself — just to move one file from your phone to your PC.
> (7.4) There's a better way. AirGPT. A local-first AI workspace that lives on your laptop — not in someone else's cloud.
> (12.0) Scan once, and your phone and PC are connected. Send a photo — it lands in chat, drops to your clipboard, pastes anywhere on Windows… and comes straight back. One loop. Zero friction.
> (27.6) Paste an engineering diagram, and AirGPT reads it — on your machine, on an audited AI path.
> (34.8) Cortex agents think idle, assist, or deep — summarizing vaults, logging every step. OpenIDE writes only what you approve. OpenForge turns chat into schematics.
> (48.6) And for the business: a Workforce Observatory, governed with Netie. See the AI work. Keep it inside. End shadow AI.
> (57.6) AirGPT. Local-first AI clipboard, chat, and phone-to-PC sync. Your work stays yours.

**Type cards (DM Sans 600, white):**
- S04 (6.2s): `Your work shouldn't leave the building.`
- S13 (25.6s, lower-third kicker, Plex Mono): `CLIPBOARD ↔ CHAT · ONE LOOP`
- S18 (33.0s): `It never left your laptop.`
- S28 (57.6s): `Local-first. Company-safe.`
- S29 end card: triangle mark + `AirGPT` + Plex Mono tagline `LOCAL-FIRST AI CLIPBOARD · CHAT · PHONE-TO-PC SYNC` + CTA `Get AirGPT + Netie` + URL.

## 6. SFX map
| TC | SFX |
|----|-----|
| 0.0 | low room tone fades in, distant phone buzz ×2 (muffled) |
| 2.2 | phone vibration on wood (dry, close) |
| 4.2 | rising airy tension pad (subtle) |
| 6.2 | everything cuts — near-silence, single sub tick under type |
| 8.0 | **bass drop** + glass sweep (logo) |
| 9.4 | soft glass morph + UI tick (chat appears) |
| 12.0 | UI tick (QR renders) |
| 14.6 | camera-shutter half-press click (phone scan) |
| 16.6 | phone tap tick (Send to PC) |
| 18.2 | **duck to near-silence (0.6s)** |
| 18.8 | soft whoosh-in + `SFX_TICK_OK` (green landing) — hero moment |
| 21.8 / 23.0 | dry copy/paste ticks (2×) |
| 23.8 | `SFX_TICK_OK` (loop closes) |
| 27.6 | `SFX_AI_ACTS_v1` (analysis stream starts), typewriter murmur under stream |
| 30.6 / 31.8 | UI ticks (Memory, Projects) |
| 34.8 | `SFX_AI_ACTS_v1` variant (Cortex gears), 3 soft state ticks |
| 39.4 | pen-click (Approve, green) `SFX_TICK_OK` |
| 41.8 | `SFX_AI_ACTS_v1` + low swell (schematic materializes) |
| 46.8 | glass morph whoosh (mood shift, warm) |
| 52.0 | air settles; music thins to pulse |
| 57.6 | final soft bass hit under type card |
| 60.6 | logo glass sweep; 66.0 tail to silence |

## 7. Music direction
- 92 BPM, minimal analog pulse (think Linear launch films / Vercel Ship): sub bass + dry rimshot + airy pad. No melody until 8.0.
- Energy curve: 0–6.2 tense sparse → 6.2–8.0 silence → **8.0 drop #1** (product era begins) → 18.2 duck → 18.8 groove locks in (hero loop) → 27.6 add texture layer (engineer section) → **41.8 lift #2** (OpenForge) → 46.8 warm harmonic shift (business) → 57.6 resolve → 60.6–70.0 single sustained pad, decays to silence.

## 8. Transition notes
- S01→S02→S03: hard cuts on beat. S03→S04: hard cut to black (audio cuts with it).
- S04→S05: dip-through — type card burns off 180ms, light sweep enters.
- S05→S06: **match cut** — light sweep position matches chat panel edge as it fades in.
- S06→S07: glass morph (10f). S07→S08: hard cut. S08→S09: whip pan left into phone capture.
- S09→S10→S11: hard cut to black, then hard cut on `SFX_TICK_OK` — the silence sells the landing.
- S11→S12→S13: hard cuts on copy/paste ticks (edit to the SFX, not the bar).
- S13→S14: glass morph (breath). S14→S15: hard cut on `SFX_AI_ACTS`.
- S15→S16→S17: 1.2s hard-cut pair. S17→S18: dip to black.
- S18→S19: type card defocuses into prism underlay (match the blur).
- S19→S20→S21: hard cuts. S21→S22: glass morph. S22→S23: hard cuts (2 fast).
- S23→S24: **glass morph with temperature shift** (cool→warm — the only warm move in the film).
- S24→S25: hard cut. S25→S26: glass morph. S26→S27: hard cuts ×3 on beat. S27→S28→S29: dip to black, logo sweep in.

## 9. Editor assembly notes
- **Full-frame UI is the default.** Capture at 2560×1440+ 60fps, retime/conform to 23.976. Scale to ~96% with a 2–3% slow push (Ken Burns, eased) and a soft glass vignette (8% edge darken + 1px frosted inner border) so captures feel filmed, not pasted.
- **Comped screens (S08 phone/laptop):** corner-pin real captures onto the HF plate; add 3% screen glow spill onto hands, 2% motion blur matched to plate movement, 3% grain overlay to unify.
- Never crop AirGPT chrome mid-element; respect the Liquid Glass panel edges.
- Cursor choreography in captures: slow, deliberate, one action per shot. Re-capture rather than speed-ramp mouse moves; only the S27 recap may use 200% speed.
- Grain: 3% fine grain over everything (plates + UI) as the final unifying layer, under the LUT.
- Type cards live on true `#0a0a0a`, not on plates, except lower-third kickers.

## 10. Connector / export package checklist
- [ ] `HF_V1_S01…S26` plates: max res, 24fps (or conform), NO watermark, neutral/flat if possible — naming `HF_V1_S08_phone-scan_v02.mp4`
- [ ] UI captures: `UI_V1_S06_chat-idle.mov` … `UI_V1_S25_admin-netie.mov`, 2560×1440 @ 60fps, ProRes 422 or lossless, cursor visible, no notifications/toasts, demo content pre-staged (real engineering diagram image; a real photo for the Tunnel demo)
- [ ] Phone captures: `UI_V1_S09_phone-sendtopc.mov` — native screen record, 60fps, portrait, clean status bar
- [ ] VO: `VO_V1_master_48k.wav`, 48kHz/24-bit, dry + light comp, alt takes for lines at 7.4 / 18.8 / 57.6
- [ ] SFX kit: `SFX_AI_ACTS_v1.wav`, `SFX_TICK_OK.wav`, tick set, glass morph set, bass drop
- [ ] Music: stems (drums/bass/pad/texture) so the 18.2 duck and 46.8 shift can be re-timed
- [ ] LUT: `AIRGPT_SHOW_LUT_v1.cube` + before/after reference stills
- [ ] Logo package: triangle mark SVG + wordmark, DM Sans + IBM Plex Mono font files, end-card layered file
- [ ] Master delivery: `AIRGPT_V1_HERO_70s_3840x2160_2398_v01.mov` ProRes 422 HQ + H.264 review proxy; captions SRT

---

# VIDEO 2 — MOAT SPOTLIGHT: PHONE→PC + CLIPBOARD

## 1. Title / runtime / aspect / use case
- **Title:** *One QR. One Loop.*
- **Runtime:** 36.0s
- **Aspect:** 16:9 master 3840×2160; frame all UI action title-safe for a 4:5 crop
- **Use case:** Product page "How it works", paid mid-funnel, sales follow-up email embed.

## 2. One-line creative thesis
No story, no villain — 36 seconds of uninterrupted product magic: the Tunnel QR handshake and the clipboard↔chat loop shown once cleanly and once fast, so the viewer's only thought is "wait, do that again."

## 3 + 4. Beat sheet + Higgsfield prompts

| # | TC (s) | Dur | Shot | Source |
|---|--------|-----|------|--------|
| S01 | 0.0–1.6 | 1.6 | Macro: phone lifted into frame in a dark room, screen dark | HF |
| S02 | 1.6–3.6 | 2.0 | **REAL UI:** AirGPT Connect screen — Tunnel QR renders | UI |
| S03 | 3.6–5.6 | 2.0 | **REAL UI (phone):** camera viewfinder locks onto QR | UI (phone capture) |
| S04 | 5.6–7.0 | 1.4 | **REAL UI:** connected — green confirmation | UI |
| S05 | 7.0–9.2 | 2.2 | Hands photographing a whiteboard full of sketches with phone | HF (screen comped) |
| S06 | 9.2–10.8 | 1.6 | **REAL UI (phone):** Send to PC tap | UI |
| S07 | 10.8–11.4 | 0.6 | Black. Near-silence | — |
| S08 | 11.4–14.0 | 2.6 | **HERO — REAL UI:** photo lands in chat, green tick | UI |
| S09 | 14.0–16.4 | 2.4 | **REAL UI:** clipboard chip → Copy to Notepad | UI |
| S10 | 16.4–18.6 | 2.2 | **REAL UI:** paste lands in Notepad (Windows) | UI |
| S11 | 18.6–21.2 | 2.6 | **REAL UI:** copy text in Windows → appears back in chat | UI |
| S12 | 21.2–24.2 | 3.0 | Speed-ramp replay: full loop again at 250%, 4 cuts | UI |
| S13 | 24.2–26.6 | 2.4 | Type card on black | Type |
| S14 | 26.6–29.0 | 2.4 | Calm wide: laptop + phone side by side on desk, both at rest | HF |
| S15 | 29.0–33.0 | 4.0 | End card: mark, tagline, CTA | Logo comp |
| S16 | 33.0–36.0 | 3.0 | Hold, audio tail | — |

**S01 — `HF_V2_S01_phone-lift`**
- Subject: macro side profile of a hand lifting a modern smartphone into frame against pure darkness, screen off, faint cool rim light tracing the phone edge
- Camera move: static (subject enters frame)
- Lens: 85mm macro, f/2.0
- Lighting: single cool rim from behind-right, black background
- Grade: near-black, monochrome
- Duration: 2s (trim 1.6) | Motion intensity: low

**S05 — `HF_V2_S05_whiteboard-photo`**
- Subject: over-the-shoulder shot of hands framing a smartphone photo of an office whiteboard densely covered in handwritten diagrams and arrows, phone screen blank/dark, shallow focus on the phone
- Camera move: slow push-in
- Lens: 50mm, f/2.0
- Lighting: soft office daylight from the left, cool
- Grade: neutral, desaturated, near-black falloff
- Duration: 3s (trim 2.2) | Motion intensity: medium
- Note: phone screen replaced with real camera capture in comp.

**S14 — `HF_V2_S14_pair-at-rest`**
- Subject: a dark laptop and a smartphone lying side by side on a clean dark desk, perfectly aligned, one thin white light band across both, still and satisfying
- Camera move: slow tilt down
- Lens: 35mm, f/4
- Lighting: single soft white band, black surround
- Grade: monochrome, precise
- Duration: 3s (trim 2.4) | Motion intensity: low

## 5. VO script + on-screen text
**VO (76 words):**
> (0.0) How many times have you emailed a photo to yourself?
> (1.6) Watch. One QR code — your phone and your PC, connected. Locally.
> (7.0) Take the shot. Send to PC.
> (11.4) It's already in chat. Already on your clipboard.
> (14.0) Paste it into Notepad. Copy anything back — it's in chat again.
> (21.2) Phone, to PC, to anywhere. And back.
> (24.2) No cable. No cloud detour. No email-to-self.
> (29.0) AirGPT. Local-first sync that just works.

**Type:**
- S04 kicker (Plex Mono, green tick glyph allowed): `CONNECTED · LOCAL TUNNEL`
- S13 card (DM Sans): `No cable. No cloud. No email-to-self.` (three lines, staggered 180ms)
- S15 end card: mark + `AirGPT` + `PHONE → PC → ANYWHERE → BACK` + CTA.

## 6. SFX map
| TC | SFX |
|----|-----|
| 0.0 | room tone, fabric/hand movement foley |
| 1.6 | UI tick (QR draws in) |
| 3.6 | camera focus-lock click |
| 5.6 | `SFX_TICK_OK` (green connect) |
| 8.4 | phone shutter (real, dry) |
| 9.6 | tap tick (Send to PC) |
| 10.8 | **duck to near-silence** |
| 11.4 | soft whoosh + `SFX_TICK_OK` — hero landing |
| 14.6 / 17.0 | copy tick / paste tick |
| 19.8 | `SFX_TICK_OK` (loop closes) |
| 21.2–24.2 | ticks retimed to the 250% replay (4 fast ticks) |
| 24.2 | sub hit under type card |
| 29.0 | glass sweep (logo), tail to silence at 33.0 |

## 7. Music direction
- 100 BPM, dry percussive minimalism — clicky rim, muted sub, no pad until the end card. The UI ticks ARE part of the groove; edit them on-grid.
- Curve: 0–10.8 building sparse groove → 10.8 full stop (silence) → **11.4 drop** (bass enters exactly on the landing tick) → 21.2 double-time hats under replay → 24.2 strip to sub only → 29.0 single warm pad chord to close.

## 8. Transition notes
- S01→S02: match cut — phone edge line matches Connect panel edge.
- S02→S03: hard cut. S03→S04: hard cut on focus-lock click.
- S04→S05: whip pan right (office energy). S05→S06: hard cut.
- S06→S07→S08: cut to black, then cut in on the OK tick. Do not cross-dissolve here — silence + hard cut is the moment.
- S08–S11: all hard cuts landing exactly on copy/paste SFX.
- S11→S12: 6-frame glass morph into the speed replay. S12→S13: hard cut to black on last tick.
- S13→S14: glass morph. S14→S15: dip to black, sweep in.

## 9. Editor assembly notes
- This video is ~80% raw capture: quality lives in the captures. Stage the demo so the photo content is legible and believable (real whiteboard sketch, not lorem).
- Keep one continuous capture take of the full loop as safety (`UI_V2_FULLLOOP_safety.mov`) — cut the beats from it so cursor position is continuous across S08–S11.
- Replay (S12): reuse the same takes at 250% with 1-frame white flashes REMOVED (no flashes — just clean fast cuts).
- Phone footage: record actual device screen (not simulator); comp into S05 plate with hand-tracked corner pin.
- Same LUT/grain/vignette rules as Video 1.

## 10. Export package checklist
- [ ] `HF_V2_S01/S05/S14` plates, 24fps, max res, naming per pattern
- [ ] `UI_V2_S02…S11` captures @1440p60 + `UI_V2_FULLLOOP_safety.mov`
- [ ] Phone screen records: `UI_V2_S03_scan.mov`, `UI_V2_S06_sendtopc.mov` (portrait 60fps)
- [ ] `VO_V2_master_48k.wav` + SFX kit (shared) + music stems
- [ ] Master: `AIRGPT_V2_MOAT_36s_3840x2160_2398_v01.mov` + 4:5 crop QC pass + SRT

---

# VIDEO 3 — BUILDER SPOTLIGHT: CORTEX + OPENIDE + OPENFORGE

## 1. Title / runtime / aspect / use case
- **Title:** *Agents That Build. Guardrails That Hold.*
- **Runtime:** 42.0s
- **Aspect:** 16:9, 3840×2160
- **Use case:** Developer/engineering audience — dev-tool newsletters, X/technical LinkedIn, docs landing, conference loop.

## 2. One-line creative thesis
For builders who distrust AI autonomy: show Cortex thinking in gears with a visible audit trail, OpenIDE asking permission before every write, and OpenForge turning a sentence into a schematic — power, permissioned.

## 3 + 4. Beat sheet + Higgsfield prompts

| # | TC (s) | Dur | Shot | Source |
|---|--------|-----|------|--------|
| S01 | 0.0–1.8 | 1.8 | Macro: single keycap pressed on a dark mechanical keyboard | HF |
| S02 | 1.8–4.2 | 2.4 | **REAL UI:** Cortex panel — Thinking Idle → Assist → Deep (3 state changes) | UI |
| S03 | 4.2–6.8 | 2.6 | **REAL UI:** Deep thinking stream running | UI (prism underlay reuse `HF_V1_S19_prism`) |
| S04 | 6.8–9.2 | 2.4 | **REAL UI:** Vault Summarizer run completes | UI |
| S05 | 9.2–11.4 | 2.2 | **REAL UI:** Audit trail — log lines appending | UI |
| S06 | 11.4–12.6 | 1.2 | Type card #1 | Type |
| S07 | 12.6–15.2 | 2.6 | **REAL UI:** OpenIDE — agent proposes a file write (diff visible) | UI |
| S08 | 15.2–16.8 | 1.6 | **REAL UI:** Approve click — green, write lands | UI |
| S09 | 16.8–18.4 | 1.6 | **REAL UI:** second proposal → Reject — write discarded | UI |
| S10 | 18.4–19.6 | 1.2 | Type card #2 | Type |
| S11 | 19.6–20.4 | 0.8 | Glass-morph plate: ruled drafting texture, breath | HF |
| S12 | 20.4–23.0 | 2.6 | **REAL UI:** OpenForge — engineer types the request in chat | UI |
| S13 | 23.0–23.6 | 0.6 | Near-silence, black | — |
| S14 | 23.6–26.8 | 3.2 | **HERO — REAL UI:** schematic materializes from chat | UI |
| S15 | 26.8–29.2 | 2.4 | **REAL UI:** Marketplace — "Fits" result, then a "Can't fit" | UI |
| S16 | 29.2–31.0 | 1.8 | **REAL UI:** Hosting glance | UI |
| S17 | 31.0–33.6 | 2.6 | Type card #3 over slow HF texture | Type + HF |
| S18 | 33.6–38.0 | 4.4 | End card: mark, dev-flavored CTA | Logo comp |
| S19 | 38.0–42.0 | 4.0 | Hold, tail | — |

**S01 — `HF_V3_S01_keycap`**
- Subject: extreme macro of a single backlit-free dark keycap being pressed on a black mechanical keyboard, shallow focus, tiny dust, restrained and precise
- Camera move: slow push-in
- Lens: 100mm macro, f/2.8
- Lighting: one hard white edge light from the right, black surround
- Grade: monochrome, deep blacks
- Duration: 2s (trim 1.8) | Motion intensity: low

**S11 — `HF_V3_S11_drafting-texture`**
- Subject: macro of fine engineering drafting paper texture with faint ruled grid lines catching a moving band of white light, abstract, no drawings visible
- Camera move: slow lateral truck right
- Lens: 85mm macro, f/4
- Lighting: single raking white band
- Grade: monochrome, subtle
- Duration: 2s (trim 0.8; extended version reused under S17 at 20% opacity) | Motion intensity: low

## 5. VO script + on-screen text
**VO (83 words):**
> (0.0) Meet the part of AirGPT that builds.
> (1.8) Cortex agents run in three gears — idle, assist, and deep — summarizing your vault, and logging every move to an audit trail.
> (12.6) OpenIDE proposes real file writes. Nothing lands until you approve it. Reject it — it's gone.
> (20.4) Then OpenForge: describe it in chat…
> (23.6) …and get a schematic.
> (26.8) Fits, or can't fit — the Marketplace tells you straight.
> (31.0) Agents that build. Guardrails that hold. All local. All audited.
> (36.0) AirGPT.

**Type:**
- S06 (11.4s): `Every step, audited.`
- S10 (18.4s): `You hold the pen.`
- S17 (31.0s): `Agents that build. Guardrails that hold.` (two lines)
- S05 kicker (Plex Mono, runs with audit log): `AUDIT · APPEND-ONLY`
- S18 end card: mark + `AirGPT` + `CORTEX · OPENIDE · OPENFORGE` + CTA `Build on your machine`.

## 6. SFX map
| TC | SFX |
|----|-----|
| 0.0 | keycap press (real, dry, close) — the opening sound IS the hook |
| 1.8 | 3 soft state ticks (Idle/Assist/Deep, rising pitch) |
| 4.2 | `SFX_AI_ACTS_v1` (deep stream), granular murmur sustained |
| 6.8 | completion tick (Vault Summarizer) |
| 9.2 | quiet log ticks, metronomic (audit lines) |
| 11.4 | sub hit under type |
| 12.6 | diff-render tick |
| 15.2 | `SFX_TICK_OK` (Approve, green) |
| 16.8 | dull decline thunk (Reject — lower pitch, no green) |
| 18.4 | sub hit under type |
| 20.4 | keystroke foley under typing |
| 23.0 | **duck to near-silence** |
| 23.6 | `SFX_AI_ACTS_v1` + slow swell — schematic hero |
| 26.8 | `SFX_TICK_OK` (Fits) then flat tick (Can't fit) |
| 31.0 | final sub hit; 33.6 logo sweep; tail out by 40.0 |

## 7. Music direction
- 84 BPM, darker and more mechanical than V1/V2 — analog sequencer pulse, felt-piano single notes, no drums until 12.6.
- Curve: 0–11.4 pulse only → 12.6 kick enters (OpenIDE decisions) → 23.0 full stop → **23.6 drop** (schematic — biggest moment, add one low string layer) → 31.0 strip back → 33.6 resolve chord, decay.

## 8. Transition notes
- S01→S02: match cut — keycap press impact frame cuts to first Cortex state change.
- S02→S03: glass morph (stream begins). S03→S04→S05: hard cuts on completion/log ticks.
- S05→S06: hard cut to black. S06→S07: type card burns off into diff render.
- S07→S08→S09: hard cuts on Approve/Reject SFX. S09→S10: hard cut to black.
- S10→S11→S12: glass morph chain (drafting texture bridges into OpenForge).
- S12→S13→S14: cut to black, hold, cut in on `SFX_AI_ACTS` — same silence-then-hero pattern as V1/V2.
- S14→S15→S16: hard cuts. S16→S17: glass morph. S17→S18: dip to black, sweep.

## 9. Editor assembly notes
- Audit trail (S05): if log lines append slowly in real capture, stack two takes — do NOT fabricate log content in After Effects; only retime real capture.
- Approve/Reject (S08/S09): frame the button interactions center-safe; punch in 110% on the click frame with a 180ms eased scale for emphasis (once each, no more).
- OpenForge hero (S14): longest hold in the film — resist cutting early; let the schematic complete on screen.
- Prism underlay behind Cortex stream at 15% opacity, screened, desaturated.
- Marketplace "Can't fit" beat matters — it sells honesty. Keep the flat tick; no green.

## 10. Export package checklist
- [ ] `HF_V3_S01_keycap`, `HF_V3_S11_drafting-texture` (+4s extended), reuse `HF_V1_S19_prism`
- [ ] `UI_V3_S02…S16` captures @1440p60: Cortex gears, Deep stream, Vault Summarizer, Audit, OpenIDE Approve + Reject takes, OpenForge full prompt→schematic take (uncut safety), Marketplace Fits + Can't-fit, Hosting
- [ ] `VO_V3_master_48k.wav`, SFX kit (shared) + `SFX_DECLINE.wav`, music stems
- [ ] Master: `AIRGPT_V3_BUILDER_42s_3840x2160_2398_v01.mov` + SRT

---

# VIDEO 4 — SOCIAL CUT PACK (3× vertical 9:16)

Common specs: 1080×1920, deliver 29.97fps (conform 23.976 masters), captions burned in (Plex Mono, bottom-safe), hook text on screen within 0.5s, sound-off legible, loop-friendly end frames. All UI captures re-framed: capture at 1440p and punch into the relevant panel region so UI is legible at phone size — never letterbox 16:9 UI inside 9:16.

---

## CUT A — "Phone → PC in four seconds" (14.0s)

1. **Title/runtime/aspect/use case:** *Phone → PC in 4 Seconds* · 14.0s · 9:16 · LinkedIn/X/Reels top-of-funnel hook; the moat in one breath.
2. **Thesis:** Pure demo speed-run of the Tunnel loop — the viewer sees the whole magic trick before they can scroll.

3+4. **Beats + prompts:**

| TC | Dur | Shot | Source |
|----|-----|------|--------|
| 0.0–1.2 | 1.2 | Hook type on black: `Stop emailing files to yourself.` | Type |
| 1.2–3.2 | 2.0 | **UI:** Tunnel QR (punch-in) → phone scan (phone capture, quick 2-cut) | UI |
| 3.2–4.6 | 1.4 | **UI (phone):** Send to PC tap | UI |
| 4.6–5.0 | 0.4 | Black flash, silence | — |
| 5.0–7.2 | 2.2 | **HERO UI:** photo lands in chat, green tick | UI |
| 7.2–9.2 | 2.0 | **UI:** Copy to Notepad → paste | UI |
| 9.2–10.8 | 1.6 | **UI:** copy back → in chat. Type kicker: `ONE LOOP` | UI |
| 10.8–14.0 | 3.2 | End card: mark + `AirGPT` + `Local-first. No cloud detour.` + CTA | Logo comp |

- **HF prompt (end-card underlay, optional) — `HF_V4A_endcard-glass`:** Subject: vertical 9:16 dark frosted glass surface with one slow white light band drifting upward, pure abstract / Camera: static / Lens: 85mm macro f/4 / Lighting: single white band / Grade: monochrome near-black / Duration: 4s loop / Motion: low.

5. **Text/VO:** No VO (sound-off first). On-screen: hook card, `CONNECTED` micro-kicker at 3.0, `ONE LOOP` at 9.2, end card copy. Captions unnecessary (no speech).
6. **SFX:** 0.0 sub tick under hook · 1.6 QR tick · 2.6 focus click · 3.8 tap · 4.6 silence · 5.0 `SFX_TICK_OK` + bass hit · 7.6/8.6 copy-paste ticks · 9.8 `SFX_TICK_OK` · 10.8 glass sweep.
7. **Music:** 104 BPM dry click groove, starts at 1.2 (hook is silent+tick), full stop 4.6, drop 5.0, out by 12.5 leaving room tone — loop point clean.
8. **Transitions:** all hard cuts; the only black is 4.6–5.0. End card holds static for loop.
9. **Assembly:** punch-ins at 130–160% on QR, chat bubble, clipboard chip; keep each punch static (no drift — too small a canvas). Green tick moment gets a 1-frame 105% pop, eased back over 180ms.
10. **Checklist:** reuse V2 captures + phone records (re-framed) · `HF_V4A_endcard-glass` · master `AIRGPT_V4A_LOOP_14s_1080x1920_2997_v01.mp4` + 3s loop-check QC.

---

## CUT B — "The AI that never leaves your laptop" (13.0s)

1. **Title/runtime/aspect/use case:** *Never Leaves Your Laptop* · 13.0s · 9:16 · LinkedIn security/IT audience; anti-shadow-AI message.
2. **Thesis:** One paste, one analysis, one audit line — then the knife: it never left the machine.

3+4. **Beats + prompts:**

| TC | Dur | Shot | Source |
|----|-----|------|--------|
| 0.0–1.4 | 1.4 | Hook type: `Your team is pasting company data into random AI tabs.` | Type |
| 1.4–3.6 | 2.2 | **UI:** engineering diagram pasted into chat (punch-in) | UI |
| 3.6–6.4 | 2.8 | **UI:** AI analysis streams (`SFX_AI_ACTS`) | UI |
| 6.4–8.0 | 1.6 | **UI:** audit trail line appends (punch-in) · kicker `AUDITED AI PATH` | UI |
| 8.0–9.6 | 1.6 | Type: `It never left your laptop.` | Type |
| 9.6–13.0 | 3.4 | End card: mark + `AirGPT + Netie` + `Company-safe AI` + CTA | Logo comp |

- **HF prompt (hook underlay) — `HF_V4B_tab-glow`:** Subject: vertical macro of a dark laptop screen edge in a black room with faint cold blue glow bleeding off-screen, no readable content / Camera: slow push-in / Lens: 50mm f/2.0 / Lighting: screen glow only / Grade: cold near-black / Duration: 2s / Motion: low. (Runs at 30% under hook text.)

5. **Text/VO:** Optional 1-line VO at 3.6: "Analyzed on your machine — on an audited path." (10 words). Otherwise text-led; burn captions if VO used.
6. **SFX:** 0.0 low tension drone · 1.4 paste tick · 3.6 `SFX_AI_ACTS_v1` · 6.4 metronomic log tick ×2 · 8.0 near-silence + sub hit on type · 9.6 glass sweep.
7. **Music:** 84 BPM sparse pulse (reuse V3 palette), duck at 8.0 so the knife line sits in silence, single resolve chord at 9.6.
8. **Transitions:** hook type defocus-morphs into the paste; hard cuts through analysis/audit; dip to black at 8.0; sweep to end card.
9. **Assembly:** stream shot must show real token streaming from capture — retime to fit 2.8s rather than trimming mid-word bursts oddly; audit punch-in 150%.
10. **Checklist:** reuse V1 S15/S20 captures re-framed · `HF_V4B_tab-glow` · optional `VO_V4B.wav` · master `AIRGPT_V4B_LOCAL_13s_1080x1920_2997_v01.mp4` + SRT if VO.

---

## CUT C — "Chat becomes a schematic" (12.0s)

1. **Title/runtime/aspect/use case:** *Chat → Schematic* · 12.0s · 9:16 · X/Reels engineering audience; OpenForge wow-moment.
2. **Thesis:** The shortest distance between a sentence and a schematic — one prompt, one near-silence, one reveal.

3+4. **Beats + prompts:**

| TC | Dur | Shot | Source |
|----|-----|------|--------|
| 0.0–1.2 | 1.2 | Hook type: `Type it. Get the schematic.` | Type |
| 1.2–3.8 | 2.6 | **UI:** OpenForge — request typed in chat (punch-in on input) | UI |
| 3.8–4.4 | 0.6 | Black, silence | — |
| 4.4–7.6 | 3.2 | **HERO UI:** schematic materializes (longest hold) | UI |
| 7.6–9.0 | 1.4 | **UI:** Marketplace `Fits` result, green | UI |
| 9.0–12.0 | 3.0 | End card: mark + `OpenForge — inside AirGPT` + CTA | Logo comp |

- **HF prompt (end-card underlay) — reuse `HF_V3_S11_drafting-texture`** cropped 9:16 at 20% opacity.

5. **Text/VO:** No VO. Kicker at 4.4 (Plex Mono): `OPENFORGE`. Kicker at 7.6: `FITS ✓` mirrors UI only if the real UI shows it — otherwise plain `FITS`.
6. **SFX:** 0.0 keycap press (V3 opener sound, brand continuity) · 1.2 keystroke foley · 3.8 silence · 4.4 `SFX_AI_ACTS_v1` + swell · 7.6 `SFX_TICK_OK` · 9.0 glass sweep.
7. **Music:** 84 BPM, pulse only until 4.4 drop; single string layer under reveal; out clean by 11.0.
8. **Transitions:** all hard cuts; black beat before reveal is the whole trick; end card static for loop.
9. **Assembly:** the schematic reveal must come from one continuous capture take (`UI_V3_S14` re-framed) — punch to the drawing region, slow 3% drift allowed here only because the hold is long.
10. **Checklist:** reuse V3 S12/S14/S15 captures re-framed · drafting texture 9:16 crop · master `AIRGPT_V4C_FORGE_12s_1080x1920_2997_v01.mp4`.

---

# MASTER HANDOFF SUMMARY (connector quick-sheet)

**Generate in Higgsfield (13 unique plates):**
`HF_V1_S01, S02, S03, S05, S08, S14, S19_prism, S24, S26 · HF_V2_S01, S05, S14 · HF_V3_S01, S11(+ext) · HF_V4A_endcard-glass · HF_V4B_tab-glow` — 24fps, max res, no watermark, neutral grade, one camera move each, reject any output violating §0.4.

**Capture from product (real UI, 1440p60, staged demo content):**
Main chat idle · Connect/Tunnel QR · phone scan + Send to PC (device records) · photo-lands-in-chat · clipboard→Notepad→back loop (plus uncut safety take) · engineering-diagram analysis stream · Memory panel · Projects hub · Cortex Idle/Assist/Deep + Deep stream · Vault Summarizer · Audit trail · OpenIDE Approve + Reject · OpenForge prompt→schematic (uncut) · Marketplace Fits + Can't fit · Hosting · Admin dual-brain Workforce Observatory + Netie.

**Shared audio kit:** `SFX_AI_ACTS_v1.wav`, `SFX_TICK_OK.wav`, `SFX_DECLINE.wav`, tick set, glass-morph set, bass drops; 4 music beds with stems (92/100/84/104 BPM).

**Design kit:** triangle mark SVG, wordmark, DM Sans + IBM Plex Mono, end-card layered files (16:9 + 9:16), `AIRGPT_SHOW_LUT_v1.cube`.

**Masters:** V1 70s + V2 36s + V3 42s @ 3840×2160 23.976 ProRes 422 HQ; V4 A/B/C @ 1080×1920 29.97 H.264 high-bitrate; SRTs for all VO videos; H.264 review proxies for everything.

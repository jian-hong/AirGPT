# AirGPT YC Multiplayer — paste-ready generation prompts

**Film:** 2:35 · RFS *Multiplayer AI*  
**Thesis:** Every other AI tool gives your team a thousand private threads. AirGPT gives you one room — one agent, everyone in it, and a host who controls who touches what.

**Act 4 note:** Cut-all-AI is a **mock visual** for smoother edit pacing. Do not subtitle it as a production kill-switch.

---

## 1. House style (prepend to every plate)

> Cinematic product film, anamorphic 2.39:1 framing inside a 16:9 frame, shallow depth of field, deep matte-black background, cool neutral grade with a single warm practical, subtle film grain, no text artefacts, no watermark, no UI mockups, no faces in focus.

**Negative:**

> `blurry, low resolution, warped text, gibberish letters, extra fingers, distorted hands, watermark, logo artefacts, oversaturated, HDR halo, jitter, morphing geometry, subtitles, captions, purple fog, neural network brain, robot humanoid, airplane, cockpit`

**Style lock (Higgsfield / Premiere):** canvas near-black `#0a0a0a`; white kinetic accent only; green `#3dd68c` only on success; screens in generated plates must be **dark blank** — real UI is composited later.

---

## 2. LTX-2 / Higgsfield plates

### PLATE 01 — QR shuffle · 3s · 24fps

> A rapid shuffle of black-and-white QR codes, each printed on a different real surface — brushed aluminium laptop lid, frosted glass meeting-room wall, an iPad screen, a dry-erase whiteboard, a fabric lanyard badge. The codes cut past camera like a riffled deck of cards, six per second, accelerating. Macro lens, extremely shallow focus, specular highlights raking across each surface as it passes. Deep black void behind. Cool white key light from upper left, single warm amber practical far background. Camera locked, subjects moving. High-contrast monochrome with a faint cyan cast.

**VO / SFX:** *"A QR code is all you need —"* · card-shuffle riffle · low sub-bass swell

### PLATE 02 — QR dissolves to mesh · 2s

> A single QR code holds centre frame, then its black modules detach and drift apart into three dimensions, becoming a constellation of glowing nodes suspended in black. Thin light-filaments draw themselves between the nodes, and pulses of bright data travel along the filaments from node to node. Slow dolly-in, 24mm, gentle parallax. The mesh reads as laptops, a server rack, and a database, abstracted to pure geometry. Cool white and pale cyan emissive light, no ambient fill. Volumetric haze.

**VO:** *"— for your whole team to work with one AI."* · clean chime on final QR

**Type overlay (Premiere, not generated):** TEAM COLLABORATION — letters land one at a time (DM Sans 600).

### PLATE 03 — the reverse riser · 1.5s

> Abstract visual tape-stop: a field of horizontal light-streaks snaps backwards, chromatic aberration splitting into red and cyan fringes at the edges, one frame of scan-line tear, then everything settles instantly to stillness. Pure black background, streaks in cool white. Violent motion resolving to perfect calm.

**SFX:** tape-stop / reversed cymbal · then silence into Act 1 interrupt

### PLATE 04 — lockdown wash · 2s (mock Act 4 B-roll)

> A network of glowing white nodes and connecting filaments, seen from slightly above. In one beat every filament drains from white to deep crimson and the nodes desaturate to cold grey, the light dying outward from centre like a power cut travelling down a grid. Then absolute stillness — no drift, no pulse, no flicker. Deep black background. Ominous, controlled, not chaotic.

**VO (quiet):** *"One host. One button. Everything stops — and nothing is lost."*  
**Score:** near-silence 1.5s — do not score the stillness hold on the REC cut.

### PLATE 05 — cleared · 2s

> The same grey network reilluminating: a single green pulse from the centre node travels outward along every filament, and as it passes, colour and motion return. Warm white light blooming back into cool geometry. Relief, exhale, forward momentum. Slow dolly out.

**SFX:** success tick `SFX_TICK_OK` · music re-enters underneath

### PLATE 06 — compression to a point · 3s

> Two dozen small rounded-rectangle screens, each glowing with abstract interface light, floating in black space. They drift inward and compress toward the centre with accelerating momentum, overlapping and shrinking until they collapse into one intense point of white light, which holds for half a second and then blooms. Motion-blurred trails, anamorphic horizontal flare on the bloom. Camera slowly pushing in throughout.

### PLATE 07 — devices unfold · 3s

> A single point of white light in black space unfolds into three devices arranged side by side — an open laptop, a tablet on a stand, a phone — all screens facing camera, all **dark blank** (no UI). Studio product photography, floating with no visible surface, soft top key and cool rim light. Slow orbit of ten degrees, shallow depth of field with focus resting on the tablet at centre.

**Composite in Premiere:** track in real Act 1 / Hub recordings onto the three screens. End card: **AirGPT** then **by NETIE.AI** with bounce-dot mark.

---

## 3. Timed VO map (2:35)

| Time | VO |
|------|-----|
| 0:00 | A QR code is all you need — |
| 0:03 | — for your whole team to work with one AI. |
| 0:16 | Someone else on your team can just… walk in. |
| 0:28 | Sharing defaults to read-only. You raise it on purpose, never by accident. |
| 1:00 | You can see who's in, what they asked, whose AI they spent, and what it cost. |
| 1:26 | *(near silence)* |
| 1:32 | One host. One button. Everything stops — and nothing is lost. |
| 2:10 | One control, everywhere. That's the whole idea. |
| 2:31 | AirGPT. Multiplayer by default. |

On-screen lower-third at 0:16: `Same session. Same agent. No new thread.`

---

## 4. Screen-record scripts (local Playwright)

Requires demo mock:

```powershell
cd D:\AirGPT
.\start_demo_mock.bat
# confirm:
(Invoke-RestMethod http://127.0.0.1:8765/api/info).demo_mock   # must be True
```

| Act | Command | Output |
|-----|---------|--------|
| Short | `AIRGPT_PW_HEADLESS=1 python video-assets/scripts/record_short_demo.py` | `03-demo-clips/multiplayer/short-demo/` + `07-exports/` (~45s MP4) |
| 1 | `python video-assets/scripts/record_act1_interrupt.py` | `03-demo-clips/multiplayer/act1/` |
| 2 | `python video-assets/scripts/record_act2_share.py` | `…/act2/` |
| 3 | `python video-assets/scripts/record_act3_hub.py` | `…/act3/` |
| 4 | `python video-assets/scripts/record_act4_lockdown_mock.py` | `…/act4/` |
| 6 | `python video-assets/scripts/record_act6_openvault.py` | `…/act6/` |

**Hard rules for REC:** Act 1 must be two real browser contexts — do not composite a fake interrupt. Act 6 must show **Simulated target** under the ship URL if `simulated: true`.

---

## 5. Cursor Cloud agent prompt (after one git remote exists)

Blocked until `git remote -v` shows exactly one remote — see `video-assets/00-handoff/CLOUD_RECORDING.md`.

```
You are recording AirGPT's YC Multiplayer film clips on DEMO MOCK only.

1. cd to the AirGPT repo root.
2. Run start_demo_mock.bat (or seed_demo_mock.py --reset then AIRGPT_DEMO_MOCK=1 python clipdrop.py).
3. Assert GET /api/info.demo_mock === true — refuse otherwise.
4. pip install playwright && playwright install chromium  (if missing).
5. Run in order:
   python video-assets/scripts/record_act1_interrupt.py
   python video-assets/scripts/record_act2_share.py
   python video-assets/scripts/record_act3_hub.py
   python video-assets/scripts/record_act4_lockdown_mock.py
   python video-assets/scripts/record_act6_openvault.py
6. Upload / leave artefacts under video-assets/03-demo-clips/multiplayer/.
7. Do not record against real ./data. Do not invent production domains without Simulated target.
```

**Hybrid path (no cloud):** generate PLATE 01–07 in Higgsfield/LTX-2 → `video-assets/05-higgsfield-plates/` or `08-ltx2-outputs/`; keep UI walks as local Playwright.

---

## 6. Premiere / Motion / Raylight assembly notes

1. Cold open 0:00–0:20 = PLATE 01–03 + Act 1 REC interrupt.
2. Never put model-generated UI on camera.
3. Act 4: cut to REC lockdown wash; hold stillness 4s; optional PLATE 04 underlay at 20% opacity.
4. Act 6: freeze frame on **Simulated target** label — honesty is the product story.
5. End: PLATE 06 → PLATE 07 with tracked REC → logo.
6. Loudness: −16 LUFS hero; true peak −1 dBTP.

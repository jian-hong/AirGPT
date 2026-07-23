# Netie Logo — Pixar Bounce Animation Spec
**Duration:** 4.8s end-sting (or 3.6s short cut)  
**Aspect:** 16:9 master + 1:1 + 9:16 crops  
**Feel:** Apple Liquid Glass + Pixar Luxo hop — cute, precise, premium  
**Assets:** `01-logos/netie/*`

---

## Characters

| Element | Role | Asset |
|---------|------|--------|
| **Square Dot** | The bouncing “Luxo” character | `netie-dot.svg` (white) or `netie-dot-black.svg` on light glass |
| **NETIE** | Full capital wordmark stage | `netie-wordmark.svg` — tracking +12, DM Sans Bold |
| **Final Mark** | Outer frame + inner square | `netie-mark.svg` / `netie-mark-transparent.svg` |
| **Glass plate** | Liquid-glass underlay | Higgsfield or AE frosted glass plane |

**Physics feel:** soft squash & stretch (max 12% squash on land, 8% stretch in air). Spring settle into final nest. No elastic rubber-band overshoot past 1 frame.

---

## Beat sheet (4.8s full)

| # | TC | Dur | Action | Camera / look |
|---|-----|-----|--------|----------------|
| N00 | 0.00–0.40 | 0.40 | Black → frosted liquid-glass plate fades in (subtle refraction) | Static, shallow DOF |
| N01 | 0.40–0.80 | 0.40 | `NETIE` letters fade+rise 8px (180ms stagger L→R, 40ms/letter) | Type on glass |
| N02 | 0.80–1.20 | 0.40 | Square Dot drops from above frame, lands on **N** with squash | Soft impact |
| N03 | 1.20–1.70 | 0.50 | Hop N → **E** (arc, stretch midair, squash land) | Follow slight pan |
| N04 | 1.70–2.20 | 0.50 | Hop E → **T** | — |
| N05 | 2.20–2.70 | 0.50 | Hop T → **I** | — |
| N06 | 2.70–3.20 | 0.50 | Hop I → **E** (last letter) — tiny celebration hop in place (0.2s) | — |
| N07 | 3.20–3.60 | 0.40 | Letters dissolve / glass-morph out (frost blur 10f) | Dot floats center |
| N08 | 3.60–4.10 | 0.50 | Outer square frame scales from 0→100% with glass refraction | Dot waits above nest |
| N09 | 4.10–4.50 | 0.40 | Dot drops into center nest — squash → settle spring | **Hero settle** |
| N10 | 4.50–4.80 | 0.30 | Hold final Netie mark + optional thin white light sweep | Lockup |

### Short cut (3.6s) for social end cards
Skip N05–N06 mid hops: N→T→E only (3 hops), then dissolve → frame → drop. Use when end-card budget is tight.

---

## Liquid Glass treatment

- Outer frame: frosted glass stroke with 1px specular rim, slight inner blur
- Inner square: denser glass / near-solid white with soft edge falloff (not hard vector after 4.10 — micro-blur 0.3px)
- Background: `#0a0a0a` with faint radial frost
- Optional: 2% slow caustic drift under letters during hops (never purple)

---

## SFX map

| TC | SFX |
|----|-----|
| 0.40 | soft glass whoosh (letters in) |
| 0.80 | soft land thud (N) — rubber-glass |
| 1.20 / 1.70 / 2.20 / 2.70 | hop whoosh + land tick (rising pitch +1 semitone each) |
| 3.00 | tiny celebration peep (very soft) |
| 3.20 | glass morph whoosh (letters out) |
| 3.60 | frame appear — crystalline tick |
| 4.10 | **settle thud** + `SFX_TICK_OK`-adjacent soft bloom |
| 4.50 | light sweep whisper |

Music: strip to single pad under end-sting; duck hard under hop ticks so the character reads as sonic brand.

---

## Higgsfield prompts (atmosphere only — animate mark in AE/Remotion/Motion)

**`HF_NETIE_GLASS_PLATE`**
- Subject: square frosted liquid-glass panel floating in pure black void, subtle white rim refraction, Apple-like glass material, no logo, no text
- Camera: slow push-in
- Lens: 85mm, f/2.8
- Lighting: single soft cool key
- Duration: 6s | Motion: low

**`HF_NETIE_LIGHT_SWEEP`**
- Subject: thin white light band sweeping across dark frosted glass surface, abstract, monochrome
- Camera: static
- Duration: 3s | Motion: low

---

## Remotion / AE assembly notes

1. Parent Dot on a motion path over letter baselines (Y = letter top − 8px at rest).
2. On each land frame: scaleY 0.88 / scaleX 1.08 for 2 frames → spring back (180ms).
3. Mid-hop: scaleY 1.08 / scaleX 0.94.
4. Final nest: Dot’s center must match final mark’s inner square exactly (use guide layer from `netie-mark.svg`).
5. Export: `NETIE_BOUNCE_4p8s_2160_2398.mov` ProRes + `NETIE_BOUNCE_3p6s_SHORT` + 9:16 crop.

---

## File naming (drop renders here)

```
02-animations/netie-bounce/
  NETIE_BOUNCE_4p8s_master.mov          ← PLACE RENDER
  NETIE_BOUNCE_3p6s_short.mov           ← PLACE RENDER
  NETIE_BOUNCE_9x16.mov                 ← PLACE RENDER
  storyboard-stills/                    ← optional keyframe PNGs
```

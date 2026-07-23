# CLAUDE + Higgsfield MCP — Handoff Pack
**Drop this entire `video-assets/` folder to Claude.**  
**Also attach:** `docs/VIDEO_PLAN_HIGGSFIELD.md` (full series bible)

---

## Mission
Generate / assemble the **17/7 AirGPT introduction video** (45–55s) and supporting plates using **Higgsfield MCP**, compositing **real UI demo clips** from `03-demo-clips/`, locked logos from `01-logos/`, and the **Netie Pixar bounce** end-sting from `02-animations/netie-bounce/ANIMATION_SPEC.md`.

---

## Hard rules
1. **Never invent AirGPT UI** — screens in HF plates stay dark/bokeh; real captures only.
2. **Never invent features** — only: clipboard loop, Tunnel QR, Send to PC, analysis, Cortex, OpenIDE Approve/Reject, OpenForge, Marketplace Fits/Can't fit, Admin+Netie.
3. **Not aviation** — reject planes/cockpits if model drifts on “Air”.
4. **No purple AI fog**, fake dashboards, glowing brains.
5. **One camera move per Higgsfield clip.**
6. **Green `#3dd68c` only on success.**
7. **Netie logo geometry is locked** — square frame + inner square from `01-logos/netie/`. Bounce the **inner square** on `NETIE` then drop into nest.
8. **AirGPT mark:** use locked choice in `01-logos/airgpt/CHOOSE.md` (user picks A/B/C/D). Until chosen, use `airgpt-mark-current.svg` for UI continuity.
9. Show real UI within first 10 seconds of the intro.
10. Near-silence 0.6s before photo-lands hero.

---

## Folder map
| Path | Contents |
|------|----------|
| `01-logos/` | Netie mark SVGs, AirGPT concepts, Netie Space star |
| `02-animations/netie-bounce/` | Bounce timing + SFX + HF underlay prompts |
| `03-demo-clips/` | Prerecorded UI (fill these before/while generating) |
| `04-intro-17-07/` | Intro spine + VO |
| `05-higgsfield-plates/` | Drop generated plates here with IDs from plan |
| `06-audio/` | VO + SFX kit |
| `07-exports/` | Masters out |

---

## Generate first (Higgsfield plate queue for intro)
1. `HF_V1_S01_glasses-reflection`
2. `HF_V1_S02_desk-overhead`
3. `HF_V1_S05_triangle-sweep` (or AirGPT locked-mark plate)
4. `HF_NETIE_GLASS_PLATE`
5. `HF_NETIE_LIGHT_SWEEP`
6. Optional: `HF_V1_S08_phone-scan` (screens dark — replace in comp)

Full prompt text: copy from `docs/VIDEO_PLAN_HIGGSFIELD.md` § Video 1 + `02-animations/netie-bounce/ANIMATION_SPEC.md`.

---

## Edit order
1. Confirm AirGPT logo choice (A/B/C/D)  
2. Confirm demo clips present (at least FULLLOOP + Tunnel + phone)  
3. Generate HF plates → save to `05-higgsfield-plates/`  
4. Build Netie bounce (AE/Remotion or motion MCP) per ANIMATION_SPEC  
5. Assemble intro timeline (`04-intro-17-07/TIMELINE.md`)  
6. Mix audio (`06-audio/`)  
7. Export to `07-exports/AIRGPT_INTRO_17-07_*.mov`

---

## Delivery naming
```
07-exports/AIRGPT_INTRO_17-07_45-55s_3840x2160_2398_v01.mov
07-exports/AIRGPT_INTRO_17-07_proxy_1080.mp4
07-exports/AIRGPT_INTRO_17-07.srt
```

---

## Style lock (short)
Canvas `#0a0a0a` · DM Sans 600 titles · IBM Plex Mono kickers · 180ms ease · `SFX_AI_ACTS_v1` on analysis · `SFX_TICK_OK` on green · Netie bounce at end.

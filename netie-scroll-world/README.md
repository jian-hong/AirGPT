# netie-scroll-world — AirGPT product page for netie.ai/airgpt

Zero-dep cinematic scroll (`scroll-world.js` + `index.html`).

## Right-side download dock

Configured via `downloadDock` in `index.html`:

- **Download AirGPT** → `https://netie.ai/airgpt/download` (installer includes Netie Space)
- **Netie Space** card below → `https://netie.ai/space/download`

## Local preview

```bat
cd /d d:\AirGPT\netie-scroll-world
python -m http.server 5500
```

Open http://127.0.0.1:5500/

## Mount on netie.ai

Client-mount `mountScrollWorld(el, config)` inside the `/airgpt` route. Do not iframe.
Prefer netie.ai global footer for Privacy/Terms; keep this page's download dock.

## Assets

Populate `assets/vid/*.mp4` from `work/prompts/` before production. Stills fall back to `assets/ph-*.svg`.

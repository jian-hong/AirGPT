# Scroll-world video pipeline

Stills-first is live. Enable MP4 scrubbing only after all 11 clips pass QA.

## 0. Preconditions

- Six approved golds in `work/stills/` (see `asset-manifest.json`)
- Exact prompts in `work/prompts/dive_*.txt` and `conn_*.txt`
- One fixed img2vid provider + model for all 11 clips (log in manifest)

## 1. Generate dives (6)

For each scene in order: desk → bridge → vault → agents → tower → hero

1. Attach gold `still_{scene}.png` as the image condition (never text-only)
2. Paste `dive_{scene}.txt` verbatim
3. Same duration / FPS / motion strength / seed policy for every dive
4. Accept only if geometry, props, characters, lighting match gold within an inch
5. Reject → **delete** the file → regenerate from the same gold + prompt

Output masters outside the web tree, e.g. `work/masters/dive_{scene}.mp4`.

## 2. Generate connectors (5)

For `conn_1` … `conn_5`:

1. Start-reference: last frame of previous dive (or previous gold)
2. End-reference: first frame of next dive (or next gold)
3. Paste `conn_N.txt` verbatim
4. Reject on seam jump, morphing, new props, text, palette drift → delete → redo

## 3. Encode web copies

```bat
ffmpeg -y -i work\masters\dive_desk.mp4 -c:v libx264 -pix_fmt yuv420p -crf 20 -g 8 -keyint_min 8 -sc_threshold 0 -an -movflags +faststart assets\vid\desk.mp4
```

Repeat for `bridge vault agents tower hero` and `conn1`…`conn5`.

Also copy approved encodes into:

```
Landing/netie-agent/public/airgpt/assets/vid/
```

## 4. Enable clips in the homepage

In `netie-agent/components/home/airgpt-scroll-world.tsx`, add per section:

```ts
clip: `/airgpt/assets/vid/${id}.mp4`,
```

and

```ts
connectors: [1,2,3,4,5].map((n) => `/airgpt/assets/vid/conn${n}.mp4`),
```

Update `asset-manifest.json` statuses to `approved` and set `clipsEnabledInHomepage: true`.

## 5. QA checklist

- Scrub all five connector seams at 0.5× and fast scroll
- No identity drift vs golds
- `prefers-reduced-motion` still skips video
- No 404s; revoke blobs on unmount (engine handles this)

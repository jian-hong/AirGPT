# Docs canvas format (Netie space)

How docs appear in AirGPT:

| Action | What you see |
|--------|----------------|
| Open a doc (default) | Rendered markdown on the right — same `renderMd` / `.ai-block` style as chat |
| **Open canvas** | Pretty companion map (Callout / Card / Table / Pill / Stat). **Never** the JSON/TSX source |
| **Source** | Raw markdown again (or the file text) |

## Authoring

1. Write normal markdown under `docs/`.
2. Optionally embed one fenced block:

````markdown
```canvas
{ "title": "…", "pills": [], "stats": [], "callouts": [], "cards": [], "sections": [] }
```
````

3. Open canvas only appears when that fence parses.

Do **not** paste `import { … } from "cursor/canvas"` into Netie docs for end users — that is Cursor IDE companion syntax. Netie renders the same *look* from the JSON fence above. Cursor agents may still write a `.canvas.tsx` beside chat when reviewing; Netie Docs stays markdown + canvas JSON.

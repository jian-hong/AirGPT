# Docs canvas format (Netie space)

How docs appear in AirGPT:

| Action | What you see |
|--------|----------------|
| Open a doc (default) | Rendered markdown on the right — full-width, justified body text |
| **Open canvas** | Pretty companion map (Callout / Card / Table / Pill / Stat). **Never** the JSON/TSX source |
| **Source** | Raw markdown text |
| **Download** | Save the `.md` file locally |

Every file under `docs/` can open canvas. Authored ` ```canvas ` JSON wins when present; otherwise Netie builds a minimal map from headings, intro paragraph, `###` chips, and markdown tables.

## Authoring (optional polish)

1. Write normal markdown under `docs/`.
2. Optionally embed one fenced block for a hand-tuned map:

````markdown
```canvas
{ "title": "…", "pills": [], "stats": [], "callouts": [], "cards": [], "sections": [] }
```
````

3. Prefer plain markdown for day-to-day edits — canvas is a view, not a second document format.

Do **not** paste `import { … } from "cursor/canvas"` into Netie docs for end users — that is Cursor IDE companion syntax. Netie renders the same *look* from the JSON fence above (or the generative fallback). Cursor agents may still write a `.canvas.tsx` beside chat when reviewing; Netie Docs stays markdown + optional canvas JSON.

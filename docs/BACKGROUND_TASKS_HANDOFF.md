# Background tasks — handoff for the remaining polish

Written 2026-07-24 by a co-developing agent. The feature is **built and working**
(`cd D:\Cortex && python -m pytest tests/test_workflow_runner.py` → 10 pass; the
whole workflow stack imports; templates compile; the recognizer routes). This
doc lists only what's left, with exact anchors, so we don't step on each other.

## Do not remove (added this session, additive)
- `D:\AirGPT\index.html` ~line 1930 — `#bgTasksTopBtn` in `.topbar-actions`: the
  persistent top-right entry point (qr-btn) the user asked for. Calls
  `window.bgTasks.open()`.
- `D:\AirGPT\index.html` — a small IIFE just before the `/* Compact chrome */`
  block: guards `window.__bgTasksTopReady`, polls `/api/workflows/tasks`, lights
  a live running-count dot on the button. Depends only on the public
  `window.bgTasks` API + that endpoint.
- `D:\Cortex\CortexOS\execution\workflow_recognizer.py` — no-match branch now
  returns a clamped normalized confidence (was leaking the raw score, e.g. 1.5).

## Remaining task 1 — deeper per-agent audit view
The user wants to click into a finished run and see *what each subagent did*
(its tool calls + a result excerpt), not just token/time totals.

The data already exists in the store but is **dropped by the panel shaper**:
- `workflow_store.get_run(run_id)` returns, per agent: `tool_detail`
  (list of `{tool, ok, ms, summary}`) and `excerpt` (the agent's output text).
- `workflow_runner._panel_task()` (`D:\Cortex\CortexOS\execution\workflow_runner.py`
  ~line 195-267) builds the per-agent dict WITHOUT `tool_detail`/`excerpt`.

Steps:
1. In `_panel_task`, add `"tool_detail": a.get("tool_detail") or []` and
   `"excerpt": (a.get("excerpt") or "")[:600]` to each agent dict.
2. In `index.html`, the panel's `agentRows(ph)` (~line 11171) renders the
   Agent/Tokens/Tools/Time table. Make each agent row expandable to show its
   `tool_detail` (tool name · ms · summary, colored by `ok`) and `excerpt`.
   Keep it collapsed by default; reuse the existing `expanded{}` pattern.

## Remaining task 2 — aesthetic scale to match the reference
The panel CSS (`index.html` ~11059-11113) hardcodes `system-ui` and
`var(--bg,#fff)` style fallbacks. Align it to the app's design tokens so it
matches the rest of the shell in both themes and scales cleanly:
- Font: `var(--sans)`. Colors: `--bg / --surface / --surface2 / --line /
  --text / --muted / --accent`. Motion: `var(--morph)` and the app's
  `cubic-bezier(.22,1,.36,1)` easing.
- Width: currently `min(430px,100vw)`; consider `clamp(340px, 30vw, 460px)` and
  verify the phone-client breakpoint (`.connect-col` mobile rules ~line 190-220
  are the reference for a right drawer that becomes a sheet under 760px).
- Match the screenshot: run title + right-aligned elapsed, "Workflow ·
  <status>", "<n> agents · <tokens>", description, then Phases with dot rows and
  a chevron; expanded phase = the agent grid.

## Remaining task 3 — live stream instead of 2s poll (optional)
Cortex already exposes SSE at `GET /api/workflows/task/{id}/events`
(`CortexOS/api/workflow_routes.py:111`). AirGPT's `clipdrop.py` proxies the JSON
workflow routes but **not** this SSE one — add a proxy using the existing
`_sse_begin` / `_sse_send` / `_sse_end` helpers (~clipdrop.py:1641), streaming
from `cortex_client` → the panel, replacing the `POLL_MS=2000` loop for an open
run. Poll can stay as the fallback for finished/history.

## Contract notes
- Panel ↔ engine contract is stable: `/api/workflows` (catalog),
  `/api/workflows/tasks` (`{running, finished}`), `/api/workflows/task/{id}`,
  `/api/workflows/run`, `/api/workflows/cancel`, `/api/workflows/clear`,
  `/api/workflows/recognize`.
- Chat auto-routing already lives in `send()` (`index.html` ~10443): recognize →
  run → open panel. Non-explicit single-keyword messages intentionally do NOT
  fan out (only explicit "invoke subagent…" phrasings or strong multi-signal
  matches auto-run), to avoid launching expensive workflows on one word.
- OpenIDE is a right-rail inside this same SPA (`openOpenIDERightRail()`), so the
  panel + top-bar entry are already available there — no separate wiring needed.

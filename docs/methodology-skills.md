# Methodology skills (Cortex engine)

Reusable playbooks for how to research, design an agent, build an agent window,
verify without fabrication, and co-edit safely. These are the canonical,
version-controlled copies. The engine loads them as individual packs from
`data/skills/*.md` (runtime, gitignored), so a few-shot prompt plus one of
these can turn into a working agent, page, or routine.

House rules for all packs: no em dash, no emoji, concrete claims, mark
uncertainty. One `#` heading is the pack name; the first line is its description.

Installed packs (also in `data/skills/`):
`build-recon`, `cortex-agent-design`, `agent-window-builder`,
`verify-no-fabrication`, `coop-editing`, `web-research`, `routine-design`.

---

## build-recon

Map before you touch. Understand a code region with search tools before editing a line.

- Before any edit to unfamiliar code, and before every edit in a co-developed tree.
- Locate with Grep or Glob. Never guess a path.
- Read only the region you will change plus its callers and callees.
- Trace the call path end to end: UI handler to backend route to function to storage.
- Confirm the exact current text right before an Edit. Re-read if the file changed on disk.
- Ready to edit when you can name the function, its file and line, its callers, and where its state persists.

## cortex-agent-design

Decide agent vs routine vs plain LLM, then scope tools tightly and write one specific prompt.

- Plain LLM chat: a one-off answer with hands and tools. No dedicated agent.
- Routine: a simple recurring task (daily or weekly ingest, a digest). Add it to the Routines page. Do not build an app.
- Agent: a durable worker with its own tools, memory scope, and surface. Build it when the task recurs with state or needs a dedicated window.
- Name from the job. Scope tools to the minimum. web_search first when facts are needed.
- Write one specific prompt: goal, steps, stop condition, output shape. A vague prompt is the top cause of a wasted run.
- Cap fan-out. One failing sub-agent must not kill the batch.

## agent-window-builder

Build a dedicated page for an agent by following the app page pattern, with honest empty states.

- showXxxPage sets sideView, calls updateSideNav and closeSide, hides the right panel, sets chat.innerHTML.
- Register the surface in updateSideNav so the composer hides on a dashboard view.
- Route it: agentSurface returns the surface; openPinnedAgent and runCortexAgent send it to the page; the nav rail gets an icon and label.
- Wire panes to real endpoints. Show a clear connect or empty state when nothing is connected. Never fabricate live data.
- Clean up timers: a poll loop self-terminates on navigate-away and never arms without a source.

## verify-no-fabrication

Prove a change works with real assertions. Never report success you did not observe.

- Front-end served on reload: navigate the browser, read console errors, assert behavior via DOM, clean up test state.
- Test the property that matters at runtime, not a proxy. For cross-process determinism, run in fresh processes with different seeds and compare.
- A regression test must fail on the old code. Prove it bites.
- Measure accuracy on realistic inputs: false positives on unrelated pairs, recall on paraphrases.
- Report what you ran and what you saw. If a step was skipped or failed, say so.

## coop-editing

Work safely in a tree that a parallel worker edits at the same time.

Tools: `git_status`, `git_diff`, `fs_glob`, `fs_search`, `fs_read`, `fs_patch`, `fs_write`, `run_command`.

- Stage file by file. Never git add all. Verify the staged list before committing.
- Re-verify a failing test before diagnosing it. It may already be fixed, or be a transient mid-edit state.
- Check file stability (mtime over a few seconds) before a burst of edits.
- Confirm exact current text right before each Edit.
- For a hot shared file, inject self-contained blocks with one anchor and their own scope.
- If a small complementary change from the other track is tangled in your file, commit it with a note rather than corrupting the file.

## web-research

Fan out across angles, verify claims, cite sources, and separate verified fact from inference.

- Split into landscape, technical depth, counter-evidence. One searcher per angle.
- Primary sources, not summaries of summaries. Capture the source URL with every claim.
- Try to refute strong claims. Default to uncertain when there is no source.
- Report accessibility honestly. If a source is private or 404, say so.
- Local and open-source tools: Playwright for a real browser; an HTML search endpoint over POST needs no key.

## routine-design

Turn a simple recurring task into a routine card, not an app.

- A routine is a named, scheduled, low-ceremony task (daily or weekly ingest, a brief, a digest).
- Fields: title, purpose, cadence (daily, weekly, or a time), content type (text, image, video, music), source, and an output card.
- Cards are scalable: text stays compact; media routines can play video or an image with words and music.
- Everything is editable in place. Duplicate a card and change the source to replicate a routine.

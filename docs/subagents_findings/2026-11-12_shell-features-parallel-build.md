keywords: [workflow, parallel, worktree, AirUI, ext.js, fork, export, chat instructions, snippets, palette, phone, seam, verifier]
main_idea: Five features built in parallel worktrees each passed their own verifier and still broke where they met. Per-lane verification does not cover the seams; a combined run does.

# Five parallel lanes: what the verifiers caught and what only the merge showed

## Workflow shape used (and why)

- 10 agents, Sonnet (repo pin for fan-out), each in its own git worktree, own
  port, own data dir. Pipeline, no barrier: 5 builders, each followed at once by
  a different agent told to assume the build was broken, reproduce on a live
  stack, attack a lane-specific list, and fix at the root on a `-fix` branch.
- Isolated context per agent. Shared facts went in one common brief; nothing
  was passed between lanes.
- Before fan-out, one small foundation commit: `ui/ext.js` (one hook for
  message buttons) and placeholder module files already loaded by the page.
  Result: 4 of 5 lanes made no edit to `index.html`, the fifth added one line,
  and the only merge conflict was two routes inserted at the same spot.
- Main session did the scoping, the foundation, the merge, the seam fixes and
  the combined verification. Preflight on this index: PARTIAL (the prompt-lens
  finding covered artifact checks, nothing covered parallel build).

## Finding 1 - a command that could never work, two that never appeared

- **Expected:** the command box offers Fork and Export and they work.
- **Actual:** it looked for `ChatTools.forkLatest`, `exportMarkdown`,
  `exportJSON`. The chat tools exposed `fork(messageId)` and
  `exportChat(format)`. The fallback matched `fork` and called it with no
  message id ("Could not fork: no chat is open"); the export commands were
  feature-detected away and silently absent.
- **Repro:** merge both lanes, press Ctrl+K, type "fork", Enter.
- **Root-cause class:** two parties agreeing on an interface by guessing. Each
  lane's verifier tested against a stub of the other, so both passed.
- **Fix:** the tools now expose the three names; the box asks for exactly
  those, no guess lists.
- **Invariant:** adversary is not verifier, and a verifier that stubs the
  neighbour has verified the stub.

## Finding 2 - a control hidden behind another control, by enumeration

- **Expected:** on a phone, the report button never covers a control.
- **Actual:** it covered Edit in the saved-prompts sheet. The phone lane hid it
  behind "the drawer, a modal, the prompt panel, the + menu", the sheets that
  existed when it was written.
- **Root-cause class:** a rule written as a list of today's cases. Fixed by
  matching any open `aria-modal` sheet.
- **Invariant:** fix the root-cause class, not the symptom.

## Finding 3 - defects the per-lane verifiers did catch

Export crashed on non-Latin titles (non-ASCII file name in an HTTP header).
Deleting a chat left its instructions in the side table. Blanks named
`__proto__` were skipped (plain object as a set). Four phone tap areas missed
by the builder's own audit. Each has a test or a re-measurement on the branch.

## Not verified

Real provider, live Cortex route, a real phone and on-screen keyboard, a real
share-guest token (guest rules are tested at the handler with the checks
patched), Cmd+K on a Mac, most Settings panels at phone widths.

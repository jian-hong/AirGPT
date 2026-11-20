keywords: [round 2, RAG, sheet SQL, negation, follow-up, provenance, export, import, untrusted, binary sniff, encoding, chat seams, edit, regenerate, queue, attachments, busy chat, 409, race, agents, tools, Cortex, failed run, Background tasks, sanitizer, style, url(), id clobbering, KaTeX maxSize, restore, allow-list, Windows paths, case-insensitive, touch targets, light theme, title bar, cloud sessions, workflow, verifier]
main_idea: Lanes that each passed their own verifier broke where they met, and fixes kept breaking at the next seam: a queue fix and an edit fix combined into a path that deleted an answered turn. Only reviewers who drove the real page, read the database rows and the model's request log found it. Two leak and restore tests could not fail on Windows, the platform the product ships on.

# Round 2: RAG, chat, agents, security and screens, built in parallel

## Workflow shape used (and why)

- PREFLIGHT: PARTIAL. 2026-11-12_shell-features-parallel-build.md covered the
  seam lesson (lanes pass alone, break together); nothing covered numeric trust
  in RAG answers or Windows-only test behaviour.
- Audit: 9 read-only Sonnet lenses at 9287bd2, each finding re-run by a second
  agent told to default to "not real".
- Build: 7 lanes. 5 in local workflows (builder, then an independent verifier
  in its own worktree that re-ran every repro, attacked, and repaired at the
  root), 2 in separate cloud sessions that ran their own verifier subagent.
- Review of the merged tree: 5 area reviewers plus a verifier per serious
  finding: 35 defects. Fix: 4 lanes (2 local, 2 cloud) plus a gap round (2
  lanes) for what lane reports and the merge turned up.
- Adversarial check of that result: 5 reviewers who drove Chromium, plus 2
  read-only cloud reviews (security, screens) as independent second passes:
  40 findings, 1 critical. Then 6 last lanes (2 local, 4 cloud) and 2 small
  follow-up lanes.
- Main session (Opus): triage, lane briefs, merges, two Windows CI fixes,
  docs. Every fan-out agent was Sonnet. Local concurrency was 2 agents per
  workflow on 4 CPUs; cloud sessions added parallel lanes without local load.

## Finding 1 - a queued line deleted an answered turn

- **Expected:** a line typed while a reply is running goes out later as a new
  question.
- **Actual:** after an Edit stopped before any text, the edit state was put
  back, then the queue drain sent the waiting line through the same send path,
  which read the edit state and sent it as a replacement. The server deleted
  the original question and its answer.
- **Repro:** answered question; Edit; type a second line (queued); Stop before
  the first token; wait; reload. Only the queued line remains.
- **Root-cause class:** shared mutable UI state (the edit target) read by every
  caller of one send function; the queue lane and the edit lane each tested
  their own path.
- **Invariant:** adversary is not the verifier; assert the artifact the user
  receives (the database rows after reload, not the toast).

## Finding 2 - negated filters ran as positive filters

- **Expected:** "total salary excl. HR" is the total without HR.
- **Actual:** the HR total, stated confidently with provenance.
- **Repro:** staff CSV; ask with "excl.", "not in", "other than".
- **Root-cause class:** a parser that drops words it does not recognise and
  still answers.
- **Invariant:** numbers shown to a user must be right; silent fallback is a
  lie. Every total was then checked against pandas.

## Finding 3 - a turn's files were inferred, not stored

- **Expected:** Regenerate and Edit send the files the question had.
- **Actual:** first they sent none (two lanes, neither knew the other); then
  they sent every file row that happened to sit before the question.
- **Root-cause class:** identity reconstructed by position instead of recorded
  at write time. Fix: store the attachment ids with the question.
- **Invariant:** fix the root-cause class, not the symptom.

## Finding 4 - check-then-act across a lock

- **Expected:** one reply per regenerate.
- **Actual:** two regenerates at the same instant both passed the busy check
  and the chat got two replies; the builder's tests passed, the verifier's
  concurrency test failed.
- **Root-cause class:** the check and the claim were two steps.

## Finding 5 - gates that could not fail on Windows

- **Expected:** the export leak test fails if a host path is in the pack.
- **Actual:** on Windows the raw path is never found in JSON text (backslashes
  are doubled), so the check could not fail; a second test asserted a
  case-variant file did not exist on a case-insensitive disk and failed
  although nothing was written.
- **Root-cause class:** tests written on Linux that assume POSIX filesystem
  rules.
- **Invariant:** prove a gate can fail. Both fixes were proven red with the
  protection switched off.

## Finding 6 - name-based deny lists for restore

- **Expected:** a restore never changes the passcode or login files.
- **Actual:** data/./workspace.json, mixed case, trailing dots and spaces, 8.3
  short names and device names reached them or (on Windows) could; files
  outside the list (the OpenVault gate URL, the access policy) were never
  protected; a failure half-applied.
- **Root-cause class:** deny-list by exact name instead of an allow-list of
  what the app's own backups contain.

## Finding 7 - demo shortcuts in the product path

- **Expected:** a web search uses the user's words.
- **Actual:** "how cognition works in dogs" searched "what is cognition
  psychology OpenStax"; any JEPA question searched a fixed LeCun query; the
  founder's name was wired in the same way.
- **Root-cause class:** hard-coded demo topics left where real queries run.

## Not verified

Real tunnel, real phone and keyboard, real cloud provider, live Cortex, the
Windows filesystem behaviour of restore names (8.3, device names), Safari and
Firefox, the n=320 RAG score on the new chunker (bench not in this clone).

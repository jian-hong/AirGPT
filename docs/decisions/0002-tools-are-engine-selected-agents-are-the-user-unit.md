---
status: accepted
date: 2026-08-06
decision-makers: founder
supersedes: none
relates-to: PRD-001 ledger rows F17-F20
---

# DR-0002 - Tools are engine-selected, agents are the user-facing unit, and the app is the deliverable

## Context and Problem Statement

Four pieces of feedback (PRD-001 ledger **F17-F20**, 2026-08-06) all turned out to rest
on one unstated boundary. Until it is written down, every session re-derives it and the
UI keeps conflating three different things: a **tool** (a capability the engine calls), a
**skill** (a named bundle of tools plus instructions), and an **agent** (a reusable thing
a person owns, names, and schedules).

The founder's framing, verbatim across two messages: *"i dont want skills to exist,
skills are tools that can be used by our normal llm engine Cortex"*, then later *"Tools
user can explicitly select but maybe not there it is just too much thing, we matched cool
thing that should and would become their needs based on their prompts, called by Cortex,
they can explicitly choose via / command"*.

A separate and larger correction landed in the same conversation. A pomodoro timer was
**hand-written by the assistant** and shipped as `pomodoro.html`. The founder's response:
*"the pomodoro is not an app u do for me it should be generate by the agent, the agent
need to be very useful and can do anything not u create and run."* That reframes the
whole programme and is recorded here as decision 5.

## Decision Outcome

### 1. Tools are engine-internal. Cortex selects them. (F17 - accepted)

The user does not browse a gallery of tools and press Use. Cortex matches capability to
the prompt. The gallery is removed as the primary path because, in the founder's words,
*"it use up too many space"* and should *"become like something auto wire for user instead
of let them press"*.

**The escape hatch stays explicit:** a user can force a specific skill with a slash
command, e.g. `/anthropic-skills:lazy-senior-dev`. Auto-selection is the default; explicit
selection is always available and always wins.

**Wire-field consequence.** `skill` / `skill_pack` on `/api/agents/<id>/run` is **not
deleted**. It becomes engine-populated instead of client-populated, which is additive and
therefore not a breaking change. Deleting the field would have been breaking; keeping it
and changing who fills it is not. This is the cheaper half of what F17 flagged.

### 2. Agents are the user-facing reusable unit (F17/F19 boundary)

An agent is what a person names, pins, schedules and re-runs. Tools and skills are
implementation detail underneath it. This is the sentence that dissolves the apparent
contradiction between "skills should not exist" and "Cortex should create reusable
agents" - they are statements about two different layers.

### 3. There is exactly one orchestrator, and it is Cortex (F19 - orchestrator declined)

Founder: *"no need the orchestrator, the orchestrate still depends on the central
orchestrator."* This confirms NETIE.md section 6. AirGPT does not decompose or delegate.
`subagent_dispatch` in `agent_tools.py` is a thin local version pointing the wrong way and
must not be grown.

The rest of F19 - connectors, downloadable local artifact, online backend - is **not
decided here**. It needs its own PRD (recommended PRD-002) because it does not serve
PRD-001's vault-first success assertion.

### 4. A scheduled agent must actually schedule (F18 - accepted, already shipped)

`config.schedule_hint` was written on every scheduled agent and read by nothing in the
estate. Clicking "Morning news brief, daily" created a pinned agent that never ran, while
a complete Cortex routines scheduler sat wired and uncalled. Fixed in commit `7b794f67`:
the schedule intent now calls `/api/cortex/routines`, stores the returned `routine_id`, and
says *"Agent saved, but NOT scheduled"* with a reason when Cortex is unreachable.

Verified live: routine `rt-dd286103` created, `interval_seconds: 300`, forced run returned
`status: completed`, `next_run_at` advanced.

Two paths for one intent, one real and one dead, is NETIE.md rule 4. There is now one.

### 5. The agent generates the app. The assistant does not. (new - supersedes how `pomodoro.html` was built)

The deliverable is **the capability to generate**, never the generated artifact. A
hand-written app demonstrates nothing about the product and is actively misleading,
because it looks like progress on a capability that was never exercised.

`pomodoro.html` (commit `52e91a68`) is therefore **a fixture, not a feature**. It stands as
the acceptance target: the same artifact must be producible by `app_scaffold` from a
one-line ask, at which point the hand-written file is deleted.

The machinery already exists and has been exercised - `apps/` currently holds five
agent-scaffolded apps (`counter-smoke`, `hello-ship-demo`, `todo-demo`, `vdml-sheet-demo`,
`pw-smoke-app`), and `app_scaffold` writes files, allocates a port, and registers a Live
App Card.

### 6. The agent loop terminates on quality, not on step count (F20 - decided, expanded)

F20 was routed as "surface only: group the tool-call rows like Claude Code". The founder
pushed back: *"i think it is apparently in llm generation need loop tool calling and
measure if quality of output is perfect and loop until enough connectors enough tools and
good answer"*, and delegated the judgement: *"you analyse if the contract makes sense...
choose the best in terms of the accuracy and best thing of the delivered."*

**Analysis.** The contract as routed does not make sense on its own. `agent_runtime.py:542`
loops `while step < max_steps and tokens_used < token_budget` - it stops when it runs out
of budget, never because the answer got good. A grouped tool-call row is a *readout* of
that loop; making the readout prettier while the loop cannot tell a good answer from an
exhausted one is polishing the gauge instead of the engine.

**Decision: F20 splits in two, and the loop half is the real work.**

- **F20a (surface, cheap, no contract change):** group tool events into collapsed rows with
  kinds, counts and `+N -M`. Blocked on `fs_write`/`fs_patch` returning line deltas, which
  they do not today.
- **F20b (engine, the actual ask):** the loop gains a stopping condition based on measured
  output quality, and continues - acquiring more tools or trying another approach - until
  it passes or a hard ceiling trips. **This is Cortex's, not AirGPT's**, per decision 3.

Grading a run must reuse the honest-verification discipline already proven in this repo:
an independent check that shares no code with the thing it grades (see
`tests/RAG/oracle_bench.py`, which scores value accuracy and schema-link recall separately
and flags a right answer reached by a wrong binding as coincidence rather than a pass).

## Consequences

**Positive.** The tools/skills/agents confusion has one written answer. `skill_pack` stays,
so nothing breaks. The scheduler stops lying. The success criterion for app generation is
an artifact that already exists, so it is unambiguous.

**Negative / accepted.** Auto-selection can pick wrong; the slash command is the mitigation
and must stay discoverable. Deleting the gallery removes a surface some users may have
learned. F20b is genuinely hard and lands in Cortex, which means a cross-repo dependency.

**Known gaps this decision does not close.** There is no image or pixel generation anywhere
in the estate (the founder's "describe the clock shape, become pixels" idea has no
implementation behind it). Gemini is wired for **text only** (`gemini-2.0-flash`,
`gemini-2.5-flash`). `app_scaffold` has no download/export path - apps run inside AirGPT's
own hub on an allocated port, so "a small downloadable python function" does not exist yet
and is a code-signing decision before it is a feature.

## Confirmation

- F17: `skill`/`skill_pack` still present on the wire and engine-populated; gallery no
  longer the primary path; `/anthropic-skills:lazy-senior-dev` style invocation works.
- F18: creating a "daily" agent produces a routine with a real `next_run_at`; Cortex down
  produces a visible refusal, never a silent no-op. **Met** as of `7b794f67`.
- F19: no decomposition or delegation code lands in AirGPT.
- F20b: a run that would previously have stopped at `max_steps` with a poor answer instead
  continues and improves it, measured by a grader that shares no code with the generator.
- Decision 5: `app_scaffold` produces the pomodoro from a one-line ask, and
  `pomodoro.html` is deleted.

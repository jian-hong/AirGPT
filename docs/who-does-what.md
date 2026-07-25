# Division of labour: Cursor vs Claude

You asked what to hand Cursor and what to keep with me. The split is not by size,
it is by **what happens when the work is wrong**.

## The rule

**Cursor takes work where the target is known and a mistake is visible.**
UI layout, animation, copy changes, moving a control, wiring a button to an
existing endpoint, repetitive edits across many files. If it renders wrong you
see it immediately.

**I take work where the target is unknown or a mistake is silent.**
Diagnosis (why is this duplicating), correctness (does rebuild lose data),
architecture (which plane owns this), safety and privacy (what do we install,
what do we claim about a real person), and research that has to be verified
before it is trusted. These fail *quietly* and cost days later.

A useful test: if the task starts with "why", it is mine. If it starts with
"make it look/move/read like X", it is Cursor's.

## Hand to Cursor

- **Animation and motion.** Fade in, morph, interactive bounce, panel open/close
  easing. Match Cursor's and Claude Code's feel. Purely visual, instantly checkable.
- **Project menu polish.** Spacing corruption, whiter menu background, light-mode
  pass, "Add project" entry, recent-chat opacity (currently unreadably faint).
- **Composer "+" menu.** A single menu with: enable web search, connect/upload
  file, query with file or photos. Wiring to endpoints that already exist.
- **Project page layout.** Remove the recommendations block from the individual
  project page and put the chat bar there (it is missing today).
- **Navigation rules.** Once the project is switched from the chats page, stay in
  chats; do not bounce to the individual project page.
- **Generation affordance.** Icons and effects while an answer streams.
- **Removing dead controls** once I have named them.

Give Cursor the file and function name plus the desired end state. It is fast and
accurate when the destination is specified, and it edits `index.html` in bursts,
so it should own that file while it is working.

## Keep with me

- **Silent-correctness bugs.** The rebuild duplication (7 files became 14 rows)
  and the docx never appearing in samples were both invisible until you looked at
  the data. Neither would have been caught by looking at the screen.
- **Duplication mysteries.** The clipboard doubling: the database is clean, so
  the fault is not where it looks. That needs evidence, not an edit.
- **Answer quality and truthfulness.** The assistant invented a person's degree
  and employer, and gave two contradictory versions in a row. That is a sampling
  and grounding problem, and it can defame a real person. This is not a UI task.
- **Retrieval behaviour.** File-scoped questions ("what did the docx say"),
  auto-detected search, per-space web-search gating.
- **Media ingestion architecture.** Video URLs, OCR, subtitles, transcript-guided
  keyframes. Needs staged design and honest gating, not a quick patch.
- **What we install on people's machines** (`docs/what-we-install.md`).
- **Anything touching memory, governance, or the three planes.**

## What you can farm out to Cursor *for* me

Cursor is good at fetching context I would otherwise spend turns collecting:

- "Inventory every call site of X and paste the surrounding 20 lines."
- "List every place we write to the clipboard or the messages table."
- "Collect the current CSS for these five components into one file."
- "Run the suite and paste the failures."

Then hand me the collected material and the question. That uses Cursor as the
retrieval layer and me as the judgement layer, which is the cheapest split.

## Anti-patterns

- Do not let two agents edit `index.html` at once. It corrupts (already happened).
  One owner per file per session.
- Do not hand Cursor "make the answers better". That is not specifiable.
- Do not hand me "make the button 4px smaller". That is a waste of a diagnosis.

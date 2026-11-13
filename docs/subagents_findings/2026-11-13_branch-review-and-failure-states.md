keywords: [review, verifier, failure state, error, toast, BYOK, no API key, dual-brain, verify call, prompt record, throttle, X-Forwarded-For, IPv6, share guest, code copy, pre-wrap, sticky]
main_idea: A first-time user with no API key saw nothing after sending a message, because the only error channel was a 2.4 s toast that then hung clipped off screen. Every suite was green the whole time; only looking at the screen as that user found it. Two rounds of independent agents then found 18 defects in work that had passed its own tests.

# Branch review and failure states

## Workflow shape used (and why)

- Review: 4 Sonnet reviewers by area (gates, server features, page, other
  pages), each in its own worktree at the pushed head, read-only; each finding
  re-tested by a separate Sonnet agent told to default to "not real". 21 agents,
  about 13 minutes. Cap of 2 concurrent agents on this 4-CPU machine.
- Main session: UI tour by screenshot (phone, tablet, laptop, both themes),
  fixes, tests seen red then green, combined suites.
- Then one more Sonnet agent, fresh worktree, attacked the two new commits on a
  live app. Preflight on this index: PARTIAL (audit and parallel-build files
  covered the method, nothing covered failure states).

## Finding 1 - the first-run error was invisible

- **Expected:** with no model reachable, sending a message says why and what to do.
- **Actual:** the stream's error became a 2.4 s toast in small mono text; the toast
  then slid up by a fixed 80px, so a two-line message stayed as a clipped strip
  at the top edge. The chat showed the question and nothing under it.
- **Repro:** fresh data folder, no keys, local model down, send "hello".
- **Root-cause class:** errors routed only to a transient channel; the place the
  user is looking (under their question) got nothing.
- **Fix:** a card in the chat that survives redraws, with the next step.
- **Invariant:** silent fallback is a lie; assert the artifact the user receives.
  855 tests and a 27-check browser run were green throughout.

## Finding 2 - a second model call rebuilt its prompt from a subset

- **Expected:** a chat's own instructions shape the answer the user reads.
- **Actual:** on Max tier the draft call had them; the verify call that writes
  the final answer got only the question and the draft. The prompt lens
  described the first call, so it looked correct.
- **Root-cause class:** a derived request assembled separately from the main one.
- **Invariant:** assert the artifact the user receives (the final reply), not the
  first request.

## Finding 3 - a documented fix applied to one path only

- **Expected:** no blank line under a user message.
- **Actual:** `.ai-block` carried a comment explaining why Markdown inside the
  pre-wrap `.body` needs `white-space:normal`; the user-message path never got
  it. It surfaced only once marked.js started loading (an earlier lane fixed the
  loader).
- **Root-cause class:** fixing the symptom where it was seen, not the class.
- **Invariant:** fix the root-cause class; grep for siblings of a fix.

## Finding 4 - verifiers are wrong too, in both directions

- A refuter marked "guest can read a fork" real; the handler forces the guest's
  own chat, and the fork holds identical copies, so the data matched by
  construction. Separate verified fact from assumption: identical output does not
  prove which row produced it.
- My own new test passed on the old page because a shared helper stopped at a
  `{}` default argument and checked an empty function. Prove a gate can fail: it
  was caught only by running it against the previous file.
- I wrote the failure card's markup and never its CSS; only the second verifier
  looked at a screenshot of it.

## Not verified

Real tunnel, real phone, real provider, live Cortex, Safari and Firefox, the p2p
messages over a real PeerJS link.

keywords: [prompt lens, prompt_trace, tools, artifact check, security block, SHELL-04, phone, UI research, subagent]
main_idea: A prompt viewer is only true if it is checked against the request the provider received. That check found 1,363 phantom tokens.

# Prompt lens: the viewer overcounted until it was checked against the provider

## Finding 1 - tool definitions counted on a turn that sent none

- **Expected:** the panel total equals what the model was sent.
- **Actual:** first version listed "Tool definitions (5,451 chars, ~1,363 tokens)"
  on a turn where the provider request had no `tools` field. Tools were the
  largest block shown and none of it went out.
- **Repro:** point `OLLAMA_BASE_URL` at a stub that records request bodies, send
  one chat turn, compare `GET /api/chat/prompt-trace` with the recorded body.
  System text and user text matched byte for byte; `tools` did not.
- **Root-cause class:** describing a pipeline from its code path instead of
  observing the call. `_standard_llm` attaches tools; the local streaming branch
  of `_standard_llm_stream` does not. The trace was built before the call, when
  the branch was not yet known.
- **Fix:** `ai_engine._turn.tools_sent` is set at the one line that attaches
  tools; the trace is finished after the call and lists tools only when set.
- **Invariant:** assert the artifact the user receives, not internals. Silent
  fallback is a lie.

## Finding 2 - security block sent twice on the fallback path

- **Expected:** `SECURITY_SYSTEM` appended to the system prompt once.
- **Actual:** `_standard_llm_stream` appended it, then handed that string to
  `_standard_llm`, which appended it again.
- **Repro:** read `ai_engine.py` at the three `SECURITY_SYSTEM` sites before
  this change; any turn with no local streaming engine took the double path.
- **Root-cause class:** the same transformation applied at two layers with no
  owner. Fixed by `_effective_system`, idempotent, used at all three sites.
- **Invariant:** fix the root-cause class, not the symptom.

## Gate that can fail

`tests/test_prompt_trace.py` asserts the recorded sections add up to the exact
prompt string. Appending an untraced block to the prompt turned 3 tests red
before it was reverted.

## Subagent shape used

One agent, Sonnet (repo pin), isolated context, web only, lens: feature
inventory of chat web UIs (prompt visibility, BYOK features, phone UX), each
claim marked verified or recalled. Main session did code reading, build and
verification. Preflight on this index was a MISS for UI and prompt inspection.

## Not verified

Real cloud provider, live Cortex route, a real phone over LAN or tunnel.

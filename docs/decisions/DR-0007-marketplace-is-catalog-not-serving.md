---
status: accepted
date: 2026-09-06
accepted: 2026-09-07
decision-makers: founder
---

# DR-0007 - AirGPT marketplace is a catalog, not a serving plane

## Context and Problem Statement

`marketplace.py` is a curated Hugging Face catalog with hardware-fit gates. It also
downloads weights, writes `env.local`, and returns copy-paste commands to start
vLLM / llama.cpp / Colibri. PRODUCT_ROLES says OpenVault owns "local ground models".
PRD-001 out of scope names inference serving (plane 1). Agents keep treating the
Marketplace tab as the place to stand up a model server, and the Constructor card
claims it is "hosted inside Cortex at /cortex/constructor/" (F50, parked).

This record needs a home in **this repo** because that is where the catalog code
lives and where the next agent will re-litigate it. OpenVault already owns the
serving lock; this file stops AirGPT from growing a second one.

## Considered Options

- **A. AirGPT owns local serving.** Rejected. Plane 1 is out of scope. A second
  model process beside OpenVault FreeRoute is a second vault-adjacent runtime.
- **B. Delete marketplace.** Rejected. The catalog + fit filter is the host-shell
  job (what can this laptop run). That is AirGPT.
- **C. Catalog + recipe here; serving and keys in OpenVault.** Chosen.

## Decision Outcome

1. AirGPT marketplace **lists** curated items and says whether they fit this machine.
2. `bind_serve` may return a command and a URL. It must not spawn a server, hold a
   pid, or become the SoT for keys. `env.local` stays an offline cache (lock 1).
3. Download-into-`data/models` is a host-shell convenience, not a serving plane.
   A live OpenAI-compatible listener is OpenVault (or a process the user starts
   from the recipe). AirGPT soft-fails to BYOK until that listener exists.
4. Constructor is a hub card (`serving=module`), not a Cortex-hosted product.
   The `/cortex/constructor/` blurb is a F50 leftover; do not merge the parked
   sidecar branch on the back of this record.

## Consequences

- Positive: the Marketplace tab stops implying that setting a passcode, or
  clicking Install, grants inference. OpenVault stays the ground-model owner.
- Negative: Colibri / vLLM "one click serve" stays a recipe, not an app-store
  launch. Anyone wanting a managed local server files that against OpenVault.
- Cross-repo: PRODUCT_ROLES lock 1 (no second vault) and PRD-001 plane-1 OOS
  are untouched. This is the AirGPT half of the same lock.

## Confirmation

- `tests/test_marketplace_roles.py` - `bind_serve` source has no subprocess /
  pid; the GGUF recipe returns a command; Constructor is `serving=module` and
  does not claim to be hosted inside Cortex.
- Re-run: `python -m pytest tests/test_marketplace_roles.py tests/test_constructor_airgpt_tools.py -q`

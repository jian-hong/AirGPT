# OpenFree — bundled free-tier gateway (AirGPT)

**OpenFree** is AirGPT's first-party name for the [OmniRoute](https://github.com/diegosouzapw/OmniRoute)
OpenAI-compatible gateway (MIT, © 2026 diegosouzapw). One tap installs and runs it locally
as a fallback path — **no user clone, no pasted key**.

## What it is

An OpenAI-compatible gateway on `http://127.0.0.1:20128/v1` that cascades across provider
tiers — subscription → BYO key → cheap → **always-on free** (Kiro/Qoder/Pollinations-class).
AirGPT runs it as an optional local sidecar and calls it before the paid cloud cascade.

## Enable (one tap)

Key Vault → **OpenFree** card → **Enable OpenFree · auto fallback**. That:

1. Sets `OMNIROUTE_ENABLED=1` and `OMNIROUTE_BASE_URL=http://127.0.0.1:20128/v1` in `env.local`.
2. Runs `scripts/start_openfree.ps1`, which installs the prebuilt package into
   `vendor/openfree/` (first run ~739 MB, one-time) and serves the gateway on loopback `:20128`.
3. The UI polls `/api/openfree/status` and reports `installing → starting → up`.

`ai_engine` then tries OpenFree before Groq/OpenRouter/Gemini. If the sidecar is down it
soft-fails to the cloud cascade — nothing breaks.

Fallback order: `openfree → groq → openrouter → gemini`.

## Boundary (owner decision)

OpenFree runs on the user's own machine and uses only providers' **keyless free tiers** or
keys the user legitimately holds. It does **not** auto-create accounts or evade any provider's
terms — that stays a human step. Netie's own paid Engine keys (Netie Official card) remain the
premium path.

## Attribution / license

OmniRoute is MIT-licensed by diegosouzapw. AirGPT re-labels it "OpenFree" in the UI only and
preserves upstream code, license, and attribution under `vendor/openfree/`. Do not remove the
upstream `LICENSE` from the installed tree.

## Diagnose

```powershell
node vendor/openfree/node_modules/omniroute/bin/omniroute.mjs doctor
# logs: data/openfree/openfree.log · state: data/openfree/state.json
```

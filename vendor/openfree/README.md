# vendor/openfree

**OpenFree** is AirGPT's bundled name for the [OmniRoute](https://github.com/diegosouzapw/OmniRoute)
OpenAI-compatible free-tier gateway by diegosouzapw, used under the **MIT License**
(© 2026 diegosouzapw). AirGPT re-labels it "OpenFree" in the user-facing UI only;
the upstream code, license, and attribution are preserved here unchanged.

## How it gets here

`scripts/start_openfree.ps1` installs the **prebuilt npm package** (`omniroute@latest`,
~739 MB) into `vendor/openfree/node_modules/` on first Enable — no monorepo build.
The installed tree is git-ignored (it's large and reproducible); only this README is tracked.

## Run / diagnose manually

```powershell
node vendor/openfree/node_modules/omniroute/bin/omniroute.mjs          # serve on :20128
node vendor/openfree/node_modules/omniroute/bin/omniroute.mjs doctor   # diagnose providers/ports
```

## Boundary

OpenFree runs locally and uses only providers' **keyless free tiers** or keys the user
already holds (via the Key Vault). It does **not** create accounts or evade any provider's
terms. See `docs/OMNIROUTE.md`.

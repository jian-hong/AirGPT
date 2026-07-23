# OpenIDE — Agents | IDE surface for AirGPT

**Source of truth for OpenIDE.** Edit files here. Root `workspace_api.py`,
`cursor_bridge.py`, and `terminal_pty.py` are thin shims that re-export this package.

**Product roles:** OpenIDE = standalone coding app (coding expert slice). Keys/gate/deploy = **OpenVault**; orchestration = **Cortex**; host shell = **AirGPT**. See [`PRODUCT_ROLES.md`](PRODUCT_ROLES.md).

## Layout

```
OpenIDE/
  workspace_api.py   # workspace bind, path-jailed FS, git fingerprint/summary
  cursor_bridge.py   # local / cursor_local / cursor_cloud agent backends
  terminal_pty.py    # allowlisted terminal (git, gh, npm, …)
  ui/
    openide.css      # shell density + Agents|IDE chrome
    openide.js       # New Agent, repos, composer, Open Tabs, Create PR
  tests/             # OpenIDE-focused pytest modules
  WORK.md            # active next slices
```

## APIs (routed from `clipdrop.py`)

| Path | Module |
|------|--------|
| `/api/openide/ready` · `/backend` · `/last-run` | `cursor_bridge` + `key_vault.ready_for_backend` |
| `/api/openvault/connect` · `/status` · `/ping` · `/mesh` · `/gate` · `/keyvault` | `openvault_bridge` → `D:\OpenVault` :5000 (keys SoT + gate) |
| `/api/workspace` · `/api/workspace/open` | `workspace_api` |
| `/api/fs/*` · `/api/git/*` | `workspace_api` |
| `/api/terminal/*` | `terminal_pty` + workspace cwd |
| `/OpenIDE/ui/*` | static CSS/JS (public asset) |

Agent runs still go through Cortex (`/api/agents/...`, `/api/cortex/*`). Cortex is shared; OpenIDE is the builder UI.

**Create-App:** empty state → **Create app** → OpenVault Key Vault (OpenFree) if needed → scaffold under `apps/<slug>/` → Cortex seed Run.

**OpenVault Key Vault:** one place for OpenFree (OmniRoute), BYOK cloud keys, CLI tokens (`GH_TOKEN`), and OpenShip deploy URL/token. Memory vault (`vault.py`) is separate.

**Context engineering:** layered prompt assembly (rules → skill → tools → state → memory/NOTES → retrieval → messages) lives in `docs/PROMPT_LAYERS.md` and `../context_engineering/`. The Cortex engine exposes the same primitives at `/api/context/*`.

## How to work

1. Change UI in `ui/openide.css` / `ui/openide.js` — hard-refresh the browser.
2. Change backend in the Python modules here — restart the AirGPT host.
3. Do **not** re-embed large OpenIDE blocks into root `index.html` (nav hooks only).
4. OpenForge is a sibling product — keep it out of this folder.

See `docs/openforge.md` for the product split (OpenIDE vs OpenForge vs Cortex).

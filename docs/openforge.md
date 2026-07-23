# OpenForge (chat-to-chip) & OpenIDE (chat-to-code)

## Product split

| Surface | Role |
|---------|------|
| **OpenForge** | Netie [chat-to-chip](https://github.com/Netie-AI/OpenForge): NL spec → simulation-gated ngspice → netlist + schematic |
| **OpenIDE** | Cursor-like Agents|IDE workspace: 3-column Agents surface, Monaco, path-jailed FS, terminal, Cursor SDK backends, Key Vault preflight |
| **Cortex** | Agentic brain: tool loop, Thinking modes (Idle / Assist / Deep), audit |

## OpenIDE (Phase 9 Agents Surface)

- **Agents mode:** left runs list · center timeline (Thought / Tool / Finish) · right Browser / Changes / Files
- **IDE mode:** Files · Git · Monaco · terminal; shared composer (Run / Help / Keys / @)
- **Cortex chip:** cycles Assist → Deep → Idle for the next run
- **Create PR:** allowlisted `git add/commit` + `gh pr create` (path-jailed)
- **Fetch latest:** injects git context into the next agent prompt + workspace fingerprint (branch/HEAD/dirty)
- **Continue:** resumes last Cursor SDK `run_id` when backend is `cursor_local` / `cursor_cloud`

## OpenIDE path jail

- Workspace root set via `POST /api/workspace/open`
- All `fs_*` tools and APIs resolve paths under root only
- Denied: `env.local`, `..` escapes, secrets

## Agent backends

| Backend | When |
|---------|------|
| `local` | Default Cortex tool loop |
| `cursor_local` | `cursor-sdk` against workspace `cwd` |
| `cursor_cloud` | Cursor cloud agent (needs git remote) |

Set `AGENT_BACKEND` and `CURSOR_API_KEY` in `env.local`.

## Keys + OmniRoute free fallback

- Key Vault (`GET /api/keyvault`): Netie Official · OmniRoute · cloud free tiers · local engines
- OpenIDE Run calls `GET /api/openide/ready` — opens Key Vault when capacity is missing
- OmniRoute: set `OMNIROUTE_ENABLED=1` and/or `OMNIROUTE_BASE_URL=http://127.0.0.1:20128/v1` (BYO keys inside OmniRoute; no auto-signup)
- `ai_engine` tries OmniRoute (when enabled) before cloud cascade

## OpenForge pipeline

`POST /api/openforge/design` with `{ "spec": "..." }` → parsed targets → template netlist → **optional ngspice smoke** (real subprocess when `ngspice` is on PATH) → SVG schematic.

`simulation_gated` is **true only if ngspice smoke succeeded**. Presence of the binary alone does not count.

Marketplace `mod-openforge` enables the chip pipeline flag under `data/marketplace/`.

Full Netie-AI/OpenForge AC/transient metrics + device models: still to vendor under `third_party/openforge`.

## Naming: OpenForge vs "The Forge"

"The Forge" on netie.ai (Solutions grid) is the enterprise-facing brand name for
this engine. Keep `OpenForge` as the technical/repo/API name everywhere in code
and docs — do not rename this module. See `docs/netie-product-architecture.md`
§7 for the full ontology/naming ruling.

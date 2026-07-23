# NEXT UPDATE — explicitly deferred

Do **not** implement in the current AirGPT Personal release:

1. Fully online Personal AI (hosted analysis without BYOK)
2. Pay-to-continue Personal tier pricing (Stripe checkout after free quota)
3. Vault federation (P12), hybrid RAG / Qdrant — unrestricted agent shell
4. Always-on reasoner / knowledge-graph database
5. Bundling full Netie Cortex into the AirGPT EXE

**Now allowed (sandboxed):** Cortex multi-step tool loop, `fs_*` workspace tools, allowlisted `run_command`, OpenIDE + OpenForge workspaces.

Stubs already present:

- `ai_engine.ONLINE_PERSONAL_AI_STUB`
- `license.ONLINE_PERSONAL_PAYWALL_STUB`
- `/api/info` field `online_personal_stub`
- Settings copy: “NEXT UPDATE: online AI pay tiers”

When ready: wire Stripe on `control_plane`, gate hosted AI behind entitlement, keep Personal local clipboard free.

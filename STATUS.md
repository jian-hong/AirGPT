# STATUS

**Hard cap: 60 lines.** Older narrative moves to CHANGELOG.md.

## Now

0. **Do not kill leftover listeners.** Live: AirGPT `:8765`, Cortex
   constructor `:8010`, engine `:8011` (`PACK=dms`), OpenVault `:5000`.
1. **S1 passcode is set.** Local host 200. Phone API without a join token
   is 401 `auth required`. Probe stays 200. Not download-safe.
2. **Scheduler.** GitHub list + review (`rt-483c184a`), AirGPT ship-gate
   (`rt-18d64fc7` FAIL-closed unseen), OpenForge 3d (`rt-dcb70626` PASS)
   run as `scheduled_work`. Digest `rt-547f4184` waits on a Google App
   Password. FreeRoute brief is `openvault_vault_sealed`. **NO** AirGPT
   PRD-002.
3. **Research (D11).** Live artifact GET 200 for three packaged runs
   (md/docx/pdf/tex; stages named). Background `deep_research`
   `wf_a563c9a4cb1d` shows 4 `think` rows on `:8765`. Not arXiv.
   `GET /api/update` = `no_update_server`.
4. **Connect.** Settings Network only. Chat grid is side+main. LTX2 mock
   outputs are gitignored so CI can run `test_apps_hub_ltx2.py`.
5. **UI branch `claude/rag-ui-improvements-qgauwt`, PR #91 (draft).**
   Rounds 1-3b are on that branch. Unverified: tunnel, phone, provider,
   Cortex, a real embedder. Owner calls: P14-P36. PR #90 is in #91.
6. **Phone preview + Open in Space.** `/data/` Range (206/416). Open for
   pdf/office/txt. Host-only `POST /api/space/open`. Needs a real iPhone
   and a Windows host. Ledger rows pending in PRD-001.
7. **BROWSER-01 (#99).** Host-only Playwright tools in `browser_mcp.py`.
   Flag `AIRGPT_BROWSER_MCP` default off. Click, type, and submit stay
   confirm-gated.

## Next

0. Do not kill `:8765`. Create a Google App Password (16 chars) and
   put it in Crew Gmail keys, then re-run `rt-547f4184`.
1. Unseal OpenVault for FreeRoute briefs.
2. NEEDS-YOU: push `fix/guest-boundary-and-phone-shell`; confirm the RAG
   reliability epic and `pypdf`; re-score n=320; decide P22-P36.
3. Fork NVIDIA/auto-ontology by hand (session scope blocked it).

## WIP

GitHub still lists D09 #56 and D10 #71 OPEN; the work is on local
`fix/guest-boundary-and-phone-shell`, not pushed. Closed: D03 #26/#69,
D05 #55, D06 #37, D07 #36, D08 #38, D09 #56, D10 #71/#74, D11 #72/#73.
Parked: D04 #22, P11 #9/#10, D01 #6, HOST-DEMO-02 #42.

## Later

- P1 50GB / P2 Meta SIRA / P4 vault-first / P7 NVIDIA
- F86 phone DISTILL after D10. F88 CF Containers = OV. F89 AGI dump refused.
- DR-0007 accepted: marketplace is catalog+recipe, not a serving plane.
- Demo: `tests/RAG/DEMO_RAG.md`. Build tab: Copilot pack + Ops card.

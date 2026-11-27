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
   (md/docx/pdf/tex; stages named). Not arXiv. `GET /api/update` =
   `no_update_server`.
4. **Connect.** Settings Network only. Chat grid is side+main. LTX2 mock
   outputs are gitignored so CI can run `test_apps_hub_ltx2.py`.
5. **UI PR #91 (draft).** Rounds 1-3b. Code `e4d0ab5`. Unverified: tunnel,
   phone, provider, Cortex, embedder.
6. **RAG benches (#93).** `rag-benches` regenerates every `*_latest.json`.
   Paraphrase success@5 64/64. File types 480/480. Real-doc n=200:
   120/200 at 1 and 5, nDCG@10 0.6. primary50 equivalent, strict `close()`
   with scalar gold at 4 decimals: hybrid 320/320, sira 44/320.
7. **CU-01 (#94).** `AIRGPT_DESKTOP_SCALE` default off. On, screenshot
   (640, 360) of 2560x1440 shown at 1280x720 maps to (1280, 720). Bench:
   flag off 0/50, flag on 50/50, at 100% and at 150%.
8. **RAG sources (#97).** GitHub ingest and a depth-capped crawl, flags
   `AIRGPT_RAG_SOURCES_GITHUB` and `AIRGPT_RAG_CRAWL`, both default off.
9. GitHub lists D09 #56 and D10 #71 OPEN. Done on
   `fix/guest-boundary-and-phone-shell`, not pushed.
10. **Phone preview.** `/data/` Range 206/416. Open in Space is host-only.

## Next

0. Do not kill `:8765`. Create a Google App Password (16 chars) and
   put it in Crew Gmail keys, then re-run `rt-547f4184`.
1. Unseal OpenVault for FreeRoute briefs.
2. NEEDS-YOU: push `fix/guest-boundary-and-phone-shell`; confirm `pypdf`;
   decide P22-P36. n=320 was re-run on the seeded equivalent only.
3. Fork NVIDIA/auto-ontology by hand (session scope blocked it).

## WIP

Closed: D03 #26/#69, D05 #55, D06 #37, D07 #36, D08 #38, D09 #56,
D10 #71/#74 (S1), D11 #72/#73 (research). Parked leftover:
D04 #22, P11 #9/#10, D01 #6, HOST-DEMO-02 #42.

## Later

- P1 50GB / P2 Meta SIRA / P4 vault-first / P7 NVIDIA
- F86 phone DISTILL after D10. F88 CF Containers = OV. F89 AGI dump refused.
- DR-0007 accepted: marketplace is catalog+recipe, not a serving plane.

Demo: `tests/RAG/DEMO_RAG.md`. Build tab: Copilot pack + Ops card.

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

5. **RAG reliability (PR #90, draft).** Benches, all synthetic, hash
   embedder, no model: file types 16 in one space 480/480 top-5, every
   hit cites a place; paraphrase (of 64) verbatim 64, synonym 45,
   lowercase+typo 49, by-another-fact 17 (weak); chunking: sheet chunks
   with header 100% (was 3%), facts whole 30/30 (was 0/30); multilingual
   8 languages top-5 26-30 of 30, Arabic rank-1 13 (weak). Offline
   answer abstains (Latin scripts) or warns (scripts without capitals).
   Suite 881 pass / 0 fail on Linux. Chunker changed: index fingerprint
   schema 2, older scores are not comparable. n=320 NOT re-run here.
6. **Daily task** "AirGPT RAG daily improve" 04:23 MYT, draft PRs only.
   It was stored with no repo source and no connectors.
7. GitHub says D09 #56 and D10 #71 are OPEN; WIP below says closed.

## Next

0. Do not kill `:8765`. Create a Google App Password (16 chars) and
   put it in Crew Gmail keys, then re-run `rt-547f4184`.
1. Unseal OpenVault for FreeRoute briefs.
2. NEEDS-YOU: confirm the reliability epic and `pypdf`; re-score the
   n=320 board on the new chunker (old rows are now incomparable).
   Open list: `docs/subagents_findings/2026-11-12_*.md`.
3. Fork NVIDIA/auto-ontology by hand (session scope blocked it).

## WIP

Closed: D03 #26/#69, D05 #55, D06 #37, D07 #36, D08 #38, D09 #56,
D10 #71/#74 (S1), D11 #72/#73 (research). Parked leftover:
D04 #22, P11 #9/#10, D01 #6, HOST-DEMO-02 #42.

## Later

- P1 50GB / P2 Meta SIRA / P4 vault-first / P7 NVIDIA
- F86 phone DISTILL after D10. F88 CF Containers = OV. F89 AGI dump refused.
- DR-0007 accepted: marketplace is catalog+recipe, not a serving plane.

## Demo open

- `tests/RAG/DEMO_RAG.md`. Build tab: Copilot pack + Ops card.

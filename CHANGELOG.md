# CHANGELOG

Append-only. Never edited, only added to. Newest first.

## 2026-08-26 — D07 leftover: retained sira_max vs hybrid_max (F13 A/B)

- **Named defect:** `frtr_cross_latest.json` held one variant. Regenerated on
  `frtr_0001` with `sira_max` + `hybrid_max` (6 gold Qs: hybrid 6/6, sira 3/6
  `--no-llm`).
- **F13 retained artifact:** `oracle_cross_latest.json` scores the SAME generated
  asks (n=7, seed 1) through both variants. Fields: `value_accuracy`,
  `schema_link_accuracy` per family, `malformed_ask_rate`, `abstention_rate`.
  hybrid_max 7/7 value; sira_max 1/7 (out_of_range refuse; rest abstain). No
  precision@k / recall@k / PR-AUC / MAP.
- Gate `tests/test_oracle_cross_variants_gate.py` fails a one-variant payload
  (R-0007) and the committed files. `MIN_TESTS` stays 380. `multilingual_gate.py`
  untouched. n=320 two-variant still owed for #13/#36 close.
- Regenerate: `python tests/RAG/oracle_bench.py --dir FRTR-bench --workbook
  frtr_0001_quarterly-summary.xlsx --n 7 --seed 1 --variants sira_max,hybrid_max`

## 2026-08-26 — Verify-close wave R-0003 (#3, #33, #34)

- **Verify Agent R-0003** on master `61c1f9b6` (CI 32902147637 green). Closed
  **#3** REPO-01 (only `third_party/colibri` gitlink; `.gitmodules` parses;
  `git submodule status` OK; OpenIDE/research normal files). Closed **#33**
  RAG-BENCH-13 and **#34** RAG-BENCH-14 (PR #49; DR-0006 stamp architecture;
  `backfill_docs_originals`; gates 9/9 pytest + 7/7 docs_original). EPIC-D08 #38
  checkboxes updated. **#31** / **#32** noted CLOSED on epics #36 / #37 (not
  reopened). **#42** commented: code landed, live host handshake still owed.
- Gates re-run this session: `docs_original_gate.py` 7/7,
  `test_establish_handshake.py` 16/16. Did not close #13/#14/#15/#20/#21/#25.

## 2026-08-25 — #33 Rebuild stamps saved architecture; #34 Docs original is the rebuild path

- **#33 / DR-0006 (proposed).** `ingest_paths` no longer hardcodes `_hybrid_` on
  the revision. `revision_profile` reads `config.architecture` (default
  `hybrid` so existing spaces stay `local_hybrid_high`). Ingest still builds
  the one hybrid index; graph/agentic stay retrieve-time templates. Gate:
  `tests/test_rag_rebuild_config.py`.
- **#34.** `backfill_docs_originals` copies a still-live original into `Docs/`
  when `meta.docs_path` is missing. Rebuild prefers that original over the
  extracted `.txt` blob. Cannot invent bytes when the original is gone (space 8
  stays 0/6 until those files exist on disk). `MIN_TESTS` stays 380.

## 2026-08-25 — Constructor + MCP auto-caller ride the Cortex sidecar

- AirGPT agents and chat gain `constructor_ghost`, `constructor_recommend`,
  `auto_caller_pick` (plus existing `dms_query`) through `cortex_client`.
  Constructor is a marketplace builtin. Soft-fail when the sidecar is down.
- Rebased onto current master so skill-catalog fixtures still pin CI
  (`feat/constructor-cortex-sidecar-tools` was based pre-#29 and went red
  11/373 on an empty `data/skills`). Landed as #48. `MIN_TESTS` stays 380.

## 2026-08-25 — tests run once per PR push, not twice

- `tests.yml` triggered on both `push: ["**"]` and `pull_request`, so every push
  to a PR branch ran the full windows-latest suite twice (live proof: runs
  32764548500 and 32764552158, same SHA). Push now fires on master only;
  `pull_request` and `workflow_dispatch` unchanged. Ledger F48,
  repo-infrastructure exemption — no ticket.
- Named consequence, accepted: a branch with no open PR gets no push CI —
  open a PR or use `workflow_dispatch`. `MIN_TESTS` floor and exclusions untouched.

## 2026-08-25 — Merge wave: demo line, extractor gate, D02 HTTP tests land on master

- PR #12 merged the whole demo/rag-cross-compare integration line (six cursor
  PRs, vault-first routing, UI design system). #2 was contained and auto-marked
  merged; #5 closed on an empty diff vs master; #1 closed as superseded by
  master's newer YC recorder. 13 branches deleted, each verified
  ancestor-of-master (or PR-ref-recoverable) before deletion.
- PR #46 rebased — its first 3 commits were already master's own SHAs — and
  merged: `rag/ingest.py` extractor gate, DR-0001, `test_rag_extractor_gate.py`.
  A duplicate `openpyxl` pin the rebase re-added was caught and dropped.
- PR #41 merged master, un-drafted, merged: `tests/test_ops_http_gate.py` covers
  the six `/api/rag/ops` endpoints over HTTP; the gate code itself was already
  on master. `tests.yml` kept master's stricter version (MIN_TESTS 380).
- Suite green on master after every merge (436 passed, floor 380). Kilo Code
  Review is out of credits and reports ACTION_REQUIRED on every PR — a billing
  notice, not findings (R-0011: named so the red check is not read as code).

## 2026-08-22 - #32 D02 HTTP gate

- The D02 loop is now asserted where a client calls it. `ops_demo_e2e.py` still
  imports `rag.ops_amend` (32/32, file-level). `tests/test_ops_http_gate.py` posts
  identify / confirm-identity / propose-amend / confirm-amend / continue / chain
  over a real `clipdrop.Handler` and reads the salary cell back out of the
  workbook (R-0001).
- UI still has zero callers (P12). `clipdrop.py`'s only change here was
  dropping a leftover duplicate `reasoning` key from the SSE done dict; #29's
  merge had already fixed the dict on master, so this just removes the
  branch's stale second copy. Catalog fixtures now merge with #29's own
  `tests/fixtures/skills/general.md` / `hi.md` / `research.md` /
  `visual-diagrams.md` (byte-identical on both sides) plus `web-research.md`;
  `MIN_TESTS` stays 380.

## 2026-08-22 — HOST-DEMO-04: Hub access bar stops claiming a grant

- The Hub picker still persists `access_level` via `set_peer_acl`. Request
  gates stay IP-only and unread that field. `read_write` and `read_only` still
  get the same 403 on `/api/rag`.
- The operator surface now says the levels are saved, not yet enforced, so a
  persist-then-403 cannot contradict the bar (R-0001). DR-0003 / F22a is
  untouched. `MIN_TESTS` stays 380.

## 2026-08-22 — pandas is a product xlsx dep, not a test-only import

- `rag/xlsx_sql.py` imports pandas at module load (`DataFrame`, `to_numeric`).
  The hybrid SQL lane cannot run without it. `tests/test_rag_xlsx_sql.py`
  collects that module, so a clone without pandas died at collection (exit 2)
  before `MIN_TESTS` could be reached.
- Added `pandas>=2.0.0` to `requirements.txt`. Floor stays 380.

## 2026-08-22 — xlsx/KPI lane leaves tests/; banners are not headers

- **Shipping.** `rag/answer.py` no longer puts `tests/RAG` on `sys.path` or imports
  `frtr_sql_baseline`. Loader + SQL-ish KPI answers live in `rag/xlsx_sql.py`
  (the #31 banner/width rule, not a second detector). A checkout with `tests/`
  deleted still loads sheets and answers Top-N / KPI asks instead of `None` (R-0011).
- Bench scripts under `tests/RAG/` re-export the production module. `sira.py`
  `_TOKEN_RE` untouched. `MIN_TESTS` stays 380.

## 2026-08-22 — MIN_TESTS stays 380

- Gating rejected lowering the floor to 377. That count was the suite after
  openpyxl and before the fixture directory itself was pinned by tests.
- Three fixture-pin tests lock `tests/fixtures/skills/` (`general`, `research`,
  `visual-diagrams`, scratch `hi`) so a clean clone still earns 380. sqlite-vec
  stays opt-in. Do not merge a 377 floor.

## 2026-08-20 - EPIC-D01 and EPIC-D02 closed over unfinished work

- Founder's explicit, informed call. **Neither epic completed.** Both closed as
  `not planned`, each with a closing comment splitting what shipped from what did not.
  Do not quote either as done without reading those comments.
- Completeness was re-derived from the code, not the task lists. Verified by running:
  #20 Docs originals 7/7 sha256; #15 reasoning chain over SSE, all checks; #21 the exact
  F14 question live -> 0.9441 with `SELECT AVG(OnTimeSLA) FROM Carriers WHERE BaseRate > 1`;
  #14 reveal -> `origin: "docs"`; #25 Settings 3 of 4 sub-clauses; oracle 400/400 on the
  clean workbook, 0.75% bound.
- **Three briefed claims were wrong.** #10 is not "not started" - `insights_export.py`
  implements the sheet and `clipdrop.py:5166` exposes it, it simply has no UI caller and
  has never been run. `test_corrective_loop_caps` is green, not red. #14's `docs` origin
  does resolve, but only for spaces ingested after #20 - space 8 is 0/6.
- **D02's 32/32 never crossed HTTP.** `ops_demo_e2e.py:25` imports `rag.ops_amend` and
  calls it directly, so the six endpoints at `clipdrop.py:5225-5297` have no coverage
  (R-0001). The endpoints do work - I probed identify live - which is why this is a
  missing gate rather than a broken lane, and why it was easy to keep postponing.
- **D02's appetite clause was violated unnoticed.** The epic ring-fenced itself onto
  `demo/rag-ops-confirm`; that branch has never existed and every commit landed on
  `demo/rag-cross-compare`, the branch it was told not to pollute.
- **Retained "multi-variant" scores hold one variant.** `frtr_cross_latest.json` has a
  `variants` list of length 1. F13's `sira_max` vs `hybrid_max` was never retained.
- Remainder carried forward before the close: #31 header binder + single-variant
  artifact, #32 D02 HTTP gate, #33 Rebuild ignores saved config, #34 `docs_path`
  backfill, #35 production imports from `tests/`; PARKING_LOT P11 (#9/#10), P12 (D02 UI
  surface), P13 (multilingual). P9 and P10 were cited as parked since 2026-08-03 with no
  row and would have vanished with this close - both now have unlock conditions.

## 2026-08-20 — #13 rescored at n=320, and two defects that explain the number

- **#13 rescored honestly.** `oracle_bench.py` over the 4 primary50 workbooks, seeds 1-4,
  80 each: value accuracy **172/320 = 0.5375**, schema-link recall **181/320 = 0.5656**.
  This REPLACES the 0.80/1.0/0.80 figure, which was n=10 and bounded nothing (R-0010).
  "Approaching 99%" was never supportable and should not be quoted again.
- Per family: `out_of_range` 44/44 = 1.00 (refusal behaviour is genuinely sound),
  `row_range_nocol` 0.77, `paraphrase` 0.61, `row_range_agg` 0.58, `filter_count` 0.52,
  `combined` 0.16, `filter_agg` 0.12. The largest single failure reason is "no answer
  from the lane" (54 of 148 failures) - abstention, not wrong answers.
- **Header detection picks banner rows.** `tests/RAG/frtr_sql_baseline.py:29` takes the
  first row in the first five with >=2 non-empty cells. On `Messy_RAW` that is the banner
  `['RAW','sheet','—','skip']`, so the real header (row 2) becomes data and the schema
  gains columns literally named `skip` and an em dash. 89 of 320 generated asks (28%) are
  malformed by this; on the 231 well-formed ones accuracy is **0.6017**. Row 2 also
  carries duplicate column names. The bench's own header-drift check reports zero,
  because it compares the loader against the oracle and both pick the banner (R-0007).
- **The product imports its xlsx engine from the tests directory.** `rag/answer.py:900`
  puts `tests/RAG` on `sys.path` at runtime and imports `frtr_sql_baseline`. A deploy
  without `tests/` loses the whole xlsx/KPI lane silently - it returns `None`, with no
  error and no degraded flag (R-0011). Routed to `prd-agent`; likely a decision record.
- Both defects routed, neither implemented - the routing rule in CLAUDE.md is absolute.

## 2026-08-20 — EPIC-D01: the chain reaches the browser, and #20 stops being a claim

- **#15 was invisible in the product.** The chain was built, yielded, and dropped at the
  transport: the SSE handler in `clipdrop.py` enumerated `thinking|meta|citations|delta|
  error|done` with no `reasoning` branch, and rebuilt its `done` payload from a fixed key
  list that omitted it. `index.html` sends `Accept: text/event-stream` on every answer, so
  that handler is the only path a founder takes. Added the branch, the key, and a renderer
  (`.ragreason`, open by default on a refusal or abstention, escaped, collapsed otherwise).
- **The gate had asserted the wrong layer.** `tests/RAG/reasoning_chain_live.py` drove the
  plain JSON handler, which passes the whole dict through — so unit tests, the JSON path,
  and the feature-being-invisible were all simultaneously true. It now drives SSE and parses
  the event stream (R-0001).
- **#25 had the same shape one layer down.** `clipdrop.py` whitelisted depth as
  `basic|high|max|manual`, so a space saved as Adaptive — persisted as `auto`, and sent on
  every ask — was silently coerced to `high`. Saving appeared to work and never took effect.
  Also corrected the Rebuild copy, which omitted the enrich stage.
- **#20 was closed on a false claim.** "Space 8 is 6/6 identical" came from a bench script in
  `stash@{0}`, not the product; production ingest wrote post-extraction text and set no
  `docs_path`, so every `rag/reveal.py` docs lookup fell through. Recovered
  `_retain_docs_original` into `rag/ingest.py` and added `tests/RAG/docs_original_gate.py`,
  which drives real ingest from outside the blob store and asserts sha256 identity plus the
  PK container magic — 7/7. New ingests only; older spaces need a backfill.
- Known red, pre-existing and unrelated: `tests/test_rag_foundation.py
  test_corrective_loop_caps` (2 != 1), identical at `b09e6033`. Left failing rather than
  weakened.
- Corrects the date on the entry below, which was filed as 2026-08-07 in error.

## 2026-08-19 — Skill catalog tests no longer depend on gitignored laptop packs

- `data/` is gitignored, so `data/skills/*.md` exists only on the machine that
  created them. The catalog tests read those packs and went green locally
  (396/0) while GitHub Actions saw an empty catalog (5 failed). That is R-0007:
  green on the author laptop, red on a stranger clone.
- Committed fixture packs live under `tests/fixtures/skills/`. The invoke and
  `/api/skills` tests pin `SKILLS_DIR` there. The product may still ship with
  no user packs; an empty `data/skills` stays an empty catalog.
- `MIN_TESTS=380` was the same laptop lie: pytest on Actions passed 371/0/15,
  then the floor failed. The 15 skips are 6 openpyxl xlsx tests (now earned:
  `openpyxl` is in `requirements.txt`), 8 sqlite-vec ANN tests (opt-in, stay
  skipped on a stranger clone), and 1 BGE embedder test (HF offline). Floor is
  377, the count a clean Actions checkout actually earns.

## 2026-08-19 — EPIC-D01 + EPIC-D02: reasoning chains and the ops write path

- **D02 ops amend-confirm** (#17–#19): `rag/ops_amend.py` rewritten to resolve columns
  from the sheet header instead of positionally, match rows honestly rather than
  guessing at the first near-hit, and carry the confirm loop through to a write. A
  spent confirm token can no longer be replayed. Scenario harness
  `tests/RAG/ops_demo_e2e.py` — 32/32, covering reject, refuse, off-rails and the
  confirmed +8% write with its audit stamp. Runbook section added to `DEMO_RAG.md`.
- **D01 reasoning chain** (#15): new `rag/reasoning.py` renders each lane's provenance
  as sentences a founder can check, replacing op codes like `bind_entities`. Every
  answer exit point in `rag/answer.py` now carries one.
- Two chains were reporting work that did not happen. The KPI catalogue's ABSTAIN path
  returned no provenance, so the chain printed "computed from the rows above" on a run
  that deliberately computed nothing; it now carries the abstention and the lane's own
  reason. Policy refusals built their chain without hits, reporting "nothing matched"
  while holding retrieved passages; they now pass the real hits.
- Chain values round through the same helper as the answer text, so a chain no longer
  shows 0.9440740740740741 beside an answer of 0.9441.
- **D01 Settings** (#25): depth and architecture controls were computed into
  `depthOpts`/`archOpts` but never rendered, so Save read elements that did not exist.
  Rendered in `index.html`; `rag/store.py` whitelist accepts `adaptive`/`auto`. Save and
  Rebuild verified over HTTP against a live instance.

## 2026-08-03 — FRTR-Bench Excel RAG smoke

- Harness: `tests/RAG/frtr_eval.py` (+ SQL baseline, Cortex lane). Sanitize materializes formula caches; strips Questions.
- AirGPT RAG: KPI sheet boost in `rag/retrieve.py`; spreadsheet index + small-sheets-first in `rag/ingest.py`.
- Result: hybrid SQL+RAG **6/6 (100%)** on `frtr_0001_quarterly-summary.xlsx`. Full 159 needs XLOOKUP/SUMIFS SQL agent + vision for chart Qs.
- Cortex `/dms/query` confirmed live for SQL-brain demo; OpenVault is not an Excel RAG path.


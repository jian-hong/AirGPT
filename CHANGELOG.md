# CHANGELOG

Append-only. Never edited, only added to. Newest first.

## 2026-09-11 -- Connect stays in Settings; LTX2 mock dumps ignored

- Chat grid is two tracks (side + main). Connect is Settings Network only,
  so a missing right pane cannot keep an empty column. `video-assets/08-ltx2-outputs/`
  is gitignored (keep `.gitkeep`) and CI runs `tests/test_apps_hub_ltx2.py`.

## 2026-09-07 -- D10 and D11 closed after independent verify

- EPIC-D10 #71 / S1-01 #74: phone without passcode is HTTP 403
  `s1_passcode_required`; probe/health stay 200. After passcode, phone without
  join token is 401. pytest `test_s1_passcode_posture.py` + research tests:
  23 passed. Live `:8765` left running.
- EPIC-D11 #72 / RES-01 #73: artifact HTTP for md/docx/pdf/tex; stages named.
  Do not unpark D04 #22, benches #9/#10, D01 #6, HOST-DEMO-02 #42.

## 2026-09-07 -- DR-0007 accepted; Constructor is a hub card

- Marketplace stays catalog + fit + recipe. `bind_serve` still writes `env.local`
  and returns a command; it does not spawn a pid. Constructor blurb no longer
  says "hosted inside Cortex at /cortex/constructor/". Serving stays OpenVault.

## 2026-09-06 -- marketplace DR-0007 proposed; mesh config stays in data/

- `docs/decisions/DR-0007-marketplace-is-catalog-not-serving.md` proposed.
  Catalog + fit here; `bind_serve` is a recipe, not a pid. Serving stays
  OpenVault. Constructor stays `serving=module`.
- `ensure_local_config` writes `DATA_DIR/openvault.local.json` only. Repo-root
  `openvault.local.json` is gitignored so CI dirty-checkout cannot fire on it.

## 2026-09-05 -- live workflow think traces on :8765

- Reloaded Cortex `:8011` only (`:8765` untouched). Stubbed runner tests
  assert `think`+`web_search` on the panel. Live `deep_research`
  `wf_a563c9a4cb1d` now shows four `think` rows through GET
  `/api/workflows/tasks`. LLM hops still fail without OV unseal. Not
  download-safe.

## 2026-09-05 -- two more research packages + think traces

- Live `:8765` serves long md/Word/PDF/TeX for three idea-to-paper ids,
  not one. HTTP tests name distinct `stage` values. Cortex agent loop
  now stores `think` + tools on the Background card; OpenForge ship-gate
  routine `rt-dcb70626` is PASS. Not download-safe.

## 2026-09-05 -- review vs open-a-PR classifier

- "code review open PRs" no longer matches `pr_create`. Live routine
  `rt-32d4bdaa` is paused with kinds github+review only. Phone without a
  join token is 401 (tested). Not download-safe.

## 2026-09-05 -- S1 passcode live; Gmail IMAP connector

- Host passcode is set. Phone `/api/ai/config` is 401 `auth required`
  (join with the passcode). Local UI stays 200.
- Cortex Gmail connector is IMAP/SMTP via Crew keys (gitignored), not
  Google OAuth. Google requires a 16-char App Password. Morning digest
  routine `rt-547f4184` is pinned. IMAP timeout for scheduled fetch is
  20s. Not download-safe.

## 2026-09-05 -- live artifacts + scheduler FreeRoute brief

- Packaged run `20260828_183237-...` now serves long markdown (7k), Word,
  PDF, and tex on `GET /api/research/artifact`. Phone still 403 until a
  host passcode exists.
- Cortex `scheduled_work` prepends a FreeRoute `model=auto` brief when the
  vault is unsealed. Live `:5000` is sealed (`openvault_vault_sealed`);
  gh/ship-gate facts still run. Not download-safe.

## 2026-09-05 -- live S1 host + passcode file merge

- Real `clipdrop.py` is listening on `:8765` (not demo-mock). Phone HTTP
  without a passcode is 403 `s1_passcode_required`. Research runs list
  and `/api/update` answer on that host. Creating a passcode no longer
  wipes the OpenIDE `root` in `data/workspace.json`.
- Cortex `:8011` draft/create is live (`work_kinds=github`). Scheduled
  `gh pr list` was timing out at Crew's 1.5s chat budget; operator
  sweeps now ask for 20s. Not download-safe.

## 2026-09-05 -- Cortex scheduler does gh/ship-gate/mail

- Routines with PR/review/build/email goals no longer echo the prompt
  on the minimal DAG. Cortex `scheduled_work` lists/diffs/creates PRs
  via Crew `gh`, runs ship-gate, reads IMAP, and sends SMTP when a
  Gmail app password is set. AirGPT Routines create no longer blocks
  on an AirGPT agent chip. Background agent cards show stored tool
  steps. `GET /api/update` is honest (`no_update_server`). S1 phone
  tests cover fs/OpenIDE/git/agents/DELETE. Live `:8765` / `:8010`
  not reloaded (do not kill). Not download-safe.

## 2026-09-05 -- S1 remote lock in tree (EPIC-D10); research artifact HTTP gated

- Founder /goal: scheduler-forever + S1 + perfect research + bg
  subagents + analog DISTILL + ship ecosystem. PRD F78-F83 named
  two in-flight epics only. Analog clones stay frozen.
- S1: phone without a host passcode gets HTTP 403
  `code=s1_passcode_required`. Probe/health/auth-status stay 200.
  Tunnel worker will not sweep until `passcode_set`. Tests:
  `tests/test_s1_passcode_posture.py` + establish suite. Live
  `:8765` not reloaded (do not kill).
- Research: `GET /api/research/artifact` proven in
  `tests/test_idea_to_paper.py`. Live 404 until clipdrop reload.
- GitHub: D10 #71 / S1-01 #74; D11 #72 / RES-01 #73.

## 2026-09-05 -- F67-F77 analog/WIP dump routed, not built

- Status: scheduler honesty yes / Cursor cron no; S0+establish yes /
  S1+CORS* no; research not perfect; OpenIDE subagents serial not
  Cortex-class; not download-safe. Analog `D:\\my*` paths ACK+SKIP
  per TAS. 9router is OpenVault FreeRoute, not a second AirGPT
  router. Lift-WIP + parallel-all refused (ESTATE-GAP section 3).
- Finding: `docs/subagents_findings/2026-09-05_prd-analog-wip-intake.md`

## 2026-09-05 -- F59-F66 EXE/safety dump routed, not built

- Founder ask (audit unbuilt + EXE upload + encoded anti-theft +
  screenshot + our-server fetch + key guide + OV/Cortex forever)
  logged as PRD-001 F59-F66. No GitHub tickets. No third epic.
- D03 never included EXE. PyInstaller onedir is extractable;
  obfuscation is not OpenVault custody. NEXT_UPDATE still forbids
  hosted Personal, Stripe, and embedding Cortex in the EXE.
- Finding: `docs/subagents_findings/2026-09-05_prd-exe-safety-intake.md`

## 2026-09-03 -- Research Word/md package on live :8765

- Idea-to-Paper run `20260828_014649` ships long markdown, path
  figures, mermaid, IEEE PDF, and stdlib Word. Live downloads use
  `/ui/exports/` because the running clipdrop process predates
  `/api/research/artifact`. Cortex still generates; AirGPT packages.
- Fixed dead Settings Marketplace (`showMarketplace`), OpenForge
  Design JSON parse, OpenIDE terminal/checkout treating Response as
  JSON, Hosting plan via GET, Research/Seek/RAG leaving OpenIDE
  overlay. OpenHBM stays parked.

## 2026-09-03 -- /api/info no longer hangs the phone

- Cold `/api/info` was 12s on live `:8766` (probe 0.3s). The request
  thread ran netsh, PowerShell WiFi/BT, Google generate_204, OpenVault
  `:5000` ping, and a SQLite device write. Phone never got
  `tunnel_attempts` (HOST-DEMO-03).
- Cache-first LAN/online/Cortex snapshots; OV `ping()` 0.6s + 8s cache;
  skip `register_device` on `/api/info`. Gate: `tests/test_info_bounded.py`.
- Rebuild HTTP now returns `revision_profile`; Save+Rebuild toast names
  the stamp (D08 / DR-0006). D07 primary50 floors still 320/320.
- Boot no longer `taskkill`s the cloudflared it just started. Health loop
  no longer restacks a sweep on `* unreachable`. Probe falls back to IPv4
  when urllib 11001s. Ready-log is cp1252-safe so a working URL is not
  thrown away. Live `:8765` published
  `https://kevin-story-multiple-companion.trycloudflare.com` (GET / 200,
  `/api/probe` 200 `via=tunnel`). Closed #69 and EPIC-D03 #26.


## 2026-08-28 -- Cortex owns Idea-to-Paper; OV auto chat restored

- Research agent + pipeline hops send `prompt_id=research.idea_to_paper`
  to Cortex `POST /api/engine/run`. AirGPT is pytest + pdflatex only.
  Fail closed if Cortex is down. Keys stay OpenVault.
- Live `:5000` restarted onto `json_safe` tree. `model=auto` chat 200
  (`openai/gpt-oss-120b`). Cortex AGENT_TASK research hop ok.

## 2026-08-28 -- DR-0002 pomodoro is scaffolded, not a host page

- `app_scaffold` / `scaffold_from_ask` turns "make a pomodoro timer" into
  a 25:00 Start/Pause live app. Hand-written `pomodoro.html` and
  `/pomodoro` `/tomato` routes deleted.
- Gates: 32 passed (`test_app_scaffold_pomodoro` + agent loop + chat tools).

## 2026-08-28 -- OpenVault E: mesh + laptop MCP arming

- `allcheck.py` probes `E:\OpenVault` tree, `:5000 /api/healthz`, and
  loopback chat (no Bearer). Dead health fails the check; unhealthy hops
  warn. Bridge prefers E: then D:. `OPENVAULT_HOME` pin documented.
- Vault already has Groq/OpenRouter/Google. Cursor and Anthropic are
  missing on disk -- paste in OpenVault Providers. Do not invent keys.
- Crew start scripts set `CORTEX_COMPUTER_CONTROL=1` and engine `:8011`.
  UACC/windows-mcp stay Confirm on mutate. Tests: OpenIDE mesh + policy.

## 2026-08-28 -- OpenVault auto 500 is encode crash (fix in OV tree)

- Live `:5000` PID 62048. `model=auto` (Cortex AGENT_TASK) returns
  uvicorn text/plain 500. Groq llama ids return typed JSON 400.
- OpenVault `json_safe` + hop continue landed; 33 passed. Live OV not
  restarted from this agent.

## 2026-08-28 -- Chat composer uses Cortex AGENT_TASK by default

- `_chat_stream_events` always posts `architecture_preset=agent`.
  `web_search` only adds tools. Prior turns ride in the prompt.
  Tool events are `type=tool`; `sendStream` paints them.
- Gates: 26 passed (`test_cortex_agent_loop` + `test_shell_d09_readout`).
- Live `:8011` loop still dies on OpenVault HTTP 500. Host restart owed.

## 2026-08-28 -- D06 closed; D03 children filed

- Closed EPIC-D06 #37: #17/#18/#19/#32/#35/#67 already closed; HTTP
  confirm + rebuild stamp 12 passed + 16 subtests this run.
- Filed HOST-DEMO-01 #68 (closed; throttle+banner 14 passed) and
  HOST-DEMO-03 #69 (open; live tunnel_url still owed).
- Remaining open children parked with unlock: #69 network, #9/#10 P11,
  D07 primary50, D08 live host + DR-0006, D04 Pointer paste.

## 2026-08-28 -- Idea-to-Paper one-shot 183237 PDF

- 8m scale loop aborted. OV `:5000` was down; restarted without
  `OPENVAULT_HOME=E:\OpenVault\.openvault`. Live POST `:8766`
  `20260828_183237-...` one-shot (no continue) landed paper.pdf + zip.
  Pytest 100/100 (8 passed), constructor generate 200 via `:8012`,
  7 OV/cascade calls, usd_est ~$0.011, `cursor_generation` false.
  Venue cs.SE. Human arXiv upload still pending.

## 2026-08-28 -- D04 pack POSTs to DMS crosscheck

- `rag/xlsx_orch.post_pack_to_dms` hits `POST /v1/studio/xlsx-orch/crosscheck`.
  DMS down stays `awaiting_dms_receipt` with the cause named. DMS accept
  becomes `awaiting_pointer_receipt`. No Pointer paste. Gates: 11 passed.



## 2026-08-28 -- D05/D09/D06/D07 ticket gates this-run

- #57 row-split tautology gone; rebuild `.txt` blobs keep `table=True`; csv
  gets sheet parents. #58 unicode_v1 + own-doc coverage positives; gate stays
  red on English-only embedder. #59 expandable `<details>` tool rows. #60
  Cortex-owned scheduler; `_engine_cfg` no longer hops to `:8011` on a failed
  probe (mock create had leaked `rt-a4f46c80`). #61 Force fold, not Skill Use.
  #65 schema-link mutation gate. #67 `/build` paths override refuses
  unregistered files. This-run: 191 passed + 16 subtests; multilingual 64/73.


## 2026-08-28 — Operator: engine seat + stuck-loop + chat quality path

- `pack=dms` is the Netie engine, not Constructor. Host `_engine_cfg`
  skips `:8010` Constructor and talks to `:8011`. Scheduler status is
  `live`. AGENT_TASK skips duplicate tool+params (OpenManus stuck
  detector). Chat `web_search` uses `/api/engine/run` preset `agent`.

## 2026-08-28 — Idea-to-Paper continue salvage 153854

- Verify blocked on missing `import urllib` + JSON `\\n` in Executor
  Python. Repair now prepends `import urllib` and unescapes doubled
  newlines. In-app `continue` landed PDF + zip, pytest 100/100 (13
  passed), constructor generate 200 via `:8012`, 8 OV calls ~$0.010.

## 2026-08-28 — Constructor generate 405 fallback

- `:8010` constructor surface 405s `POST /cortex/constructor/generate`.
  `cx_recommend` retries `:8011` then `:8012`. Live: generate 200 via `:8012`.
  Loop tick 9 did not fire another paper POST (152325 already passed).

## 2026-08-28 — LOOP-02 live LLM+tools on :8011 and host :8766

- OpenVault loopback 401s dummy bearers. AGENT_TASK uses OpenVaultAdapter
  + native tool_calls. DDG lite search restores ranked links. Host
  `/api/agents/:id/run` SSE ends with chunk `0` so clients see
  `stop_reason=quality`. Live: OpenResearch cited FoundationAgents/OpenManus.

## 2026-08-28 — Idea-to-Paper bib inject + constructor 401 guard

- `inject_bibliography` fills empty `thebibliography` from kept
  `references.bib`. `_post_status` no longer crashes when FastAPI
  `detail` is a string (constructor 401).
- Live POST `:8766` `20260828_152325-...` one-shot PDF + zip, 7 OV
  calls, usd_est ~$0.006, `cursor_generation` false. Venue `cs.SE`.
  Constructor recommend 200; generate still 405 on DMS `:8012`.

## 2026-08-28 — LOOP-02 live: OpenVault no-bearer + Constructor fallback

- Dummy `Authorization: Bearer openvault-loopback` 401s OpenVault loopback.
  Cortex AGENT_TASK now uses OpenVaultAdapter (httpx, no dummy token) and
  native tool_calls. AirGPT engine client accepts Netie `/api/engine/specs`
  and falls back from Constructor `:8010` to engine `:8011`.

## 2026-08-28 — In-app Idea-to-Paper one-shot PDF

- POST `:8766` `/api/research/idea-to-paper` run `20260828_151105-...`
  landed `paper.pdf` + `arxiv_source.zip` in ~64s with no continue/resume.
  Execute `max_tokens` 4096 (8192 was Groq 413 / empty files). 6 OV calls,
  usd_est ~$0.006, `cursor_generation` false.

## 2026-08-28 — LOOP-02: host consumes Cortex quality loop

- Cortex preset `agent` -> POST `/api/engine/run` runs AGENT_TASK with an
  independent verifier. AirGPT agent SSE prefers that path; names the skip
  when Cortex is down. Tests: Cortex 19, AirGPT 3.

## 2026-08-28 — Idea-to-Paper facts Limitations inject + 142102 PDF

- LLM IEEEtran omitted `\\section{Limitations}`. `inject_limitations`
  copies bullets from `00_verified_facts.md` (same as tables-from-facts).
  `20260828_142102-...` now has `paper.pdf` + `arxiv_source.zip`.

## 2026-08-28 — F53 Manus-class routing; Cortex LOOP-01

- Founder /goal to become Manus-class: jailbreak + leaked prompts +
  reconstructed Grok bots refused. OpenManus/OpenWorker/rakazo cloned
  for P19 distill only (Cortex `skill_distill/sources/oss/`, gitignored).
- F20b quality-terminated AGENT_TASK loop lands in Cortex
  (`stop_reason=quality|max_steps|final`, independent verifier, fail-closed).
  AirGPT D09 stays the shell; it does not grow a second orchestrator.

## 2026-08-28 — Scale-forever Idea-to-Paper loop

- Armed 8-minute local loop. Stopped latching OpenVault HTTP 500 onto
  Gemini for the rest of the process. Execute timeout no longer clamped
  to 12s. One-shot POST `20260828_142102-...` reached facts 100/100;
  paper-tex still dies when OV fallback pool is Groq 413 / no gpt-oss.

## 2026-08-28 — In-app continue salvage + URL-regex repair

- POST `:8766` `/api/research/idea-to-paper` with `continue: true` salvaged
  `20260828_120423-...` after pytest SyntaxError from JSON `[^"]`. Repair
  maps that regex to `\\S+`. 2-page PDF + `arxiv_source.zip`, ~$0.007.
  Research UI polls and auto-continues a blocked verifier.

## 2026-08-28 — In-app Idea-to-Paper POST + paper-tex OV backoff

- POST `:8766` `/api/research/idea-to-paper` queued `20260828_114641-...`.
  Research/method/PoC/paper-md via `gpt-oss-120b`. Paper-tex hit OV 502
  (Groq 429, pool empty); resume after cooldown wrote a 3-page PDF
  (~$0.008). `ov_chat` now waits 8s and retries OV on 502/503 before
  cascade.

## 2026-08-28 — OpenVault chat restored; OV-authored 3-page PDF

- Restart OV without `OPENVAULT_HOME=E:\OpenVault\.openvault` (that
  master.key is DPAPI-wrapped by another account). Chat 200 via
  `openai/gpt-oss-120b`. Run `20260828_114035-...` research/method/PoC/paper
  through `/v1/chat/completions` + constructor `:8012`. 3-page PDF,
  usd_est ~$0.007, `cursor_generation` false.

## 2026-08-28 — Idea-to-Paper constructor :8012 + in-app POST

- `cx_recommend` falls back to Constructor/DMS `:8012` when `:8010` is
  down. Live POST `:8766` `/api/research/idea-to-paper` queued a run.
  Resolve-or-drop now seeds kept DOIs when the LLM returns title-only cites.
  OpenVault `/v1/chat` still 500; Gemini quota blocked that hop's Executor.

## 2026-08-28 — Idea-to-Paper salvage + second PDF

- Executor JSON with Python regex `\d` now parses (`_fix_json_escapes`).
  `--continue-run` re-scores a verify-blocked run then authors paper.
  Run `20260828_112219-...`: pytest 100/100, 3-page PDF, usd_est $0.007.
  OpenVault `/v1/chat` still 500; Cortex constructor down this hop.

## 2026-08-28 — Idea-to-Paper 3-page PDF (OpenVault down)

- Replaced the 1-page `_fallback_tex` stub with a compiled IEEEtran PDF
  (3 pages) via Gemini cascade after OpenVault `/v1/chat` 500/502.
  Cursor did not author the paper body. Gate still rejects stub + fake
  `test_gate.py` / Python 3.11 transcripts.
- Residual: Results still contains `passed=None` (status.json dropped
  scores on resume). Google 429 stopped the repair hop.

## 2026-08-27 — Idea-to-Paper spine on OpenVault + Cortex

- Research agent can run OpenHBM-style Idea-to-Paper without Cursor
  generation: `idea_to_paper.py` calls OpenVault `/v1/chat/completions`
  (keys SoT) and Cortex constructor recommend/generate, then pytest-gates
  a software PoC (lint 20 / tests 50 / all-green 30, retry 3), freezes
  `Captured:` facts, charts, IEEEtran `arxiv_package/paper.tex`.
- HTTP: `POST /api/research/idea-to-paper`, `GET /api/research/runs`.
  Skill: `.cursor/skills/idea-to-paper/` (also `/skill idea-to-paper`).
- Gate: `tests/test_idea_to_paper.py`. Cost ledger in each run `cost.json`.

## 2026-08-27 — SHELL-02 live clock on :8766; HTTP gate

- Verify host `:8766` (does not kill `:8765`): POST `/api/cortex/routines`
  creates `hr-*` with `next_run_at`; `/run` advances it. Response names
  Cortex-missing `/api/routines` instead of toast theater.
- `tests/test_shell_d09_http.py` locks Handler create+run + Force-fold HTML
  + `line_delta` +N/-M.

## 2026-08-27 — SHELL-03: gallery off primary path; slash peels then sends

- Cortex home Skills fold is **Force a skill** (optional). Cards show
  `/skill <id>` + Force, not a primary Use shop (DR-0002).
- `commands.peel_skill_slash`: `/skill pack job`, `/skill:pack`,
  `/skill-pack`, `/anthropic-skills:pack job`. Arm then send remainder.
  Forced `skill_pack` wins over auto-match; auto-match no longer silently
  fills `skill_pack`. Composer hint: Auto tools · `/skill pack` to force.
- API `skill=` arming (`tests/test_skills_registry.py`) unchanged.

## 2026-08-27 — CHUNK-02 unicode tokenizer; host-clock scheduler

- `rag/sira.py` `unicode_v1`: CJK/Thai n-grams + letter runs. Coverage no
  longer returns 1.0 on empty ASCII tokens. Fingerprint records
  `lexical.tokenizer`. `multilingual_gate.py` **20/25** (was 7/25). Remaining
  red is English-only BGE + whitespace `.split()`, not the ASCII tokenizer.
- SHELL-02: Cortex `:8010` has no `/api/routines`. `host_routines.py` owns
  the clock (`hr-*`); orchestrator tick fires due rows. UI toasts host clock.
- SHELL-01: write/patch return `added`/`removed`; agent stream groups tool rows.

## 2026-08-27 — F52: D05/D09 filed; CHUNK-01 row windows

- Founder: Open WebUI-class host shell, far from ChatGPT; become better
  than Claude/ChatGPT at tools, scheduler, automation, ease of use.
- PRD-001 F52. EPIC-D05 [#55](https://github.com/jian-hong/AirGPT/issues/55)
  (authorized F25c-R, never on GitHub until now). EPIC-D09
  [#56](https://github.com/jian-hong/AirGPT/issues/56). Tickets #57-#61.
- CHUNK-01: `parent_child_chunk(..., table=True)` packs whole sheet rows;
  ingest sets it for xlsx/csv. Fingerprint records `chunker.table`.
  D07/D03 queued until this chunker lands. `multilingual_gate.py` untouched.

## 2026-08-26 — D04 #23/#24 AirGPT half: identify + Copilot pack + honest reveal

- `rag/xlsx_orch.py` locates an ingested xlsx (schema + name; no first-file
  guess) and emits a structured Excel Copilot prompt pack: Cover → OnTime
  Export → Analysis (AVERAGEIF/FILTER) → Presentation Chart.
- AirGPT does **not** paste, drive Copilot, or call Pointer. Pack is a DMS
  cross-check candidate (`paste_owner=pointer`, `cross_check_owner=dms`).
- Handoff stays `awaiting_dms_receipt` until a durable result path is posted
  (no silent fake DMS wire). Reveal reuses `rag/reveal` (#14). Incomplete
  result workbooks are flagged, not greened.
- HTTP: `POST /api/rag/xlsx-orch/{identify,handoff,reveal}`. Build tab card
  is the click-through. Gates: `tests/test_xlsx_orch.py` +
  `tests/test_xlsx_orch_http.py`. `MIN_TESTS` stays 380.
  `multilingual_gate.py` untouched.

## 2026-08-26 — D02 #17-#19 thin ops click-through on Build

- `index.html` now calls the six existing `/api/rag/ops` endpoints (P12 was
  zero callers). Identify asks "is it that one?", amend still needs a second
  confirm, continue starts a fresh pair of gates. Cortex-direct honesty.
  Not a second ops product. Not OpenVault. Not DR-0003.
- Gate `tests/test_ops_ui_callers.py`. HTTP loop still `test_ops_http_gate.py`.
  `MIN_TESTS` stays 380. `multilingual_gate.py` untouched.

## 2026-08-26 — D07 leftover: n=320 two-variant on primary50

- Ran `oracle_bench.py --variants sira_max,hybrid_max` over the four primary50
  workbooks, n=80, seeds 1-4. Same generated asks per workbook.
- **hybrid_max** value **320/320 = 1.0** (per workbook 80/80, every family 1.0).
  F13b floors 0.99 pooled / 0.95 per workbook / 0.90 per family MET.
  `malformed_ask_rate` 0.0 (< 5%).
- **sira_max** value **44/320 = 0.1375** - all 44 are `out_of_range` refuses;
  every KPI family abstains (retrieve-only, `use_llm=False`). Not a 99% claim.
- Retained: `tests/RAG/results/oracle_cross_primary50_{1..4}.json` and pooled
  `oracle_cross_primary50.json`. n=7 CI smoke `oracle_cross_latest.json` kept.
  Named `--out` no longer copies onto that smoke file.
- Gate `test_oracle_cross_variants_gate.py` now reads the pack (shape + hybrid
  floors + malformed ceiling). `MIN_TESTS` stays 380. `multilingual_gate.py`
  untouched. Do not close #13/#36 from this run.
- Regenerate: four `--dir primary50 --n 80 --seed {1..4} --variants sira_max,hybrid_max --out oracle_cross_primary50_{1..4}.json` then `--aggregate-primary50`.

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


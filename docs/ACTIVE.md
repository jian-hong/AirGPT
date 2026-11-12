# Active map

What exists in this repo and where. Update when structure changes, not when state changes
- state lives in STATUS.md.

- `prompt_trace.py` -- prompt lens record: what one chat turn sent to the
  model. Filled where the request is built (`ai_engine._prepare_text_chat`,
  `chat_text_stream`, `clipdrop._cortex_prompt_trace`), stored per reply in
  `prompt_traces`. `GET /api/chat/prompt-trace?message_id=|session_id=`;
  non-host devices get private blocks without text. Tokens are an estimate.
- `ui/promptlens.js` + `ui/promptlens.css` -- the panel and composer meter.
  `window.PromptLens.open(messageId)`. Hook in `index.html` is one button in
  `renderMsg` plus the two asset tags.
- `commands.py` `peel_skill_slash` — `/skill`, `/skill:`, `/skill-`,
  `/anthropic-skills:` arm a pack; remainder is the job (SHELL-03).
- `openpyxl` and `pandas` are product xlsx deps (`rag/ingest.py`,
  `rag/xlsx_sql.py`) and live in `requirements.txt`. `sqlite-vec` stays opt-in.
- `rag/chunking.py` -- parent/child: heading + paragraph windows (prose),
  code-symbol parents (source), whole-row children (`table=True` for
  xlsx/csv). Never regex-the-file; never mid-row char-split.
- `rag/sira.py` `tokenize` / `TOKENIZER_ID=unicode_v1` -- CHUNK-02; ASCII
  identifiers plus CJK/Thai n-grams and Hangul/Arabic/Cyrillic letter runs.
- `cortex_client.scheduler_status` -- named refusal (`wrong_surface` /
  `cortex_down` / `no_scheduler`). AirGPT host clock is legacy-only.
  Real scheduled work is Cortex `scheduled_work` (gh / ship-gate / mail).
- `GET /api/update` -- `license.check_update`; `no_update_server` until
  `AIRGPT_API_BASE` names a signed channel. Not download-safe.
- `clipdrop._rag_check_build_paths` -- `/build` paths must be this space.
- `rag/ingest.py` — `revision_profile` stamps saved architecture on rebuild
  (DR-0006 / #33). `table=True` for xlsx/csv. Rebuild prefers Docs original.
- `rag/xlsx_sql.py` — production xlsx loader + SQL-ish KPI answers. Product
  must not import this from `tests/`.
- `rag/xlsx_orch.py` — F15 / EPIC-D04 AirGPT half: identify ingested xlsx +
  structured Copilot prompt pack + honest DMS handoff/reveal. Does not paste
  or drive Copilot (`paste_owner=pointer`, `cross_check_owner=dms`).
- `rag/sheet_sql.py` — schema-aware filter+aggregate over those frames.
- `rag/answer.py` `_try_hybrid_sql_lane` — wires both into the ask path.
- `tests/RAG/oracle_bench.py --variants sira_max,hybrid_max` — F13 A/B on one
  generated question set; CI smoke `tests/RAG/results/oracle_cross_latest.json`
  (frtr_0001 n=7). Pack: `oracle_cross_primary50_{1..4}.json` + pooled
  `oracle_cross_primary50.json` (n=320, F13b floors on hybrid_max).
- `idea_to_paper.py` — Cortex `prompt_id=research.idea_to_paper` owns
  generation. AirGPT is pytest + facts inject + pdflatex. Keys stay
  OpenVault. HTTP `POST /api/research/idea-to-paper`. Cursor is not
  the generator.
- `allcheck.py` plus `OpenIDE/openvault_bridge.py` -- OpenVault mesh
  (`E:\OpenVault`, `:5000` health, loopback chat). Keys SoT is OV.
  `ensure_local_config` writes `DATA_DIR/openvault.local.json` only (DR-0007).
- `marketplace.py` -- catalog + fit. `bind_serve` is a recipe, not a pid
  (DR-0007 accepted). Constructor blurb is a hub card, not a Cortex-hosted
  LLM server.

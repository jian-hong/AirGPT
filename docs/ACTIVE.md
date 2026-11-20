# Active map

What exists in this repo and where. Update when structure changes, not when state changes
- state lives in STATUS.md.

- Request gates in `clipdrop.py`, in the order they run: `_wrap_dispatch`
  (cross-site guard `_origin_gate`, bad JSON 400, crash 500) around every
  `do_*`; then `Handler._gate` (passcode set, token, host-only paths,
  handshake, share-guest allow-list `_GUEST_GET` / `_GUEST_POST`). Host trust
  is `_is_host_request` and needs `_is_trusted_host(Host)`. A new route is
  closed to share guests until it is added to the allow-list. Tests:
  `tests/test_origin_guard.py`, `tests/test_guest_scope.py`.
- `ui/sanitize.js` -- allow-list HTML cleaner (`AirSanitize.clean`), used when
  DOMPurify is missing. Buttons built from data use `data-call="fn"` with
  `data-arg` / `data-args`, dispatched by one listener in `index.html`
  (`_dataCall`); never an inline handler built from data.
- `ui/ext.js` -- `window.AirUI.addMsgAction(fn)`: how add-on modules put a
  button on a message. New shell features live in their own `ui/<name>.js` +
  `.css` (already loaded by `index.html`), not in the page.
- `ui/chattools.*` + `db.fork_session` / `db.export_session` -- Fork a chat from
  a reply (`POST /api/sessions/fork`), export one chat
  (`GET /api/sessions/export?format=md|json`). `window.ChatTools`.
- `chat_prefs.py` + `ui/chatprefs.*` -- instructions for one chat
  (`GET|POST /api/chat/prefs`), added to the prompt on both routes and traced
  as `chat_instructions`. `window.ChatPrefs`.
- `snippets.py` + `ui/snippets.*` -- saved prompts with `{{blanks}}`
  (`/api/snippets`, `DATA_DIR/snippets.json`). `window.Snippets`.
- `ui/palette.*` -- command box (Ctrl/Cmd+K, or `Commands` in the + menu).
  `window.Palette`. Commands are feature-detected, never listed dead.
- `ui/phone.css` + `ui/phone.js` -- phone-only overrides (760px and below),
  loaded after the page styles.
- `prompt_trace.py` -- prompt lens record: what one chat turn sent to the
  model. Filled where the request is built (`ai_engine._prepare_text_chat`,
  `chat_text_stream`, `clipdrop._cortex_prompt_trace`), stored per reply in
  `prompt_traces`. `GET /api/chat/prompt-trace?message_id=|session_id=`;
  non-host devices get private blocks without text. Tokens are an estimate.
- `ui/promptlens.js` + `ui/promptlens.css` -- the panel and composer meter.
  `window.PromptLens.open(messageId)`. Hook in `index.html` is one button in
  `renderMsg` plus the two asset tags.
- Chat stream lifecycle (`clipdrop.py`): the first SSE event carries
  `stream_id`; `POST /api/chat/cancel {stream_id}` stops it (a view-only share
  guest gets 403, a share link only reaches its own chat). The partial is
  saved with `ai_status='stopped'` and the stream ends with
  `{"type":"stopped","saved":bool}`; closing the browser alone does not cancel.
  `_chat_streams` plus `_run_tracked` feed `_generating_sessions()`, shown as
  `generating` on `/api/messages?full=1`, `/api/wait` and `/api/sessions` rows.
- Edit and regenerate: the stream request takes `replace_msg_id` or
  `regenerate_msg_id` (last turn only, anything else 409). Page side
  `ui/turnedit.js` + `.css`; waiting messages and per-chat drafts live in
  `index.html` `send()` / `_sendInner()` (drafts in localStorage).
- Attachments: the stream request takes `attachment_ids` (files in this chat
  only); `ai_engine._attachments_block` adds one fenced untrusted block, traced
  as `attachments`. The upload reply carries `attach{readable,reason,chars,cut}`.
  Word files are read by `rag.ingest._docx_text` (no python-docx).
  `QUESTION_LIMIT` cuts a long message and the reply says so.
- Paging: `/api/messages?full=1&limit=&before_id=` (`has_more`),
  `/api/sessions?offset=` (`total`, `has_more`), `GET /api/sessions/<id>`.
  `_json` gzips bodies of 1 KB or more; `/ui` and `/OpenIDE/ui` go through
  `_send_static` (ETag, 304, gzip).
- `ui/voice.js` + `.css` -- voice input in the message box.
- Agent runs live on a server thread (`agent_runtime.start_background_run`,
  `tail_run`): `POST /api/agents/<id>/run` watches, `GET
  /api/agents/runs/<id>/events` re-attaches, the Stop flag is checked between
  steps, the done event carries `runner`, `model`, `own_tools`.
- Backup and restore: `/api/export` and `/api/import` are host-only. Backups
  leave out `env.local` and the login, passcode, share and licence files
  (`_BACKUP_SECRET_FILES`, listed in `MANIFEST.json`). Restore plans first,
  checks free space, writes `pre-restore-<time>.zip`, needs `confirm=1`.
- `memory_index.forget_session` -- deleting a chat removes its memory rows,
  embeddings, chat folders and vault notes.
- RAG answer shape: stream meta/done carry `goal, lane, sql, provenance,
  citations, web_used, degraded`. `GET /api/rag/passages/<chunk_id>` and
  `GET /api/rag/sources/<id>/file` (script types download only). URL ingest
  runs `_check_public_url` on every redirect hop. `/sources` refuses `force`.
- A question stores the files sent with it (`messages.attachment_ids`, a
  JSON list; NULL means saved before this existed and falls back to the
  file rows right before it). Regenerate and Edit reload exactly those
  through `_attachment_files`; files past 12 are named in the reply
  (`_left_out_note`). A queued line is always a new question.
- Restore (`clipdrop._restore_package`) skips secret and control files
  (`_BACKUP_SECRET_FILES`, `_RESTORE_CONTROL_PREFIXES`) and Windows aliases
  (`_alias_reason`), checks every `.db` opens as SQLite, and rolls back
  from its safety copy on any failure.
- `sanitizeHtml` drops `style`, url-bearing attributes, `id`, `name` and
  classes (except `language-*` on code) from model, document and web
  markup; `renderMd` sets KaTeX and Mermaid output aside with per-render
  nonce tokens and puts them back only outside tags. KaTeX runs with
  `maxSize`, `maxExpand`, `trust:false`.
- RAG packs carry each sheet as a values-only CSV (`table_workbook`,
  `table_sheet` in the manifest) so an imported space still calculates.
  `rag/ingest._east_asian_codec` reads GBK, Big5, Shift-JIS, EUC and
  UTF-16 without a byte-order mark; `looks_binary` decodes instead of
  peeking; `unreadable_reason` names an encoding it cannot tell.
- `openfree.py` `cannot_run()` -- OpenFree needs PowerShell (Windows or
  `pwsh`); elsewhere the key manager says so and the enable route refuses
  before changing settings.
- `ui/touch.css` -- under `(pointer: coarse)`, small controls keep their
  look and get an invisible 44x44 tap layer. On phones the chat title bar
  folds Background tasks, Export and Share into one menu (`#chatMoreBtn`).
- Rendering: `renderMd` caps KaTeX (`_KATEX_SAFE`, a TeX length limit,
  no `\def`-style macros) and runs `cleanMermaidSvg` after Mermaid draws, so
  labels and themeCSS cannot carry page ids; `sanitizeHtml` also drops
  `for`, `form*`, `popover*`, `list`, `usemap`, `aria-*` and size attributes.
- Restore checks each known database by the columns the app needs
  (`_db_refusal`, `_probe_schema` builds the reference from a fresh app-made
  database), runs the start-up upgrades after the swap, caps unpacked bytes
  (`_RESTORE_MIN_CAP`) and refuses over-long paths.
- `ai_engine` records why a provider is cooling down ("key refused", "rate
  limited", "unreachable") and puts it in the error text; saving a key in
  Settings clears that provider's cooldown. The page reads those words.
- `rag/retrieve.py` cuts Hangul words into 2-character pieces so a stem
  finds its inflected forms. Packs write formula-looking cells as text.
- A line starting with `@` runs an agent only when an agent has that exact
  name (longest match); the line, the answer in full and any failure are
  saved as chat rows.
- `tests/devkit/` -- stand-ins for live checks, not product code:
  `stub_llm.py` and `stub_rich.py` (OpenAI-compatible, log every request
  body), `stub_cortex.py` (keywords STUBSLOW, STUBFAIL, STUBEMPTY,
  STUBTOOLFAIL), `run_app.py` (any port, own data folder), `integ.js` (27
  browser checks), `composer.js`.
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
- `tests/RAG/filetype_bench.py` -- 11 file types in one space, planted facts,
  recall at 1/5 and whether the hit names a place. Live gate
  `tests/test_filetype_bench_gate.py` (n=10). No model call.
- `rag/retrieve.py` `exact_term_search` -- weighted fusion channel for a rare
  code or name from the question. A code counts alone; a name needs the chunk
  to cover half of the rest; a bare number never counts.
- `rag/ingest.py` extractors emit structure the chunker turns into citations:
  `## Page N` (pdf), heading styles + table rows (docx), shown slide order +
  notes (pptx), headings + cells (html), `.eml`, whole json records.
- `rag/chunking.py` -- chunker `parent_child_sentence`: every sheet row
  window carries its header row; prose is cut at sentence ends (CJK, Thai,
  Arabic marks too); size budget is per script. `index_fingerprint`
  schema 2, so older scores read as not comparable.
  `tests/RAG/chunk_bench.py` measures it.
- `tests/RAG/multilingual_bench.py` -- 8 languages in one space. Scripts
  without capitals get a warning line for an unfound word, never a refusal.
- `rag/ontology.py` -- `ONTOLOGY_VERSION=4`: Unicode keys, tsv/json/xml
  records as tables, relations across file types.
- `tests/RAG/paraphrase_bench.py` -- same facts asked four ways (verbatim,
  synonym, lowercase+typo, by another fact). Gate pins measured floors; two are
  deliberately weak and say so. Measure only.
- `rag/answer.py` `abstention` -- offline answer says the space does not
  mention a name / file / attribute instead of quoting a look-alike.
- `rag/ingest.py` -- also `.tsv .xml .log .ipynb .rtf`. Re-ingesting a file
  replaces its chunks; identical files share a source row with every origin.
- `rag/ontology.py` -- `probable_foreign_key` (70-90% overlap) is never
  counted in `n_relations` or stated as fact.
- `/api/rag/spaces/<id>/upload` adds. It rebuilds only on `force=1`.
- `rag/ontology.py` -- `ONTOLOGY_VERSION=2`. Induced from cell values: keys
  from uniqueness, relations from value containment, column kind/role/date
  format, table grain. xlsx + csv, cross-workbook. Cache keyed on the source
  files. No keyword list, no model call. Ideas after NVIDIA/auto-ontology
  (clean-room; running their stack is P7). `tests/test_rag_ontology.py`.
- `rag/xlsx_sql.py` — production xlsx loader + SQL-ish KPI answers. Product
  must not import this from `tests/`.
- `rag/xlsx_orch.py` — F15 / EPIC-D04 AirGPT half: identify ingested xlsx +
  structured Copilot prompt pack + honest DMS handoff/reveal. Does not paste
  or drive Copilot (`paste_owner=pointer`, `cross_check_owner=dms`).
- `rag/sheet_sql.py` — schema-aware filter+aggregate over those frames: bare aggregates,
  text filters read off the data, group-by and ranking over every sheet and
  csv, with provenance.
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

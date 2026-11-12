# Active map

What exists in this repo and where. Update when structure changes, not when state changes
- state lives in STATUS.md.

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

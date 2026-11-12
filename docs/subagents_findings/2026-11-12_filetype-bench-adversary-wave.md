keywords: [RAG, filetype bench, pdf, docx, pptx, eml, csv, html, json, fusion, exact match, upload force, adversary, workflow, citation, page, slide]
main_idea: A per-file-type bench went red on first run (json/csv/xlsx 0 of 30) and a live HTTP run showed a second upload wiping the first. Fusion, extractors, upload and the offline answer were fixed; five adversaries then reproduced 25 more defects, 17 fixed, 8 left open with reasons.

# File-type bench, the upload wipe, and the adversary wave

## Finding 1 - rank fusion buried the exact match

- Expected: a question naming "Tasulaado" returns the one chunk that says Tasulaado.
- Actual: json, csv and xlsx found 0 of 30, python 8 of 30; recall at 5 was 264 of 330.
  The keyword channel ranked the right chunk first, the offline hash embedder did not
  rank it at all, and plain RRF let any chunk that was lukewarm in two channels win.
  The sparse score was also a constant 1.0 (sqlite bm25 is negative; it was clamped).
- Repro: `python tests/RAG/filetype_bench.py --no-write` at commit 391c45a.
- Root-cause class: equal-vote fusion with one weak channel; a trace value that is a
  constant (R-0011).
- Fix: `retrieve.exact_term_search`, a weighted channel for a rare code or name from
  the question. A code counts alone. A capitalised word counts only where the chunk
  also covers half of the rest of the question, and a bare number never counts
  (adversary findings: "Tromso", "2024", "Request").
- Invariant: assert what the user receives; prove a gate can fail (it did, first run).

## Finding 2 - a second upload wiped the first

- Expected: adding files adds files.
- Actual: `POST /api/rag/spaces/<id>/upload` defaulted `force` ON. The UI sent
  `force=0`; any other caller cleared every earlier chunk, while the sources list
  still showed the old files. Found by driving the live server, 6 of 11 types gone.
- Root-cause class: destructive default; a list that reports state it no longer has.
- Fix: force only on an explicit `1`/`true`. `tests/test_rag_upload_keeps_space.py`
  runs through the real handler and fails on the old default.
- Invariants: data-loss handling; silent fallback is a lie.

## Finding 3 - citations named no place, and the offline answer hid the answer

- PDF had no page, docx no section, html no heading, eml was raw MIME, pptx notes
  were not read. The offline answer clipped each chunk at 180 characters, so the value
  was cut off. Now: `## Page N`, heading styles, table rows, notes, eml fields, json
  records kept whole, and the offline answer quotes the matching sentence with its
  location.

## Adversary wave (workflow, 5 agents, Sonnet, isolated context, read-only on the repo)

Lenses: office, pdf, fusion, ontology, text formats. 25 defects reproduced, 8 high.
Each agent wrote fixtures in its own temp dir and returned a runnable repro. The
repros were replayed inline after the fix; `tests/test_rag_adversary_regressions.py`
pins 13 of them with hand-built fixtures.

Fixed: pptx slide number follows shown order not file name; hidden slides marked;
numeric speaker notes kept; docx tabs/breaks, text box read once, custom heading
styles via styles.xml, footnotes/headers/footers; pdf page text starting with `#`
cannot replace the page heading; no 200-page cap; encrypted/corrupt/empty PDFs say so;
research attach with nothing indexed is `ok: false`; html heading inside skipped tags,
empty headings, table cells; BOM and UTF-16 decode; csv empty cells keep their column
and cell line breaks do not split a record; eml unknown charset and forwarded message;
ontology false join on a small shared value set, quantity run as key, csv banner/BOM,
same sheet name in two workbooks.

Open, with the reason each was not done here:

| Defect | Why open |
|---|---|
| xlsx empty cells dropped, values shift under the wrong header (same class as the csv fix) | changes every xlsx chunk, which makes retained score rows incomparable. Founder call, as F25c was |
| Two-row or merged xlsx headers bind the first data row as header (`rag/xlsx_sql.py`) | product loader shared with the SQL lane and its n=320 board |
| Dirty foreign keys missed: `001` text vs `1` number, 85% overlap | needs a "probable" relation tier, not a threshold nudge |
| Relations into a table past `MAX_ROWS` are dropped | sampling design |
| Text dates in other notations and text percentages classed as key | needs a real date/number parser pass |
| Nested docx tables flattened; merged cells lose column alignment | low severity |
| html heading with a line break inside it | low severity |
| A name typed in lowercase gets no exact boost | no signal without a vocabulary; documented limit |

## What the numbers do and do not say

Bench: recall at 5 is 330 of 330, recall at 1 is 323 of 330, every locator correct.
Synthetic facts, hash embedder, no model call, n=30 per type. It proves each lane
ingests, retrieves and cites a place. It bounds nothing about real documents, and no
bench exists yet for answer quality with a model or for abstention.

## Wave 2 (same day): four builders in worktrees, one adversary each

Shape: workflow, 8 agents, Sonnet. Four builders with `isolation: worktree` on
disjoint files; each commit then went to an independent adversary that could not
edit. Nothing was merged on a builder's word: the commits were unwrapped, every
reproduced defect was fixed inline, then the suite and both benches were re-run.
Workflow lesson: worktrees are cut from the default branch, not the session branch.
The first launch would have built on stale code; each agent now resets to the
branch head first.

| Slice | Adversary verdict | What was done about it |
|---|---|---|
| Abstention (offline answer says "not in this space") | merge, 2 medium | stem tolerance so a rewording does not flip answer to refusal; sentence runs anchored on the subject so "payment terms for globex" no longer quotes another vendor |
| Dirty-data ontology (probable tier, `001` vs `1`, text dates and amounts, full-table profiling) | merge, 1 medium | zero-padding on the referencing side no longer downgrades a clean join; csv keeps `001` as written |
| More types (tsv, xml, log, ipynb, rtf), re-upload replaces | NO merge, 1 high | identical files share one source row and editing one deleted the other's content: origins are now tracked per row. xml tail text, tsv quoting, rtf code page, notebook v3 headings fixed |
| Paraphrase bench (measure only) | merge | floors raised after the fixes below |

Finding 4 - the flat hot-file bonus. `retrieve._search` added +0.05 to every chunk of
the five files the file-level search liked. A first-place rank vote is 0.016, so with
more than five files any chunk of a favoured file beat the chunk holding the answer.
The 11-type bench hid it; 16 types exposed it (log 10 of 30, xlsx 14 of 30). The
builder had worked around it by giving each new type its own space. That workaround
was removed and the bonus resized to one rank vote: 480 of 480 in one shared space.
Root-cause class: a constant tuned against a small corpus (same class as F28a).
Invariant: fix the class, not the symptom; a gate that cannot fail this way is no gate.

Paraphrase bench, of 64 per style (rank 1 / top 5), before -> after:
verbatim 57/57 -> 64/64; synonym 24/44 -> 26/45; lowercase with a typo 10/35 -> 40/49
(the existing `rag/spell.py` corrector is reused in a lowercase exact-match channel);
identify-by-another-fact 5/17 -> 5/17.

Open after wave 2:

- Identify-by-another-fact questions: 17 of 64. Needs a second hop; nothing lexical fixes it.
- Synonym questions: 45 of 64. The offline embedder is lexical. P13 covers the embedder.
- Abstention is offline only, needs every named thing missing ("Acme and Zorblax"
  answers for Acme and says nothing of Zorblax), and judges the statement, not the
  labelled "closest" passages.
- A table past one million rows reports `n_rows` as the cap; European number
  notation (`1.200,50`) and non-English month names are not read.
- Re-upload identity is the resolved path: a changed copy under a new path is a new file.

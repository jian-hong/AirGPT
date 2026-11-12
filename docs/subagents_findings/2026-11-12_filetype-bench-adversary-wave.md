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

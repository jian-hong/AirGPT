# DR-0001 - Binary extractor lanes announce themselves, they do not fail quiet

- **Status:** proposed
- **Ticket:** jian-hong/AirGPT#35 (RAG-BENCH-15)
- **Invariants:** R-0011 (a silent fallback is a lie), R-0004 (fix the root cause class),
  R-0005 (a control that refuses legitimate work is a failure)

## Context

`.xlsx` and `.xlsm` are listed in `TEXT_SUFFIXES`, so the product tells the user it
indexes spreadsheets. The extractor behind that promise is `openpyxl`, which was never
declared in `requirements.txt`. It happens to be installed on the dev box and every
spreadsheet test guards itself with `pytest.importorskip("openpyxl")`, so the whole
estate is green on a machine where the package exists and silent on one where it does not.

Reproduced before any change, with `openpyxl` blocked at import:

```
WITH openpyxl   : '## Sheet: Sheet\nSample | Result\nRS622XK | PASS 41.2'
WITHOUT openpyxl: ''
```

`_xlsx_text` returned `""`. `ingest_paths` then hit `if not text.strip(): continue` and
dropped the file with no row, no job error and no message. The upload reported success.
Asked about the spreadsheet, the space answered as if the document had never been given
to it - a missing dependency became "no evidence found". That is the failure mode the
ticket names: a silent None that reads as no evidence.

The root cause class is broader than one lane. **An unavailable extractor and a genuinely
blank file both produce the empty string**, and nothing downstream can tell them apart.
Any lane whose extractor rides a third-party package inherits the same lie.

## Decision

Gate at the extractor boundary, in `rag/ingest.py`:

1. `xlsx_supported()` beside the existing `pdf_supported()`, and `_EXTRACTOR_GATES`
   mapping each suffix set to its stated reason plus a capability probe.
2. `extractor_gap(suffix)` returns that reason, or `""` when the lane is healthy.
3. `ingest_paths` checks the gate **before** extracting, and records every dropped file
   in a `skipped` list carrying `path`, `reason`, and `lane_unavailable`.
4. A run that indexed nothing **because a lane is down** returns `ok: False` with the
   reason as its error, and marks the job and space errored. A run that indexed nothing
   because the files were blank stays a success - the two no longer collapse.
5. `openpyxl>=3.1.0` is declared in `requirements.txt`. A normal deploy answers the same
   as before; only a genuinely broken install takes the stated-unavailable path.

Both halves of the acceptance criterion are covered: normal installs answer identically,
and an install without the extractor states that the spreadsheet lane is unavailable.

The upload endpoint (`clipdrop.py`, `/api/rag/spaces/<id>/upload`) already returns the
ingest dict verbatim as JSON, so `skipped` and `lanes_unavailable` reach the client with
no new plumbing. `ingest_research` now extends that list instead of assigning over it -
assigning would have discarded the downed-lane rows and restored the silence.

## Alternatives rejected

**Move the extractor into `rag/` and have the bench import the product.** The ticket
framed the choice as move-into-`rag/` versus duplicate. Neither applies as written: this
repo has no `tests/RAG` package and no production import of `tests/` (verified by grep
across every branch). The dependency that goes missing in production is a PyPI package,
not a test module, so there is nothing to move.

**Duplicate a spreadsheet parser into `rag/`.** Rejected. Writing an OOXML sheet parser
to avoid a dependency trades a declared package for several hundred lines that drift
from the format, and it would not fix the class - the PDF and media lanes stay silent.

**Declare `openpyxl` in `requirements.txt` and stop there.** Rejected as the whole fix.
It makes the healthy path likelier but leaves the lie in place: any install where the
package fails to land is still silently empty, and a requirements line is not a control.
Kept as one part of the change, not as the change.

**Insert a placeholder chunk such as `[spreadsheet extractor unavailable]` into the
corpus.** Rejected, and it is the worst option. It puts text into the index that
retrieval can rank and cite, so an infrastructure fault becomes fabricated evidence in
an answer. Refusing loudly at ingest keeps the corpus honest (R-0001).

**Raise from `_xlsx_text` instead of gating.** Rejected. The extractors are called inside
a broad `try/except` in `ingest_paths`; an exception there aborts the entire batch, so one
spreadsheet in a fifty-file upload would take down the other forty-nine. That trades a
silent failure for a refusal of legitimate work (R-0005).

## Confirmation

`tests/test_rag_extractor_gate.py` - 7 tests, all failing against the unfixed
`rag/ingest.py` except the no-regression case, which passes both before and after by
design:

| Test | Asserts |
|---|---|
| `test_xlsx_supported_reports_truthfully` | capability probe does not lie |
| `test_extractor_gap_names_the_missing_package` | the reason names `openpyxl` |
| `test_extractor_gap_is_empty_when_the_lane_is_healthy` | no false alarm |
| `test_stdlib_lanes_are_never_gated` | `.docx`/`.pptx`/`.md` are never gated |
| `test_ingest_states_the_lane_instead_of_indexing_nothing` | the acceptance criterion |
| `test_healthy_lane_still_indexes_the_spreadsheet` | R-0005, no legitimate work refused |
| `test_blank_file_is_reported_separately_from_a_downed_lane` | the two causes stay distinct |

Gate proven able to fail (R-0007): with `rag/ingest.py` stashed, 6 of the 7 fail.

Regression check: `tests/test_rag_foundation.py`, `test_rag_ingest_formats.py`,
`test_rag_rebuild_import.py`, `test_rag_export_import.py` and the new file - 55 passed.

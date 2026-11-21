keywords: [round 3, round 3b, bridge hop, multi-hop, contextual index, depth, abstention, char-presence, CJK refusal, cross-language, Thai marks, Word tables, PDF tables, Total row, line endings, CRLF, RAG, random uploads, stress corpus, pandas truth, European decimals, currency, percent, banner row, semicolon csv, json records, dropped condition, multi-file, hijacked lookup, ingest speed, name channel, rare name, fusion weight, hash embedder, held-out seeds, self-tuning, Contextual Retrieval, Corrective RAG, Adaptive-RAG, merge regression, rank 1, gate floor]
main_idea: A random-upload corpus with pandas truth found spreadsheet answers that were confidently wrong (7 of 20 sampled), all in one class: a parser that drops what it does not understand and still answers. Two lanes that each improved retrieval alone cut rank-1 answers from 26 to 8 of 64 when merged, and one lane had lowered gate floors to ship its own gain. Per-space self-tuning from a space's own words was measured and could not tell settings apart.

# Round 3: does RAG survive random uploads, and what does current research add

## Workflow shape used (and why)

- PREFLIGHT: PARTIAL. 2026-11-20_round2-parallel-lanes.md covered "lanes pass
  alone, break together" and "silent fallback is a lie" for negated filters;
  nothing covered number formats, banner rows, fusion weights or tuning.
- Local workflow, 6 Sonnet agents, 2 at a time: per track a discovery agent
  (read-only, measures), a builder (own worktree) and an independent verifier
  (own worktree, new seed, attacks, repairs at the root). Tracks: "robust"
  (26-file stress corpus, 83 questions, truth from pandas) and "research"
  (2024-2026 RAG literature mapped to the code, four benches as baseline).
- One cloud session (Sonnet) for screens, with its own verifier subagent.
- Main session (Opus): briefs, the merge, the merge-regression fix, docs.

## Finding 1 - a condition the question states was dropped, and the total was returned

- **Expected:** "How many invoices are paid yes?" counts 84 of 240.
- **Actual:** 240, with provenance that looked normal (`SELECT COUNT(invoice)`,
  no WHERE). Same for "issued after 2024-09-01", "between 6 and 8", "not paid".
- **Repro:** money_mixed.csv (240 rows); ask it with `use_llm=False`.
- **Root-cause class:** a planner that silently drops the words it cannot bind
  and still answers. The fix declines and names the unmatched words.
- **Invariant:** silent fallback is a lie; assert the number the user receives
  against pandas, not the SQL text.

## Finding 2 - European decimals read 1000 times too small

- **Expected:** "1.234,56" is 1234.56.
- **Actual:** 1.23456; the shop total was 3.2346 instead of 3234.56.
- **Root-cause class:** one global number format assumed for every column.
  Fixed per column, and an ambiguous "1.234" is not guessed.

## Finding 3 - the first file that yields a number wins

- **Expected:** "total qty where region is North" uses the file with a region
  column (433).
- **Actual:** 155544 from another file that has qty but no region.
- **Root-cause class:** first-match across sources instead of planning over all
  of them (the multi-sheet planner was right; the lane in answer.py bypassed it).

## Finding 4 - merging two retrieval gains lost rank 1

- **Expected:** each lane's gain survives the merge.
- **Actual:** synonym questions at rank 1 fell from 26 (base), 33 (robust lane)
  and 21 (research lane) to 8 of 64 merged. The new name channel ordered its few
  chunks by how strongly the name matched, so its first-place vote went to the
  shortest chunk with the name; the research lane had cut the vector weight, the
  only other signal that told those chunks apart.
- **Repro:** `python3 tests/RAG/paraphrase_bench.py --no-write` on the merge of
  lane3/robust-fix and lane3/research.
- **Root-cause class:** a channel's internal order chosen by its own evidence,
  not by the question; measured lanes merged without re-measuring.
- **Fix:** order the name channel by the other channels at equal weight; vector
  weight 0.6, the lowest of 0.25, 0.4, 0.6 and 1.0 where no style loses rank-1
  answers on seeds 1-7. A first version ordered by the weighted channels and lost
  1 to 4 synonym answers per seed against full weight; the full suite caught it.
- **Invariant:** adversary is not the verifier (each lane's verifier passed);
  don't weaken a check: the research lane had lowered two r@1 gate floors to
  ship 0.25. They are restored and a test now fails at 0.25.

## Finding 5 - self-tuning on a space's own words cannot tell settings apart

- **Expected:** questions generated from a space's chunks rank fusion settings
  the way real questions do.
- **Actual:** across 33 settings they scored 0.885 or 1.000 everywhere while the
  real paraphrase bench ranged 159 to 206 of 256 (Spearman 0.21); the tuner
  would have picked a setting scoring 175 when 206 was available.
- **Root-cause class:** an evaluation set that copies the answer's words cannot
  measure vocabulary mismatch, which is the thing being tuned.
- **Invariant:** prove a gate can fail before trusting it.

## Finding 6 - one connection and one commit per chunk

- **Expected:** a 7 MB CSV ingests in seconds.
- **Actual:** 417 s for 20,000 rows (about 20 ms per chunk), long enough for a
  web upload to time out. Now about 12 s.
- **Root-cause class:** per-item transaction in a bulk path.

## Finding 7 - a Windows file was read differently from the same file on Linux

- **Expected:** a document gives the same chunks and answers whatever line
  endings it was saved with.
- **Actual:** Windows CI refused 5 Japanese name questions where Linux refused 3,
  and the gate failed. The bench writes its files in text mode, so on Windows every
  line ends in CRLF; `read_text_file` folded CRLF only for the source hash (with a
  comment saying so), and the text handed to the chunker kept every carriage return.
- **Repro:** run the multilingual bench on Linux with its files written as CRLF:
  the Japanese name cell goes from 3 to 5 refusals, exactly the Windows number.
- **Root-cause class:** a normalisation applied to the identity of the data but not
  to the data itself; tests that only run on one platform's file conventions.
- **Fix:** one fold of CRLF and CR to LF for every reader, before chunking. The bench
  with CRLF files now matches the LF run exactly, and the LF numbers did not move.
- **Invariant:** assert the artifact the user receives (the chunk text), not a hash.

## Round 3b (same day): what the second pair of lanes found

### Finding 8 - one presence rule caused both missing and false refusals

- **Expected:** a made-up Chinese name is refused; an English question about a
  Russian or Malay document that holds the name is answered.
- **Actual:** abstain-control 0 of 10 in Chinese, Japanese, Korean, Arabic and
  Thai; English questions about Russian, Malay and Spanish files refused 30, 30
  and 24 of 30 although retrieval had the passage in the top five.
- **Root-cause class:** `answer._token_in_blob` counted a non-Latin word as present
  when half its characters appeared anywhere, so every invented CJK name looked
  covered, and a real Russian name was dropped as "a word every passage holds",
  leaving only English attribute words no foreign passage contains. One loose
  rule, two opposite symptoms.
- **Fix:** whole-word and whole-string matching, Arabic name pairs, a name-only
  judgement for cross-language questions, a name lookup before judging. The
  verifier then found Thai combining marks cut words apart (Python `\w` does not
  match them) and Korean question words counted as missing terms; both fixed.

### Finding 9 - a Total row was added to the rows it totals

- **Expected:** "total Amount" over a Word table equals the pandas sum.
- **Actual:** double the true figure (175,243.08 for 87,621.54): the table's own
  closing Total row was summed with the body. Also: PDF tables with one-character
  cells were all declined (a greedy cell pattern), and a table continued on page 2
  without its header gave a page-1-only total with no caveat.
- **Root-cause class:** a new reader trusted a document table to be pure data;
  the builder's corpus had no total row, no single-digit cells, no page break.
  The verifier's second corpus (different generator, different seed) found all
  three. Assert the number against pandas on data the builder did not make.

### Finding 10 - a deeper search found less than a shallow one

- **Expected:** depth high never finds fewer answers than basic.
- **Actual:** paraphrase top five 203 of 256 at high against 208 at basic. The
  file boost gave every chunk of a favoured file one more vote, but only when a
  file row happened to fit in the fused list, which happened at high and max and
  not at basic.
- **Root-cause class:** a side effect gated by an unrelated size limit. The boost
  now reads the file channel at every depth and needs evidence (`FILE_BOOST_MIN_BM25`).

### Finding 11 - a saturated metric made a strict test fail

- **Expected:** the weight test separates 0.6 from 1.0.
- **Actual:** after the bridge hop, both weights find 256 of 256 at depth high, so
  "strictly more in the top five" failed 256 > 256. Both agents were blocked from
  editing the test and reported it instead; the comparison now runs at depth
  basic, where it passes at 0.6 and fails at 1.0.
- **Invariant:** prove a gate can fail; a gate that saturates stops measuring.

### Finding 12 - four lanes each read past the files the user chose

- **Expected:** a question limited to some files (`source_ids`) uses, cites and
  names only those files, in every lane.
- **Actual:** the retrieval channels honoured the scope, but four later steps did
  not: the bridge hop (found by its verifier), the name lookup before judging
  (found in the merge review), the spreadsheet and document-table maths lane (found
  twice, by two seam finders independently: a question scoped to one CSV added up
  another, 16,150 instead of 150), and the "what does this space contain" inventory,
  which named every file.
- **Root-cause class:** a scope applied at the first search and assumed downstream;
  every new path that goes back to the store (a lookup, a second search, a table
  read, a summary) must take the scope again. Each lane was verified alone and none
  had a scoped test.
- **Fix:** each of the four takes `source_ids`; `tests/test_rag_scope_seams.py` and
  `tests/test_rag_scope_pack_concurrency.py` assert the answer, citations, SQL and
  provenance hold no out-of-scope file. The same seam pass found and fixed: duplicate
  sources from concurrent uploads of one file (a per-space ingest lock), the
  repeated-column note lost after pack import, document tables silently becoming
  text after import (now said in the pack and the import notice), an empty duplicate
  source after a rebuild of a pre-CRLF-fold space, "whose" and "has" counted as
  missing words, a Chinese name one character off answered with the real person's
  code, a Japanese name built from two real names answered, the phone Stop button
  showing the Copy icon, and a stopped reply showing two icon rows.
- **Invariant:** adversary is not the verifier; fix the root-cause class (all four
  paths, not the one found first).

### Finding 13 - two Windows blind spots in tests written on Linux, again

- **Expected:** a test that passes on Linux passes on the Windows runner.
- **Actual:** a rebuild test kept two sources on Windows: the code compared a
  resolved path with an unresolved one as strings, and Windows resolves the
  `RUNNER~1` short name. A second test imported python-docx, which only the Linux
  container had.
- **Root-cause class:** path identity by string; test dependencies taken from the
  machine instead of `requirements.txt`. Same class as round 2's JSON-escaped
  paths and case-insensitive disk.
- **Fix:** `_same_path` (samefile, else resolved and case-folded); the Word file is
  built with zipfile; the full suite re-run with python-docx blocked; a symlink test
  reproduces the path bug on Linux.
- **Invariant:** prove a gate can fail (on the platform it guards).

## Not verified

A real embedding model or reranker (none installed; every number is the hash
embedder), real documents instead of synthetic ones, the answer step with a
real model, Windows CI at the merged head, a real phone, live Cortex.

keywords: [round 3, RAG, random uploads, stress corpus, pandas truth, European decimals, currency, percent, banner row, semicolon csv, json records, dropped condition, multi-file, hijacked lookup, ingest speed, name channel, rare name, fusion weight, hash embedder, held-out seeds, self-tuning, Contextual Retrieval, Corrective RAG, Adaptive-RAG, merge regression, rank 1, gate floor]
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
- **Fix:** order the name channel by the other channels; vector weight 0.6, the
  lowest where no style loses rank-1 answers on seeds 1 and 4-7.
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

## Not verified

A real embedding model or reranker (none installed; every number is the hash
embedder), real documents instead of synthetic ones, the answer step with a
real model, Windows CI at the merged head, a real phone, live Cortex.

"""Multilingual retrieval + offline answer gate (live, not a retained artifact).

Runs tests/RAG/multilingual_bench.py at n=30 per language: eight languages, four
file types, one shared space, 20 look-alike names per language, hash embedder, no
model. Floors are the counts measured on the seeded set minus one (r@1/r@5/answer)
so a one-question wobble does not break the build while a real regression does.
Before the retrieval fixes: zh r@1 8/30, th name-only r@1 3/30, and Malay and
Spanish refused answerable questions 12-13 of 30.

READ THIS BEFORE CALLING IT GREEN.
- Unanswerable questions are REFUSED in every language, not only warned about: abstained
  is 10 of 10 in all eight (it was 0 of 10 in zh ja ko ar th, 5 in ru). The root cause of
  both the missing refusals and the false ones was one rule: a non-Latin word counted as
  present when half its characters were found anywhere in the evidence (see
  answer._token_in_blob). Chinese, Japanese and Thai are now judged on whole strings,
  Arabic names on the pair of words, and an English question put to a passage in another
  language is judged on the name only (the c_english column used to be refused 6 to 30
  times of 30 although retrieval had found the passage).
- Questions are put through answer.rescue_hits, as the app does: a name the space holds
  but retrieval missed is looked up before the answer is judged. r@1 and r@5 here include
  that lookup; plain retrieval is unchanged.
- Arabic is still the weakest on r@1 (12-13 of 30): whole-word names shared between
  customers are not told apart by the ranking.
- n=30 per language bounds nothing about real documents; templates are hand-written
  and were not reviewed by native speakers.
- Style c (English question) keeps the name in its own script. A pure English
  paraphrase of a non-English document is not tested: it needs the parked embedder (P13).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "RAG"))
sys.path.insert(0, str(ROOT))

import multilingual_bench as mb  # noqa: E402

# lang: ((a r@1, a r@5, a answer, a false-abstain max), (b ...same...), flagged min)
# flagged = unanswerable questions refused or warned about, of 10.
# Recall and answer floors are the measured count minus one; the false-abstain
# ceiling is the measured count PLUS one, for the same reason. A "false abstention"
# here is almost always a retrieval miss: the right passage is not in the top five,
# so the name truly is absent from the evidence and the answer says so. Which passage
# lands fifth differs between SQLite and numpy builds (Linux measured ja name-only at
# 3, the Windows runner at 4), so the ceiling moves with the recall floor beside it.
FLOORS = {
    "zh": ((20, 28, 24, 1), (22, 27, 25, 1), 10),
    "ja": ((19, 28, 24, 1), (20, 28, 26, 4), 10),
    "ko": ((19, 29, 29, 1), (29, 29, 29, 1), 10),
    "ar": ((12, 29, 24, 1), (12, 29, 29, 1), 10),   # r@1 weak: see docstring
    "th": ((19, 29, 27, 1), (24, 29, 26, 1), 10),
    "ru": ((29, 29, 29, 3), (29, 29, 29, 1), 10),
    "ms": ((29, 29, 29, 2), (29, 29, 29, 5), 10),
    "es": ((29, 29, 29, 1), (29, 29, 29, 2), 10),
}


@pytest.fixture(scope="module")
def board():
    return mb.run(n=30, seed=1)


def test_all_eight_languages_are_on_the_board(board):
    assert set(board["languages"]) == set(FLOORS)
    for code, row in board["languages"].items():
        assert not row["skipped"], f"{code}: {row['skipped']}"
        assert row["a_own"]["n"] == 30


@pytest.mark.parametrize("code", list(FLOORS))
def test_language_meets_its_floor(board, code):
    row = board["languages"][code]
    (a, b, abst) = FLOORS[code]
    for key, (r1, r5, ans, fa) in (("a_own", a), ("b_name", b)):
        s = row[key]
        assert s["recall_at_1"] >= r1, f"{code} {key} r@1 {s['recall_at_1']}/30 misses {s['misses']}"
        assert s["recall_at_5"] >= r5, f"{code} {key} r@5 {s['recall_at_5']}/30 misses {s['misses']}"
        assert s["answer_has_value"] >= ans, f"{code} {key} answer {s['answer_has_value']}/30"
        assert s["false_abstain"] <= fa, f"{code} {key} refused {s['false_abstain']} answerable questions"
        assert s["locator_ok"] == s["locator_n"], f"{code} {key} cites a wrong place"
    u = row["unanswerable"]
    flagged = u["abstained"] + u["warned"]
    assert flagged >= abst, f"{code} flagged {flagged}/{u['n']}, answered with no warning: {u['missed']}"
    assert u["abstained"] >= 9, f"{code} refused only {u['abstained']}/{u['n']} unanswerable questions: {u['missed']}"


def test_english_question_about_foreign_document_has_a_weak_floor(board):
    """Named weakness: the pure-English paraphrase is not tested (needs P13). Weak floor only."""
    for code, row in board["languages"].items():
        assert row["c_english"]["recall_at_5"] >= 20, code


def test_english_question_about_foreign_document_is_not_refused(board):
    """The passage is found (r@5) and its name is in the question: refusing it was the bug."""
    for code, row in board["languages"].items():
        assert row["c_english"]["false_abstain"] <= 2, (code, row["c_english"]["false_abstain"])


def test_board_states_its_limits(board):
    assert "honesty" in board and "native speaker" in board["honesty"]
    assert board["index_fingerprint"]
    assert "hi" in board["tokenizer_gaps"]
    assert "pdf_rtl" in board["ingest_gaps"]

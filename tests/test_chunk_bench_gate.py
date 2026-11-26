"""Chunking gate: pins what tests/RAG/chunk_bench.py measures now.

Floors, not certification. The documents are synthetic (a 640-row sheet with blank
cells, a three-page wrapped PDF, zh / ja / th / ar text), the embedder is the offline
hash one, and a fact counts as whole when one child chunk holds it verbatim. The old
character-count chunker's numbers are kept in the bench (BASELINE_OLD); the first
test fails if the new numbers are not better than those, so this cannot pass on a
fixture that was always easy.

Known limit, written down: Thai is 27 of 30 whole, because a Thai phrase can be
longer than the overlap and a fact whose first phrase is long loses its entity on a cut.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "RAG"))
sys.path.insert(0, str(ROOT))

import chunk_bench as cb  # noqa: E402


@pytest.fixture(scope="module")
def res():
    return cb.run(seed=1)


def test_beats_the_old_chunker_where_it_was_broken(res):
    d, old = res["documents"], cb.BASELINE_OLD
    assert d["sheet"]["facts_whole"] > old["sheet"]["facts_whole"]
    assert d["sheet"]["header_share"] > old["sheet"]["header_share"]
    assert d["pdf"]["facts_aimed_whole"] > old["pdf"]["facts_aimed_whole"]
    assert d["pdf"]["sentence_share"] > old["pdf"]["sentence_share"]
    for lang in ("zh", "ja"):
        assert d[lang]["tokens"]["max"] < old[lang]["max_tokens"] / 3


def test_every_row_chunk_carries_the_header_and_blank_cells_stay_put(res):
    sh = res["documents"]["sheet"]
    assert sh["header_share"] == 1.0
    assert sh["facts_whole"] == sh["facts"] == 30
    assert sh["facts_blank_cell_whole"] == sh["facts_blank_cell"] > 0


def test_pdf_facts_survive_including_those_on_the_old_cut(res):
    pdf = res["documents"]["pdf"]
    assert pdf["facts_aimed_at_old_cut"] >= 10
    assert pdf["facts_whole"] == 30
    assert pdf["facts_aimed_whole"] == pdf["facts_aimed_at_old_cut"]
    assert pdf["sentence_share"] >= 0.85  # 88% measured: an upper-case wrapped line is read as a new sentence


@pytest.mark.parametrize("lang,floor_facts,floor_sent", [("zh", 30, 0.95), ("ja", 30, 0.95), ("ar", 30, 0.95), ("th", 27, 0.9)])
def test_other_scripts(res, lang, floor_facts, floor_sent):
    d = res["documents"][lang]
    assert d["facts_whole"] >= floor_facts, d
    assert d["sentence_share"] >= floor_sent, d


def test_no_chunk_is_over_budget_in_any_script(res):
    for name, d in res["documents"].items():
        assert d["tokens"]["max"] <= 205, (name, d["tokens"])

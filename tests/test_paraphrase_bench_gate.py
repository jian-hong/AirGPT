"""Paraphrase gate: pins how well retrieval copes with questions in other words.

Runs tests/RAG/paraphrase_bench.py (64 planted facts in md, docx, pdf, xlsx, each
asked four ways) and pins the CURRENT measured counts as floors per style, so a
regression goes red.

READ THIS BEFORE CALLING IT GREEN. These floors record a weakness; they do not
certify the behaviour. Measured (of 64), first when this gate was added, then after
the hot-file bonus was resized and lowercase words got an exact-match channel:

    style        r@1  r@5      r@1  r@5
    verbatim      57   57  ->   64   64
    synonym       24   44  ->   26   45
    lower_typo    10   35  ->   40   49   (xlsx still 0 of 16 at rank 1)
    property       5   17  ->    5   17

Two floors are DELIBERATELY WEAK and named as such: SYNONYM and PROPERTY. A product that answers 17 of 64 "identify it by another fact" questions is
not demo-ready; the floor only stops it getting worse. Raise a floor when rag/
improves, never lower one to make a change pass. The bench measures, it does not
tune rag/: counts are on a small synthetic set and say nothing about real files.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "RAG"))
sys.path.insert(0, str(ROOT))

import paraphrase_bench as pb  # noqa: E402

# (floor r@1, floor r@5), exact counts out of 64. Deterministic: hash embedder, seeded.
FLOORS = {
    "verbatim": (64, 64),    # control
    # Raised in round 3 by the name channel (a rare name gets its own vote, its chunks
    # ordered by the other channels) and the vector channel at 0.6 under the hash
    # embedder (tests/test_dense_weight.py). No r@1 floor was lowered.
    "synonym": (43, 64),     # was (26, 45)
    # Raised in round 3b: the file boost no longer lifts every chunk of a favoured file over
    # the answer (lower_typo 40/53 -> 56/64), and the bridge hop (retrieve.bridge_hops)
    # reads the name the first passage holds next to the question's value and searches
    # again for it (property 5/22 -> 64/64). Seeds 4-7, held out, give property 64/64 too.
    "lower_typo": (56, 64),  # was (40, 53)
    "property": (64, 64),    # was (5, 22)
}


@pytest.fixture(scope="module")
def result():
    return pb.run(seed=1)


def test_bench_covers_64_facts_in_four_styles(result):
    assert result["n_facts"] >= 60 and result["n_questions"] == result["n_facts"] * 4
    for style in pb.STYLES:
        assert result["styles"][style]["n"] == result["n_facts"], style
    assert result["index_fingerprint"] and "honesty" in result


@pytest.mark.parametrize("style", pb.STYLES)
def test_style_does_not_regress_below_recorded_floor(result, style):
    cell = result["styles"][style]
    f1, f5 = FLOORS[style]
    assert cell["recall_at_5"] >= f5, f"{style}: r@5 {cell['recall_at_5']}/{cell['n']} < floor {f5}; {result['sample_misses'][style]}"
    assert cell["recall_at_1"] >= f1, f"{style}: r@1 {cell['recall_at_1']}/{cell['n']} < floor {f1}"


def test_questions_really_are_the_style_they_claim():
    """A bench that silently asks verbatim questions would pass every floor above."""
    plan = pb.build_plan(1)
    seen = {s: 0 for s in pb.STYLES}
    for _, (_, qs) in plan.items():
        for item in qs:
            seen[item["style"]] += 1
            q, f = item["q"], item["f"]
            if item["style"] == "verbatim":
                assert f.entity in q and f.attr in q
            elif item["style"] == "synonym":
                assert f.entity in q and f.attr not in q.lower(), q
            elif item["style"] == "lower_typo":
                assert f.entity not in q and f.entity.lower() not in q, q
            elif item["style"] == "property":
                assert f.entity not in q and f.entity.lower() not in q, q
    assert set(seen.values()) == {64}


def test_property_is_stated_in_a_different_section_than_the_fact():
    plan = pb.build_plan(1)
    for _, (facts, _) in plan.items():
        mains = {f.entity: f for f in facts if f.attr != pb.PROP_ATTR}
        for p in (f for f in facts if f.attr == pb.PROP_ATTR):
            assert p.group != mains[p.entity].group, p.entity

"""Round-2 RAG gaps: the not-calculated note, group-by carry-over, user-worded web goals,
and a chat summary that never ends inside a citation mark. Expected figures come from
pandas, never from the code under test."""
from __future__ import annotations

import pandas as pd
import pytest

from rag import answer, sheet_sql, store

ROWS = [
    {"Region": ["North", "South", "East"][i % 3], "Product": ["Widget", "Gadget", "Gizmo"][(i // 3) % 3],
     "Amount": 10 + (i * 37) % 211}
    for i in range(60)
]
DF = pd.DataFrame(ROWS)
FRAMES = {("shop.csv", "shop"): DF}


def _groups(hit):
    return {g["group"]: g["value"] for g in hit["groups"]}


def test_group_by_answer_carries_and_followup_repeats_it_for_south():
    first = sheet_sql.answer_filter_aggregate("total Amount by Product where Region is North", FRAMES)
    assert first["carry"]["group_by"] == "Product"
    q2 = sheet_sql.carry_followup("and for South?", first["carry"], FRAMES)
    assert q2 and "by Product" in q2
    hit = sheet_sql.answer_filter_aggregate(q2, FRAMES)
    want = DF[DF.Region == "South"].groupby("Product").Amount.sum().to_dict()
    assert _groups(hit) == pytest.approx(want)
    # and the next change keeps the grouping too
    q3 = sheet_sql.carry_followup("and the average?", hit["carry"], FRAMES)
    hit3 = sheet_sql.answer_filter_aggregate(q3, FRAMES)
    assert _groups(hit3) == pytest.approx(DF[DF.Region == "South"].groupby("Product").Amount.mean().round(4).to_dict())


def test_plain_aggregate_carry_has_no_group():
    first = sheet_sql.answer_filter_aggregate("total Amount where Region is North", FRAMES)
    q2 = sheet_sql.carry_followup("and for South?", first["carry"], FRAMES)
    assert q2 and " by " not in q2


def _fake(events):
    def gen(*a, **k):
        yield from events

    return gen


RETRIEVAL = [
    {"type": "meta", "lane": "retrieval"},
    {"type": "delta", "text": "Part one. "},
    {"type": "delta", "text": "Part two."},
    {"type": "done", "answer": "Part one. Part two.", "lane": "retrieval", "provenance": {}},
]
CALC_HISTORY = [
    {"role": "user", "content": "total Amount where Region is North"},
    {"role": "assistant", "content": "x", "provenance": {"carry": {"agg": "SUM", "metric": "Amount"}}},
]
PASSAGE_HISTORY = [
    {"role": "user", "content": "what is in the notes"},
    {"role": "assistant", "content": "x", "provenance": {}},
]


def _run(monkeypatch, q, history, events=RETRIEVAL):
    monkeypatch.setattr(answer, "_answer_events", _fake(events))
    return list(answer.answer_events(1, q, history=history))


def test_uncarried_followup_says_it_was_not_calculated(monkeypatch):
    evs = _run(monkeypatch, "and the Discount column?", CALC_HISTORY)
    live = "".join(e["text"] for e in evs if e["type"] == "delta")
    done = next(e for e in evs if e["type"] == "done")
    assert live.startswith(answer.FOLLOWUP_NOT_CALCULATED)
    assert done["answer"].startswith(answer.FOLLOWUP_NOT_CALCULATED)
    assert done["answer"].endswith("Part one. Part two.")
    assert done["provenance"]["followup_not_calculated"] is True


def test_note_is_not_added_to_ordinary_questions(monkeypatch):
    for q, hist in [
        ("and the Discount column?", []),  # fresh chat
        ("and the Discount column?", PASSAGE_HISTORY),  # after a passage answer
        ("Please write a long summary of everything the handbook says about leave, pay and conduct today", CALC_HISTORY),
    ]:
        evs = _run(monkeypatch, q, hist)
        done = next(e for e in evs if e["type"] == "done")
        assert done["answer"] == "Part one. Part two."
        assert "followup_not_calculated" not in done["provenance"]
        assert "".join(e["text"] for e in evs if e["type"] == "delta") == "Part one. Part two."


def test_note_not_added_when_the_followup_was_calculated(monkeypatch):
    sql = [
        {"type": "meta", "lane": "sql"},
        {"type": "delta", "text": "33519"},
        {"type": "done", "answer": "33519", "lane": "sql", "provenance": {"carry": {"agg": "SUM"}}},
    ]
    evs = _run(monkeypatch, "and for South?", CALC_HISTORY, sql)
    assert next(e for e in evs if e["type"] == "done")["answer"] == "33519"


def test_web_goals_use_the_users_own_words():
    assert answer.split_web_goals("search the web for how cognition works in dogs") == ["how cognition works in dogs"]
    assert answer.split_web_goals("web search JEPA training code on github") == ["JEPA training code on github"]
    goals = answer.split_web_goals("search the web for normal distribution tutorial")
    assert goals == ["normal distribution tutorial"]


def test_no_hardcoded_demo_goals_remain():
    import inspect

    src = inspect.getsource(answer.split_web_goals) + inspect.getsource(answer._goal_ok)
    for word in ("OpenStax", "LeCun", "Jian Hong", "entity_goals"):
        assert word not in src


def test_summary_never_ends_in_half_a_citation_mark():
    text = "x" * 218 + " [1] more"
    assert store._cut_summary(text) == "x" * 218  # noqa: SLF001
    assert store._cut_summary("y" * 217 + " [12, 3] tail") == "y" * 217  # noqa: SLF001
    assert store._cut_summary("short [1]") == "short [1]"  # noqa: SLF001
    assert store._cut_summary("z" * 300) == "z" * 220  # noqa: SLF001

"""Spreadsheet answers that must be right or say they could not be: negation, several
sheets named in one ask, and follow-ups. Every expected figure is computed here in plain
Python from the same rows, never by calling the code under test."""
from __future__ import annotations

import pandas as pd
import pytest

from rag import sheet_sql

DEPTS = ["Eng", "Ops", "HR", "Research and Development"]
STAFF = [
    {"Name": f"P{i}", "Dept": DEPTS[i % 4], "Salary": 1000 + i * 37 + (i % 5) * 11}
    for i in range(25)
]
PRODUCTS = ["Widget", "Gadget", "Gizmo"]
STATUS = ["Paid", "Open"]


def _sales(region, n):
    return [
        {
            "Product": PRODUCTS[i % 3], "Region": region, "Status": STATUS[(i // 3) % 2],
            "Units": 1 + (i * 7) % 11,
            "Revenue": round(100 + (i * 37.31) % 411 + (3 if region == "South" else 0), 2),
        }
        for i in range(n)
    ]


NORTH, SOUTH = _sales("North", 40), _sales("South", 30)


@pytest.fixture()
def frames():
    return {
        ("staff.csv", "staff"): pd.DataFrame(STAFF),
        ("sales.xlsx", "North"): pd.DataFrame(NORTH),
        ("sales.xlsx", "South"): pd.DataFrame(SOUTH),
    }


def total(rows, col, pred):
    return sum(r[col] for r in rows if pred(r))


def fmt(x):
    return sheet_sql._round(round(x, 4))  # noqa: SLF001


def ask(frames, q):
    return sheet_sql.answer_filter_aggregate(q, frames)


@pytest.mark.parametrize("q", [
    "total salary excluding HR",
    "total salary except HR",
    "total salary without HR",
    "total salary not HR",
    "total salary other than HR",
    "total salary where Dept is not HR",
])
def test_negation_is_the_complement(frames, q):
    want = total(STAFF, "Salary", lambda r: r["Dept"] != "HR")
    hit = ask(frames, q)
    assert hit and not hit.get("abstained"), hit
    assert hit["value"] == pytest.approx(want)
    assert fmt(want) in hit["answer"]
    assert "NOT" in hit["sql"].upper() or "<>" in hit["sql"]
    hr = fmt(total(STAFF, "Salary", lambda r: r["Dept"] == "HR"))
    assert hr not in hit["answer"].split("SQL:")[0]


def test_negation_two_values(frames):
    hit = ask(frames, "total salary excluding HR and Ops")
    want = total(STAFF, "Salary", lambda r: r["Dept"] not in ("HR", "Ops"))
    assert hit["value"] == pytest.approx(want)
    assert "NOT IN" in hit["sql"]


def test_negation_second_sheet_filter(frames):
    hit = ask(frames, "total revenue in the South sheet where Product is not Widget")
    want = total(SOUTH, "Revenue", lambda r: r["Product"] != "Widget")
    assert hit["value"] == pytest.approx(want)
    assert "Product IN" not in hit["sql"]


def test_negation_combines_with_positive_filter(frames):
    hit = ask(frames, "total revenue in the South sheet for Paid excluding Widget")
    want = total(SOUTH, "Revenue", lambda r: r["Status"] == "Paid" and r["Product"] != "Widget")
    assert hit["value"] == pytest.approx(want)


def test_negation_unknown_value_abstains_in_plain_words(frames):
    hit = ask(frames, "total salary excluding Hrr")
    assert hit and hit["abstained"] is True
    assert 'could not apply "excluding Hrr"' in hit["answer"]
    assert "no such value in Dept" in hit["answer"]
    assert hit.get("value") is None


def test_excluding_a_column_is_refused_not_dropped(frames):
    hit = ask(frames, "total salary excluding Dept")
    assert hit["abstained"] is True
    assert "Dept is a column, not a value" in hit["answer"]


def test_ordinary_not_and_without_words_do_not_block(frames):
    # a comparison, a number and a different sentence are not value exclusions
    cut = sorted(r["Salary"] for r in STAFF)[10]
    hit = ask(frames, f"total salary where Salary is not below {cut}")
    assert hit and not hit.get("abstained"), hit
    # "not below" is the other side of "below", never "below" itself
    assert hit["value"] == pytest.approx(total(STAFF, "Salary", lambda r: r["Salary"] >= cut))
    hit = ask(frames, f"total salary where Salary is not above {cut}")
    assert hit["value"] == pytest.approx(total(STAFF, "Salary", lambda r: r["Salary"] <= cut))
    hit = ask(frames, f"total salary where Salary is not equal to {cut}")
    assert hit["value"] == pytest.approx(total(STAFF, "Salary", lambda r: r["Salary"] != cut))
    hit = ask(frames, "total salary for Eng")
    assert hit["value"] == pytest.approx(total(STAFF, "Salary", lambda r: r["Dept"] == "Eng"))


def test_positive_questions_unchanged(frames):
    hit = ask(frames, "total salary for HR")
    assert hit["value"] == pytest.approx(total(STAFF, "Salary", lambda r: r["Dept"] == "HR"))
    hit = ask(frames, "total salary for Research and Development")
    want = total(STAFF, "Salary", lambda r: r["Dept"] == "Research and Development")
    assert hit["value"] == pytest.approx(want)
    assert "Research and Development" in hit["sql"]


def test_negated_real_value_with_and(frames):
    hit = ask(frames, "total salary excluding Research and Development")
    want = total(STAFF, "Salary", lambda r: r["Dept"] != "Research and Development")
    assert hit["value"] == pytest.approx(want)


def test_two_sheets_named_with_filter(frames):
    hit = ask(frames, "total revenue for Widget in North and South")
    n = total(NORTH, "Revenue", lambda r: r["Product"] == "Widget")
    s = total(SOUTH, "Revenue", lambda r: r["Product"] == "Widget")
    assert not hit.get("abstained")
    a = hit["answer"]
    assert fmt(n) in a and fmt(s) in a and fmt(n + s) in a
    assert hit["value"] == pytest.approx(n + s)


def test_two_sheets_named_across(frames):
    hit = ask(frames, "total revenue for Widget across North and South")
    n = total(NORTH, "Revenue", lambda r: r["Product"] == "Widget")
    s = total(SOUTH, "Revenue", lambda r: r["Product"] == "Widget")
    assert hit["value"] == pytest.approx(n + s)


def test_one_sheet_named_still_one_sheet(frames):
    hit = ask(frames, "total revenue for Widget in North")
    assert hit["value"] == pytest.approx(total(NORTH, "Revenue", lambda r: r["Product"] == "Widget"))


def test_group_values_are_rounded(frames):
    hit = ask(frames, "total revenue by product across both sheets")
    for g in hit["groups"]:
        assert g["value"] == round(g["value"], 4)


def test_group_values_have_no_float_noise():
    rows = [{"Product": "A", "Revenue": 0.1}, {"Product": "A", "Revenue": 0.2},
            {"Product": "B", "Revenue": 1.1}, {"Product": "B", "Revenue": 2.2}]
    assert 0.1 + 0.2 != 0.3  # the noise this test is about
    hit = ask({("t.csv", "t"): pd.DataFrame(rows)}, "total Revenue by Product")
    for g in hit["groups"]:
        want = round(sum(r["Revenue"] for r in rows if r["Product"] == g["group"]), 4)
        assert g["value"] == want
        assert len(repr(g["value"])) <= 10, g["value"]

"""An aggregate ask that names no column must not hand the model a slice of rows.

Expected figures are computed here from the same rows that are written to the file.
"""
from __future__ import annotations

import pytest

ROWS = [(f"ORD-{i}", "North" if i % 2 else "South", i * 10, i % 5) for i in range(1, 38)]


@pytest.fixture()
def lane(tmp_path, monkeypatch):
    from rag import answer, reveal

    p = tmp_path / "orders.csv"
    p.write_text("Order,Region,Amount,Qty\n" + "\n".join(",".join(map(str, r)) for r in ROWS) + "\n")
    monkeypatch.setattr(answer.store, "list_sources", lambda sid: [{"path": str(p), "title": "orders.csv"}])
    monkeypatch.setattr(reveal, "resolve_source_path", lambda src: (str(p), "path"))
    return lambda q: answer._try_hybrid_sql_lane(1, q)


@pytest.mark.parametrize("q", ["What is the total?", "what's the average", "What is the sum?", "highest?"])
def test_column_less_aggregate_asks_which_column(lane, q):
    hit = lane(q)
    assert hit is not None, "the ask used to fall through to retrieval and a row slice"
    assert hit["provenance"]["abstained"] is True
    assert hit["provenance"]["rows_total"] == len(ROWS)
    # Both numeric columns are listed, the text ones are not, and nothing was calculated.
    assert "Amount" in hit["answer"] and "Qty" in hit["answer"]
    assert "Region" not in hit["answer"].split("hold numbers")[-1].split("Ask again")[0]
    assert "I have not calculated anything" in hit["answer"]
    assert str(sum(r[2] for r in ROWS)) not in hit["answer"]


def test_row_count_is_computed_over_every_row_and_says_so(lane):
    hit = lane("how many rows")
    prov = hit["provenance"]
    assert prov["operation"] == "COUNT" and prov["value"] == len(ROWS)
    assert prov["rows_matched"] == prov["rows_total"] == len(ROWS)
    assert prov["abstained"] is False and prov["assumed"]
    assert f"{len(ROWS)} rows" in hit["answer"]


@pytest.mark.parametrize(
    "q",
    ["What is the total Amount for North?", "who wrote the handbook", "what is the total revenue policy", "average rows per page of the handbook"],
)
def test_asks_that_name_something_are_left_alone(lane, q):
    hit = lane(q)
    # either computed from named columns, or not a table question at all
    assert hit is None or "Which column do you mean" not in hit["answer"]


def test_row_count_over_several_sheets_reports_all_of_them(tmp_path, monkeypatch):
    """The headline said "406 ... from Q1, 3 of 3 rows": the figure was the sum, the rest was sheet 1."""
    from rag import answer, reveal

    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("Order,Amount\n" + "\n".join(f"{i},{i}" for i in range(1, 6)) + "\n")
    b.write_text("Order,Amount\n" + "\n".join(f"{i},{i}" for i in range(1, 9)) + "\n")
    srcs = [{"path": str(a), "title": "a.csv"}, {"path": str(b), "title": "b.csv"}]
    monkeypatch.setattr(answer.store, "list_sources", lambda sid: srcs)
    monkeypatch.setattr(reveal, "resolve_source_path", lambda src: (src["path"], "path"))
    hit = answer._try_hybrid_sql_lane(1, "how many rows")
    prov = hit["provenance"]
    assert prov["value"] == 13
    # the totals shown beside the 13 are over every table, not the first one
    assert prov["rows_matched"] == prov["rows_total"] == 13
    assert "a.csv" in prov["workbook"] and "b.csv" in prov["workbook"]
    # SQL in the answer text is code, so a Markdown renderer cannot eat the asterisks
    assert "`SELECT COUNT(*)" in hit["answer"]
    # and when it has to ask which column, it does not call the first sheet's size "the sheet"
    ask = answer._try_hybrid_sql_lane(1, "what is the total?")["provenance"]
    assert ask["abstained"] is True and "rows_total" not in ask

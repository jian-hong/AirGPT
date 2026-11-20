"""Numbers computed from spreadsheets must be right, complete and say where they came from.

Every expected figure below is computed here in plain Python from the same rows that
are written into the file, never by calling the code under test.
"""
from __future__ import annotations

import re
from pathlib import Path

import openpyxl
import pytest

from rag import sheet_sql
from rag.xlsx_sql import answer_sqlish, load_table_file

# (region, product, revenue as typed in the cell, units). Includes a duplicate row,
# a text number with a thousands comma, a negative, a blank, spaces and odd casing.
Q1 = [
    ("North", "Widget", 1000, 1),
    ("North", "Widget", 1000, 1),  # exact duplicate row: both count
    ("north ", "Gadget", "200", 2),  # text number, lower case, trailing space
    ("South", "Widget", "1,500", 3),  # thousands comma
    ("East", "Widget", -100, 4),  # negative
    ("North", "Gadget", None, 5),  # blank revenue
    ("West", "Gadget", 40.5, 6),
]
Q2 = [
    ("North", "Widget", 1300, 7),
    ("South", "Gadget", 950, 8),
    ("East", "Widget", 3500, 9),
]


def _val(v):
    if v is None:
        return None
    return float(str(v).replace(",", ""))


def truth(rows, *, region=None, product=None):
    got = [
        _val(r[2])
        for r in rows
        if (region is None or r[0].strip().lower() == region.lower())
        and (product is None or r[1].strip().lower() == product.lower())
        and _val(r[2]) is not None
    ]
    return got


def fmt(x):
    return str(int(x)) if float(x).is_integer() else f"{x:,.4f}".rstrip("0").rstrip(".")


@pytest.fixture()
def frames(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Q1"
    ws.append(["Region", "Product", "Revenue", "Units"])
    for r in Q1:
        ws.append(list(r))
    w2 = wb.create_sheet("Q2")
    w2.append(["Region", "Product", "Revenue", "Units"])
    for r in Q2:
        w2.append(list(r))
    p = tmp_path / "sales.xlsx"
    wb.save(p)
    out = {}
    for k, df in load_table_file(p).items():
        out[("sales.xlsx", k)] = df
    return out


def numbers(text):
    return {m.replace(",", "") for m in re.findall(r"-?\d[\d,]*\.?\d*", text)}


def test_two_sheets_total_is_per_sheet_and_combined(frames):
    hit = sheet_sql.answer_filter_aggregate("What is the total Revenue for North?", frames)
    q1 = sum(truth(Q1, region="North"))
    q2 = sum(truth(Q2, region="North"))
    assert q1 == 2200 and q2 == 1300
    assert hit["value"] == q1 + q2
    by_sheet = {s["sheet"]: s for s in hit["sheets"]}
    assert by_sheet["Q1"]["value"] == q1 and by_sheet["Q2"]["value"] == q2
    assert "Q1" in hit["answer"] and "Q2" in hit["answer"] and fmt(q1 + q2) in hit["answer"]
    # rows used and sheet size are stated, per sheet and in structured form
    assert by_sheet["Q1"]["rows_matched"] == 4 and by_sheet["Q1"]["rows_total"] == len(Q1)
    assert by_sheet["Q2"]["rows_matched"] == 1 and by_sheet["Q2"]["rows_total"] == len(Q2)
    assert hit["operation"] == "SUM" and "Region is North" in hit["filter"]
    # the blank revenue cell is reported, not silently dropped
    assert "blank" in hit["answer"]


@pytest.mark.parametrize(
    "ask,kw",
    [
        ("sum of Revenue where Product is Widget", {"product": "Widget"}),
        ("total revenue for Gadget", {"product": "gadget"}),
        ("total revenue", {}),
    ],
)
def test_total_over_every_row_of_every_sheet(frames, ask, kw):
    hit = sheet_sql.answer_filter_aggregate(ask, frames)
    want = sum(truth(Q1, **kw)) + sum(truth(Q2, **kw))
    assert hit["value"] == pytest.approx(want)
    assert fmt(want) in hit["answer"]
    assert hit["rows_total"] == len(Q1) + len(Q2)


def test_average_pools_values_not_sheet_averages(frames):
    hit = sheet_sql.answer_filter_aggregate("average Revenue for Widget", frames)
    vals = truth(Q1, product="Widget") + truth(Q2, product="Widget")
    assert hit["value"] == pytest.approx(sum(vals) / len(vals))
    per = [truth(Q1, product="Widget"), truth(Q2, product="Widget")]
    # the naive mean of the two sheet averages is a different (wrong) number
    assert sum(sum(p) / len(p) for p in per) / 2 != pytest.approx(hit["value"])


@pytest.mark.parametrize(
    "ask,fn",
    [("maximum Revenue", max), ("lowest Revenue", min)],
)
def test_max_min(frames, ask, fn):
    hit = sheet_sql.answer_filter_aggregate(ask, frames)
    assert hit["value"] == fn(truth(Q1) + truth(Q2))


def test_count_and_numeric_filter(frames):
    hit = sheet_sql.answer_filter_aggregate("how many rows where Units > 5", frames)
    want = sum(1 for r in Q1 + Q2 if r[3] > 5)
    assert hit["value"] == want
    hit = sheet_sql.answer_filter_aggregate("sum of Revenue where Units <= 3", frames)
    assert hit["value"] == sum(_val(r[2]) for r in Q1 + Q2 if r[3] <= 3 and _val(r[2]) is not None)


def test_group_by_and_ranking(frames):
    allrows = Q1 + Q2
    tot = {}
    for r in allrows:
        v = _val(r[2])
        if v is not None:
            tot[r[0].strip().lower()] = tot.get(r[0].strip().lower(), 0) + v
    top = max(tot, key=tot.get)
    # the single biggest row is East (3500); the biggest total is North
    assert top == "north"
    hit = sheet_sql.answer_filter_aggregate("which region has the highest total revenue", frames)
    assert hit["answer"].startswith("North has the highest")
    assert hit["value"] == tot["north"]
    got = {g["group"].strip().lower(): g["value"] for g in hit["groups"]}
    assert got == pytest.approx(tot)
    assert hit["rows_matched"] == len(allrows)
    hit = sheet_sql.answer_filter_aggregate("revenue by region", frames)
    got = {g["group"].strip().lower(): g["value"] for g in hit["groups"]}
    assert got == pytest.approx(tot)
    assert "assumed" in hit["answer"].lower() or hit["assumed"] is not None


def test_ranking_without_total_word_says_what_it_assumed(frames):
    hit = sheet_sql.answer_filter_aggregate("which region has the highest revenue", frames)
    assert hit["answer"].startswith("North has the highest")
    assert hit["assumed"] and "assumed" in hit["answer"].lower()


def test_catalogue_no_longer_returns_first_row_or_biggest_row(frames):
    sheets = {k[1]: v for k, v in frames.items()}
    # these used to answer "1000" (first matching row) and "East" (biggest single row)
    assert answer_sqlish(sheets, "what is the total Revenue for North") is None
    assert answer_sqlish(sheets, "which region has the highest total revenue") is None


def test_text_filter_is_case_and_space_insensitive(frames):
    hit = sheet_sql.answer_filter_aggregate("total revenue where region = NORTH and product is gadget", frames)
    assert hit["value"] == sum(truth(Q1, region="north", product="gadget")) + sum(
        truth(Q2, region="north", product="gadget")
    )


def test_csv_matches_xlsx(tmp_path):
    rows = [("ORD-1", "North", "1,200"), ("ORD-2", "South", "300"), ("ORD-3", "north", "(50)"), ("ORD-4", "East", "")]
    p = tmp_path / "o.csv"
    p.write_text("Order,Region,Amount\n" + "\n".join(",".join(f'"{c}"' for c in r) for r in rows) + "\n")
    fr = {("o.csv", k): v for k, v in load_table_file(p).items()}
    nums = [1200.0, 300.0, -50.0]
    assert sheet_sql.answer_filter_aggregate("What is the total Amount?", fr)["value"] == sum(nums)
    assert sheet_sql.answer_filter_aggregate("average Amount", fr)["value"] == pytest.approx(sum(nums) / 3)
    assert sheet_sql.answer_filter_aggregate("What is the total Amount for North?", fr)["value"] == 1150
    hit = sheet_sql.answer_filter_aggregate("How many orders are there?", fr)
    assert hit["value"] == 4 and "o.csv" in hit["answer"]
    # tab separated reads the same way
    t = tmp_path / "o.tsv"
    t.write_text("Order\tRegion\tAmount\n" + "\n".join("\t".join(r) for r in rows) + "\n")
    fr2 = {("o.tsv", k): v for k, v in load_table_file(t).items()}
    assert sheet_sql.answer_filter_aggregate("total Amount", fr2)["value"] == sum(nums)


def test_ambiguous_value_asks_instead_of_guessing(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("Ship,Bill,Amount\nNorth,South,10\nSouth,North,20\n")
    fr = {("a.csv", k): v for k, v in load_table_file(p).items()}
    hit = sheet_sql.answer_filter_aggregate("total Amount for North", fr)
    assert hit["abstained"] and "Ship" in hit["answer"] and "Bill" in hit["answer"]


def test_sheet_missing_the_word_is_not_given_the_unfiltered_total(tmp_path):
    wb = openpyxl.Workbook()
    a = wb.active
    a.title = "A"
    a.append(["Region", "Revenue"])
    a.append(["North", 5])
    b = wb.create_sheet("B")
    b.append(["Region", "Revenue"])
    b.append(["South", 7])
    p = tmp_path / "w.xlsx"
    wb.save(p)
    fr = {("w.xlsx", k): v for k, v in load_table_file(p).items()}
    hit = sheet_sql.answer_filter_aggregate("total Revenue for North", fr)
    assert hit["value"] == 5
    assert "no rows match" in hit["answer"]


def test_unreachable_ask_names_the_gap_instead_of_a_sample(frames):
    miss = sheet_sql.explain_no_plan("what is the total Product", frames)
    assert miss and miss["abstained"]
    assert "did not" in miss["answer"] and str(len(Q1)) in miss["answer"]
    assert sheet_sql.explain_no_plan("who wrote the handbook", frames) is None


def test_lane_reads_csv_and_names_rows(tmp_path, monkeypatch):
    from rag import answer, reveal

    p = tmp_path / "orders.csv"
    p.write_text("Order,Region,Amount\n" + "\n".join(f"ORD-{i},{'North' if i % 2 else 'South'},{i}" for i in range(1, 11)) + "\n")
    monkeypatch.setattr(answer.store, "list_sources", lambda sid: [{"path": str(p), "title": "orders.csv"}])
    monkeypatch.setattr(reveal, "resolve_source_path", lambda src: (str(p), "path"))
    hit = answer._try_hybrid_sql_lane(1, "What is the total Amount for North?")
    assert hit and "25" in hit["answer"] and "5 of 10 rows" in hit["answer"]
    prov = hit["provenance"]
    assert prov["rows_matched"] == 5 and prov["rows_total"] == 10 and prov["operation"] == "SUM"
    assert "orders.csv" in prov["workbook"]
    miss = answer._try_hybrid_sql_lane(1, "what is the total order")
    # not computable: the user is told, no sample is handed to a model
    assert miss and miss["provenance"]["abstained"]


def _orders(tmp_path):
    rows = [(f"O{i:04d}", ["North", "South", "East"][i % 3], (i * 37) % 500) for i in range(60)]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Orders"
    ws.append(["Order", "Region", "Amount"])
    for r in rows:
        ws.append(list(r))
    wb.save(tmp_path / "orders.xlsx")
    (tmp_path / "orders.csv").write_text("Order,Region,Amount\n" + "\n".join(",".join(map(str, r)) for r in rows) + "\n")
    return rows


def test_same_table_as_xlsx_and_csv_is_counted_once(tmp_path):
    rows = _orders(tmp_path)
    fr = {}
    for f in ("orders.xlsx", "orders.csv"):
        for k, df in load_table_file(tmp_path / f).items():
            fr[(f, k)] = df
    hit = sheet_sql.answer_filter_aggregate("What is the total Amount for North?", fr)
    want = sum(r[2] for r in rows if r[1] == "North")
    assert hit["value"] == want and len(hit["sheets"]) == 2
    assert all(s["value"] == want for s in hit["sheets"])
    assert "counted once" in hit["answer"]
    hit = sheet_sql.answer_filter_aggregate("How many orders are there?", fr)
    assert hit["value"] == len(rows)  # a sheet called Orders and a column called Order


def test_catalogue_does_not_name_the_biggest_order_id_for_which_region(tmp_path):
    _orders(tmp_path)
    sheets = load_table_file(tmp_path / "orders.xlsx")
    assert answer_sqlish(sheets, "which region has the highest total revenue") is None


def test_count_by_value_without_naming_a_column(tmp_path):
    p = tmp_path / "people.csv"
    p.write_text("name,dept,salary\nAna,Eng,5000\nBen,Eng,6000\nCho,Ops,4000\nDev,Ops,4500\n")
    fr = {("people.csv", k): v for k, v in load_table_file(p).items()}
    assert sheet_sql.answer_filter_aggregate("how many people work in Ops", fr)["value"] == 2
    hit = sheet_sql.answer_filter_aggregate("total salary by dept", fr)
    assert {g["group"]: g["value"] for g in hit["groups"]} == {"Eng": 11000, "Ops": 8500}


def _plain(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("Id,Region,Product,Revenue\n1,North,A,10\n2,East,B,500\n3,North,A,20\n4,South,B,30\n")
    return {("t.csv", k): v for k, v in load_table_file(p).items()}, p


@pytest.mark.parametrize("ask", [
    "total Revenue where Region is Papua",
    "sum of Revenue where Region = 'nowhere'",
])
def test_stated_filter_value_not_in_data_is_not_dropped(tmp_path, ask):
    fr, _ = _plain(tmp_path)
    hit = sheet_sql.answer_filter_aggregate(ask, fr)
    # the unfiltered total is 560; a filter nobody matches must never produce it
    assert hit is not None and "560" not in hit["answer"]
    assert "no rows match" in hit["answer"].lower()


def test_stated_short_value_and_non_latin_column_are_filters(tmp_path):
    p = tmp_path / "u.csv"
    p.write_text("Wilayah,Jualan,产品,数量\nUtara,100,A,1\nSelatan,200,B,2\nUtara,300,A,3\nTimur,400,B,4\n", encoding="utf-8")
    fr = {("u.csv", k): v for k, v in load_table_file(p).items()}
    assert sheet_sql.answer_filter_aggregate("sum of 数量 where 产品 is A", fr)["value"] == 1 + 3
    assert sheet_sql.answer_filter_aggregate("sum of Jualan where 产品 = B", fr)["value"] == 200 + 400


def test_catalogue_does_not_answer_which_product_with_an_id(tmp_path):
    fr, p = _plain(tmp_path)
    sheets = load_table_file(p)
    for ask in ("which product has the highest revenue", "highest revenue by region"):
        assert answer_sqlish(sheets, ask) is None
    hit = sheet_sql.answer_filter_aggregate("which product has the highest revenue", fr)
    assert hit["answer"].startswith("B ")  # B = 500 + 30 beats A = 10 + 20

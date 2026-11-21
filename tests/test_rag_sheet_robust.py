"""Round 3, robust spreadsheet maths: a figure the founder reads must be right, or the
app must say plainly what it could not work out. Each class below failed on the base
commit. Every expected figure is computed here in plain Python from the same rows."""
from __future__ import annotations

import csv
import re

import pandas as pd
import pytest

from rag import sheet_sql
from rag.xlsx_sql import load_table_file


def _ask(q, frames):
    return sheet_sql.answer_filter_aggregate(q, frames)


def _text(hit):
    return str((hit or {}).get("answer") or "")


def _head(hit):
    return _text(hit).replace(",", "").split(" - ")[0].split("\n")[0]


def _invoices():
    rows = []
    regions = ["North", "South", "East", "West"]
    for i in range(60):
        rows.append({
            "invoice": f"INV-{1000 + i}",
            "region": regions[i % 4],
            "amount": str(100 + i * 7),
            "paid": ["yes", "no", ""][i % 3],
            "issued": f"2024-{1 + (i % 12):02d}-{1 + (i % 27):02d}",
        })
    return rows


@pytest.fixture()
def inv():
    rows = _invoices()
    return rows, {("inv.csv", "inv"): pd.DataFrame(rows).astype(str)}


# ---- R-01: a condition that is not understood is never dropped silently -------------

def test_paid_yes_is_a_filter_not_noise(inv):
    rows, fr = inv
    want = sum(1 for r in rows if r["paid"] == "yes")
    got = _head(_ask("How many invoices are paid yes?", fr))
    assert re.match(rf"\s*{want}\b", got), got


def test_paid_no_is_a_filter(inv):
    rows, fr = inv
    want = sum(1 for r in rows if r["paid"] == "no")
    got = _head(_ask("How many invoices have paid no?", fr))
    assert re.match(rf"\s*{want}\b", got), got


def test_date_condition_is_applied_or_declined_never_dropped(inv):
    rows, fr = inv
    want = sum(1 for r in rows if r["issued"] > "2024-09-01")
    hit = _ask("How many invoices were issued after 2024-09-01?", fr)
    got = _head(hit)
    if hit and not hit.get("abstained"):
        assert re.match(rf"\s*{want}\b", got), got
    else:
        assert "issued" in _text(hit).lower()
    assert not re.match(rf"\s*{len(rows)}\b", got)


def test_unknown_condition_word_never_returns_the_unfiltered_total(inv):
    rows, fr = inv
    hit = _ask("How many invoices are paid yes after the audit?", fr)
    assert not re.match(rf"\s*{len(rows)}\b", _head(hit))


# ---- R-02 / R-07: decimal marks, currency codes, percent ----------------------------

def test_european_decimals_are_read_as_decimals():
    df = pd.DataFrame({"shop": ["Alpha", "Alpha", "Beta", "Beta"],
                       "sales": ["1.234,56", "2.000,00", "10,50", "1.000,00"]})
    fr = {("eu.csv", "eu"): df}
    assert re.match(r"\s*3234\.56\b", _head(_ask("What is the sum of sales for shop Alpha?", fr)))
    assert re.match(r"\s*1010\.5\b", _head(_ask("What is the sum of sales for shop Beta?", fr)))


def test_us_thousands_still_read_as_thousands():
    df = pd.DataFrame({"shop": ["A", "A"], "sales": ["1,234.56", "2,000.00"]})
    got = _head(_ask("What is the sum of sales for shop A?", {("us.csv", "us"): df}))
    assert re.match(r"\s*3234\.56\b", got), got


def test_percent_and_currency_code_cells_are_numbers():
    df = pd.DataFrame({"shop": ["Alpha", "Alpha", "Beta"],
                       "disc": ["10%", "20%", "5%"],
                       "price": ["RM 5.00", "RM 7.50", "RM 1.00"]})
    fr = {("pc.csv", "pc"): df}
    assert re.match(r"\s*15\b", _head(_ask("What is the average disc for shop Alpha?", fr)))
    assert re.match(r"\s*13\.5\b", _head(_ask("What is the sum of price?", fr)))


def test_mixed_currencies_are_not_added_together():
    df = pd.DataFrame({"inv": ["a", "b", "c"], "amount": ["$10.00", "RM 20.00", "30,00 EUR"]})
    hit = _ask("What is the total amount?", {("m.csv", "m"): df})
    got = _text(hit)
    assert not re.search(r"\b60\b", got.replace(",", ""))
    assert "currenc" in got.lower()


def test_one_currency_can_be_asked_for_and_is_summed_alone():
    cells = ["$10.00", "RM 20.00", "30,00 EUR", "$5.50", "RM 1,000.25"]
    df = pd.DataFrame({"inv": list("abcde"), "amount": cells})
    fr = {("m.csv", "m"): df}
    assert re.match(r"\s*1020\.25\b", _head(_ask("What is the total amount in RM?", fr)))
    assert re.match(r"\s*10\b", _head(_ask("What is the highest amount in $?", fr)))
    assert re.match(r"\s*30\b", _head(_ask("What is the highest amount in EUR?", fr)))


def test_a_word_that_is_also_a_sheet_name_does_not_pick_the_wrong_table():
    orders = pd.DataFrame({"id": ["1", "2"], "region": ["North", "South"], "qty": ["5", "7"]})
    big = pd.DataFrame({"order_id": [str(i) for i in range(10)],
                        "status": ["closed" if i % 5 == 0 else "open" for i in range(10)]})
    fr = {("book.xlsx", "Orders"): orders, ("big.csv", "big"): big}
    assert re.match(r"\s*2\b", _head(_ask("How many orders have status closed?", fr)))


# ---- R-06: "total qty" is the total of qty, even when a column is called total ------

def test_total_qty_when_a_column_is_called_total():
    df = pd.DataFrame({"id": ["1", "2", "3"], "region": ["North", "South", "North"],
                       "qty": ["5", "7", "11"], "total": ["50", "70", "110"]})
    fr = {("book.xlsx", "Orders"): df}
    for q in ("What is the total qty where region is North?",
              "What is the total qty for region North?"):
        got = _head(_ask(q, fr))
        assert re.match(r"\s*16\b", got), (q, got)
    assert re.match(r"\s*230\b", _head(_ask("What is the sum of total?", fr)))


# ---- R-04: a title line above a CSV header ------------------------------------------

def test_csv_with_title_line_above_the_header(tmp_path):
    p = tmp_path / "ledger.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Quarterly export generated by ERP v9", "", "", ""])
        w.writerow(["order_id", "region", "units", "status"])
        for i in range(30):
            w.writerow([i, ["East", "West"][i % 2], i + 1, ["open", "closed"][i % 3 == 0]])
    sheets = load_table_file(p)
    df = next(iter(sheets.values()))
    assert list(df.columns) == ["order_id", "region", "units", "status"]
    assert len(df) == 30
    assert df.attrs["header_excel_row"] == 2
    fr = {("ledger.csv", "ledger"): df}
    want = sum(1 for i in range(30) if i % 3 == 0)
    assert re.match(rf"\s*{want}\b", _head(_ask("How many orders have status closed?", fr)))


def test_plain_csv_header_still_row_one(tmp_path):
    p = tmp_path / "plain.csv"
    p.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    df = next(iter(load_table_file(p).values()))
    assert list(df.columns) == ["a", "b"] and len(df) == 2
    assert df.attrs["header_excel_row"] == 1


# ---- verifier round: conditions on the counted column, between, semicolon files -------

def _small():
    df = pd.DataFrame({
        "region": ["North", "South", "South", "North", "East"],
        "units": ["5", "6", "7", "8", "9"],
        "paid": ["yes", "no", "yes", "yes", "no"],
    })
    return {("f.csv", "f"): df}


def _lead(hit):
    return _text(hit).split(" ")[0].replace(",", "")


def test_count_of_the_column_the_value_belongs_to_is_filtered():
    fr = _small()
    assert _lead(_ask("How many rows where paid is no?", fr)) == "2"
    assert _lead(_ask("How many records are paid yes?", fr)) == "3"
    assert _lead(_ask("how many records are not paid?", fr)) == "2"


def test_a_value_no_row_holds_after_the_counted_column_is_declined_not_counted():
    fr = _small()
    for q in ("How many rows have region West?", "How many rows have region S?"):
        out = _text(_ask(q, fr))
        assert "could not apply" in out and not out.startswith("5")


def test_between_is_a_range_filter_not_dropped():
    fr = _small()
    assert _lead(_ask("How many rows have units between 6 and 8?", fr)) == "3"


def test_semicolon_csv_is_read_with_its_columns(tmp_path):
    from rag import ingest, xlsx_sql

    p = tmp_path / "semi.csv"
    body = "item;price;qty\nbolt;1,50;10\nnut;2,25;4\nscrew;3,00;6\n"
    p.write_text(body, encoding="utf-8")
    df = next(iter(load_table_file(p).values()))
    assert list(df.columns) == ["item", "price", "qty"] and len(df) == 3
    out = _text(_ask("What is the total price?", {("semi.csv", "semi"): df}))
    assert out.startswith("6.75")
    assert "item | price | qty" in ingest._csv_text(p, body, xlsx_sql.sniff_delimiter(body))

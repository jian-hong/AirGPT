"""Dirty-data ontology: ids across text/number, near-miss keys, text dates and
numbers, and tables past MAX_ROWS. Fixtures are built by hand."""
from __future__ import annotations

import openpyxl
import pytest

from rag import ontology


def _book(path, sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    wb.save(path)
    return path


def _rels(ont):
    return {(r["type"], f"{r['from_sheet']}.{r['from_column']}", f"{r['to_sheet']}.{r['to_column']}")
            for r in ont["relations"]}


def _cols(ont, sheet):
    for w in ont["workbooks"]:
        for t in w.get("sheets") or []:
            if t["name"] == sheet:
                return {c["name"]: c for c in t["columns"]}
    raise AssertionError(sheet)


def test_text_id_001_meets_number_id_1(tmp_path):
    p = _book(tmp_path / "w.xlsx", {
        "Customers": [["customer_id", "name"]] + [[f"{i:03d}", f"c{i}"] for i in range(1, 21)],
        "Orders": [["order_no", "customer_id"]] + [[100 + i, (i % 20) + 1] for i in range(40)],
    })
    ont = ontology.build_ontology([p])
    assert ("foreign_key", "Orders.customer_id", "Customers.customer_id") in _rels(ont)
    assert "leading zeros" in ont["relations"][0]["evidence"]


def test_column_holding_01_and_1_is_not_merged(tmp_path):
    # "01" and "1" sit in one column, so they are different codes there.
    p = _book(tmp_path / "w.xlsx", {
        "Codes": [["code", "d"]] + [[c, i] for i, c in enumerate(
            ["01", "1", "02", "2", "03", "3", "04", "4", "05", "5"])],
        "Use": [["code", "n"]] + [[str(i % 5 + 1), i] for i in range(30)],
    })
    for r in ontology.build_ontology([p])["relations"]:
        assert "leading zeros" not in r["evidence"]


def test_text_01a_never_matches_number_1(tmp_path):
    p = _book(tmp_path / "w.xlsx", {
        "Parts": [["part_id", "d"]] + [[f"{i:02d}A", i] for i in range(1, 21)],
        "Use": [["part_id", "n"]] + [[(i % 20) + 1, i] for i in range(40)],
    })
    assert ontology.build_ontology([p])["relations"] == []


def test_85_percent_foreign_key_is_probable_and_carries_overlap(tmp_path):
    parent = [["cust_ref", "n"]] + [[f"K{i:03d}", i] for i in range(40)]
    kids = [f"K{i:03d}" for i in range(34)] + [f"X{i}" for i in range(6)]
    child = [["cust_ref", "amt"]] + [[k, i] for i, k in enumerate(kids * 2)]  # repeats: not a key
    p = _book(tmp_path / "w.xlsx", {"Parent": parent, "Child": child})
    ont = ontology.build_ontology([p])
    (r,) = ont["relations"]
    assert r["type"] == "probable_foreign_key" and r["confidence"] == "probable"
    assert r["overlap"] == 0.85
    assert ont["summary"]["n_relations"] == 0 and ont["summary"]["n_probable_relations"] == 1
    step = {s["op"]: s["detail"] for s in ontology.logic_for_query(ont, "child cust_ref parent")}["use_relations"]
    assert "probable" in step and "85%" in step


def test_low_overlap_is_still_nothing(tmp_path):
    parent = [["cust_ref", "n"]] + [[f"K{i:03d}", i] for i in range(40)]
    kids = [f"K{i:03d}" for i in range(24)] + [f"X{i}" for i in range(16)]
    child = [["cust_ref", "amt"]] + [[k, i] for i, k in enumerate(kids * 2)]
    p = _book(tmp_path / "w.xlsx", {"Parent": parent, "Child": child})
    assert ontology.build_ontology([p])["relations"] == []


@pytest.mark.parametrize("vals,fmt_set", [
    (["12 Mar 2026", "01 Apr 2026", "30 Jan 2025"], {"%d %b %Y"}),
    (["March 12, 2026", "April 1, 2026", "January 30, 2025"], {"%B %d, %Y"}),
    (["2026.03.12", "2026.04.01", "2025.01.30"], {"%Y.%m.%d"}),
    (["12-Mar-26", "01-Apr-26", "30-Jan-25"], {"%d-%b-%y"}),
])
def test_text_dates_in_other_notations(vals, fmt_set):
    prof, _ = ontology.profile_column("when", vals * 3)
    assert prof["role"] == "temporal" and prof["format"] in fmt_set


@pytest.mark.parametrize("vals", [
    ["45%", "12.5%", "100%", "7%"],
    ["RM 1,200.50", "RM 300.00", "RM 99.90", "RM 4,000.00"],
    ["$3,400", "$12", "$1,000", "$250"],
])
def test_text_numbers_are_measures(vals):
    prof, _ = ontology.profile_column("amount", vals)
    assert prof["kind"] == "number" and prof["role"] == "measure"


def test_zero_padded_codes_and_plain_digit_text_are_not_measures():
    prof, _ = ontology.profile_column("code", ["001", "002", "003", "004"])
    assert prof["kind"] == "text" and prof["role"] == "key"
    prof, _ = ontology.profile_column("phone", ["60123456789", "60198765432", "60111111111"])
    assert prof["role"] != "measure"


def test_table_past_max_rows_is_profiled_in_full(tmp_path, monkeypatch):
    # The old ceiling was 50 000 rows; the tail used to be invisible.
    n = 60_000
    big = tmp_path / "big.csv"
    big.write_text("sku_id,qty\n" + "".join(f"S{i:05d},{i % 7}\n" for i in range(n)), encoding="utf-8")
    use = tmp_path / "use.csv"
    use.write_text("sku_id,units\n" + "".join(f"S{i:05d},{i}\n" for i in range(55_000, 55_040)), encoding="utf-8")
    ont = ontology.build_ontology([big, use])
    cols = _cols(ont, "big")
    assert cols["sku_id"]["is_unique"] and cols["sku_id"]["n_distinct"] == n
    assert any(r["from_sheet"] == "use" and r["to_sheet"] == "big" and r["confidence"] == "established"
               for r in ont["relations"])


def test_truncated_table_marks_relations_as_from_a_sample(tmp_path, monkeypatch):
    monkeypatch.setattr(ontology, "MAX_ROWS", 500)
    big = tmp_path / "big.csv"
    big.write_text("sku_id,qty\n" + "".join(f"S{i:05d},{i % 7}\n" for i in range(800)), encoding="utf-8")
    use = tmp_path / "use.csv"
    use.write_text("sku_id,units\n" + "".join(f"S{i:05d},{i}\n" for i in range(10, 50)), encoding="utf-8")
    ont = ontology.build_ontology([big, use])
    (t,) = [t for w in ont["workbooks"] for t in w["sheets"] if t["name"] == "big"]
    assert t["sampled"] and t["columns"][0]["from_sample"]
    (r,) = ont["relations"]
    assert r["sampled"] is True and r["type"] == "probable_foreign_key"
    assert "sample" in r["evidence"]


def test_payload_version_bumped():
    assert ontology.ONTOLOGY_VERSION >= 3


def test_referencing_column_that_mixes_1_and_01_is_still_the_same_id(tmp_path):
    """An adversary case: every order points at a real customer, but some ids were
    typed zero-padded. That was reported as a 77% "probable" relation."""
    import openpyxl

    from rag import ontology

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    c = wb.create_sheet("Customers")
    c.append(["customer_id", "n"])
    for i in range(1, 31):
        c.append([i, f"name {i}"])
    o = wb.create_sheet("Orders")
    o.append(["order_no", "customer_id"])
    for i in range(120):
        cust = (i % 30) + 1
        o.append([f"O{i}", f"{cust:02d}" if (i // 30) % 2 and cust < 10 else str(cust)])
    wb.save(tmp_path / "o.xlsx")
    rels = ontology.build_ontology([tmp_path / "o.xlsx"])["relations"]
    assert [(r["type"], r["from_column"], r["to_sheet"]) for r in rels] == [("foreign_key", "customer_id", "Customers")]
    assert rels[0]["overlap"] == 1.0


def test_csv_keeps_zero_padded_codes_as_written(tmp_path):
    from rag import ontology

    p = tmp_path / "c.csv"
    p.write_text("customer_id,total\n" + "".join(f"{i:03d},{i * 2}\n" for i in range(1, 13)), encoding="utf-8")
    cols = {c["name"]: c for w in ontology.build_ontology([p])["workbooks"] for t in w["sheets"] for c in t["columns"]}
    assert cols["customer_id"]["samples"][0] == "001" and cols["customer_id"]["kind"] == "text"
    assert cols["total"]["kind"] == "number"

"""ops_amend must read and write the same sheet and find the row by employee key.

Round 2, lane rag-core: with a first sheet that was not Payroll_RAW, identify read the
first sheet but the write went to Payroll_RAW at the same row NUMBER, so the salary
landed on a different employee. Each test failed on the base commit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

openpyxl = pytest.importorskip("openpyxl")
from rag import ops_amend  # noqa: E402

HDR = ["Emp ID", "Name", "Base Salary", "Notes"]


def _book(path, sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets:
        ws = wb.create_sheet(name)
        ws.append(HDR)
        for r in rows:
            ws.append(r)
    wb.save(path)


def _cells(path, sheet):
    wb = openpyxl.load_workbook(path)
    try:
        return [[c.value for c in row] for row in wb[sheet].iter_rows(min_row=2)]
    finally:
        wb.close()


def _run(path, ask="salary raise for E-0001", salary=99999):
    out = ops_amend.identify_employee(path, ask)
    assert out["ok"], out
    tok = out["pending"]["token"]
    assert ops_amend.confirm_identity(tok, True)["ok"]
    assert ops_amend.propose_amend(tok, new_salary=salary)["ok"]
    return tok, ops_amend.confirm_amend(tok, True)


def test_first_sheet_not_payroll_raw_writes_the_right_employee(tmp_path):
    f = tmp_path / "p.xlsx"
    _book(f, [
        ("Summary", [["E-0001", "Alice", 100, ""], ["E-0002", "Bob", 200, ""]]),
        ("Payroll_RAW", [["E-0002", "Bob", 200, ""], ["E-0001", "Alice", 100, ""]]),
    ])
    tok, out = _run(f)
    assert out["ok"], out
    raw = _cells(f, "Payroll_RAW")
    assert raw[0][:3] == ["E-0002", "Bob", 200], "Bob must not be touched"
    assert raw[1][:3] == ["E-0001", "Alice", 99999.0]
    assert _cells(f, "Summary")[0][2] == 100 and _cells(f, "Summary")[1][2] == 200


def test_single_sheet_with_another_name_is_amended(tmp_path):
    f = tmp_path / "p.xlsx"
    _book(f, [("Staff", [["E-0001", "Alice", 100, ""], ["E-0002", "Bob", 200, ""]])])
    tok, out = _run(f, "salary raise for E-0002", 250)
    assert out["ok"], out
    assert _cells(f, "Staff")[1][2] == 250.0
    assert _cells(f, "Staff")[0][2] == 100


def test_rows_moved_after_identify_still_hit_the_same_employee(tmp_path):
    f = tmp_path / "p.xlsx"
    _book(f, [("Payroll_RAW", [["E-0001", "Alice", 100, ""], ["E-0002", "Bob", 200, ""]])])
    out = ops_amend.identify_employee(f, "salary raise for E-0002")
    tok = out["pending"]["token"]
    ops_amend.confirm_identity(tok, True)
    ops_amend.propose_amend(tok, new_salary=300)
    wb = openpyxl.load_workbook(f)
    wb["Payroll_RAW"].insert_rows(2)  # someone adds a row on top: Bob moves down
    wb["Payroll_RAW"].cell(2, 1).value = "E-0099"
    wb["Payroll_RAW"].cell(2, 2).value = "Newcomer"
    wb["Payroll_RAW"].cell(2, 3).value = 1
    wb.save(f)
    res = ops_amend.confirm_amend(tok, True)
    assert res["ok"], res
    rows = {r[0]: r[2] for r in _cells(f, "Payroll_RAW")}
    assert rows == {"E-0099": 1, "E-0001": 100, "E-0002": 300.0}


def test_duplicate_employee_key_is_refused_in_plain_words(tmp_path):
    f = tmp_path / "p.xlsx"
    _book(f, [("Payroll_RAW", [["E-0001", "Alice", 100, ""], ["E-0001", "Alicia", 150, ""]])])
    out = ops_amend.identify_employee(f, "salary raise for E-0001")
    assert out["ok"] is False
    assert "more than one" in out["error"].lower()
    assert _cells(f, "Payroll_RAW")[0][2] == 100 and _cells(f, "Payroll_RAW")[1][2] == 150


def test_key_duplicated_after_identify_is_refused_and_nothing_written(tmp_path):
    f = tmp_path / "p.xlsx"
    _book(f, [("Payroll_RAW", [["E-0001", "Alice", 100, ""]])])
    out = ops_amend.identify_employee(f, "salary raise for E-0001")
    tok = out["pending"]["token"]
    ops_amend.confirm_identity(tok, True)
    ops_amend.propose_amend(tok, new_salary=500)
    wb = openpyxl.load_workbook(f)
    wb["Payroll_RAW"].append(["E-0001", "Twin", 120, ""])
    wb.save(f)
    res = ops_amend.confirm_amend(tok, True)
    assert res["ok"] is False and "more than one" in res["error"].lower()
    assert [r[2] for r in _cells(f, "Payroll_RAW")] == [100, 120]


def test_key_gone_after_identify_is_refused(tmp_path):
    f = tmp_path / "p.xlsx"
    _book(f, [("Payroll_RAW", [["E-0001", "Alice", 100, ""], ["E-0002", "Bob", 200, ""]])])
    tok = ops_amend.identify_employee(f, "salary raise for E-0002")["pending"]["token"]
    ops_amend.confirm_identity(tok, True)
    ops_amend.propose_amend(tok, new_salary=1)
    wb = openpyxl.load_workbook(f)
    wb["Payroll_RAW"].delete_rows(3)
    wb.save(f)
    res = ops_amend.confirm_amend(tok, True)
    assert res["ok"] is False and "not found" in res["error"].lower()
    assert [r[2] for r in _cells(f, "Payroll_RAW")] == [100]

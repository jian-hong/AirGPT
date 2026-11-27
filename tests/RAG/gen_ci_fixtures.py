"""Write the workbooks CI can re-run. Outputs are committed.

primary50: four seeded workbooks. The 2026-08-26 files were gitignored and are
not in this clone, so these are a documented equivalent (a title line, two
numeric sheets, hundreds of rows), not those bytes and not those asks.

frtr_min: one quarterly workbook with a Questions sheet, used when
AIRGPT_FRTR_BENCH points here. The original FRTR-bench directory is gitignored.

payroll_ops: a three-row stand-in for the gitignored 120MB ops fixture.
"""
from __future__ import annotations

import hashlib
import random
from pathlib import Path

import openpyxl

RAG = Path(__file__).resolve().parent
PRIMARY = RAG / "primary50"
FRTR = RAG / "fixtures" / "frtr_min"
OPS = RAG / "fixtures" / "ops"


def _book(path: Path, seed: int, first: str, second: str) -> None:
    rng = random.Random(seed)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = first
    # Two text cells so the pre-#31 "first wide row" rule treats this banner as
    # the header. The shipped binder walks back from the first numeric row and
    # keeps the real header on the next line. malformed_field_gate.py needs
    # that split.
    ws.append(["export dump", "skip"])
    ws.append(["Region", "Qty", "UnitPrice", "Revenue"])
    for i in range(400):
        qty = rng.randint(1, 80)
        price = round(rng.uniform(2, 40), 2)
        ws.append([rng.choice(["North", "South", "East", "West"]), qty, price, round(qty * price, 2)])
    ws2 = wb.create_sheet(second)
    ws2.append(["Units", "Amount"])
    for i in range(160):
        ws2.append([rng.randint(1, 40), round(rng.uniform(5, 200), 2)])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _frtr(path: Path) -> None:
    wb = openpyxl.Workbook()
    rev = wb.active
    rev.title = "Revenue"
    rev.append(["Region", "Qty", "UnitPrice", "Revenue"])
    qty, revenue = [], []
    for i in range(120):
        q = (i % 17) + 1
        price = round(2 + (i % 9) * 0.5, 2)
        r = round(q * price, 2)
        qty.append(q)
        revenue.append(r)
        rev.append(["North" if i % 2 == 0 else "South", q, price, r])
    ex = wb.create_sheet("Expenses")
    ex.append(["Units", "Amount"])
    units, amounts = [], []
    for i in range(80):
        u = (i % 11) + 1
        a = round(10 + i * 0.25, 2)
        units.append(u)
        amounts.append(a)
        ex.append([u, a])
    qsum = sum(qty[:20])
    rsum = round(sum(revenue[:20]), 2)
    usum = sum(units[:15])
    asum = round(sum(amounts[:15]), 2)
    qmax = max(qty[10:40])
    umin = min(units[5:25])
    qs = wb.create_sheet("Questions")
    qs.append(["Question", "Answer", "ReasoningType", "Difficulty", "Provenance"])
    for question, answer, kind, diff in (
        ("On the Revenue sheet, sum Qty for rows 2 to 21", qsum, "Aggregation", "Easy"),
        ("On the Revenue sheet, total Revenue for rows 2 to 21", rsum, "Aggregation", "Easy"),
        ("On the Expenses sheet, sum Units for rows 2 to 16", usum, "Aggregation", "Medium"),
        ("On the Expenses sheet, total Amount for rows 2 to 16", asum, "Aggregation", "Medium"),
        ("On the Revenue sheet, maximum Qty for rows 12 to 41", qmax, "Comparison", "Hard"),
        ("On the Expenses sheet, minimum Units for rows 7 to 26", umin, "Comparison", "Hard"),
    ):
        qs.append([question, str(answer), kind, diff, "fixture"])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _payroll(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Payroll_RAW"
    ws.append(["Emp ID", "Name", "Dept", "Base Salary", "Notes"])
    ws.append(["E-0003", "Cy East", "Ops", 3000, ""])
    ws.append(["E-0012", "Ada North", "Ops", 4100, ""])
    ws.append(["E-0500", "Bea South", "Ops", 5200.5, ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _sums(paths: list[Path], dest: Path) -> None:
    lines = []
    for p in paths:
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        lines.append(f"{digest}  {p.name}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    books = [
        (PRIMARY / "p50_01_sales_messy.xlsx", 1, "Sales", "Costs"),
        (PRIMARY / "p50_02_ops_messy.xlsx", 2, "Ops", "Costs"),
        (PRIMARY / "p50_03_inventory_messy.xlsx", 3, "Inventory", "Costs"),
        (PRIMARY / "p50_04_mixed_messy.xlsx", 4, "Mixed", "Costs"),
    ]
    for path, seed, first, second in books:
        _book(path, seed, first, second)
        print(f"wrote {path}")
    _sums([p for p, *_ in books], PRIMARY / "SHA256SUMS")
    fr = FRTR / "frtr_0001_quarterly-summary.xlsx"
    _frtr(fr)
    _sums([fr], FRTR / "SHA256SUMS")
    pay = OPS / "payroll_ops.xlsx"
    _payroll(pay)
    _sums([pay], OPS / "SHA256SUMS")
    print("fixtures ready")


if __name__ == "__main__":
    main()

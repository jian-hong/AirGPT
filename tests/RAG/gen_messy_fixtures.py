"""Generate sample-messy multi-sheet workbooks (~target_mb, default 120).

Writes under tests/RAG/messy/ (gitignored). Not 2GB.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "messy"
RESULTS = ROOT / "results"


def _write_csv_blob(path: Path, n_rows: int, seed: int = 7) -> int:
    """Fast large sheet-as-CSV (messy headers / blanks / mixed types)."""
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Messy: duplicate headers, blank columns, mixed date formats
    header = "SKU , Region,  sales_value_myr,qty,notes,,Date,Vendor\n"
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# RAW DUMP — do not trust header spacing\n")
        f.write(header)
        f.write("sku,region,sales_value_myr,qty,notes,junk,date,vendor\n")  # duplicate messy
        for i in range(n_rows):
            sku = f"SKU-{rng.randint(1, 500):05d}"
            region = rng.choice(["West", "East", "Central", "North", "", " west "])
            val = round(rng.uniform(10, 90000), 2)
            qty = rng.randint(0, 400)
            note = rng.choice(["", "n/a", "TBD", "ok", "???"])
            date = rng.choice([f"2024-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}", "31/02/2024", ""])
            vendor = rng.choice(["Acme", "Globex", "Initech", None, " acme "])
            f.write(f"{sku},{region},{val},{qty},{note},,{date},{vendor or ''}\n")
    return path.stat().st_size


def _write_payroll_xlsx(path: Path, n_employees: int = 800) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Payroll_RAW"
    ws.append(["Emp ID", "Name", "Dept", "Base Salary", "Last Raise %", "Notes"])
    rng = random.Random(11)
    for i in range(1, n_employees + 1):
        ws.append(
            [
                f"E-{i:04d}",
                f"Person {i}",
                rng.choice(["Ops", "Sales", "Eng", "HR", ""]),
                round(rng.uniform(2800, 12000), 2),
                round(rng.uniform(0, 12), 2),
                rng.choice(["", "pending", "ok"]),
            ]
        )
    ws2 = wb.create_sheet("Sales_Messy")
    ws2.append(["sku", "sales_value_myr", "region"])
    for i in range(5000):
        ws2.append([f"SKU-{rng.randint(1, 200):05d}", round(rng.uniform(100, 50000), 2), rng.choice(["West", "East"])])
    wb.save(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-mb", type=float, default=120.0)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)

    # ~120MB via CSV rows (~120 bytes/row => ~1e6 rows)
    bytes_target = int(args.target_mb * 1024 * 1024)
    rows = max(50_000, bytes_target // 120)
    csv_path = OUT / "messy_sales_raw.csv"
    xlsx_path = OUT / "messy_payroll_ops.xlsx"
    print(f"writing ~{rows} csv rows -> {csv_path}", flush=True)
    t0 = time.perf_counter()
    sz = _write_csv_blob(csv_path, rows)
    _write_payroll_xlsx(xlsx_path)
    xsz = xlsx_path.stat().st_size
    meta = {
        "ok": True,
        "target_mb": args.target_mb,
        "files": [
            {"path": str(csv_path), "bytes": sz, "mb": round(sz / 1e6, 2)},
            {"path": str(xlsx_path), "bytes": xsz, "mb": round(xsz / 1e6, 2)},
        ],
        "total_mb": round((sz + xsz) / 1e6, 2),
        "note": "Generated locally; gitignored. Not 2GB (P6).",
        "secs": round(time.perf_counter() - t0, 1),
    }
    (RESULTS / "messy_fixtures_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2), flush=True)


if __name__ == "__main__":
    main()

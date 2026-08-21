"""R-0007 proof for oracle_bench's `malformed_ask_rate` field.

F13b gates on `malformed_ask_rate < 5%`, so the field decides whether a target is
met. A number nobody has watched fail is not evidence, and this repo already
shipped one field that could not: `header_drift` read `[]` when 89 of 320 asks
were malformed AND when none were, because it compared the loader against the
oracle while both picked the same banner row.

So this drives the real generator twice over the same workbook - once against the
pre-#31 header rule ("first row in the first five with >= 2 non-empty cells", the
rule that let an export banner win) and once against the shipped binder - and
asserts the field separates them. If it ever stops separating them, the field has
stopped measuring and F13b is unassessable, whatever number it prints.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
for _p in (str(REPO), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.stdio_utf8 import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

import openpyxl  # noqa: E402

import oracle_bench as ob  # noqa: E402

WORKBOOK = ROOT / "primary50" / "p50_01_sales_messy.xlsx"
N = 80
SEED = 1


def old_read_schema(p: Path) -> dict[str, dict]:
    """The pre-#31 rule, kept verbatim so the comparison stays honest."""
    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    out: dict[str, dict] = {}
    try:
        for name in wb.sheetnames:
            ws = wb[name]
            hdr, cols = None, []
            for i, row in enumerate(ws.iter_rows(min_row=1, max_row=5, values_only=True), start=1):
                cells = [c for c in row if c is not None and str(c).strip()]
                if len(cells) >= 2:
                    hdr = i
                    cols = [str(c).strip() if c is not None else "" for c in row]
                    break
            if hdr is None:
                continue
            last = ws.max_row or hdr
            if last <= hdr:
                continue
            numeric: dict[str, int] = {}
            for idx, c in enumerate(cols):
                if not str(c).strip():
                    continue
                vals, _ = ob.oracle_values(p, name, idx, hdr + 1, min(last, hdr + 60))
                if len(vals) >= 3:
                    numeric[str(c)] = idx
            out[name] = {
                "header_row": hdr, "columns": cols, "first_data_row": hdr + 1,
                "last_data_row": last, "numeric": numeric, "numeric_cols": list(numeric),
            }
    finally:
        wb.close()
    return out


def rate(schema: dict) -> tuple[float, list[str]]:
    cases = ob.generate(WORKBOOK, schema, random.Random(SEED), N)
    mal = sum(1 for c in cases if ob._case_is_malformed(c))
    junk = sorted({
        str(c.get("col")) for c in cases
        if c.get("col") is not None and ob._is_junk_column(c.get("col"))
    })
    return mal / max(1, len(cases)), junk


def main() -> int:
    if not WORKBOOK.is_file():
        print(f"fixture missing: {WORKBOOK}")
        return 2
    print("=" * 68)
    print("R-0007 - can malformed_ask_rate report a problem at all?")
    print("=" * 68)
    old, old_junk = rate(old_read_schema(WORKBOOK))
    new, _ = rate(ob.read_schema(WORKBOOK))
    print(f"  pre-#31 header rule : malformed_ask_rate = {old:.4f}")
    if old_junk:
        print(f"                        asked about {old_junk[:6]}")
    print(f"  shipped binder      : malformed_ask_rate = {new:.4f}")
    print()
    fails = []
    if not old > 0.05:
        fails.append("field does NOT report the known-broken state - it cannot fail")
    if not new <= 0.05:
        fails.append(f"shipped binder still malformed at {new:.4f} - F13b's <5% clause is unmet")
    if not old > new:
        fails.append("field does not separate the two states")
    for f in fails:
        print(f"  FAIL  {f}")
    if not fails:
        print("  PASS  the field moves between the broken and the fixed state")
        print("  PASS  the shipped binder is under F13b's 5% clause")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

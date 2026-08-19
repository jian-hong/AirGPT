"""Randomised oracle benchmark for the SELECT-only lane.

The point of this harness is that **the grader does not share code with the thing
it grades**. Ground truth is read straight out of the workbook with openpyxl, by
spreadsheet row number, with no use of `load_sheets`, `sheet_sql`, or any planner.
If the lane and the oracle disagree, one of them is wrong and the run says so.

Questions are generated, not curated, so a different `--seed` asks different things
about different sheets, columns and row spans. A curated question list stops being
evidence the moment the code is tuned to it; a generator that draws fresh spans
every run does not.

Families cover the shapes a founder actually asks:

  row_range_agg     "On the Carriers sheet, sum BaseRate for rows 330 to 660"
  row_range_nocol   "select rows 330 to 660 on Carriers, sum"
  filter_agg        "average OnTimeSLA where BaseRate > 1"
  filter_count      "how many rows have BaseRate above 1"
  combined          row span AND a column filter
  paraphrase        the same question written three ways - answers must agree
  out_of_range      rows past the end of the sheet - must refuse, not answer 0

Usage:
    python tests/RAG/oracle_bench.py --workbook frtr_00027_supply-chain-regional.xlsx
    python tests/RAG/oracle_bench.py --space-id 6 --n 40 --seed 7
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
RESULTS = ROOT / "results"
for _p in (str(REPO), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Before the first print: a U+2014 in a fixture header came back as "?" from this
# bench, which reads as corrupted data and is not - it is the Windows console
# encoding. On a non-English corpus every answer would look broken (R-0012).
from scripts.stdio_utf8 import ensure_utf8_stdio  # noqa: E402

if not ensure_utf8_stdio():
    print("[warn] stdout is not UTF-8; non-ASCII in questions and answers may be lossy")

TOL = 1e-6


# --------------------------------------------------------------------------
# Oracle - independent of everything the lane uses.
# --------------------------------------------------------------------------
def read_schema(path: Path) -> dict[str, dict]:
    """Sheet -> {header_row, columns, first_data_row, last_data_row, numeric_cols}.

    Deliberately re-derives the header position instead of importing the loader's
    opinion of it. If the two ever disagree, that disagreement is a real finding.
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out: dict[str, dict] = {}
    try:
        for name in wb.sheetnames:
            ws = wb[name]
            header_row = None
            columns: list[str] = []
            for i, row in enumerate(ws.iter_rows(min_row=1, max_row=5, values_only=True), start=1):
                cells = [c for c in row if c is not None and str(c).strip()]
                if len(cells) >= 2:
                    header_row = i
                    columns = [str(c).strip() if c is not None else "" for c in row]
                    break
            if header_row is None:
                continue
            last = ws.max_row or header_row
            if last <= header_row:
                continue
            numeric: dict[str, int] = {}
            probe_to = min(last, header_row + 60)
            for idx, col in enumerate(columns):
                if not col:
                    continue
                hits = 0
                seen = 0
                for row in ws.iter_rows(
                    min_row=header_row + 1, max_row=probe_to, min_col=idx + 1, max_col=idx + 1,
                    values_only=True,
                ):
                    v = row[0]
                    if v is None:
                        continue
                    seen += 1
                    try:
                        float(v)
                        hits += 1
                    except (TypeError, ValueError):
                        pass
                if seen and hits / seen >= 0.9:
                    numeric[col] = idx
            out[name] = {
                "header_row": header_row,
                "columns": columns,
                "first_data_row": header_row + 1,
                "last_data_row": last,
                "numeric": numeric,
            }
    finally:
        wb.close()
    return out


# Row 1 of the sheet is index 1 here, so a spreadsheet row number indexes directly.
# Cached because a 200k-row sheet re-opened once per generated question dominates
# the run. Still plain openpyxl cell reads - the cache changes the cost, not the
# independence.
_SHEET_CACHE: dict[tuple[str, str], list[tuple]] = {}


def _sheet_rows(path: Path, sheet: str) -> list[tuple]:
    key = (str(path), sheet)
    cached = _SHEET_CACHE.get(key)
    if cached is None:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            cached = [()] + list(wb[sheet].iter_rows(values_only=True))
        finally:
            wb.close()
        _SHEET_CACHE[key] = cached
    return cached


def _cell(row: tuple, idx: int) -> float | None:
    try:
        return float(row[idx])
    except (TypeError, ValueError, IndexError):
        return None


def oracle_values(path: Path, sheet: str, col_idx: int, lo: int, hi: int) -> tuple[list[float], int]:
    """Numeric values in a column between two spreadsheet rows, inclusive."""
    rows = _sheet_rows(path, sheet)
    lo = max(1, lo)
    hi = min(len(rows) - 1, hi)
    vals: list[float] = []
    scanned = 0
    for r in range(lo, hi + 1):
        scanned += 1
        v = _cell(rows[r], col_idx)
        if v is not None:
            vals.append(v)
    return vals, scanned


def oracle_filtered(
    path: Path, sheet: str, metric_idx: int, filter_idx: int, op: str, value: float,
    first_row: int, last_row: int,
) -> list[float]:
    """Metric values on rows whose filter column satisfies the comparison."""
    rows = _sheet_rows(path, sheet)
    first = max(1, first_row)
    last = min(len(rows) - 1, last_row)
    keep: list[float] = []
    for r in range(first, last + 1):
        f = _cell(rows[r], filter_idx)
        if f is None:
            continue
        ok = {
            ">": f > value, ">=": f >= value,
            "<": f < value, "<=": f <= value, "=": f == value,
        }[op]
        if not ok:
            continue
        m = _cell(rows[r], metric_idx)
        if m is not None:
            keep.append(m)
    return keep


def apply_agg(agg: str, vals: list[float]) -> float | None:
    if not vals:
        return None
    return {
        "SUM": sum(vals),
        "AVG": sum(vals) / len(vals),
        "MAX": max(vals),
        "MIN": min(vals),
        "COUNT": float(len(vals)),
    }[agg]


# --------------------------------------------------------------------------
# Question generation
# --------------------------------------------------------------------------
_AGG_WORDS = {"SUM": ["sum", "total"], "AVG": ["average", "mean"], "MAX": ["maximum", "highest"], "MIN": ["minimum", "lowest"]}
_OP_WORDS = {">": ["above", "greater than", "over"], ">=": ["at least"], "<": ["below", "less than"], "<=": ["at most"]}


def _spaced(name: str) -> str:
    """`BaseRate` -> `base rate`, so generated asks are not all exact-case echoes."""
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i and not name[i - 1].isupper():
            out.append(" ")
        out.append(ch)
    return "".join(out).lower()


def generate(path: Path, schema: dict[str, dict], rng: random.Random, n: int) -> list[dict]:
    usable = [
        (s, meta) for s, meta in schema.items()
        if meta["numeric"] and meta["last_data_row"] - meta["first_data_row"] > 30
    ]
    if not usable:
        return []
    cases: list[dict] = []
    families = [
        "row_range_agg", "row_range_nocol", "filter_agg",
        "filter_count", "combined", "paraphrase", "out_of_range",
    ]
    while len(cases) < n:
        fam = families[len(cases) % len(families)]
        sheet, meta = rng.choice(usable)
        numeric = list(meta["numeric"].items())
        first, last = meta["first_data_row"], meta["last_data_row"]
        col, cidx = rng.choice(numeric)
        agg = rng.choice(["SUM", "AVG", "MAX", "MIN"])
        aggw = rng.choice(_AGG_WORDS[agg])

        if fam in ("row_range_agg", "row_range_nocol", "combined", "paraphrase"):
            span = rng.randint(20, max(21, min(2000, (last - first) // 2)))
            lo = rng.randint(first, max(first, last - span))
            hi = min(last, lo + span)
        else:
            lo = hi = 0

        if fam == "row_range_agg":
            cases.append({
                "family": fam, "sheet": sheet, "question":
                f"On the {sheet} sheet, {aggw} {col} for rows {lo} to {hi}",
                "agg": agg, "col": col, "cidx": cidx, "lo": lo, "hi": hi,
            })
        elif fam == "row_range_nocol":
            cases.append({
                "family": fam, "sheet": sheet,
                "question": f"select rows {lo} to {hi} on {sheet}, {aggw}",
                "agg": agg, "col": None, "lo": lo, "hi": hi,
                "numeric": dict(numeric),
            })
        elif fam in ("filter_agg", "filter_count", "combined"):
            if len(numeric) < 2:
                continue
            fcol, fidx = rng.choice([c for c in numeric if c[0] != col])
            probe, _ = oracle_values(path, sheet, fidx, first, min(last, first + 400))
            if not probe:
                continue
            pivot = round(sorted(probe)[len(probe) // 2], 3)
            op = rng.choice(list(_OP_WORDS))
            opw = rng.choice(_OP_WORDS[op])
            if fam == "filter_count":
                cases.append({
                    "family": fam, "sheet": sheet,
                    "question": f"On {sheet}, how many rows have {_spaced(fcol)} {opw} {pivot}",
                    "agg": "COUNT", "col": fcol, "cidx": fidx,
                    "fcol": fcol, "fidx": fidx, "op": op, "pivot": pivot,
                    "first": first, "last": last,
                })
            elif fam == "filter_agg":
                cases.append({
                    "family": fam, "sheet": sheet,
                    "question": f"On {sheet}, what is the {aggw} {col} where {_spaced(fcol)} {opw} {pivot}",
                    "agg": agg, "col": col, "cidx": cidx,
                    "fcol": fcol, "fidx": fidx, "op": op, "pivot": pivot,
                    "first": first, "last": last,
                })
            else:
                cases.append({
                    "family": fam, "sheet": sheet,
                    "question": (
                        f"On the {sheet} sheet, {aggw} {col} for rows {lo} to {hi} "
                        f"where {_spaced(fcol)} {opw} {pivot}"
                    ),
                    "agg": agg, "col": col, "cidx": cidx,
                    "fcol": fcol, "fidx": fidx, "op": op, "pivot": pivot,
                    "lo": lo, "hi": hi,
                })
        elif fam == "paraphrase":
            cases.append({
                "family": fam, "sheet": sheet, "agg": agg, "col": col, "cidx": cidx,
                "lo": lo, "hi": hi,
                "variants": [
                    f"On the {sheet} sheet, {aggw} {col} for rows {lo} to {hi}",
                    f"{aggw} of {_spaced(col)} between rows {lo} and {hi} on {sheet}",
                    f"On {sheet}, rows {lo}-{hi}, give me the {aggw} of {col}",
                ],
                "question": f"On the {sheet} sheet, {aggw} {col} for rows {lo} to {hi}",
            })
        elif fam == "out_of_range":
            far = last + rng.randint(5000, 50000)
            cases.append({
                "family": fam, "sheet": sheet,
                "question": f"On the {sheet} sheet, {aggw} {col} for rows {far} to {far + 100}",
                "agg": agg, "col": col, "cidx": cidx, "lo": far, "hi": far + 100,
            })
    return cases[:n]


def expected(path: Path, case: dict) -> dict:
    fam = case["family"]
    if fam in ("row_range_agg", "paraphrase"):
        vals, _ = oracle_values(path, case["sheet"], case["cidx"], case["lo"], case["hi"])
        return {"kind": "scalar", "value": apply_agg(case["agg"], vals), "n": len(vals)}
    if fam == "out_of_range":
        return {"kind": "refusal"}
    if fam == "row_range_nocol":
        per = {}
        for col, idx in case["numeric"].items():
            vals, _ = oracle_values(path, case["sheet"], idx, case["lo"], case["hi"])
            got = apply_agg(case["agg"], vals)
            if got is not None:
                per[col] = got
        return {"kind": "per_column", "per_column": per}
    if fam == "filter_count":
        keep = oracle_filtered(
            path, case["sheet"], case["fidx"], case["fidx"], case["op"], case["pivot"],
            case["first"], case["last"],
        )
        return {"kind": "scalar", "value": float(len(keep)), "n": len(keep)}
    if fam == "filter_agg":
        keep = oracle_filtered(
            path, case["sheet"], case["cidx"], case["fidx"], case["op"], case["pivot"],
            case["first"], case["last"],
        )
        return {"kind": "scalar", "value": apply_agg(case["agg"], keep), "n": len(keep)}
    if fam == "combined":
        keep = oracle_filtered(
            path, case["sheet"], case["cidx"], case["fidx"], case["op"], case["pivot"],
            case["lo"], case["hi"],
        )
        return {"kind": "scalar", "value": apply_agg(case["agg"], keep), "n": len(keep)}
    return {"kind": "unknown"}


# --------------------------------------------------------------------------
# Ask the system
# --------------------------------------------------------------------------
def ask(frames: dict, question: str) -> dict | None:
    from rag import sheet_sql

    return sheet_sql.answer_filter_aggregate(question, frames)


def close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    if b == 0:
        return abs(a) < TOL
    return abs(a - b) <= max(TOL, abs(b) * 1e-9)


def required_links(case: dict) -> tuple[str, set[str]]:
    """Sheet and columns the query must bind to be answering the right question."""
    fam = case["family"]
    cols: set[str] = set()
    if fam in ("row_range_agg", "paraphrase", "out_of_range"):
        cols = {case["col"]} if case.get("col") else set()
    elif fam == "row_range_nocol":
        cols = set()  # no column named, so binding the sheet is the whole job
    elif fam == "filter_count":
        cols = {case["fcol"]}
    elif fam in ("filter_agg", "combined"):
        cols = {case["col"], case["fcol"]}
    return case["sheet"], cols


def link_check(case: dict, exp: dict, got: dict | None) -> tuple[bool, str]:
    """Schema Linking Recall for one case.

    Spider 2.0-era NL2SQL work treats this as the metric that actually predicts
    failure: if a required column is not linked, the SQL cannot be right, and a
    value-only comparison can still pass by coincidence on a correlated column.
    """
    want_sheet, want_cols = required_links(case)
    if got is None:
        return (case["family"] == "out_of_range"), "nothing returned"
    linked = got.get("linked") or {}
    if got.get("abstained"):
        # A refusal that bound the right sheet and columns and then found no rows
        # linked the schema correctly - the empty result is the data's answer, not
        # a retrieval failure. Only an unbound refusal counts against recall.
        if case["family"] == "out_of_range":
            return True, "refused: rows outside the sheet"
        if exp.get("value") is None and not exp.get("per_column"):
            if linked.get("sheet") == want_sheet:
                return True, "refused, bound correctly, no rows matched"
            return False, f"refused after binding sheet {linked.get('sheet')!r}"
        return False, "refused although the oracle found rows"
    if linked.get("sheet") != want_sheet:
        return False, f"sheet {linked.get('sheet')!r} != {want_sheet!r}"
    if linked.get("all_numeric"):
        return (not want_cols), "bound sheet, all numeric columns"
    bound = {linked.get("metric")} | set(linked.get("filters") or [])
    bound.discard("")
    missing = want_cols - bound
    if missing:
        return False, f"unlinked columns {sorted(missing)}"
    return True, "sheet + columns bound"


def judge(case: dict, exp: dict, got: dict | None) -> tuple[bool, str]:
    fam = case["family"]
    if exp["kind"] == "refusal":
        if got is None or got.get("abstained"):
            return True, "refused as it should"
        return False, f"answered {got.get('value')!r} for rows that do not exist"
    if got is None:
        return False, "no answer from the lane"
    if got.get("abstained"):
        if exp.get("value") is None and not exp.get("per_column"):
            return True, "refused, and there was nothing to compute"
        return False, f"refused, but the oracle computed {exp.get('value')}"
    if exp["kind"] == "per_column":
        want = exp["per_column"]
        have = {c["column"]: c["value"] for c in (got.get("per_column") or [])}
        if not have:
            return False, "expected per-column output, got a single value"
        missing = [c for c in want if c not in have]
        if missing:
            return False, f"missing columns {missing}"
        for col, wv in want.items():
            if not close(have[col], wv):
                return False, f"{col}: got {have[col]!r} want {wv!r}"
        return True, f"{len(want)} columns match"
    wv = exp.get("value")
    gv = got.get("value")
    if wv is None:
        return (gv is None), f"oracle had no value, lane gave {gv!r}"
    if close(gv, wv):
        return True, f"{gv}"
    return False, f"got {gv!r} want {wv!r}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workbook", default="frtr_00027_supply-chain-regional.xlsx")
    ap.add_argument("--dir", default="FRTR-bench")
    ap.add_argument("--n", type=int, default=35)
    ap.add_argument("--seed", type=int, default=0, help="0 = fresh questions each run")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    src = ROOT / args.dir / args.workbook
    if not src.is_file():
        raise SystemExit(f"missing workbook {src}")

    seed = args.seed or int(time.time())
    rng = random.Random(seed)
    print(f"workbook {src.name} | seed {seed} | n {args.n}", flush=True)

    schema = read_schema(src)
    print("schema (oracle-derived):", flush=True)
    for s, m in schema.items():
        print(f"  {s:12} header@{m['header_row']} data {m['first_data_row']}-{m['last_data_row']} "
              f"numeric={list(m['numeric'])}", flush=True)

    from frtr_sql_baseline import load_sheets

    frames = {(src.name, k): v for k, v in load_sheets(src).items()}

    # Cross-check the loader against the oracle's own header detection before
    # trusting any answer that depends on row alignment.
    drift = []
    for sheet, meta in schema.items():
        df = frames.get((src.name, sheet))
        if df is None:
            continue
        loader_first = int(df.attrs.get("first_data_excel_row") or -1)
        if loader_first != meta["first_data_row"]:
            drift.append((sheet, loader_first, meta["first_data_row"]))
    if drift:
        print("\n!! HEADER DRIFT - loader and oracle disagree on where data starts:", flush=True)
        for sheet, a, b in drift:
            print(f"   {sheet}: loader={a} oracle={b}", flush=True)

    cases = generate(src, schema, rng, args.n)
    rows = []
    for i, case in enumerate(cases, start=1):
        exp = expected(src, case)
        t0 = time.time()
        if case["family"] == "paraphrase":
            answers = [ask(frames, v) for v in case["variants"]]
            ok, why = judge(case, exp, answers[0])
            vals = [None if a is None or a.get("abstained") else a.get("value") for a in answers]
            agree = all(close(v, vals[0]) for v in vals)
            if not agree:
                ok, why = False, f"paraphrases disagree: {vals}"
            elif ok:
                why = f"{vals[0]} (3 phrasings agree)"
            got = answers[0]
        else:
            got = ask(frames, case["question"])
            ok, why = judge(case, exp, got)
        ms = round((time.time() - t0) * 1000, 1)
        linked_ok, link_why = link_check(case, exp, got)
        rows.append({
            "family": case["family"], "question": case["question"],
            "ok": ok, "why": why, "ms": ms, "linked_ok": linked_ok, "link_why": link_why,
            "sql": (got or {}).get("sql"), "sheet": (got or {}).get("sheet"),
            "linked": (got or {}).get("linked"),
        })
        flag = "OK  " if ok else "FAIL"
        # A value that matches while the binding is wrong is a coincidence, not a
        # pass - call it out rather than letting it hide inside the accuracy number.
        if ok and not linked_ok:
            flag = "LUCK"
        print(f"[{i}/{len(cases)}] {flag} {case['family']:16} {why[:80]}", flush=True)
        if not ok or not linked_ok:
            print(f"        Q: {case['question']}", flush=True)
            print(f"        link: {link_why}", flush=True)
            print(f"        SQL: {(got or {}).get('sql')}", flush=True)

    by_family: dict[str, dict] = {}
    for r in rows:
        b = by_family.setdefault(r["family"], {"n": 0, "ok": 0, "linked": 0})
        b["n"] += 1
        b["ok"] += 1 if r["ok"] else 0
        b["linked"] += 1 if r["linked_ok"] else 0
    total_ok = sum(1 for r in rows if r["ok"])
    total_linked = sum(1 for r in rows if r["linked_ok"])
    lucky = [r for r in rows if r["ok"] and not r["linked_ok"]]

    print("\n=== oracle bench ===", flush=True)
    print(f"  {'family':16} {'value':>9}  {'schema-link':>11}", flush=True)
    for fam, b in sorted(by_family.items()):
        print(f"  {fam:16} {b['ok']:>4}/{b['n']:<4} {b['linked']:>6}/{b['n']:<4}", flush=True)
    print(f"  {'TOTAL':16} {total_ok:>4}/{len(rows):<4} {total_linked:>6}/{len(rows):<4}", flush=True)
    print(f"  value accuracy   {round(total_ok / max(1, len(rows)), 4)}", flush=True)
    print(f"  schema-link rec. {round(total_linked / max(1, len(rows)), 4)}", flush=True)
    if lucky:
        print(f"  !! {len(lucky)} right-value-wrong-binding (coincidence, not a pass)", flush=True)
    # Rule of three (R-0010): zero failures in n bounds the true rate at 3/n.
    if total_ok == len(rows) and rows:
        print(f"  0 failures in {len(rows)} -> true error rate bounded at "
              f"{round(3 / len(rows) * 100, 1)}% (95%), not 0%", flush=True)

    payload = {
        "ok": True, "workbook": src.name, "seed": seed, "n": len(rows),
        "correct": total_ok, "accuracy": round(total_ok / max(1, len(rows)), 4),
        "schema_link_recall": round(total_linked / max(1, len(rows)), 4),
        "right_value_wrong_binding": len(lucky),
        "by_family": by_family, "header_drift": drift, "rows": rows,
        "oracle": "openpyxl direct cell reads by spreadsheet row - shares no code with the lane",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else RESULTS / "oracle_bench_latest.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out}", flush=True)
    if total_ok != len(rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

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

    # F13 retained A/B (same generated questions; hybrid_max = SQL lane,
    # sira_max = retrieve with hybrid_sql_lane off). Writes oracle_cross_latest.json.
    python tests/RAG/oracle_bench.py --dir FRTR-bench --workbook frtr_0001_quarterly-summary.xlsx --n 7 --seed 1 --variants sira_max,hybrid_max

    # F13b n=320 two-variant on primary50 (not CI). One workbook shown; seeds 1-4.
    python tests/RAG/oracle_bench.py --dir primary50 --workbook p50_01_sales_messy.xlsx --n 80 --seed 1 --variants sira_max,hybrid_max --out tests/RAG/results/oracle_cross_primary50_1.json
    python tests/RAG/oracle_bench.py --aggregate-primary50
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
# A generated ask is malformed when it was built on a column name that is not a
# column - the banner-row header bug produced schemas carrying "skip" and an em
# dash, and 28% of asks referenced those. Judged on the column NAME rather than on
# whether the lane answered, so a malformed ask that happens to pass still counts
# as malformed; otherwise the rate would flatter itself.
_JUNK_COLUMN_MARKERS = ("skip", "sheet", "raw", "unnamed", "do not trust", "export dump")


def _is_junk_column(name: object) -> bool:
    s = str(name or "").strip()
    if not s:
        return True
    low = s.lower()
    if low in _JUNK_COLUMN_MARKERS:
        return True
    # A name with no letter or digit at all is punctuation, not an identifier.
    return not any(ch.isalnum() for ch in s)


def _case_is_malformed(case: dict) -> bool:
    names = [case.get("col"), case.get("fcol")]
    numeric = case.get("numeric")
    if isinstance(numeric, dict):
        names.extend(numeric.keys())
    return any(_is_junk_column(n) for n in names if n is not None)


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
            # Ticket #31. This block used to claim it re-derived the header
            # independently while running logic byte-identical to the loader's, so
            # the drift check below compared an opinion with itself and always
            # agreed - including when both picked a banner row. Two implementations
            # of the same wrong assumption are not independent (R-0003).
            #
            # Different SIGNAL, deliberately: the loader decides structurally, by
            # column width. This decides by type transition - the header is the last
            # text row above the first row that reads as data. The two can now
            # actually disagree, which is the only way the drift check means anything.
            probe = list(ws.iter_rows(min_row=1, max_row=12, values_only=True))
            header_row = None
            columns: list[str] = []
            first_data = None
            for i, row in enumerate(probe, start=1):
                vals = [c for c in row if c is not None and str(c).strip()]
                if len(vals) < 2:
                    continue
                numeric = sum(1 for c in vals if isinstance(c, (int, float)) and not isinstance(c, bool))
                # Any numeric at all, not a majority. A real table row is usually
                # mixed - Messy_RAW's first data row is sku, sku, 21169.18, 21169.18,
                # region, so only 2 of 5 are numeric and a majority test never fires.
                # A header row is all text, which is the actual distinguishing signal.
                if numeric >= 1:
                    first_data = i
                    break
            if first_data and first_data > 1:
                for i in range(first_data - 1, 0, -1):
                    if len([c for c in probe[i - 1] if c is not None and str(c).strip()]) >= 2:
                        header_row = i
                        columns = [str(c).strip() if c is not None else "" for c in probe[i - 1]]
                        break
            if header_row is None:
                for i, row in enumerate(probe[:5], start=1):
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


# One list, so a family added here cannot quietly skip the mutation gate in
# tests/test_oracle_schema_link_mutation.py, which iterates this exact tuple.
FAMILIES = (
    "row_range_agg", "row_range_nocol", "filter_agg",
    "filter_count", "combined", "paraphrase", "out_of_range",
)


def generate(path: Path, schema: dict[str, dict], rng: random.Random, n: int) -> list[dict]:
    usable = [
        (s, meta) for s, meta in schema.items()
        if meta["numeric"] and meta["last_data_row"] - meta["first_data_row"] > 30
    ]
    if not usable:
        return []
    cases: list[dict] = []
    families = list(FAMILIES)
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
    if abs(a - b) <= max(TOL, abs(b) * 1e-9):
        return True
    # sheet_sql publishes round(value, 4). Scoring 42.6346 against
    # 42.63461538461539 as a miss makes value accuracy unreadable: every
    # inexact average fails while the lane is doing what it documents.
    return round(float(a), 4) == round(float(b), 4)


def required_links(case: dict) -> tuple[str, set[str]]:
    """Sheet and columns the query must bind to be answering the right question."""
    fam = case["family"]
    cols: set[str] = set()
    if fam in ("row_range_agg", "paraphrase", "out_of_range"):
        cols = {case["col"]} if case.get("col") else set()
    elif fam == "row_range_nocol":
        # No column is named, but the question is not column-free: expected() grades
        # a per_column result over every numeric column, so that is the set the lane
        # has to reach. An empty set here made the check vacuously true (R-0007).
        cols = set(case.get("numeric") or {})
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
        # Nothing came back, so nothing bound. Refusing by not answering is a value
        # outcome, not evidence that the schema was ever resolved.
        return False, "nothing returned"
    linked = got.get("linked") or {}
    note = ""
    if got.get("abstained"):
        # A refusal that bound the right sheet and columns and then found no rows
        # linked the schema correctly - the empty result is the data's answer, not
        # a retrieval failure. Only an unbound refusal counts against recall, so the
        # refusal takes the same sheet + column check as an answer rather than
        # passing on the strength of being a refusal (sheet_sql reports `linked` on
        # the abstain path precisely so this stays checkable).
        if exp.get("value") is not None or exp.get("per_column"):
            return False, "refused although the oracle found rows"
        note = "refused: "
    if linked.get("sheet") != want_sheet:
        return False, f"{note}sheet {linked.get('sheet')!r} != {want_sheet!r}"
    if linked.get("all_numeric"):
        # The lane's "I answered every numeric column" plan. Grading it against the
        # sheet's numeric columns is circular for row_range_nocol, whose required set
        # IS that column list - the comparison is then always true and the branch
        # cannot fail (R-0007 again, one branch deeper than the empty set at
        # required_links). sheet_sql sets all_numeric whenever no column is named,
        # so this is the branch the family actually takes in production.
        #
        # Grade the claim against what came back instead. per_column carries the
        # columns the lane really delivered, so "I answered every numeric column" is
        # checkable evidence rather than self-certification.
        delivered = {c.get("column") for c in (got.get("per_column") or [])}
        delivered.discard(None)
        if delivered:
            missing = want_cols - delivered
            if missing:
                return False, f"{note}all-numeric plan did not deliver {sorted(missing)}"
            return True, f"{note}bound sheet, all numeric columns delivered"
        # An abstention delivers no columns, so there is nothing to grade the claim
        # against; fall back to the sheet's numeric set. Answers always populate
        # per_column, so this path is refusals only.
        numeric = set(case.get("numeric") or ())
        if want_cols <= numeric:
            return True, f"{note}bound sheet, all numeric columns"
        return False, f"{note}all-numeric plan misses {sorted(want_cols - numeric)}"
    bound = {linked.get("metric")} | set(linked.get("filters") or [])
    bound.discard("")
    missing = want_cols - bound
    if missing:
        return False, f"{note}unlinked columns {sorted(missing)}"
    return True, f"{note}sheet + columns bound"


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


CROSS_VARIANTS = ("sira_max", "hybrid_max")
# Bumped whenever link_check changes in a way that moves the numbers. Every
# artifact this file writes carries the stamp; aggregate_cross_pack withholds the
# schema-link figures of any artifact that does not carry the current one, so a
# pre-fix run cannot be quoted by accident.
#   1  original rule - row_range_nocol required no columns and out_of_range
#      short-circuited to True, so both families scored 1.000 by construction.
#   2  RAG-BENCH-16: both families take the same sheet + column check as the rest.
SCHEMA_LINK_RULE = 2
FORBIDDEN_F13_KEYS = (
    "precision@k",
    "recall@k",
    "precision_at_k",
    "recall_at_k",
    "pr_auc",
    "PR-AUC",
    "MAP",
)


def _row_abstained(got: dict | None) -> bool:
    return got is None or bool((got or {}).get("abstained"))


def score_cases(src: Path, cases: list[dict], ask_fn, *, label: str = "") -> list[dict]:
    """Grade one ask function over an already-generated case list.

    Same questions, same oracle, same judge. The only variable is ask_fn.
    """
    rows = []
    prefix = f"{label} " if label else ""
    for i, case in enumerate(cases, start=1):
        exp = expected(src, case)
        t0 = time.time()
        if case["family"] == "paraphrase":
            answers = [ask_fn(v) for v in case["variants"]]
            ok, why = judge(case, exp, answers[0])
            vals = [None if a is None or a.get("abstained") else a.get("value") for a in answers]
            agree = all(close(v, vals[0]) for v in vals)
            if not agree:
                ok, why = False, f"paraphrases disagree: {vals}"
            elif ok:
                why = f"{vals[0]} (3 phrasings agree)"
            got = answers[0]
        else:
            got = ask_fn(case["question"])
            ok, why = judge(case, exp, got)
        ms = round((time.time() - t0) * 1000, 1)
        linked_ok, link_why = link_check(case, exp, got)
        rows.append({
            "family": case["family"], "question": case["question"],
            "ok": ok, "why": why, "ms": ms, "linked_ok": linked_ok, "link_why": link_why,
            "sql": (got or {}).get("sql"), "sheet": (got or {}).get("sheet"),
            "linked": (got or {}).get("linked"),
            "malformed": _case_is_malformed(case),
            "abstained": _row_abstained(got),
        })
        flag = "OK  " if ok else "FAIL"
        if ok and not linked_ok:
            flag = "LUCK"
        print(f"{prefix}[{i}/{len(cases)}] {flag} {case['family']:16} {why[:80]}", flush=True)
        if not ok or not linked_ok:
            print(f"        Q: {case['question']}", flush=True)
            print(f"        link: {link_why}", flush=True)
            print(f"        SQL: {(got or {}).get('sql')}", flush=True)
    return rows


def summarize_f13(rows: list[dict]) -> dict:
    """F13 fields only: value_accuracy, schema_link_accuracy per family,
    malformed_ask_rate, abstention_rate. No pooled schema-link. No IR@k.
    """
    by_family: dict[str, dict] = {}
    for r in rows:
        b = by_family.setdefault(r["family"], {"n": 0, "ok": 0, "linked": 0, "abstained": 0})
        b["n"] += 1
        b["ok"] += 1 if r["ok"] else 0
        b["linked"] += 1 if r["linked_ok"] else 0
        b["abstained"] += 1 if r.get("abstained") else 0
    for _fam, b in by_family.items():
        n = max(1, b["n"])
        b["value_accuracy"] = round(b["ok"] / n, 4)
        b["schema_link_accuracy"] = round(b["linked"] / n, 4)
        b["abstention_rate"] = round(b["abstained"] / n, 4)
    n = max(1, len(rows))
    return {
        "n": len(rows),
        "correct": sum(1 for r in rows if r["ok"]),
        "value_accuracy": round(sum(1 for r in rows if r["ok"]) / n, 4),
        "schema_link_accuracy": {
            fam: by_family[fam]["schema_link_accuracy"] for fam in sorted(by_family)
        },
        "malformed_ask_rate": round(
            sum(1 for r in rows if r.get("malformed")) / n, 4
        ),
        "abstention_rate": round(
            sum(1 for r in rows if r.get("abstained")) / n, 4
        ),
        "by_family": by_family,
        "right_value_wrong_binding": sum(
            1 for r in rows if r["ok"] and not r["linked_ok"]
        ),
    }


def got_from_answer(res: dict | None) -> dict | None:
    """Map rag.answer.answer() onto the sheet_sql-shaped dict the judge expects."""
    if not res or not res.get("ok"):
        return None
    prov = res.get("provenance") or {}
    if str(res.get("lane") or "") == "sql":
        return {
            "abstained": bool(prov.get("abstained")),
            "value": prov.get("value"),
            "per_column": prov.get("per_column"),
            "linked": prov.get("linked") or {},
            "sql": res.get("sql") or prov.get("sql"),
            "sheet": res.get("sheet") or prov.get("sheet"),
            "answer": res.get("answer"),
        }
    text = str(res.get("answer") or "").strip()
    if not text:
        return None
    # Retrieve wrote prose, not a computed KPI. Counting that as a number would
    # be a second grader. Abstain is the honest retrieve-only outcome.
    return {
        "abstained": True,
        "linked": {},
        "value": None,
        "sql": res.get("sql") or "",
        "sheet": None,
        "answer": text,
    }


def ask_sira(space_id: int, question: str, *, depth: str = "max") -> dict | None:
    from rag import answer as rag_answer

    res = rag_answer.answer(
        space_id, question, depth=depth, use_llm=False, use_web=False
    )
    return got_from_answer(res)


def ingest_sira_space(src: Path) -> int:
    import uuid

    from rag import demo_variants, ingest, store

    store.init()
    space = store.create_space(f"oracle-cross-{uuid.uuid4().hex[:8]}")
    sid = int(space["id"])
    res = ingest.ingest_paths(sid, [str(src)])
    if not res.get("ok"):
        raise SystemExit(f"sira_max ingest failed: {res}")
    demo_variants.select_variant(sid, "sira_max")
    print(f"sira_max ingested -> space {sid} (hybrid_sql_lane=False)", flush=True)
    return sid


PRIMARY50_BOOKS = (
    ("p50_01_sales_messy.xlsx", 1, "oracle_cross_primary50_1.json"),
    ("p50_02_ops_messy.xlsx", 2, "oracle_cross_primary50_2.json"),
    ("p50_03_inventory_messy.xlsx", 3, "oracle_cross_primary50_3.json"),
    ("p50_04_mixed_messy.xlsx", 4, "oracle_cross_primary50_4.json"),
)
F13B_POOLED_FLOOR = 0.99
F13B_WORKBOOK_FLOOR = 0.95
F13B_FAMILY_FLOOR = 0.90
F13B_MALFORMED_CEILING = 0.05


def aggregate_cross_pack(payloads: list[dict]) -> dict:
    """Pool two-variant F13 metrics across workbooks. No precision@k.

    Source of truth stays the per-workbook files; this summary is for quoting
    pooled / per-workbook / per-family floors without re-deriving in session.
    """
    if not payloads:
        raise ValueError("no payloads to aggregate")
    # A pooled schema-link number is only meaningful if every source was scored
    # under the rule this file implements today. Anything older is withheld rather
    # than pooled - the alternative is a figure nobody can reproduce.
    stale_rules = sorted(
        {
            str(d.get("schema_link_rule") or "pre-fix")
            for d in payloads
            if d.get("schema_link_rule") != SCHEMA_LINK_RULE
        }
    )
    withheld = "" if not stale_rules else (
        f"scored under schema_link_rule {stale_rules}, current rule is "
        f"{SCHEMA_LINK_RULE}. Re-score the pack - the stored per-family figures "
        "predate RAG-BENCH-16 and are not quotable."
    )
    variants: dict[str, dict] = {}
    workbooks = []
    for data in payloads:
        wb = {
            "workbook": data.get("workbook"),
            "seed": data.get("seed"),
            "n": data.get("n"),
            "header_drift": data.get("header_drift") or [],
            "variants": {},
        }
        for v in data.get("variants") or []:
            name = v.get("name")
            if not name:
                continue
            wb["variants"][name] = {
                "n": v.get("n"),
                "correct": v.get("correct"),
                "value_accuracy": v.get("value_accuracy"),
                "malformed_ask_rate": v.get("malformed_ask_rate"),
                "abstention_rate": v.get("abstention_rate"),
                "schema_link_accuracy": v.get("schema_link_accuracy"),
                "by_family": v.get("by_family"),
            }
            acc = variants.setdefault(
                name,
                {
                    "name": name,
                    "n": 0,
                    "correct": 0,
                    "malformed": 0,
                    "abstained": 0,
                    "by_family": {},
                    "per_workbook": [],
                },
            )
            rows = v.get("rows") or []
            n = int(v.get("n") or (len(rows) if rows else 0))
            acc["n"] += n
            if rows:
                acc["correct"] += sum(1 for r in rows if r.get("ok"))
                acc["malformed"] += sum(1 for r in rows if r.get("malformed"))
                acc["abstained"] += sum(1 for r in rows if r.get("abstained"))
            else:
                acc["correct"] += int(v.get("correct") or 0)
                acc["malformed"] += int(round(float(v.get("malformed_ask_rate") or 0) * n))
                acc["abstained"] += int(round(float(v.get("abstention_rate") or 0) * n))
            acc["per_workbook"].append(
                {
                    "workbook": data.get("workbook"),
                    "seed": data.get("seed"),
                    "n": n,
                    "correct": v.get("correct"),
                    "value_accuracy": v.get("value_accuracy"),
                    "malformed_ask_rate": v.get("malformed_ask_rate"),
                }
            )
            for fam, b in (v.get("by_family") or {}).items():
                slot = acc["by_family"].setdefault(
                    fam, {"n": 0, "ok": 0, "linked": 0, "abstained": 0}
                )
                slot["n"] += int(b.get("n") or 0)
                slot["ok"] += int(b.get("ok") or 0)
                slot["linked"] += int(b.get("linked") or 0)
                slot["abstained"] += int(b.get("abstained") or 0)
        workbooks.append(wb)

    out_variants = []
    for name in CROSS_VARIANTS:
        acc = variants.get(name)
        if not acc:
            continue
        n = max(1, acc["n"])
        by_family = {}
        sla = {}
        for fam, b in acc["by_family"].items():
            fn = max(1, b["n"])
            by_family[fam] = {
                "n": b["n"],
                "ok": b["ok"],
                "linked": b["linked"],
                "abstained": b["abstained"],
                "value_accuracy": round(b["ok"] / fn, 4),
                "schema_link_accuracy": round(b["linked"] / fn, 4),
                "abstention_rate": round(b["abstained"] / fn, 4),
            }
            if withheld:
                by_family[fam]["schema_link_accuracy"] = None
                by_family[fam]["schema_link_withheld"] = withheld
            sla[fam] = by_family[fam]["schema_link_accuracy"]
        out_variants.append(
            {
                "name": name,
                "n": acc["n"],
                "correct": acc["correct"],
                "value_accuracy": round(acc["correct"] / n, 4),
                "malformed_ask_rate": round(acc["malformed"] / n, 4),
                "abstention_rate": round(acc["abstained"] / n, 4),
                "schema_link_accuracy": sla,
                "by_family": by_family,
                "per_workbook": acc["per_workbook"],
            }
        )
    return {
        "ok": True,
        "artifact": "oracle_cross_primary50",
        "pack": "primary50",
        "n": sum(int(w.get("n") or 0) for w in workbooks),
        "workbooks": workbooks,
        "variants": out_variants,
        "schema_link_rule": SCHEMA_LINK_RULE,
        "schema_link_withheld": withheld or None,
        "floors": {
            "pooled_value_accuracy": F13B_POOLED_FLOOR,
            "per_workbook_value_accuracy": F13B_WORKBOOK_FLOOR,
            "per_family_value_accuracy": F13B_FAMILY_FLOOR,
            "malformed_ask_rate": F13B_MALFORMED_CEILING,
            "applies_to": "hybrid_max",
            "sira_max": "retained on the same questions; retrieve-only, no 0.99 floor",
        },
        "honesty": (
            "hybrid_max is the SQL lane on generated asks. sira_max is retrieve-only "
            "(hybrid_sql_lane off, use_llm=False) on the SAME asks. F13 fields only. "
            "No precision@k / recall@k / PR-AUC / MAP."
        ),
    }


def _print_f13(name: str, summary: dict) -> None:
    print(f"\n=== {name} ===", flush=True)
    print(f"  {'family':16} {'value':>9}  {'schema-link':>11}  {'abstain':>8}", flush=True)
    by_family = summary.get("by_family") or {}
    for fam, b in sorted(by_family.items()):
        print(
            f"  {fam:16} {b['ok']:>4}/{b['n']:<4} {b['linked']:>6}/{b['n']:<4} "
            f"{b.get('abstention_rate', 0):>8.3f}",
            flush=True,
        )
    print(f"  value_accuracy          {summary.get('value_accuracy')}", flush=True)
    print(f"  malformed_ask_rate      {summary.get('malformed_ask_rate')}", flush=True)
    print(f"  abstention_rate         {summary.get('abstention_rate')}", flush=True)
    print(
        f"  schema_link_accuracy    {summary.get('schema_link_accuracy')}",
        flush=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workbook", default="frtr_00027_supply-chain-regional.xlsx")
    ap.add_argument("--dir", default="FRTR-bench")
    ap.add_argument("--n", type=int, default=35)
    ap.add_argument("--seed", type=int, default=0, help="0 = fresh questions each run")
    ap.add_argument("--out", default="")
    ap.add_argument(
        "--variants",
        default="",
        help="comma names; empty = single SQL-lane run. F13 A/B: sira_max,hybrid_max",
    )
    ap.add_argument("--space-id", type=int, default=0)
    ap.add_argument(
        "--no-ingest",
        action="store_true",
        help="for sira_max, require --space-id instead of ingesting",
    )
    ap.add_argument(
        "--aggregate-primary50",
        action="store_true",
        help="pool oracle_cross_primary50_{1..4}.json into oracle_cross_primary50.json",
    )
    args = ap.parse_args()

    if args.aggregate_primary50:
        payloads = []
        for _wb, _seed, name in PRIMARY50_BOOKS:
            path = RESULTS / name
            if not path.is_file():
                raise SystemExit(f"missing {path}")
            payloads.append(json.loads(path.read_text(encoding="utf-8")))
        pooled = aggregate_cross_pack(payloads)
        out = Path(args.out) if args.out else RESULTS / "oracle_cross_primary50.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        pooled["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        pooled["corpus"] = (
            "tests/RAG/primary50 seeded equivalent. The 2026-08-26 primary50 "
            "workbooks were gitignored and are not in this clone, so this pack "
            "is not those bytes and not those asks."
        )
        from bench_stamp import write_json
        write_json(out, pooled)
        print(f"pack n={pooled['n']} wrote {out}", flush=True)
        for v in pooled.get("variants") or []:
            _print_f13(f"pack {v['name']}", v)
            print(f"  per_workbook {v.get('per_workbook')}", flush=True)
        return

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
    if not cases:
        raise SystemExit("generator produced 0 cases - workbook has no usable numeric sheets")

    want = [v.strip() for v in args.variants.split(",") if v.strip()]
    RESULTS.mkdir(parents=True, exist_ok=True)

    oracle_note = (
        "openpyxl direct cell reads by spreadsheet row. Shares no code with the "
        "lane AND uses a different header signal: the lane picks by modal body "
        "width, this picks by type transition (last text row above the first row "
        "containing a number). They disagree in both directions on synthetic "
        "sheets, which is what makes the drift check meaningful. Shared residual: "
        "both fall back to the pre-#31 first-wide-row rule when their primary "
        "signal is inconclusive."
    )

    def _ontology_version() -> int:
        from rag import ontology

        return ontology.ONTOLOGY_VERSION

    try:
        from rag import index_fingerprint

        _fp = index_fingerprint.fingerprint(
            table=src.suffix.lower() in {".xlsx", ".xlsm", ".xls", ".csv"},
            extra={"pack": args.dir, "workbook": src.name, "ontology_version": _ontology_version()},
        )
        print(f"  {index_fingerprint.describe(_fp)}", flush=True)
    except Exception as exc:
        _fp = None
        print(f"  [warn] no index fingerprint: {type(exc).__name__}: {exc}", flush=True)

    if want:
        unknown = [n for n in want if n not in CROSS_VARIANTS]
        if unknown:
            raise SystemExit(
                f"unknown variant(s) {unknown}; F13 cross-compare is {','.join(CROSS_VARIANTS)}"
            )
        questions = [c["question"] for c in cases]
        variants_out = []
        sira_space = args.space_id
        for name in want:
            print(f"\n=== variant {name} ===", flush=True)
            if name == "hybrid_max":
                ask_fn = lambda q, _frames=frames: ask(_frames, q)
            else:
                if not sira_space:
                    if args.no_ingest:
                        raise SystemExit("sira_max needs --space-id when --no-ingest is set")
                    sira_space = ingest_sira_space(src)
                else:
                    from rag import demo_variants

                    demo_variants.select_variant(sira_space, "sira_max")
                ask_fn = lambda q, _sid=sira_space: ask_sira(_sid, q)
            rows = score_cases(src, cases, ask_fn, label=name)
            summary = summarize_f13(rows)
            _print_f13(name, summary)
            variant = {
                "name": name,
                "value_accuracy": summary["value_accuracy"],
                "schema_link_accuracy": summary["schema_link_accuracy"],
                "malformed_ask_rate": summary["malformed_ask_rate"],
                "abstention_rate": summary["abstention_rate"],
                "by_family": summary["by_family"],
                "n": summary["n"],
                "correct": summary["correct"],
                "right_value_wrong_binding": summary["right_value_wrong_binding"],
                "rows": rows,
            }
            variants_out.append(variant)

        payload = {
            "ok": True,
            "artifact": "oracle_cross",
            "workbook": src.name,
            "seed": seed,
            "n": len(cases),
            "questions": questions,
            "header_drift": drift,
            "variants": variants_out,
            "schema_link_rule": SCHEMA_LINK_RULE,
            "index_fingerprint": _fp,
            "oracle": oracle_note,
            "honesty": (
                "hybrid_max scores the SQL engine (sheet_sql) on generated asks. "
                "sira_max scores retrieve-only (answer() with hybrid_sql_lane off, "
                "use_llm=False) on the SAME generated asks. F13 metrics only."
            ),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        out = Path(args.out) if args.out else RESULTS / "oracle_cross_latest.json"
        from bench_stamp import write_json
        write_json(out, payload)
        print(f"wrote {out}", flush=True)
        # Named --out must not clobber the n=7 CI smoke at oracle_cross_latest.json.
        # F13b pack runs write oracle_cross_primary50_*.json instead.
        names = [v["name"] for v in variants_out]
        missing = [n for n in CROSS_VARIANTS if n not in names]
        if missing:
            raise SystemExit(f"retained cross artifact missing variants: {missing}")
        return

    rows = score_cases(src, cases, lambda q: ask(frames, q))
    f13 = summarize_f13(rows)
    by_family = f13["by_family"]
    total_ok = f13["correct"]
    total_linked = sum(1 for r in rows if r["linked_ok"])
    lucky = [r for r in rows if r["ok"] and not r["linked_ok"]]

    print("\n=== oracle bench ===", flush=True)
    print(f"  {'family':16} {'value':>9}  {'schema-link':>11}", flush=True)
    for fam, b in sorted(by_family.items()):
        print(f"  {fam:16} {b['ok']:>4}/{b['n']:<4} {b['linked']:>6}/{b['n']:<4}", flush=True)
    print(f"  {'TOTAL':16} {total_ok:>4}/{len(rows):<4} {total_linked:>6}/{len(rows):<4}", flush=True)
    print(f"  value accuracy   {f13['value_accuracy']}", flush=True)
    print(f"  schema-link rec. {round(total_linked / max(1, len(rows)), 4)}", flush=True)
    print(f"  abstention_rate  {f13['abstention_rate']}", flush=True)
    if lucky:
        print(f"  !! {len(lucky)} right-value-wrong-binding (coincidence, not a pass)", flush=True)
    if total_ok == len(rows) and rows:
        print(f"  0 failures in {len(rows)} -> true error rate bounded at "
              f"{round(3 / len(rows) * 100, 1)}% (95%), not 0%", flush=True)

    payload = {
        "ok": True, "workbook": src.name, "seed": seed, "n": len(rows),
        "correct": total_ok, "accuracy": f13["value_accuracy"],
        "schema_link_recall": round(total_linked / max(1, len(rows)), 4),
        "schema_link_rule": SCHEMA_LINK_RULE,
        "right_value_wrong_binding": len(lucky),
        "by_family": by_family, "header_drift": drift, "rows": rows,
        "malformed_asks": sum(1 for r in rows if r.get("malformed")),
        "malformed_ask_rate": f13["malformed_ask_rate"],
        "abstention_rate": f13["abstention_rate"],
        "index_fingerprint": _fp,
        "oracle": oracle_note,
    }
    out = Path(args.out) if args.out else RESULTS / "oracle_bench_latest.json"
    from bench_stamp import write_json
    write_json(out, payload)
    print(f"wrote {out}", flush=True)
    if total_ok != len(rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

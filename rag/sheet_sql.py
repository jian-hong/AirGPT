"""Schema-aware SELECT-only filter -> aggregate over ingested workbook sheets.

`tests/RAG/frtr_sql_baseline.answer_sqlish` answers a fixed catalogue of KPI shapes
by regex ("total refund", "open POs", warehouse Top-N). That catalogue cannot answer
"the average OnTimeSLA for all base rate above 1", and adding one more regex for
OnTimeSLA would leave the next filter+aggregate KPI just as broken.

This module resolves the ask against the *schema* instead: it matches column names
mentioned in the question to real columns across the ingested sheets, reads the
aggregate and the comparison out of the question, picks the sheet that can actually
satisfy both, and runs the aggregate. Every operation is a read - the emitted SQL is
provenance for the founder, not something we execute against a database.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Aggregate wording -> SQL function. Order matters: longer phrases first so
# "how many" is not shadowed by "many".
_AGGS: list[tuple[str, str]] = [
    (r"how many|number of|count of|\bcount\b", "COUNT"),
    (r"\baverage\b|\bavg\b|\bmean\b", "AVG"),
    (r"\btotal\b|\bsum\b|\bcombined\b", "SUM"),
    (r"\bmaximum\b|\bhighest\b|\blargest\b|\bgreatest\b|\bmax\b", "MAX"),
    (r"\bminimum\b|\blowest\b|\bsmallest\b|\bmin\b", "MIN"),
]

# Comparison wording -> SQL operator. Longer phrases first, again.
_CMPS: list[tuple[str, str]] = [
    (r"greater than or equal to|no less than|at least|>=", ">="),
    (r"less than or equal to|no more than|at most|<=", "<="),
    (r"greater than|more than|larger than|higher than|above|over|exceeds?|>", ">"),
    (r"less than|fewer than|smaller than|lower than|below|under|<", "<"),
    (r"equal to|equals|is exactly|==|=", "="),
]

_NUM = r"(-?\d+(?:\.\d+)?)"

# A column name shorter than this matches too much ("id" inside "identify").
_MIN_COL_CHARS = 4


@dataclass
class Filter:
    column: str
    op: str
    value: float

    def sql(self) -> str:
        return f"{_quote(self.column)} {self.op} {_fmt_num(self.value)}"


@dataclass
class Plan:
    agg: str
    metric: str
    filters: list[Filter] = field(default_factory=list)
    sheet: str = ""
    workbook: str = ""
    score: float = 0.0

    def sql(self) -> str:
        where = ""
        if self.filters:
            where = " WHERE " + " AND ".join(f.sql() for f in self.filters)
        target = "*" if self.agg == "COUNT" and not self.metric else _quote(self.metric)
        return f"SELECT {self.agg}({target}) FROM {_quote(self.sheet)}{where}"


def _quote(name: str) -> str:
    return f'"{name}"' if re.search(r"\W", name or "") else (name or "")


def _fmt_num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def _norm_with_map(text: str) -> tuple[str, list[int]]:
    """Alphanumeric-only lowercase text, plus each kept char's original index.

    Lets "base rate" in the question match a `BaseRate` column while still knowing
    where in the original string the match landed, so nearby words (the aggregate,
    the comparison) can be read off.
    """
    chars: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text or ""):
        if ch.isalnum():
            chars.append(ch.lower())
            idx.append(i)
    return "".join(chars), idx


def _norm(text: str) -> str:
    return "".join(ch.lower() for ch in (text or "") if ch.isalnum())


def _mentions(question: str, column: str) -> list[tuple[int, int]]:
    """Original-string (start, end) spans where `column` is named in `question`."""
    cn = _norm(column)
    if len(cn) < _MIN_COL_CHARS:
        return []
    qn, idx = _norm_with_map(question)
    spans: list[tuple[int, int]] = []
    start = qn.find(cn)
    while start != -1:
        spans.append((idx[start], idx[start + len(cn) - 1] + 1))
        start = qn.find(cn, start + 1)
    return spans


def _agg_before(question: str, pos: int, floor: int = 0, *, window: int = 40) -> str | None:
    """Aggregate keyword in the run-up to a column mention ("average OnTimeSLA").

    `floor` is where the previous column mention ended - the aggregate belongs to
    whichever column it sits closest in front of, so the search never reaches back
    past another column name.
    """
    start = max(floor, pos - window, 0)
    lead = question[start:pos].lower()
    best: tuple[int, str] | None = None
    for pattern, fn in _AGGS:
        for m in re.finditer(pattern, lead):
            if best is None or m.start() > best[0]:
                best = (m.start(), fn)
    return best[1] if best else None


def _filter_after(question: str, end: int, ceiling: int | None = None) -> tuple[str, float] | None:
    """Comparison + number just after a column mention ("base rate above 1").

    `ceiling` is where the next column mention begins. Without it a scan started at
    OnTimeSLA in "average OnTimeSLA where BaseRate > 1" runs straight through the
    next column name and claims `> 1` as OnTimeSLA's own filter, which loses the
    metric entirely. Filler words ("is", "that are", "where") are allowed in
    between; another column name is not.
    """
    stop = len(question) if ceiling is None else ceiling
    tail = question[end:stop].lower()
    for pattern, op in _CMPS:
        m = re.search(rf"^\W*(?:{pattern})\s*{_NUM}", tail)
        if m:
            return op, float(m.group(1))
    # "BaseRate is above 1" / "where BaseRate exceeds 1" carry filler words.
    for pattern, op in _CMPS:
        m = re.search(rf"^[a-z\s,'()]{{0,20}}(?:{pattern})\s*{_NUM}", tail)
        if m:
            return op, float(m.group(1))
    return None


def _numeric_ratio(series: Any) -> float:
    import pandas as pd

    vals = pd.to_numeric(series, errors="coerce")
    return float(vals.notna().mean()) if len(vals) else 0.0


def plan_query(question: str, frames: dict[tuple[str, str], Any]) -> Plan | None:
    """Best filter->aggregate plan across every (workbook, sheet) we have ingested.

    `frames` maps (workbook name, sheet name) -> DataFrame. Returns None when the
    question does not name an aggregate over a column we actually hold - abstaining
    is correct here, the retrieve lane still gets its turn.
    """
    q = question or ""
    if not q.strip() or not frames:
        return None
    # No aggregate word anywhere means this is not a KPI ask; do not guess one.
    if not any(re.search(p, q.lower()) for p, _ in _AGGS):
        return None

    best: Plan | None = None
    for (wb_name, sheet_name), df in frames.items():
        if df is None or not len(df) or df.empty:
            continue
        # Every column mention on this sheet, in the order the founder wrote them.
        # Longer names win an overlap so `OnTime` cannot steal `OnTimeSLA`.
        mentions: list[tuple[int, int, str]] = []
        for col in df.columns:
            name = str(col)
            for start, end in _mentions(q, name):
                mentions.append((start, end, name))
        mentions.sort(key=lambda m: (m[0], -(m[1] - m[0])))
        kept: list[tuple[int, int, str]] = []
        for start, end, name in mentions:
            if kept and start < kept[-1][1]:
                continue
            kept.append((start, end, name))
        if not kept:
            continue

        metric: str | None = None
        metric_agg: str | None = None
        filters: list[Filter] = []
        for i, (start, end, name) in enumerate(kept):
            prev_end = kept[i - 1][1] if i else 0
            next_start = kept[i + 1][0] if i + 1 < len(kept) else None
            got = _filter_after(q, end, next_start)
            if got and _numeric_ratio(df[name]) >= 0.6:
                op, value = got
                filters.append(Filter(column=name, op=op, value=value))
                continue
            if metric is None:
                fn = _agg_before(q, start, prev_end)
                if fn and (fn == "COUNT" or _numeric_ratio(df[name]) >= 0.6):
                    metric, metric_agg = name, fn

        # "how many carriers have BaseRate above 3" names no metric column - that is
        # a COUNT(*) over the filtered rows, not a failure to understand the ask.
        if metric is None and filters and re.search(_AGGS[0][0], q.lower()):
            metric, metric_agg = "", "COUNT"

        if metric_agg is None:
            continue
        # A bare aggregate with no filter is already served by the existing KPI
        # catalogue; this lane exists for the filter+aggregate shape it cannot do.
        if not filters and metric_agg != "COUNT":
            continue
        # Prefer the sheet that matched the most named columns, then the one with
        # real depth - Summary-style rollups are small and are exactly the trap.
        named = len({name for _, _, name in kept})
        score = named * 10.0 + min(len(df), 100000) / 100000.0
        cand = Plan(
            agg=metric_agg,
            metric=metric,
            filters=filters,
            sheet=sheet_name,
            workbook=wb_name,
            score=score,
        )
        if best is None or cand.score > best.score:
            best = cand
    return best


def run_plan(plan: Plan, df: Any) -> dict | None:
    """Execute a plan as reads only. Returns None if the sheet cannot satisfy it."""
    import pandas as pd

    if df is None or df.empty:
        return None
    work = df
    for f in plan.filters:
        if f.column not in work.columns:
            return None
        col = pd.to_numeric(work[f.column], errors="coerce")
        if f.op == ">":
            mask = col > f.value
        elif f.op == ">=":
            mask = col >= f.value
        elif f.op == "<":
            mask = col < f.value
        elif f.op == "<=":
            mask = col <= f.value
        else:
            mask = col == f.value
        work = work[mask.fillna(False)]

    rows_matched = int(len(work))
    if plan.agg == "COUNT" and not plan.metric:
        value: float = float(rows_matched)
    else:
        if plan.metric not in work.columns:
            return None
        vals = pd.to_numeric(work[plan.metric], errors="coerce").dropna()
        if plan.agg == "COUNT":
            value = float(len(vals))
        elif not len(vals):
            # Filter matched nothing, or the column held no numbers. Say so rather
            # than reporting 0 as if it were a measurement.
            return {
                "ok": False,
                "reason": "no rows matched the filter",
                "sql": plan.sql(),
                "sheet": plan.sheet,
                "workbook": plan.workbook,
                "rows_matched": rows_matched,
                "rows_total": int(len(df)),
            }
        elif plan.agg == "AVG":
            value = float(vals.mean())
        elif plan.agg == "SUM":
            value = float(vals.sum())
        elif plan.agg == "MAX":
            value = float(vals.max())
        else:
            value = float(vals.min())

    return {
        "ok": True,
        "value": value,
        "agg": plan.agg,
        "metric": plan.metric,
        "sheet": plan.sheet,
        "workbook": plan.workbook,
        "sql": plan.sql(),
        "rows_matched": rows_matched,
        "rows_total": int(len(df)),
    }


def _round(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    text = f"{value:,.4f}".rstrip("0").rstrip(".")
    return text or "0"


def answer_filter_aggregate(question: str, frames: dict[tuple[str, str], Any]) -> dict | None:
    """Locate the workbook/sheet, run the SELECT, and report it with provenance."""
    plan = plan_query(question, frames)
    if plan is None:
        return None
    df = frames.get((plan.workbook, plan.sheet))
    result = run_plan(plan, df)
    if result is None:
        return None
    if not result.get("ok"):
        return {
            "answer": (
                f"No rows in {plan.workbook} / {plan.sheet} match "
                f"{' and '.join(f.sql() for f in plan.filters)}, so "
                f"{plan.agg}({plan.metric}) has nothing to average over.\n\n"
                f"SQL: {result['sql']}"
            ),
            "sql": result["sql"],
            "sheet": plan.sheet,
            "workbook": plan.workbook,
            "abstained": True,
        }

    where = " and ".join(f.sql() for f in plan.filters)
    scope = f" where {where}" if where else ""
    label = {"AVG": "average", "SUM": "total", "COUNT": "count", "MAX": "maximum", "MIN": "minimum"}[plan.agg]
    answer = (
        f"{_round(result['value'])} — the {label} of {plan.metric}{scope}, "
        f"over {result['rows_matched']:,} of {result['rows_total']:,} rows on the "
        f"{plan.sheet} sheet of {plan.workbook}.\n\n"
        f"SQL: {result['sql']}"
    )
    return {
        "answer": answer,
        "value": result["value"],
        "sql": result["sql"],
        "sheet": plan.sheet,
        "workbook": plan.workbook,
        "rows_matched": result["rows_matched"],
        "rows_total": result["rows_total"],
        "abstained": False,
    }

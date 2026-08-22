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

# Below this, a column name is only honoured as a STANDALONE WORD. The danger the
# old blanket cutoff guarded against is real - "id" must not match inside
# "identify" - but banning short names by length threw out every legitimate one
# with them. `qty`, `sku` and `bin` were invisible to the lane, so "sum
# sales_value_myr where qty at least 35" bound no filter, the plan bailed, and the
# whole filter_agg family returned no answer at all (37 of 48 asks).
#
# Same root-cause class as the banner-row header (#31) and the sheet name binding a
# column: match without excluding the non-target case. Exclude the case - an
# embedded substring - rather than the whole population (R-0004).
_MIN_COL_CHARS = 4
# Under two characters a name is a single letter and carries no signal worth the risk.
_MIN_COL_CHARS_ABS = 2


# "rows 330 to 660", "row 330-660", "between rows 330 and 660", "rows 330 through 660"
_ROW_RANGE = re.compile(
    r"\brows?\s*"
    r"(?:from\s+)?(\d{1,7})"
    r"\s*(?:\-|–|—|to|through|thru|until|and)\s*"
    r"(?:row\s*)?(\d{1,7})",
    re.I,
)
_ROW_RANGE_BETWEEN = re.compile(
    r"\bbetween\s+rows?\s*(\d{1,7})\s*and\s*(?:row\s*)?(\d{1,7})", re.I
)


@dataclass
class Filter:
    column: str
    op: str
    value: float

    def sql(self) -> str:
        return f"{_quote(self.column)} {self.op} {_fmt_num(self.value)}"


@dataclass
class RowRange:
    """An inclusive span of *spreadsheet* rows, as the founder sees them in Excel."""

    start: int
    end: int

    def sql(self) -> str:
        return f"_excel_row BETWEEN {self.start} AND {self.end}"


def parse_row_range(question: str) -> RowRange | None:
    m = _ROW_RANGE_BETWEEN.search(question or "") or _ROW_RANGE.search(question or "")
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if a > b:
        a, b = b, a
    return RowRange(start=a, end=b)


@dataclass
class Plan:
    agg: str
    metric: str
    filters: list[Filter] = field(default_factory=list)
    sheet: str = ""
    workbook: str = ""
    score: float = 0.0
    rows: RowRange | None = None
    # When the ask gives a row range and an aggregate but names no column, the
    # honest reading is "aggregate every numeric column over those rows".
    all_numeric: bool = False
    # Columns a single question word could equally have meant. Non-empty means the
    # ask is under-specified and the plan must not be executed.
    ambiguous: list[str] = field(default_factory=list)

    def _where(self) -> str:
        parts = [f.sql() for f in self.filters]
        if self.rows:
            parts.append(self.rows.sql())
        return (" WHERE " + " AND ".join(parts)) if parts else ""

    def sql(self) -> str:
        target = "*" if self.agg == "COUNT" and not self.metric else _quote(self.metric)
        return f"SELECT {self.agg}({target}) FROM {_quote(self.sheet)}{self._where()}"

    def sql_for(self, column: str) -> str:
        return f"SELECT {self.agg}({_quote(column)}) FROM {_quote(self.sheet)}{self._where()}"


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


def _mentions(question: str, column: str, *, bounded: bool = False) -> list[tuple[int, int]]:
    """Original-string (start, end) spans where `column` is named in `question`.

    `bounded` requires the match to begin at a word boundary in the original text.
    Without it, "total TotalShipments" reads as a mention of the Shipments *sheet*,
    which sends the whole query to the wrong 200k-row table.
    """
    cn = _norm(column)
    if len(cn) < _MIN_COL_CHARS_ABS:
        return []
    # A short name is accepted only when it stands alone on BOTH sides, so "qty" in
    # "where qty at least 35" is a mention and "id" in "identify" is not.
    standalone_only = len(cn) < _MIN_COL_CHARS
    qn, idx = _norm_with_map(question)
    spans: list[tuple[int, int]] = []
    start = qn.find(cn)
    while start != -1:
        s, e = idx[start], idx[start + len(cn) - 1] + 1
        left_free = s == 0 or not question[s - 1].isalnum()
        right_free = e >= len(question) or not question[e].isalnum()
        if (not bounded or left_free) and (not standalone_only or (left_free and right_free)):
            spans.append((s, e))
        start = qn.find(cn, start + 1)
    return spans


_SHEET_SELECTOR_BEFORE = re.compile(r"\b(?:on|in|from|of)\s+(?:the\s+)?$", re.I)
_SHEET_SELECTOR_AFTER = re.compile(r"^\s*(?:sheet|tab|worksheet)\b", re.I)


def _in_sheet_selector_position(question: str, start: int, end: int) -> bool:
    """Is this mention being used to CHOOSE a sheet rather than name a column?

    "on Sales", "in the Sales sheet", "Sales tab" select a sheet. A bare mention
    inside a longer phrase - "sum total shipments" - does not, which is why this
    asks about position instead of just matching the name.
    """
    return bool(
        _SHEET_SELECTOR_BEFORE.search(question[:start])
        or _SHEET_SELECTOR_AFTER.match(question[end:])
    )


def _resolve_mentions(question: str, columns: set[str]) -> list[tuple[int, int, str]]:
    """Non-overlapping column mentions, longest match winning at each position.

    Resolved across *every* sheet at once. Done per sheet, `OnTime` on a 200k-row
    Shipments sheet and `OnTimeSLA` on a 5k-row Carriers sheet never compete, so
    "on time sla" matches both and the bigger sheet wins on row count alone - the
    query then answers about the wrong column entirely.
    """
    found: list[tuple[int, int, str]] = []
    for name in columns:
        for start, end in _mentions(question, name):
            found.append((start, end, name))
    found.sort(key=lambda m: (m[0], -(m[1] - m[0])))
    kept: list[tuple[int, int, str]] = []
    for start, end, name in found:
        if kept and start < kept[-1][1]:
            continue
        kept.append((start, end, name))
    return kept


_STOPWORDS = {
    "what", "which", "there", "these", "those", "give", "show", "find", "tell",
    "rows", "row", "from", "where", "with", "that", "have", "many", "much",
    "than", "then", "above", "below", "over", "under", "least", "most", "between",
    "sheet", "column", "value", "values", "total", "count", "average", "mean",
    "maximum", "minimum", "highest", "lowest", "largest", "smallest", "sum",
    "please", "about", "into", "does", "this", "them", "only", "all", "for",
    "the", "and", "its",
}


def _reverse_candidates(question: str, df: Any, *, numeric_only: bool = True) -> dict[str, list[str]]:
    """Question word -> columns whose *name contains* that word.

    Column-name-in-question matching is one-directional: it finds `AvgCost` when
    the founder writes "AvgCost" or "avg cost", and misses it entirely when they
    write "the cost". Matching the other way round as well is what the schema
    linking literature calls bidirectional linking, and it is the single cheapest
    recall win available - unmatched columns are the dominant text-to-SQL failure.

    Ambiguity is preserved, not resolved by guessing: "cost" on a sheet holding
    both `AvgCost` and `CostUSD` returns both, and the caller declines to answer.
    """
    out: dict[str, list[str]] = {}
    words = {
        w for w in re.findall(r"[a-z]{4,}", (question or "").lower())
        if w not in _STOPWORDS
    }
    if not words:
        return out
    for col in df.columns:
        name = str(col)
        if numeric_only and _numeric_ratio(df[col]) < 0.6:
            continue
        cn = _norm(name)
        for w in words:
            # Only count it when the question word is a real component of the
            # column name, not an incidental letter run.
            if w in cn and len(w) >= max(4, len(cn) // 3):
                out.setdefault(w, [])
                if name not in out[w]:
                    out[w].append(name)
    return out


def _entity_of(column: str) -> str:
    """Ontology entity for a column name, via the shared hint vocabulary."""
    try:
        from rag.ontology import _ENTITY_HINTS
    except Exception:
        return "Unknown"
    key = _norm(column)
    for tip, kind in _ENTITY_HINTS.items():
        if tip in key:
            return kind
    return "Unknown"


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


def _agg_anywhere(question: str) -> str | None:
    """First aggregate keyword in the ask, wherever it sits.

    Used only when a row range is present and no column is named - "rows 330 to
    660, sum" puts the aggregate after the span, not in front of a column.
    """
    lowered = (question or "").lower()
    best: tuple[int, str] | None = None
    for pattern, fn in _AGGS:
        m = re.search(pattern, lowered)
        if m and (best is None or m.start() < best[0]):
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

    rows = parse_row_range(q)

    # Resolve column mentions once, across all sheets, so the longest name wins
    # globally rather than within whichever sheet happens to be iterated first.
    all_columns: set[str] = set()
    for _key, _df in frames.items():
        if _df is not None and not _df.empty:
            all_columns.update(str(c) for c in _df.columns)
    global_kept = _resolve_mentions(q, all_columns)

    # If the ask names a sheet, that beats every other signal - row 330 and a
    # column called OnTime exist on more than one sheet, the sheet name does not.
    # But a sheet name sitting *inside* a column mention is not a reference to the
    # sheet: "sum total shipments" names the TotalShipments column, not the
    # Shipments sheet, and reading it as the sheet sends the query somewhere the
    # column does not even exist. Longest column match wins, then longest sheet.
    named_sheet = ""
    named_sheet_spans: list[tuple[int, int]] = []
    for (_wb, sheet_name), _df in frames.items():
        for start, end in _mentions(q, sheet_name, bounded=True):
            covered = any(cs <= start and end <= ce for cs, ce, _c in global_kept)
            # A mention in selector position ("on Sales", "the Sales sheet") is the
            # sheet even when a column shares the name exactly. Without this the
            # covered test hands the whole phrase to the column, `named_sheet` stays
            # empty, the reverse-direction guard below never runs, and "on Sales,
            # average" silently becomes AVG(sales) - the same narrowing that guard
            # was added to stop, reappearing on a schema where sheet and column
            # names collide (R-0004: fix the class, not the one shape).
            if (not covered or _in_sheet_selector_position(q, start, end)) and len(
                sheet_name
            ) > len(named_sheet):
                named_sheet = sheet_name
                named_sheet_spans = [
                    (s, e)
                    for s, e in _mentions(q, sheet_name, bounded=True)
                    if not any(cs <= s and e <= ce for cs, ce, _c in global_kept)
                    or _in_sheet_selector_position(q, s, e)
                ]

    best: Plan | None = None
    for (wb_name, sheet_name), df in frames.items():
        if df is None or not len(df) or df.empty:
            continue
        if named_sheet and sheet_name != named_sheet:
            continue
        own = {str(c) for c in df.columns}
        kept = [m for m in global_kept if m[2] in own]
        # Drop column mentions that ARE the sheet selector. "on Sales, average" on a
        # sheet that also has a `sales` column must report every numeric column, not
        # silently narrow to the one whose name happens to match the sheet.
        if named_sheet_spans:
            kept = [
                m
                for m in kept
                if not any(ss <= m[0] and m[1] <= se for ss, se in named_sheet_spans)
            ]
        # An ask can legitimately name no column directly - "rows 330 to 660, sum"
        # gives a span instead, and "the average cost" names a column only in the
        # reverse direction. Bail out only when there is no route at all.
        if not kept and not rows and not _reverse_candidates(q, df):
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

        # Nothing bound by name. Try the reverse direction - a question word that
        # is a component of a column name ("cost" -> AvgCost) - before giving up.
        ambiguous: list[str] = []
        if metric is None:
            bound_as_filter = {f.column for f in filters}
            cands = {
                w: [c for c in cols if c not in bound_as_filter]
                for w, cols in _reverse_candidates(q, df).items()
            }
            # A column already carrying the comparison is not also the thing being
            # aggregated: "average sla where base rate above 1" must not quietly
            # become AVG(BaseRate) just because "base" matched something.
            cands = {w: cols for w, cols in cands.items() if cols}
            # The words that SELECTED the sheet are not also naming a column.
            # "select rows 285 to 328 on Sales, average" names no column, but
            # "Sales" reverse-matched sales_value_myr, so the ask silently became
            # AVG(sales_value_myr) instead of reporting every numeric column. Drop a
            # word only when its every mention sits inside the sheet-name match, so
            # "average sales on Sales" still binds the column on its other mention
            # (R-0005 - this must not refuse an ask that really does name it).
            if named_sheet_spans:
                cands = {
                    w: cols
                    for w, cols in cands.items()
                    if not all(
                        any(ss <= s and e <= se for ss, se in named_sheet_spans)
                        for s, e in (_mentions(q, w) or [(-1, -1)])
                    )
                }
            for word, cols in sorted(cands.items()):
                if len(cols) > 1:
                    # Same word fits several columns. Naming one would be a guess.
                    ambiguous = sorted(cols)
                    continue
                col = cols[0]
                spans = _mentions(q, word)
                fn = None
                for start, _end in spans:
                    fn = _agg_before(q, start) or _agg_anywhere(q)
                    break
                if fn:
                    metric, metric_agg = col, fn
                    break

        # "how many carriers have BaseRate above 3" names no metric column - that is
        # a COUNT(*) over the filtered rows, not a failure to understand the ask.
        if metric is None and (filters or rows) and re.search(_AGGS[0][0], q.lower()):
            metric, metric_agg = "", "COUNT"

        if metric is None and ambiguous and not rows:
            # Say which columns it could have meant rather than picking one.
            return Plan(
                agg=_agg_anywhere(q) or "SUM", metric="", sheet=sheet_name,
                workbook=wb_name, score=0.0, ambiguous=ambiguous,
            )

        # "select rows 330 to 660, sum" gives a span and an aggregate but names no
        # column. Aggregating every numeric column is the reading that answers it
        # without inventing which column was meant.
        all_numeric = False
        if metric_agg is None and rows:
            fn = _agg_anywhere(q)
            if fn:
                metric, metric_agg, all_numeric = "", fn, fn != "COUNT"

        if metric_agg is None:
            continue
        # A bare aggregate with no filter is already served by the existing KPI
        # catalogue; this lane exists for the filter+aggregate shape it cannot do.
        if not filters and not rows and metric_agg != "COUNT":
            continue
        # Prefer the sheet that matched the most named columns, then the one with
        # real depth - Summary-style rollups are small and are exactly the trap.
        named = len({name for _, _, name in kept})
        score = named * 10.0 + min(len(df), 100000) / 100000.0
        if named_sheet and sheet_name == named_sheet:
            score += 50.0
        cand = Plan(
            agg=metric_agg,
            metric=metric or "",
            filters=filters,
            sheet=sheet_name,
            workbook=wb_name,
            score=score,
            rows=rows,
            all_numeric=all_numeric,
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
    row_note = ""
    if plan.rows:
        # df row 0 is not spreadsheet row 1 - these sheets carry a banner above the
        # header, so the offset is read off the sheet rather than assumed.
        first = int(df.attrs.get("first_data_excel_row") or 2)
        lo = plan.rows.start - first
        hi = plan.rows.end - first
        total = len(df)
        clipped_lo, clipped_hi = max(0, lo), min(total - 1, hi)
        if clipped_lo > clipped_hi:
            return {
                "ok": False,
                "reason": (
                    f"rows {plan.rows.start}-{plan.rows.end} are outside {plan.sheet}, "
                    f"which holds data in spreadsheet rows {first}-{first + total - 1}"
                ),
                "sql": plan.sql(),
                "sheet": plan.sheet,
                "workbook": plan.workbook,
                "rows_matched": 0,
                "rows_total": total,
            }
        work = work.iloc[clipped_lo : clipped_hi + 1]
        row_note = (
            f"spreadsheet rows {clipped_lo + first}-{clipped_hi + first} "
            f"(data rows {clipped_lo + 1}-{clipped_hi + 1} of {total})"
        )
        if (lo, hi) != (clipped_lo, clipped_hi):
            row_note += f"; asked for {plan.rows.start}-{plan.rows.end}, clipped to the data"

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

    # No column named: aggregate every numeric column over the selected rows.
    if plan.all_numeric:
        per_column: list[dict] = []
        for col in work.columns:
            vals = pd.to_numeric(work[col], errors="coerce")
            if not len(vals) or vals.notna().mean() < 0.6:
                continue
            vals = vals.dropna()
            if not len(vals):
                continue
            agg = {
                "SUM": vals.sum(),
                "AVG": vals.mean(),
                "MAX": vals.max(),
                "MIN": vals.min(),
                "COUNT": len(vals),
            }[plan.agg]
            per_column.append({"column": str(col), "value": float(agg), "sql": plan.sql_for(str(col))})
        if not per_column:
            return {
                "ok": False,
                "reason": f"no numeric columns on {plan.sheet} to {plan.agg.lower()}",
                "sql": plan.sql(),
                "sheet": plan.sheet,
                "workbook": plan.workbook,
                "rows_matched": rows_matched,
                "rows_total": int(len(df)),
            }
        return {
            "ok": True,
            "per_column": per_column,
            "agg": plan.agg,
            "metric": "",
            "sheet": plan.sheet,
            "workbook": plan.workbook,
            "sql": "; ".join(c["sql"] for c in per_column),
            "rows_matched": rows_matched,
            "rows_total": int(len(df)),
            "row_note": row_note,
        }

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
        "row_note": row_note,
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
    if plan.ambiguous:
        opts = ", ".join(plan.ambiguous)
        return {
            "answer": (
                f"That could mean more than one column on the {plan.sheet} sheet of "
                f"{plan.workbook}: {opts}. Name which one and I will run it."
            ),
            "sql": None,
            "sheet": plan.sheet,
            "workbook": plan.workbook,
            "abstained": True,
            "ambiguous": plan.ambiguous,
            "linked": {"sheet": plan.sheet, "workbook": plan.workbook,
                       "metric": "", "filters": [], "all_numeric": False},
        }
    df = frames.get((plan.workbook, plan.sheet))
    result = run_plan(plan, df)
    if result is None:
        return None
    # Reported on the refusal too: a query that bound the right sheet and columns
    # and then legitimately found no rows is a different event from one that never
    # resolved the schema, and only the binding tells them apart.
    linked = {
        "sheet": plan.sheet,
        "workbook": plan.workbook,
        "metric": plan.metric,
        "filters": [f.column for f in plan.filters],
        "all_numeric": plan.all_numeric,
    }

    if not result.get("ok"):
        return {
            "answer": (
                f"Nothing to aggregate in {plan.workbook} / {plan.sheet}: "
                f"{result.get('reason')}.\n\nSQL: {result['sql']}"
            ),
            "sql": result["sql"],
            "sheet": plan.sheet,
            "workbook": plan.workbook,
            "abstained": True,
            "linked": linked,
        }

    label = {"AVG": "average", "SUM": "total", "COUNT": "count", "MAX": "maximum", "MIN": "minimum"}[plan.agg]
    where = " and ".join(f.sql() for f in plan.filters)
    scope = f" where {where}" if where else ""
    note = result.get("row_note") or ""
    # The row mapping is the part a founder cannot check by eye, so it is stated
    # rather than assumed - "rows 330-660" is not rows 330-660 of the dataframe.
    span = f" across {note}" if note else ""

    if result.get("per_column"):
        lines = [
            f"  {c['column']}: {_round(c['value'])}" for c in result["per_column"]
        ]
        answer = (
            f"{label.capitalize()} over {result['rows_matched']:,} rows"
            f"{span} on the {plan.sheet} sheet of {plan.workbook} "
            f"— no column was named, so every numeric column is reported:\n"
            + "\n".join(lines)
            + f"\n\nSQL: {result['sql']}"
        )
        return {
            "answer": answer,
            "per_column": result["per_column"],
            "sql": result["sql"],
            "sheet": plan.sheet,
            "workbook": plan.workbook,
            "rows_matched": result["rows_matched"],
            "rows_total": result["rows_total"],
            "abstained": False,
            "linked": linked,
        }

    answer = (
        f"{_round(result['value'])} — the {label} of {plan.metric or 'matching rows'}{scope}"
        f"{span}, over {result['rows_matched']:,} of {result['rows_total']:,} rows on the "
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
        "linked": linked,
    }

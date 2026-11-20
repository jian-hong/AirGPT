"""Schema-aware SELECT-only filter -> aggregate over ingested workbook sheets.

`rag.xlsx_sql.answer_sqlish` answers a fixed catalogue of KPI shapes
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

import difflib
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
    (r"!=|<>|not equal to|does not equal|doesn't equal", "!="),
    (r"greater than or equal to|no less than|at least|>=", ">="),
    (r"less than or equal to|no more than|at most|<=", "<="),
    (r"greater than|more than|larger than|higher than|above|over|exceeds?|>", ">"),
    (r"less than|fewer than|smaller than|lower than|below|under|<", "<"),
    (r"equal to|equals|is exactly|==|=|(?:is|are|was)(?=\s*-?\d)", "="),
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
class TextFilter:
    """Column equals one of these words (or, when `negate`, none of them); case and edge
    spaces do not matter."""

    column: str
    values: list[str]
    negate: bool = False

    def sql(self) -> str:
        vals = [v.replace("'", "''") for v in self.values]
        col = _quote(self.column)
        if self.negate:
            body = (
                f"{col} <> '{vals[0]}'" if len(vals) == 1
                else f"{col} NOT IN ({', '.join(repr(v) for v in vals)})"
            )
            # A blank cell is not the excluded value, so it stays in.
            return f"({body} OR {col} IS NULL)"
        if len(vals) == 1:
            return f"{col} = '{vals[0]}'"
        return f"{col} IN ({', '.join(repr(v) for v in vals)})"

    def words(self) -> str:
        if self.negate:
            return f"{self.column} is not " + " and not ".join(self.values)
        return f"{self.column} is " + " or ".join(self.values)


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
    text_filters: list[TextFilter] = field(default_factory=list)
    # "revenue by region" / "which region has the highest total revenue".
    group_by: str = ""
    rank: str = ""  # "desc" | "asc" | "" (show every group)
    # Things the question left open that the plan filled in. They are printed.
    assumed: list[str] = field(default_factory=list)
    # The sheet has the column but none of the asked-for words: report 0 rows.
    no_match: bool = False
    ambiguous_kind: str = "column"  # "value" when a cell value fits several columns
    # Plain-words reason the ask cannot be run as written (a negated value that is not in
    # the data). Non-empty means: say it, calculate nothing.
    refuse: str = ""
    # Sheets the ask named when it named more than one ("North and South").
    named_sheets: list[str] = field(default_factory=list)

    def _where(self) -> str:
        parts = [f.sql() for f in self.filters] + [t.sql() for t in self.text_filters]
        if self.rows:
            parts.append(self.rows.sql())
        return (" WHERE " + " AND ".join(parts)) if parts else ""

    def sql(self) -> str:
        target = "*" if self.agg == "COUNT" and not self.metric else _quote(self.metric)
        if self.group_by:
            g = _quote(self.group_by)
            return (
                f"SELECT {g}, {self.agg}({target}) FROM {_quote(self.sheet)}"
                f"{self._where()} GROUP BY {g}"
            )
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
    # "BaseRate is above 1" / "where BaseRate exceeds 1" carry filler words. "is NOT above
    # 1" among them turns the comparison round: reading it as "above 1" is the opposite rows.
    for pattern, op in _CMPS:
        m = re.search(rf"^([a-z\s,'()]{{0,20}}?)(?:{pattern})\s*{_NUM}", tail)
        if m:
            if re.search(r"\bnot\b|n't\b", m.group(1)):
                op = _NEGATED_OP[op]
            return op, float(m.group(m.lastindex))
    return None


_NEGATED_OP = {">": "<=", ">=": "<", "<": ">=", "<=": ">", "=": "!=", "!=": "="}


def _num(series: Any) -> Any:
    """Series -> floats, the way a person reads a spreadsheet column.

    Text cells such as "1,200", "$1,200.50" and "(300)" (accounting negative) are
    numbers to the founder, and pd.to_numeric turns them all into NaN, which the
    sum then drops without a word. Blanks and real words stay NaN.
    """
    import pandas as pd

    kind = getattr(getattr(series, "dtype", None), "kind", "")
    if kind in ("i", "u", "f"):
        return pd.to_numeric(series, errors="coerce")
    s = series.astype(str).str.strip()
    neg = s.str.match(r"^\(.*\)$")
    s = s.str.replace(r"^\((.*)\)$", r"\1", regex=True)
    s = s.str.replace(r"[,\s$\u20ac\u00a3\u00a5]", "", regex=True)
    out = pd.to_numeric(s, errors="coerce")
    return out.where(~neg, -out)


def _numeric_ratio(series: Any) -> float:
    vals = _num(series)
    # Blank cells say nothing about the column's type, so judge on the filled ones.
    filled = series.notna() & (series.astype(str).str.strip() != "")
    return float(vals[filled].notna().mean()) if filled.any() else 0.0


_NOT_VALUES = {
    "total", "sum", "average", "mean", "count", "max", "min", "all", "none", "nan",
    "null", "other", "others", "number", "highest", "lowest", "each", "per", "by",
    "and", "the", "for", "not", "yes", "no", "is", "in", "of", "or", "a", "an",
}
_GROUP_LEAD = re.compile(r"(?:\bby|\bper|\bfor\s+each|\beach|\bevery|\bwhich|\bwhat)\s+(?:the\s+)?$", re.I)
_RANK_DESC = re.compile(r"\b(highest|most|largest|biggest|greatest|best|top|maximum|max)\b", re.I)
_RANK_ASC = re.compile(r"\b(lowest|least|smallest|fewest|worst|minimum|min)\b", re.I)


def _key(series: Any) -> Any:
    return series.astype(str).str.strip().str.casefold()


def _find_text_filters(
    q: str, df: Any, spans: list[tuple[int, int, str]], skip: set[str]
) -> tuple[list[TextFilter], list[str]]:
    """Words in the question that are cell values of a text column ("North", "Widget").

    Read off the data, not a word list: a value counts only when it stands alone in
    the question (case-insensitive) and is not part of a column name or an aggregate
    word. Returns (filters, ambiguous) where `ambiguous` names value/column pairs the
    question could equally have meant.
    """
    low = q.lower()
    found: dict[str, list[tuple[str, str, int]]] = {}  # value key -> [(col, shown, pos)]
    for col in df.columns:
        name = str(col)
        if name in skip or _numeric_ratio(df[col]) >= 0.6:
            continue
        shown = df[col].dropna().astype(str).str.strip()
        shown = shown[shown != ""].drop_duplicates()
        if len(shown) > 5000:
            continue
        for v in shown:
            k = v.casefold()
            if len(k) < 2 or k in _NOT_VALUES or k in _STOPWORDS:
                continue
            m = re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", low)
            if not m:
                continue
            if any(cs <= m.start() and m.end() <= ce for cs, ce, _c in spans):
                continue
            found.setdefault(k, []).append((name, v, m.start()))
    # Longest value first, so "North East" beats "North"; drop values inside a longer one.
    kept: list[tuple[str, list[tuple[str, str, int]]]] = []
    taken: list[tuple[int, int]] = []
    for k in sorted(found, key=lambda x: -len(x)):
        pos = found[k][0][2]
        if any(a <= pos < b for a, b in taken):
            continue
        taken.append((pos, pos + len(k)))
        kept.append((k, found[k]))
    # Which kept values sit behind "excluding", "except", "not" ... Walk them left to
    # right so "excluding HR and Ops" carries the exclusion over to Ops.
    neg_of: dict[str, bool] = {}
    prev_end, prev_neg = 0, False
    for k, opts in sorted(kept, key=lambda kv: kv[1][0][2]):
        pos = opts[0][2]
        gap = low[prev_end:pos]
        neg = bool(_NEG_CUE.search(gap)) or bool(prev_neg and _LIST_GAP.match(gap))
        neg_of[k] = neg
        prev_end, prev_neg = pos + len(k), neg
    by_col: dict[tuple[str, bool], list[str]] = {}
    ambiguous: list[str] = []
    for k, opts in kept:
        cols = {c for c, _v, _p in opts}
        if len(cols) > 1:
            # Prefer the column the question names right in front of the value.
            named = [
                c for c in cols
                if any(ce <= opts[0][2] and opts[0][2] - ce <= 25 and nm == c
                       for cs, ce, nm in spans)
            ]
            if len(named) == 1:
                cols = set(named)
            else:
                ambiguous.append(f"{opts[0][1]} in " + " or ".join(sorted(cols)))
                continue
        col = next(iter(cols))
        by_col.setdefault((col, neg_of[k]), []).append(next(v for c, v, _p in opts if c == col))
    return [TextFilter(column=c, values=v, negate=n) for (c, n), v in by_col.items()], ambiguous


# "excluding", "except (for)", "without", "other than", "not" ... right in front of a value.
_NEG_CUE = re.compile(
    r"(?:\b(?:excl(?:uding|udes?)?\b\.?|except(?:\s+for)?|without|other\s+than|apart\s+from|"
    r"aside\s+from|besides|but\s+not|ignoring|minus|not|neither)|n['’]t|!=|<>)"
    r"[\s:]*(?:(?:the|any|all|of|in)\s+)?$"
)
_LIST_GAP = re.compile(r"^\s*(?:,|,?\s*(?:and|or|nor))\s*(?:not\s+)?$")
# A word after a cue that makes it something other than a value ("not above 5").
_NEG_SKIP = re.compile(
    r"^(?:including|only|just|more|less|many|much|exactly|equal|equals?|at|a|an|\d|[$€£]|"
    r"(?:" + "|".join(p for p, _ in _CMPS if p[:1].isalpha()) + r")\b)",
    re.I,
)
_NEG_PHRASE = re.compile(
    r"^[\"'‘“]?([^\s,;?!.\"']+(?:\s+(?!(?:and|or|in|on|for|from|where|by|per|across|with|at|of|then)\b)"
    r"[^\s,;?!.\"']+){0,3})",
    re.I,
)


def _unmatched_negation(q: str, frames: dict, spans: list[tuple[int, int, str]]) -> str:
    """Plain-words refusal for "excluding X" when X is not a value in any text column.

    A negation we cannot apply must never turn into a positive filter or a silent
    drop, so the ask stops here and says what it could not do.
    """
    low = q.lower()
    cues = list(re.finditer(
        r"\b(?:excl(?:uding|udes?)?|except(?:\s+for)?|without|other\s+than|apart\s+from|aside\s+from|"
        r"besides|but\s+not|ignoring|minus|not)\b|!=|<>", low))
    if not cues:
        return ""
    values: dict[str, tuple[str, str]] = {}  # casefold value -> (column, shown)
    cols: dict[str, str] = {}
    for df in frames.values():
        if df is None or df.empty:
            continue
        for col in df.columns:
            if _numeric_ratio(df[col]) >= 0.6:
                continue
            cols.setdefault(str(col), str(col))
            for v in df[col].dropna().astype(str).str.strip().drop_duplicates().head(5000):
                if v:
                    values.setdefault(v.casefold(), (str(col), v))
    for m in cues:
        rest = low[m.end():]
        rest = re.sub(r"^[\s:.]*(?:(?:the|any|all|of|in)\s+)?", "", rest)
        if not rest:
            continue
        strong = not m.group(0).startswith(("not", "but", "!=", "<>"))
        if _NEG_SKIP.match(rest) and not (strong and re.match(r"[\d$€£]", rest)):
            continue
        start = m.end() + (len(low[m.end():]) - len(rest))
        on_col = next(((cs, ce) for cs, ce, _n in spans if cs <= start < ce), None)
        if on_col:
            # "excluding Refunds" where Refunds is a column: there is no value to leave
            # out, and dropping the words would hand back the figure with it still in.
            if re.match(r"(?:excl|except|without|minus|other|apart|aside|besides|ignoring)", m.group(0)):
                return (
                    f'I could not apply "{q[m.start():m.end()].strip()} {q[on_col[0]:on_col[1]]}": '
                    f"{q[on_col[0]:on_col[1]]} is a column, not a value I can leave out. I did not calculate anything."
                )
            continue
        word = re.match(r"[a-z0-9À-￿'_-]+", rest)
        if not word or word.group(0) in _STOPWORDS or word.group(0) in _NOT_VALUES:
            continue
        held = [k for k in values if rest.startswith(k) and not rest[len(k):len(k) + 1].isalnum()]
        if held:
            k = max(held, key=len)
            if len(k) < 2:
                return (
                    f'I could not apply "{q[m.start():m.end()].strip()} {values[k][1]}": a one-letter value is '
                    "too short for me to match safely. I did not calculate anything."
                )
            # "excluding Eng and Hrr": the first item is real, so check the rest of the list.
            tail = rest[len(k):]
            while True:
                lg = re.match(r"\s*(?:,|,?\s*(?:and|or|nor))\s*(?:not\s+)?", tail)
                if not lg:
                    break
                tail = tail[lg.end():]
                nxt = [k2 for k2 in values if tail.startswith(k2) and not tail[len(k2):len(k2) + 1].isalnum()]
                if nxt:
                    tail = tail[len(max(nxt, key=len)):]
                    continue
                w = re.match(r"[a-z0-9À-￿'_-]+", tail)
                near2 = difflib.get_close_matches(w.group(0), list(values), n=1, cutoff=0.75) if w else []
                if near2:
                    return (
                        f'I could not apply "{q[m.start():m.end()].strip()} ... {w.group(0)}": there is no such '
                        f"value in {values[near2[0]][0]}. Did you mean {values[near2[0]][1]}? "
                        "I did not calculate anything. Check the spelling and ask again."
                    )
                break
            continue
        # Not a value we hold: name the phrase, and the closest real value if there is one.
        pm = _NEG_PHRASE.match(q[start:])
        said = (pm.group(1) if pm else word.group(0)).strip()
        said = re.split(r"\s+(?:and|or)\s+", said)[0].strip() or word.group(0)
        cue = q[m.start():m.end()].strip()
        near = difflib.get_close_matches(said.casefold(), list(values), n=1, cutoff=0.6)
        named = [n for _s, _e, n in spans if n in cols]
        where = values[near[0]][0] if near else (named[0] if named else "")
        msg = f'I could not apply "{cue} {said}": there is no such value in {where or "the text columns of these tables"}.'
        if near:
            msg += f" Did you mean {values[near[0]][1]}?"
        return msg + " I did not calculate anything. Check the spelling and ask again."
    return ""


_STATED_VALUE = re.compile(
    r"^\s*(?P<op>is|are|=|==|!=|<>|equals?|equal to|:)\s*['\"\u2018\u201c]?(.+?)['\"\u2019\u201d]?"
    r"\s*(?:$|[?.,;!]|\s+(?:and|or|but|for|in|on|from)\b)",
    re.I,
)


def _bind_stated_values(q, df, kept, text_filters, filters, metric):
    """"where Product is Gizmo": the question STATES the value for a text column.

    Values are normally read off the data, which cannot see a value that is not there
    ("Region is Papua") or one too short to trust on its own (a product called "A"). A
    stated filter dropped on either would hand back the unfiltered total as the
    answer. Bind what was stated; a value no row holds then shows as "no rows match".
    """
    by_col = {(t.column, t.negate): t for t in text_filters}
    bound = {f.column for f in filters} | ({metric} if metric else set())
    for start, end, name in kept:
        if name in bound or name not in df.columns or _numeric_ratio(df[name]) >= 0.6:
            continue
        m = _STATED_VALUE.match(q[end:])
        if not m:
            continue
        said = m.group(2).strip()
        # "Dept is not HR" / "Dept != HR": the same column, the value excluded.
        neg = m.group("op") in ("!=", "<>")
        nm_ = re.match(r"^(?:not\s+|!=\s*|<>\s*)(.+)$", said, re.I)
        if nm_:
            neg, said = True, nm_.group(1).strip()
        if not said:
            continue
        vals = df[name].dropna().astype(str).str.strip()
        hit = vals[vals.str.casefold() == said.casefold()]
        shown = hit.iloc[0] if len(hit) else said
        tf = by_col.get((name, neg))
        if tf is None:
            tf = by_col[(name, neg)] = TextFilter(column=name, values=[], negate=neg)
            text_filters = list(text_filters) + [tf]
        if shown.casefold() not in {v.casefold() for v in tf.values}:
            tf.values.append(shown)
    return text_filters


# "how many rows", "number of rows", "row count", "count the Q1 rows": a count of rows, no column.
_ROW_COUNT = re.compile(
    r"\b(?:how\s+many|number\s+of|count(?:\s+of)?)\s+(?:the\s+)?(?:\w+\s+)?rows?\b|\brows?\s+count\b|\bcount\s+(?:the\s+)?(?:\w+\s+)?rows?\b",
    re.I,
)


def plan_query(
    question: str,
    frames: dict[tuple[str, str], Any],
    collect: list[Plan] | None = None,
) -> Plan | None:
    """Best filter->aggregate plan across every (workbook, sheet) we have ingested.

    `frames` maps (workbook name, sheet name) -> DataFrame. Returns None when the
    question does not name an aggregate over a column we actually hold - abstaining
    is correct here, the retrieve lane still gets its turn.
    """
    q = question or ""
    if not q.strip() or not frames:
        return None
    # No aggregate word anywhere means this is not a KPI ask; do not guess one.
    if not any(re.search(p, q.lower()) for p, _ in _AGGS) and not re.search(
        r"\b(?:by|per)\s+[a-z]|\bfor\s+each\b|\beach\b", q.lower()
    ):
        return None

    rows = parse_row_range(q)

    # Resolve column mentions once, across all sheets, so the longest name wins
    # globally rather than within whichever sheet happens to be iterated first.
    all_columns: set[str] = set()
    for _key, _df in frames.items():
        if _df is not None and not _df.empty:
            all_columns.update(str(c) for c in _df.columns)
    global_kept = _resolve_mentions(q, all_columns)

    # "excluding Hrr": a negation whose value is not in the data. Say so; never guess.
    said = _unmatched_negation(q, frames, global_kept)
    if said:
        (_wb0, _sh0) = next(iter(frames))
        return Plan(agg=_agg_anywhere(q) or "SUM", metric="", sheet=_sh0, workbook=_wb0, refuse=said)

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
            # A csv has one table and its "sheet" is the file name. "how many orders"
            # over orders.csv names the Order column, not a choice of sheet.
            if str(_wb).lower().endswith((".csv", ".tsv")) and not _in_sheet_selector_position(q, start, end):
                continue
            # Overlap, not containment: "how many orders" reads the Order column even
            # though the sheet is called Orders and the match runs one letter longer.
            covered = any(cs < end and start < ce for cs, ce, _c in global_kept)
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

    # "North and South": more than one sheet named. Every one of them is asked, and the
    # words that picked the sheets are not also values to filter on.
    named_set = {named_sheet} if named_sheet else set()
    value_spans = list(global_kept)
    if named_sheet:
        for (_wb, sn), _df in frames.items():
            if sn in named_set:
                continue
            for s0, e0 in _mentions(q, sn, bounded=True):
                if str(_wb).lower().endswith((".csv", ".tsv")) and not _in_sheet_selector_position(q, s0, e0):
                    continue
                if any(cs < e0 and s0 < ce for cs, ce, _c in global_kept) and not _in_sheet_selector_position(q, s0, e0):
                    continue
                if any(ss < e0 and s0 < se for ss, se in named_sheet_spans):
                    continue
                named_set.add(sn)
                named_sheet_spans.append((s0, e0))
                break
        if len(named_set) > 1:
            value_spans += [(a, b, "") for a, b in named_sheet_spans]

    best: Plan | None = None
    for (wb_name, sheet_name), df in frames.items():
        if df is None or not len(df) or df.empty:
            continue
        if named_set and sheet_name not in named_set:
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
        # "how many people work in Ops" names no column, only a value from one.
        row_count = bool(_ROW_COUNT.search(q)) and sheet_name in named_set  # COUNT(*) of the sheet named
        if not kept and not rows and not row_count and not _reverse_candidates(q, df):
            if not (re.search(_AGGS[0][0], q.lower()) and _find_text_filters(q, df, value_spans, set())[0]):
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

        # Words in the question that are values in a text column ("North", "Widget").
        text_filters, ambiguous_values = _find_text_filters(q, df, value_spans, set())
        text_filters = _bind_stated_values(q, df, kept, text_filters, filters, metric)

        # "by region" / "which region has the highest ...": a group-by on a text column.
        group_by, group_lead = "", ""
        _bound = {f.column for f in filters} | ({metric} if metric else set())
        for g_start, g_end, g_name in kept:
            if g_name in _bound or g_name not in df.columns:
                continue
            if _numeric_ratio(df[g_name]) >= 0.6:
                continue
            lead = _GROUP_LEAD.search(q[max(0, g_start - 16):g_start])
            if lead:
                group_by, group_lead = g_name, lead.group(0).split()[0].lower()
                break

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

        # "revenue by region" names the number without an aggregate word. Taking the
        # numeric column the question names is the reading; the sum is announced.
        assumed: list[str] = []
        if metric is None and group_by:
            _num_cols = [
                n for _s, _e, n in kept
                if n not in _bound and n != group_by and _numeric_ratio(df[n]) >= 0.6
            ]
            if not _num_cols:
                _rc = [
                    cols[0] for w, cols in _reverse_candidates(q, df).items()
                    if len(cols) == 1 and cols[0] not in _bound
                ]
                _num_cols = _rc[:1]
            if _num_cols:
                metric, metric_agg = _num_cols[0], _agg_anywhere(q) or "SUM"

        # "how many carriers have BaseRate above 3" names no metric column - that is
        # a COUNT(*) over the filtered rows, not a failure to understand the ask.
        if (
            metric is None
            and (filters or rows or text_filters or group_by or row_count)
            and re.search(_AGGS[0][0], q.lower())
        ):
            metric, metric_agg = "", "COUNT"

        if metric is None and ambiguous and not rows and not group_by:
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
        # A group question ranks or lists groups. "Highest total revenue" is the
        # total per group, then the top one; the word "highest" is not MAX of a row.
        rank = ""
        if group_by:
            if group_lead in ("which", "what"):
                rank = "desc" if _RANK_DESC.search(q) else ("asc" if _RANK_ASC.search(q) else "")
            ql = q.lower()
            if re.search(r"\btotal\b|\bsum\b|\bcombined\b", ql):
                metric_agg = "SUM"
            elif re.search(_AGGS[1][0], ql):
                metric_agg = "AVG"
            elif re.search(_AGGS[0][0], ql):
                metric_agg = "COUNT"
            elif rank or metric_agg is None:
                metric_agg = "SUM"
                assumed.append("added up each group (the question did not say total or average)")
            if metric == "" and metric_agg != "COUNT":
                continue
        if ambiguous_values:
            ambiguous = ambiguous_values
        # Prefer the sheet that matched the most named columns, then the one with
        # real depth - Summary-style rollups are small and are exactly the trap.
        named = len({name for _, _, name in kept})
        score = named * 10.0 + min(len(df), 100000) / 100000.0 + 5.0 * len(text_filters)
        if sheet_name in named_set:
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
            text_filters=text_filters,
            group_by=group_by,
            rank=rank,
            assumed=assumed,
            ambiguous=ambiguous_values,
            ambiguous_kind="value" if ambiguous_values else "column",
            named_sheets=sorted(named_set) if len(named_set) > 1 else [],
        )
        if collect is not None:
            collect.append(cand)
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
        col = _num(work[f.column])
        if f.op == ">":
            mask = col > f.value
        elif f.op == ">=":
            mask = col >= f.value
        elif f.op == "<":
            mask = col < f.value
        elif f.op == "<=":
            mask = col <= f.value
        elif f.op == "!=":
            mask = col != f.value
        else:
            mask = col == f.value
        work = work[mask.fillna(False)]

    for t in plan.text_filters:
        if t.column not in work.columns:
            return None
        hit = _key(work[t.column]).isin({v.strip().casefold() for v in t.values})
        work = work[~hit if t.negate else hit]

    rows_matched = int(len(work))

    # No column named: aggregate every numeric column over the selected rows.
    if plan.all_numeric:
        per_column: list[dict] = []
        for col in work.columns:
            vals = _num(work[col])
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

    pool: dict = {}
    if plan.agg == "COUNT" and not plan.metric:
        value: float = float(rows_matched)
        pool = {"values_used": rows_matched}
    else:
        if plan.metric not in work.columns:
            return None
        cells = work[plan.metric]
        vals = _num(cells).dropna()
        if plan.agg == "COUNT":
            # SQL COUNT(col): filled cells. Counting only numbers made "how many
            # orders" over text ids come out as 0.
            value = float(int((cells.notna() & (cells.astype(str).str.strip() != "")).sum()))
            pool = {"values_used": int(value)}
        elif not len(vals):
            # Filter matched nothing, or the column held no numbers. Say so rather
            # than reporting 0 as if it were a measurement.
            return {
                "ok": False,
                "reason": (
                    "no rows matched the filter" if not rows_matched
                    else f"none of the {rows_matched:,} matching rows has a number in {plan.metric}"
                ),
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
        if plan.agg != "COUNT":
            pool = {
                "values_used": int(len(vals)), "sum": float(vals.sum()),
                "min": float(vals.min()), "max": float(vals.max()),
            }

    return {
        "ok": True,
        "_work": work,
        **pool,
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


def _answer_single(plan: Plan, frames: dict[tuple[str, str], Any]) -> dict | None:
    """One sheet, one figure (or one table of figures), with provenance."""
    if plan.refuse:
        return {
            "answer": plan.refuse, "sql": None, "sheet": plan.sheet, "workbook": plan.workbook,
            "abstained": True, "abstain_reason": plan.refuse,
            "linked": {"sheet": plan.sheet, "workbook": plan.workbook,
                       "metric": "", "filters": [], "all_numeric": False},
        }
    if plan.ambiguous:
        opts = ", ".join(plan.ambiguous)
        what = "a word in your question matches more than one column" if plan.ambiguous_kind == "value" else "That could mean more than one column"
        return {
            "answer": (
                f"{what[0].upper() + what[1:]} on the {plan.sheet} sheet of "
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
    where = _where_words(plan)
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
        f"{span}, over {result['rows_matched']:,} of {result['rows_total']:,} rows on "
        f"{_src(plan.workbook, plan.sheet)}.{_skipped_note(result)}"
        f"{_assumed_note(plan)}\n\n"
        f"SQL: {result['sql']}"
    )
    return {
        "answer": answer,
        "value": round(result["value"], 4),
        "sql": result["sql"],
        "sheet": plan.sheet,
        "workbook": plan.workbook,
        "rows_matched": result["rows_matched"],
        "rows_total": result["rows_total"],
        "abstained": False,
        "linked": linked,
        "operation": plan.agg,
        "filter": where,
        "values_used": result.get("values_used"),
        "assumed": plan.assumed,
        "carry": _carry(plan),
    }


# --------------------------------------------------------------------------------------
# Several sheets / files, group-by, and the plain-words provenance around them.
# --------------------------------------------------------------------------------------


def _carry(plan: Plan) -> dict:
    """What a later short question ("and for South?") needs to repeat this calculation."""
    return {
        "agg": plan.agg,
        "metric": plan.metric,
        "sheet": plan.sheet,
        "workbook": plan.workbook,
        "text": [{"column": t.column, "values": list(t.values), "negate": t.negate} for t in plan.text_filters],
        "num": [{"column": f.column, "op": f.op, "value": f.value} for f in plan.filters],
    }


def _where_words(plan: Plan) -> str:
    parts = [f.sql() for f in plan.filters] + [t.words() for t in plan.text_filters]
    return " and ".join(parts)


def _src(workbook: str, sheet: str) -> str:
    """How to name where a figure came from. A csv has one table: the file is it."""
    wb = str(workbook or "")
    if wb.lower().endswith((".csv", ".tsv")):
        return f"the file {wb}"
    return f"the {sheet} sheet of {wb}"


def _skipped_note(result: dict) -> str:
    used, matched = result.get("values_used"), result.get("rows_matched")
    if isinstance(used, int) and isinstance(matched, int) and used < matched:
        n = matched - used
        return f" {n:,} blank or non-number {'cell was' if n == 1 else 'cells were'} left out."
    return ""


def _assumed_note(plan: Plan) -> str:
    return (" I assumed: " + "; ".join(plan.assumed) + ".") if plan.assumed else ""


_LABEL = {"AVG": "average", "SUM": "total", "COUNT": "count", "MAX": "maximum", "MIN": "minimum"}


def _core_sig(c: Plan) -> tuple:
    return (c.agg, c.metric, tuple(f.sql() for f in c.filters), c.group_by, c.all_numeric)


def _siblings(plan: Plan, cands: list[Plan], frames: dict) -> list[tuple[Plan, bool]]:
    """Every sheet that answers the same question. (plan, no_match) pairs.

    Same aggregate, column and numeric filters. A sheet that lacks the asked-for words
    (no North rows in Q3) is listed as having no matching rows; it must never fall
    back to an unfiltered figure.
    """
    if plan.rows or plan.ambiguous or plan.refuse:
        return [(plan, False)]
    mine = {t.sql() for t in plan.text_filters}
    out: list[tuple[Plan, bool]] = []
    for c in cands:
        if c.rows or c.ambiguous or _core_sig(c) != _core_sig(plan):
            continue
        theirs = {t.sql() for t in c.text_filters}
        if theirs == mine:
            out.append((c, False))
        elif theirs < mine:
            out.append((c, True))
    if not any(c is plan for c, _ in out):
        out.insert(0, (plan, False))
    return out


def _fingerprint(df: Any) -> tuple:
    """Same columns and same rows (numbers compared as numbers) -> same fingerprint.

    The same table uploaded as both orders.xlsx and orders.csv must be counted once
    in a combined figure, not twice.
    """
    import pandas as pd

    cols = []
    for c in df.columns:
        n = _num(df[c])
        filled = df[c].notna() & (df[c].astype(str).str.strip() != "")
        cols.append(n.where(filled & n.notna(), df[c].astype(str).str.strip()).astype(str))
    norm = pd.concat(cols, axis=1) if cols else pd.DataFrame()
    return (tuple(str(c) for c in df.columns), len(df), int(pd.util.hash_pandas_object(norm, index=False).sum()))


def _fmt_rows(res: dict) -> str:
    return f"{res['rows_matched']:,} of {res['rows_total']:,} rows"


def _answer_multi(plan: Plan, sibs: list[tuple[Plan, bool]], frames: dict) -> dict | None:
    import pandas as pd

    label = _LABEL[plan.agg]
    where = _where_words(plan)
    scope = f" where {where}" if where else ""
    metric = plan.metric or "matching rows"
    entries: list[dict] = []
    for c, no_match in sibs:
        df = frames.get((c.workbook, c.sheet))
        if df is None:
            continue
        if no_match:
            entries.append({"plan": c, "ok": False, "none": True, "rows_matched": 0,
                            "rows_total": int(len(df)), "cols": tuple(map(str, df.columns)),
                            "workbook": c.workbook, "sheet": c.sheet, "sql": c.sql()})
            continue
        res = run_plan(c, df)
        if res is None:
            continue
        res = dict(res)
        res["plan"], res["cols"] = c, tuple(map(str, df.columns))
        res["fp"] = _fingerprint(df)
        res.setdefault("workbook", c.workbook)
        res.setdefault("sheet", c.sheet)
        entries.append(res)
    if not entries:
        return None
    lines = []
    for e in entries:
        who = f"{e['sheet']} ({e['workbook']})"
        if e.get("ok"):
            lines.append(f"- {who}: {_round(e['value'])} ({_fmt_rows(e)}){_skipped_note(e)}")
        elif e.get("none"):
            lines.append(f"- {who}: no rows match ({e['rows_total']:,} rows in the sheet)")
        else:
            lines.append(f"- {who}: nothing to {label.lower()} ({e.get('reason')})")
    oks = [e for e in entries if e.get("ok")]
    combined = None
    tail = ""
    if len(oks) >= 2:
        same_shape = len({e["cols"] for e in entries}) == 1
        if same_shape:
            uniq: dict = {}
            for e in oks:
                uniq.setdefault(e["fp"], e)
            dups = len(oks) - len(uniq)
            use = list(uniq.values())
            if plan.agg in ("SUM", "COUNT"):
                combined = sum(e["value"] for e in use)
            elif plan.agg == "AVG":
                n = sum(e["values_used"] for e in use)
                combined = (sum(e["sum"] for e in use) / n) if n else None
            elif plan.agg == "MAX":
                combined = max(e["value"] for e in use)
            else:
                combined = min(e["value"] for e in use)
            if combined is not None:
                used = sum(e["rows_matched"] for e in use)
                tot = sum(e["rows_total"] for e in use)
                if len(use) == 1:
                    lines.append(
                        f"These {len(oks)} hold the same rows, so they are counted once: "
                        f"{_round(combined)} ({used:,} of {tot:,} rows)."
                    )
                else:
                    word = "Both sheets" if len(use) == 2 else f"All {len(use)} sheets"
                    lines.append(f"{word} together: {_round(combined)} ({used:,} of {tot:,} rows).")
                    if dups:
                        lines.append(f"{dups} sheet{'s hold' if dups > 1 else ' holds'} the same rows as another and {'were' if dups > 1 else 'was'} counted once.")
        else:
            tail = (
                "\nThese sheets have different columns, so I did not add them together. "
                "Tell me which one you mean."
            )
    head = f"{label.capitalize()} of {metric}{scope}, on {len(entries)} sheets that fit the question:"
    sql = "; ".join(e["sql"] for e in entries if e.get("sql"))
    answer = head + "\n" + "\n".join(lines) + tail + _assumed_note(plan) + f"\n\nSQL: {sql}"
    rows_matched = sum(e["rows_matched"] for e in oks)
    rows_total = sum(e["rows_total"] for e in entries)
    first = oks[0] if oks else entries[0]
    return {
        "answer": answer,
        "value": round(combined if combined is not None else (oks[0]["value"] if len(oks) == 1 else None), 4)
        if (combined is not None or len(oks) == 1) else None,
        "sql": sql,
        "sheet": ", ".join(e["sheet"] for e in entries),
        "workbook": first["workbook"],
        "rows_matched": rows_matched,
        "rows_total": rows_total,
        "abstained": False,
        "operation": plan.agg,
        "filter": where,
        "assumed": plan.assumed,
        "carry": {**_carry(plan), "sheet": ""},
        "sheets": [
            {"workbook": e["workbook"], "sheet": e["sheet"],
             "value": round(e["value"], 4) if e.get("value") is not None else None, "rows_matched": e["rows_matched"],
             "rows_total": e["rows_total"], "values_used": e.get("values_used"),
             "sql": e.get("sql")}
            for e in entries
        ],
        "linked": {"sheet": first["sheet"], "workbook": first["workbook"], "metric": plan.metric,
                   "filters": [f.column for f in plan.filters] + [t.column for t in plan.text_filters],
                   "all_numeric": False},
    }


def _answer_group(plan: Plan, sibs: list[tuple[Plan, bool]], frames: dict) -> dict | None:
    """'Revenue by region', 'which region has the highest total revenue'."""
    import pandas as pd

    runs = []
    for c, no_match in sibs:
        df = frames.get((c.workbook, c.sheet))
        if df is None or no_match:
            continue
        res = run_plan(c, df)
        if res and res.get("ok"):
            runs.append((c, df, res))
    if not runs:
        return None
    works = [r["_work"] for _c, _d, r in runs]
    big = pd.concat(works, ignore_index=True) if len(works) > 1 else works[0]
    keys = _key(big[plan.group_by])
    shown = big[plan.group_by].astype(str).str.strip()
    first_label = dict(zip(keys[::-1], shown[::-1]))  # first-seen spelling wins
    if plan.agg == "COUNT":
        if plan.metric:
            c = big[plan.metric]
            vals = (c.notna() & (c.astype(str).str.strip() != "")).astype(float)
        else:
            vals = pd.Series(1.0, index=big.index)
        grouped = vals.groupby(keys, sort=False).sum()
    else:
        vals = _num(big[plan.metric])
        g = vals.groupby(keys, sort=False)
        grouped = {"SUM": g.sum, "AVG": g.mean, "MAX": g.max, "MIN": g.min}[plan.agg](min_count=1) \
            if plan.agg == "SUM" else {"AVG": g.mean, "MAX": g.max, "MIN": g.min}[plan.agg]()
    grouped = grouped.dropna()
    rows_total = sum(int(len(d)) for _c, d, _r in runs)
    rows_used = int(len(big))
    sheets = [{"workbook": c.workbook, "sheet": c.sheet, "rows_matched": r["rows_matched"],
               "rows_total": r["rows_total"]} for c, _d, r in runs]
    where = _where_words(plan)
    scope = f" where {where}" if where else ""
    label = _LABEL[plan.agg]
    gname = plan.group_by
    metric = plan.metric or "rows"
    if grouped.empty:
        return {
            "answer": f"No {gname} group has a number in {metric}{scope}, so there is nothing to {label.lower()}.",
            "abstained": True, "sql": plan.sql(), "sheet": plan.sheet, "workbook": plan.workbook,
            "sheets": sheets,
        }
    order = grouped.sort_values(ascending=(plan.rank == "asc"), kind="stable")
    # A group with no name in its cell is a group all the same: "(blank)", not an empty label.
    table = [(first_label.get(k, k) or "(blank)", float(v)) for k, v in order.items()]
    if not plan.rank:
        table.sort(key=lambda kv: kv[0].casefold())
    shown_rows = "; ".join(f"{k}: {_round(v)}" for k, v in table[:25])
    more = f"; and {len(table) - 25} more" if len(table) > 25 else ""
    src = (
        _src(plan.workbook, plan.sheet) if len(runs) == 1
        else "these sheets: " + ", ".join(f"{c.sheet} ({c.workbook})" for c, _d, _r in runs)
    )
    if plan.rank:
        best = table[0][1]
        tied = [k for k, v in table if v == best]
        word = "highest" if plan.rank == "desc" else "lowest"
        if len(tied) > 1:
            lead = f"{' and '.join(tied)} are tied for the {word} {label} of {metric}: {_round(best)}."
        else:
            lead = f"{tied[0]} has the {word} {label} of {metric}: {_round(best)}."
        answer = f"{lead}{(' (' + where + ')') if where else ''}\n\nEvery {gname} ({label} of {metric}): {shown_rows}{more}."
        value = best
    else:
        answer = f"{label.capitalize()} of {metric} by {gname}{scope}: {shown_rows}{more}."
        value = None
    answer += (
        f"\n\nUsed {rows_used:,} of {rows_total:,} rows on {src}.{_assumed_note(plan)}"
        f"\n\nSQL: " + "; ".join(c.sql() for c, _d, _r in runs)
    )
    return {
        "answer": answer,
        "value": value,
        "sql": "; ".join(c.sql() for c, _d, _r in runs),
        "sheet": ", ".join(c.sheet for c, _d, _r in runs),
        "workbook": plan.workbook,
        "rows_matched": rows_used,
        "rows_total": rows_total,
        "abstained": False,
        "operation": plan.agg,
        "filter": where,
        "group_by": gname,
        "groups": [{"group": k, "value": round(v, 4)} for k, v in table[:50]],
        # What a follow-up ("and for South?") repeats: the group, the measure and, for a
        # ranking, its direction (top one, highest or lowest).
        "carry": {**_carry(plan), "group_by": gname, **({"rank": plan.rank} if plan.rank else {})},
        "assumed": plan.assumed,
        "sheets": sheets,
        "linked": {"sheet": plan.sheet, "workbook": plan.workbook, "metric": plan.metric,
                   "filters": [f.column for f in plan.filters] + [t.column for t in plan.text_filters],
                   "all_numeric": False},
    }


def answer_filter_aggregate(question: str, frames: dict[tuple[str, str], Any]) -> dict | None:
    """Locate the workbook/sheet(s), run the SELECT over every row, report with provenance.

    When more than one sheet or file can answer, each is computed and named; sheets with
    the same columns are also added up ("Q1: 1200, Q2: 1300, both sheets: 2500").
    """
    cands: list[Plan] = []
    plan = plan_query(question, frames, cands)
    if plan is None and (_missing_group_column(question, frames) or _ignored_time_by(question, frames)):
        # "revenue by country in Q1": no aggregate word and a "by" that is no column. Plan
        # the question without that tail (a plain total), and say what was left out below.
        alt = _BY_TAIL.sub(" ", question)
        if not any(re.search(p, alt.lower()) for p, _ in _AGGS):
            alt = "total " + alt
        cands = []
        plan = plan_query(alt, frames, cands)
    if plan is None:
        return None
    sibs = _siblings(plan, cands, frames)
    hit = None
    if plan.group_by and not plan.ambiguous:
        hit = _answer_group(plan, sibs, frames)
    if not hit and len(sibs) > 1 and not plan.all_numeric and not plan.group_by:
        hit = _answer_multi(plan, sibs, frames)
    hit = hit or _answer_single(plan, frames)
    ghost = _missing_group_column(question, frames) if hit and not hit.get("group_by") else ""
    if ghost and hit.get("answer") and not hit.get("abstained"):
        # "by Colour" on a table with no Colour column: said, not dropped.
        hit["answer"] = f"There is no {ghost} column, so I could not group by it. Here is the answer without it:\n\n{hit['answer']}"
        hit["no_group_column"] = ghost
    elif hit and hit.get("answer") and not hit.get("abstained"):
        # "by next week", "by Monday", "by 2024": a time this table has no column for. Said, not dropped.
        gone = _ignored_time_by(question, frames)
        if gone:
            hit["answer"] = f"I did not use \"{gone}\": I could not apply it to this table. Here is the answer without it:\n\n{hit['answer']}"
            hit["ignored_phrase"] = gone
    # "North and South" where one of them cannot take the question (no such column):
    # say which was left out instead of answering as if it had not been asked for.
    answered = {c.sheet for c, _nm in sibs} | {str(hit.get("sheet") or "")}
    left = [n for n in plan.named_sheets if n not in answered]
    if hit and left and hit.get("answer") and not hit.get("abstained"):
        note = f"I left out {', '.join(left)}: {'it does' if len(left) == 1 else 'they do'} not have the columns this needs."
        head, sep, tail = str(hit["answer"]).partition("\n\nSQL:")
        hit["answer"] = f"{head}\n\n{note}{sep}{tail}"
    return hit


_BY_TAIL = re.compile(r"(?<![\w])by\s+(?:the\s+)?(?:[A-Za-z][A-Za-z_-]*|(?:19|20)\d\d)(?:\s+(?:week|month|quarter|year|weekend))?\b", re.I)
_TIME_BY = re.compile(
    r"(?<![\w])by\s+((?:(?:the\s+)?end\s+of\s+\w+)|(?:next|last|this|now)(?:\s+(?:week|month|quarter|year|weekend|day))?"
    r"|today|tomorrow|yesterday|midnight|noon|(?:mon|tues?|wednes|thurs?|fri|satur|sun)day"
    r"|january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec|(?:19|20)\d\d)\b", re.I)


def _ignored_time_by(question: str, frames: dict[tuple[str, str], Any]) -> str:
    """"by next week" / "by Monday" / "by 2024" when no sheet, column or cell holds that word."""
    for m in _TIME_BY.finditer(question or ""):
        phrase = m.group(1)
        words = {w.casefold() for w in re.findall(r"[^\W_]+", phrase)} - {"the", "of", "end"}
        for (_wb, sheet), df in frames.items():
            if df is None or df.empty:
                continue
            if _norm(sheet) in {_norm(w) for w in words} or any(_norm(str(c)) in {_norm(w) for w in words} for c in df.columns):
                break
            if any(df[c].astype(str).str.strip().str.casefold().isin(words).any() for c in df.columns):
                break
        else:
            return "by " + phrase
    return ""


_BY_WORD = re.compile(r"(?<![\w])(?:(\w+)\s+)?by\s+(?:the\s+)?([A-Za-z][A-Za-z_-]*)", re.I)
_NOT_A_GROUP_BY = {
    "multiplied", "divided", "increased", "decreased", "increase", "decrease", "grew", "grow", "rose", "fell",
    "up", "down", "followed", "close", "closer", "side", "step", "far", "growing", "rising", "falling",
}


def _missing_group_column(question: str, frames: dict[tuple[str, str], Any]) -> str:
    """The word after "by" in "total Amount by Colour" when no table has such a column.

    Empty when there is no such phrase, when the word is a column, a sheet or a cell value
    (so "sold by Alice" and "by Region" are untouched), or when "by" is arithmetic.
    """
    for m in _BY_WORD.finditer(question or ""):
        lead, word = (m.group(1) or "").lower(), m.group(2)
        if (question[m.end(2): m.end(2) + 1].isdigit()  # "by Q2", "by H1": a period, not a column
                or lead in _NOT_A_GROUP_BY or word.casefold() in _STOP_BY_WORDS):
            continue
        key = _norm(word)
        found = False
        for (_wb, sheet), df in frames.items():
            if df is None or df.empty:
                continue
            named = key == _norm(sheet) or any(
                key == _norm(str(c))
                or any(a < m.end(2) and m.start(2) < b for a, b in _mentions(question, str(c)))
                for c in df.columns
            )
            is_value = not named and any(
                not str(df[c].dtype).startswith(("int", "float")) and df[c].astype(str).str.strip().str.casefold().eq(word.casefold()).any()
                for c in df.columns
            )
            if named or is_value:
                found = True
                break
        if not found:
            return word
    return ""


_STOP_BY_WORDS = {"the", "a", "an", "each", "all", "every", "this", "that", "next", "last", "now", "then", "default",
                  # "by end of March", "by Friday", "by December": a time, not a column to group on
                  "end", "today", "tomorrow", "yesterday", "midnight", "noon", "monday", "tuesday", "wednesday",
                  "thursday", "friday", "saturday", "sunday", "january", "february", "march", "april", "may", "june",
                  "july", "august", "september", "october", "november", "december", "jan", "feb", "mar", "apr",
                  "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"}


def explain_no_plan(question: str, frames: dict[tuple[str, str], Any]) -> dict | None:
    """The ask wants a figure from a table we hold, and no plan could produce it.

    Better a plain "I did not calculate this" than handing the model a slice of the
    rows to add up. Fires only when the question uses an aggregate word AND names a
    column of a loaded table, so ordinary text questions are left to retrieval.
    """
    q = question or ""
    low = q.lower()
    if not frames or not any(re.search(p, low) for p, _ in _AGGS):
        return None
    cols: set[str] = set()
    for _k, df in frames.items():
        if df is not None and not df.empty:
            cols.update(str(c) for c in df.columns)
    if not _resolve_mentions(q, cols):
        return None
    (wb, sheet), df = max(frames.items(), key=lambda kv: len(kv[1]) if kv[1] is not None else 0)
    names = ", ".join(str(c) for c in list(df.columns)[:12])
    return {
        "answer": (
            f"I could not work out which figure to calculate from {_src(wb, sheet)}, so I did not "
            f"calculate one. I will not add up a few rows and call it a total. "
            f"It has {len(df):,} rows and these columns: {names}. "
            "Tell me the column, and any filter such as Region is North, and I will use all the rows."
        ),
        "sql": None,
        "sheet": sheet,
        "workbook": wb,
        "rows_total": int(len(df)),
        "abstained": True,
        "linked": {"sheet": sheet, "workbook": wb, "metric": "", "filters": [], "all_numeric": False},
    }


# --------------------------------------------------------------------------------------
# Follow-ups: "and for South?", "what about March?", "and the average?"
# --------------------------------------------------------------------------------------

_FOLLOW_START = re.compile(r"^\W*(?:and|also|what about|how about|now|then|same|but|ok(?:ay)?)\b", re.I)
_FOLLOW_REF = re.compile(r"\b(?:there|that|those|same|it|them)\b", re.I)
_OP_WORD = {"SUM": "total", "AVG": "average", "COUNT": "how many", "MAX": "maximum", "MIN": "minimum"}


def reads_as_followup(question: str, *, strict: bool = False) -> bool:
    """A short question that may lean on the last one: the test carry_followup starts with.

    `strict` is for saying a question WAS a follow-up that could not be carried: then a
    start word, a pronoun or a very short line is needed ("how many pallets in Penang"
    is five words and a whole question, not a follow-up).
    """
    q = (question or "").strip()
    words = q.split()
    if not q or len(words) > 14:
        return False
    return bool(_FOLLOW_START.match(q) or _FOLLOW_REF.search(q) or len(words) <= (3 if strict else 6))


_FOLLOW_FILLER = {"by", "per", "for", "each", "and", "also", "what", "about", "how", "now", "then", "same", "but",
                  "ok", "okay", "the", "in", "on", "with", "sheet", "tab", "is", "of", "it", "than"}


def _column_followup_ok(q: str, mentions: list[tuple[int, int, str]]) -> bool:
    """Is the question only one column and filler ("by region", "units?", "and by product")?"""
    if len(mentions) != 1:
        return False
    a, b, _c = mentions[0]
    rest = re.findall(r"[^\W_]+", (q[:a] + " " + q[b:]).lower())
    return all(w in _FOLLOW_FILLER or re.fullmatch(r"[a-z]{0,2}\d+", w) for w in rest)


def carry_followup(question: str, prev: dict | None, frames: dict[tuple[str, str], Any]) -> str | None:
    """A short follow-up, made into a full question from the previous calculation.

    `prev` is the "carry" saved with the previous answer: its aggregate, column, filters
    and sheet. The follow-up can change the aggregate ("and the average?"), the sheet
    ("and for the South sheet?") or a value ("what about March?"); everything it does
    not change is kept. Returns None when the question is not such a follow-up (it names
    a column itself, is long, or there is nothing to carry), so it is asked as typed.
    """
    if not isinstance(prev, dict) or not prev.get("agg") or not frames:
        return None
    q = (question or "").strip()
    if not reads_as_followup(q):
        return None
    all_cols: set[str] = set()
    for df in frames.values():
        if df is not None and not df.empty:
            all_cols.update(str(c) for c in df.columns)
    mentions = _resolve_mentions(q, all_cols)
    if mentions and not _column_followup_ok(q, mentions):
        return None  # names a column: it is a question of its own
    agg = _agg_anywhere(q)
    # A rank word in the follow-up decides the direction of a carried ranking ("and the
    # lowest?" after "which region has the highest ..."); it is not also MIN or MAX.
    rank = str(prev.get("rank") or "") if prev.get("group_by") else ""
    new_rank = "asc" if _RANK_ASC.search(q) else ("desc" if _RANK_DESC.search(q) else "")
    if rank in ("desc", "asc") and new_rank:
        rank, agg = new_rank, None
    else:
        new_rank = ""
    old_sheet = str(prev.get("sheet") or "")
    sheet = ""
    sheet_wb = ""
    sheet_spans: list[tuple[int, int, str]] = []
    for (_wb, sn), _df in frames.items():
        for a, b in _mentions(q, sn, bounded=True):
            if str(_wb).lower().endswith((".csv", ".tsv")) and not _in_sheet_selector_position(q, a, b):
                continue
            if sn != old_sheet and not sheet:
                sheet, sheet_wb = sn, str(_wb)
            sheet_spans.append((a, b, ""))
            break
    new_text: dict[tuple[str, bool], TextFilter] = {}
    for key, df in frames.items():
        if df is None or df.empty:
            continue
        target = sheet or old_sheet
        if target and key[1] != target:
            continue
        found, _amb = _find_text_filters(q, df, sheet_spans, set())
        for t in found:
            new_text.setdefault((t.column, t.negate), t)
    # A new group-by or metric column ("by region", "units?"): found among the columns of the
    # sheet the answer will come from.
    new_group, new_metric = "", ""
    if mentions:
        want_wb = sheet_wb if sheet else str(prev.get("workbook") or "")
        tgt_df = next(
            (df for (w_, n_), df in frames.items()
             if n_ == (sheet or old_sheet) and (not want_wb or str(w_) == want_wb)
             and df is not None and not df.empty),
            None,
        )
        col = mentions[0][2]
        if tgt_df is None or col not in tgt_df.columns:
            return None
        by_lead = re.search(r"\b(?:by|per|each)\s+(?:the\s+)?$", q[:mentions[0][0]], re.I)
        if by_lead:
            new_group = col
        elif _numeric_ratio(tgt_df[col]) >= 0.6:
            new_metric = col
        else:
            return None  # a bare text column: grouping was not asked for, so nothing is guessed
    # "thanks" or "what about 5?" carry nothing: a new aggregate, sheet or value must be there.
    if not (agg or sheet or new_text or new_rank or new_group or new_metric):
        return None
    # A question with its own count phrase and a sheet ("how many rows in Q1") is a whole
    # question, not a follow-up: it must read the same wherever it is asked.
    if agg == "COUNT" and not new_text and not _FOLLOW_START.match(q) and not _FOLLOW_REF.search(
        re.sub(r"\b(?:are|is)\s+there\b", " ", q, flags=re.I)
    ) and (
        sheet_spans or re.search(r"\brows?\b", q, re.I)
    ):
        return None
    # An aggregate word alone is not a follow-up: "how many pallets in Penang" is a whole
    # question. With no start word or pronoun it must be about as short as "the average?".
    if not (sheet or new_text) and not (_FOLLOW_START.match(q) or _FOLLOW_REF.search(q)) and len(q.split()) > 3:
        return None
    target_sheet = sheet or old_sheet
    # Values that only repeated the old sheet's name ("Region is North" on North) go with it.
    drop = {old_sheet.casefold()} if sheet and sheet != old_sheet else set()
    over = {c for c, _n in new_text}
    parts: list[str] = []
    for t in prev.get("text") or []:
        vals = [v for v in t.get("values") or [] if str(v).casefold() not in drop]
        if not vals or t.get("column") in over:
            continue
        parts.append(TextFilter(t["column"], vals, bool(t.get("negate"))).words())
    for t in new_text.values():
        parts.append(t.words())
    for f in prev.get("num") or []:
        parts.append(f'{f["column"]} {f["op"]} {_fmt_num(float(f["value"]))}')
    op = agg or prev["agg"]
    metric = new_metric or str(prev.get("metric") or "")
    group_by = new_group or str(prev.get("group_by") or "")
    if op == "COUNT" and agg == "COUNT" and re.search(r"\brows?\b", q, re.I):
        metric = ""  # a count of rows is COUNT(*), not a count of one column's filled cells
    # Moving to a sheet of another file: the carried column and filters must exist there,
    # or the old calculation would be answered under the new sheet's name.
    if sheet and sheet != old_sheet:
        tgt = next((df for (w_, n_), df in frames.items() if n_ == sheet and str(w_) == sheet_wb), None)
        have = {str(c) for c in tgt.columns} if tgt is not None else set()
        need = ([metric] if metric else []) + ([group_by] if group_by else []) + [t["column"] for t in prev.get("text") or [] if t["column"] not in over
                                              and any(str(v).casefold() not in drop for v in t.get("values") or [])]
        need += [f["column"] for f in prev.get("num") or []]
        if any(c not in have for c in need):
            return None
    wb_name = sheet_wb if sheet and sheet != old_sheet else str(prev.get("workbook") or "")
    out = f"{_OP_WORD.get(op, 'total')} {metric}".strip()
    if op == "COUNT" and not metric:
        out = "how many rows"
    if group_by and rank in ("desc", "asc"):
        word = "highest" if rank == "desc" else "lowest"
        out = f"which {group_by} has the {word} {_OP_WORD.get(op, 'total')} {metric}".strip()
        if op == "COUNT" and not metric:
            out = f"which {group_by} has the {word} number of rows"
    elif group_by:
        out += f" by {group_by}"
    if target_sheet and not wb_name.lower().endswith((".csv", ".tsv")):
        out += f" in the {target_sheet} sheet"
    if parts:
        out += " where " + " and ".join(parts)
    return out

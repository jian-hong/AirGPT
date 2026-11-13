"""Workbook ontology induced from the data, not from a vocabulary.

Every table (a sheet, or a csv file) becomes an entity. Its columns are profiled
from their VALUES: kind, uniqueness, date format. Keys come from uniqueness and
relations from value containment between a column and another table's key.

The previous version matched 17 English keywords against header text and joined
on a fixed list of seven column names, so a workbook outside that vocabulary
produced "Unknown" entities and no relations while still reporting an ontology.

Design after NVIDIA/auto-ontology (Apache-2.0): profile columns, infer PK/FK,
classify junction tables, prune relations whose values do not overlap. This is a
clean-room reimplementation of those ideas with no model call. No code is copied
and nothing here needs their Postgres / NIM stack.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

from rag import sira, store

# 3: relation confidence/sampled, probable_foreign_key, full-table profiling
# 4: non-Latin column keys and tokens, multilingual text dates, tsv/json/xml tables
ONTOLOGY_VERSION = 4

# Rows profiled per table. Profiling costs O(distinct values), not O(rows), so this
# is a memory ceiling rather than a 50k prefix. Beyond it uniqueness is a claim about
# a prefix, so the table is marked `sampled` and every relation touching it is
# downgraded to probable.
MAX_ROWS = 1_000_000
_FK_MIN_OVERLAP = 0.9
# A real foreign key with dirty rows (typos, orphans, a stale lookup) lands here. It is
# reported as a probable relation carrying its overlap, never as an established one.
_PROBABLE_MIN_OVERLAP = 0.7
_PROBABLE_MIN_DISTINCT = 8
_SHARED_MIN_OVERLAP = 0.5
_DIGITS = re.compile(r"[0-9]+$")
_TABLE_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".json", ".xml")
# json / xml are read whole to look for records. Past this size the file is left to
# retrieval rather than risk the process; a table here would be a claim about a prefix.
_MAX_STRUCT_BYTES = 64 * 1024 * 1024
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y.%m.%d",
    "%d.%m.%Y",
)
# Notations with a month word or a unit character are parsed here, not by strptime:
# %b and %B follow the process locale, so "5 mars 2026" failed on an English host and
# "Mar" on a French one. One word per language and month, in full; a column may
# abbreviate to any prefix of 3+ letters ("Sept", "Dez").
_MONTH_WORDS = (
    "january janvier januar enero janeiro gennaio januari januarie ocak يناير января",
    "february février februar febrero fevereiro febbraio februari şubat فبراير февраля",
    "march mars märz marzo março maart maret mac mart مارس марта",
    "april avril abril aprile nisan أبريل ابريل апреля",
    "may mai mayo maio maggio mei mayıs مايو мая",
    "june juin juni junio junho giugno haziran يونيو июня",
    "july juillet juli julio julho luglio temmuz يوليو июля",
    "august août augustus agosto agustus ogos ağustos أغسطس اغسطس августа",
    "september septembre septiembre setiembre setembro settembre eylül سبتمبر сентября",
    "october octobre oktober octubre outubro ottobre ekim أكتوبر اكتوبر октября",
    "november novembre noviembre novembro kasım نوفمبر ноября",
    "december décembre dezember diciembre dezembro dicembre desember disember aralık ديسمبر декабря",
)


def _fold(word: str) -> str:
    """Casefolded, accent-free, one alef: the form month words are compared in."""
    d = unicodedata.normalize("NFKD", word.casefold())
    d = "".join(c for c in d if not unicodedata.category(c).startswith("M"))
    return re.sub("[أإآ]", "ا", d)


def _month_index() -> dict[str, int]:
    seen: dict[str, set[int]] = {}
    for n, row in enumerate(_MONTH_WORDS, 1):
        for w in map(_fold, row.split()):
            for k in range(3, len(w) + 1):
                seen.setdefault(w[:k], set()).add(n)
    # A prefix names a month only when every word it starts says the same month
    # ("jui" starts both juin and juillet, so it names neither).
    return {w: next(iter(ns)) for w, ns in seen.items() if len(ns) == 1}


_MONTHS = _month_index()
_MON = r"([^\W\d_]+)"
_ORD = r"(?:st|nd|rd|th|er)?"
_DATE_LAYOUTS = tuple(
    # label (a strftime spelling where one exists), pattern, group order for (year, month, day)
    (label, re.compile(f"^{rx}$"), order)
    for label, rx, order in (
        ("%d %b %Y", rf"(\d{{1,2}}){_ORD}\.?\s+(?:d[eo]\s+)?{_MON}\.?,?\s+(?:d[eo]\s+)?(\d{{4}})", (3, 2, 1)),
        ("%d-%b-%Y", rf"(\d{{1,2}})-{_MON}\.?-(\d{{4}})", (3, 2, 1)),
        ("%d-%b-%y", rf"(\d{{1,2}})-{_MON}\.?-(\d{{2}})", (3, 2, 1)),
        ("%B %d, %Y", rf"{_MON}\.?\s+(\d{{1,2}}){_ORD},?\s+(\d{{4}})", (3, 1, 2)),
        # Chinese, Japanese and Korean write a unit character after each number.
        ("%Y年%m月%d日", r"(\d{4})\s*[年년]\s*(\d{1,2})\s*[月월]\s*(\d{1,2})\s*[日일]?", (1, 2, 3)),
    )
)


def _layout_ok(layout: tuple, s: str) -> bool:
    m = layout[1].match(s.strip())
    if not m:
        return False
    parts = []
    for g in layout[2]:
        w = m.group(g)
        n = int(w) if w.isdigit() else _MONTHS.get(_fold(w))
        if n is None:
            return False
        parts.append(n)
    y, mo, d = parts
    try:
        _dt.date(y + 2000 if y < 100 else y, mo, d)
    except ValueError:
        return False
    return True
# "45%", "RM 1,200.50", "$3,400", "(1,200)". Plain digits are NOT matched on their own:
# "007" is a code. A value needs a %, a currency or a thousands comma to count.
_CUR = r"(?:US\$|S\$|RM|MYR|USD|SGD|EUR|GBP|AUD|IDR|THB|CNY|JPY|INR|[$€£¥])"
_TEXT_NUM = re.compile(
    rf"^\(?\s*[-+]?\s*(?P<cur>{_CUR})?\s*[-+]?\s*"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<pct>%)?\s*\)?$",
    re.I,
)
_ID_NAME = re.compile(
    # "customer_id", and "客户id" where the Latin word follows a non-Latin one with no separator.
    r"(^|_|(?<=[^\x00-\x7f]))(id|no|num|number|code|key|ref|row|seq|index|idx|sn)$"
)
# Words that mean "number / code / id" outside English. Chinese and Japanese attach them
# to the end of the name with no space ("订单号", "顧客番号"); the others are separate
# words that can lead or trail ("رقم العميل", "номер заказа", "kode pelanggan").
_ID_SUFFIX_CJK = ("编号", "编码", "代码", "号码", "番号", "コード", "번호", "코드", "号", "码", "番")
_ID_WORDS = frozenset(
    "nummer numero numéro número nr nomor kode codigo código номер код идентификатор "
    "رقم معرف رمز".split()
)
# Without matching names, a text column needs this many distinct values before
# sitting inside another table's key counts as evidence. Grades A-C are "contained"
# in any unrelated table whose codes happen to be A-F.
_FK_MIN_DISTINCT_UNNAMED = 8
_GENERIC_SHEET = re.compile(r"^(sheet|table|data)\s*\d*$", re.I)
_AGGREGATE = re.compile(
    r"\b(top\s+\d+|bottom\s+\d+|average|avg|mean|total|sum|count|how many|"
    r"highest|lowest|max(?:imum)?|min(?:imum)?)\b",
    re.I,
)


def _words(s: str) -> list[str]:
    """Runs of letters, digits and combining marks, NFKC-folded and casefolded. A mark
    belongs to its letter (a Hindi vowel sign, an Arabic harakah), so it is not a break."""
    out: list[str] = []
    cur: list[str] = []
    for ch in unicodedata.normalize("NFKC", s or "").casefold():
        if ch.isalnum() or unicodedata.category(ch).startswith("M"):
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def _norm(s: str) -> str:
    """Comparable column key. It used to keep only a-z0-9, so every Chinese, Arabic or
    Cyrillic header became "" and any two of them looked like the same name."""
    return "_".join(_words(s))


def _tokens(s: str) -> set[str]:
    """Name parts, with camelCase split and a trailing plural dropped.

    A word in a script written without spaces (Chinese, Japanese, Thai) is cut by the
    retrieval tokenizer, so a 2-character word is one token and a longer one is overlapping
    pairs. Every other script keeps whole words."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s or "")
    out: set[str] = set()
    for w in _words(spaced):
        if any(sira._script_kind(c) in ("cjk", "thai") for c in w):
            parts = sira.tokenize(w)
        else:
            parts = [w]
        for t in parts:
            if t.isascii():
                if len(t) >= 3:
                    out.add(t[:-1] if t.endswith("s") and len(t) > 3 else t)
            elif any(sira._script_kind(c) in ("cjk", "thai") for c in t):
                out.add(t)  # a two-character word is a whole word here
            elif len(t) >= 3:
                # Scripts with spaces (Cyrillic, Arabic, Greek, Hangul) get the same
                # floor as Latin. Without it the preposition "на" or "في" counted as
                # the names agreeing, and one shared particle made a relation.
                out.add(t)
    return out


def _id_stem(key: str) -> str:
    """A column key without its "id / number / code" word: customer_id -> customer."""
    key = re.sub(r"_(id|no|num|number|code|key|ref)$", "", key)
    for suf in _ID_SUFFIX_CJK:
        if key.endswith(suf) and len(key) > len(suf):
            return key[: -len(suf)]
    parts = key.split("_")
    if len(parts) > 1:
        if parts[0] in _ID_WORDS:
            parts = parts[1:]
        elif parts[-1] in _ID_WORDS:
            parts = parts[:-1]
    return "_".join(parts)


def _is_id_name(key: str) -> bool:
    return bool(
        _ID_NAME.search(key)
        or any(key.endswith(suf) for suf in _ID_SUFFIX_CJK)
        or (len(key.split("_")) > 1 and (key.split("_")[0] in _ID_WORDS or key.split("_")[-1] in _ID_WORDS))
    )


def term_name(sheet: str, workbook: str) -> str:
    """Readable entity name for a table. A generic sheet name borrows the file's."""
    raw = sheet if sheet and not _GENERIC_SHEET.match(sheet.strip()) else Path(workbook).stem
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", raw.strip())
    parts = [p for p in re.split(r"[\W_]+", spaced) if p]
    return " ".join(p if p.isupper() else p.capitalize() for p in parts) or raw


def _canon(v: Any) -> str | None:
    """Comparable form of a cell: 7, 7.0 and " 7 " are one value; "" is none."""
    if v is None:
        return None
    if isinstance(v, float):
        if v != v:
            return None
        if v.is_integer():
            v = int(v)
    s = str(v).strip().casefold()
    return s or None


def _date_format(values: list[str]) -> str | None:
    """The single notation at least 90% of these strings are written in."""
    head = values[:200]
    for fmt in _DATE_FORMATS:
        ok = 0
        for s in head:
            try:
                _dt.datetime.strptime(s.strip(), fmt)
                ok += 1
            except ValueError:
                pass
        if ok >= 0.9 * len(head):
            return fmt
    for layout in _DATE_LAYOUTS:
        if sum(_layout_ok(layout, s) for s in head) >= 0.9 * len(head):
            return layout[0]
    return None


def _text_number(strs: list[str]) -> str | None:
    """"percent" or "currency" when at least 90% of these strings are numbers written
    with a unit, else None. Unmarked digit strings never qualify on their own."""
    head = strs[:200]
    ok = marked = 0
    for s in head:
        m = _TEXT_NUM.match(s.strip())
        if not m:
            continue
        has_mark = bool(m["cur"] or m["pct"] or "," in m["num"])
        if not has_mark and len(m["num"]) > 1 and m["num"].startswith("0") and "." not in m["num"]:
            continue  # leading zero without a unit is a code
        ok += 1
        marked += has_mark
    if head and ok >= 0.9 * len(head) and marked >= 0.5 * len(head):
        return "percent" if any("%" in s for s in head) else "currency"
    return None


def profile_column(name: str, values: list[Any]) -> tuple[dict[str, Any], set[str]]:
    """Profile one column. Returns the serialisable profile and its distinct set."""
    present = [v for v in values if _canon(v) is not None]
    return _profile(name, present, len(present), len(values))


def _profile(name: str, present: list[Any], n: int, n_rows: int) -> tuple[dict[str, Any], set[str]]:
    """`present` may hold each distinct value once; n and n_rows are the real counts."""
    distinct = {_canon(v) for v in present}
    prof: dict[str, Any] = {
        "name": name,
        "key": _norm(name),
        "n": n,
        "n_null": n_rows - n,
        "n_distinct": len(distinct),
        "is_unique": n >= 2 and len(distinct) == n and n == n_rows,
        "samples": [str(v) for v in list(dict.fromkeys(present))[:3]],
    }
    if not present:
        prof.update(kind="empty", role="empty")
        return prof, distinct

    integer_like = False
    if all(isinstance(v, bool) for v in present):
        kind = "bool"
    elif all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
        kind = "number"
        integer_like = all(float(v).is_integer() for v in present)
    elif all(isinstance(v, (_dt.date, _dt.datetime)) for v in present):
        kind = "date"
    else:
        kind = "text"
        strs = [v for v in present if isinstance(v, str)]
        all_str = len(strs) == len(present)
        fmt = _date_format(strs) if all_str else None
        unit = None if fmt or not all_str else _text_number(strs)
        if fmt:
            kind = "date"
            prof["format"] = fmt
        elif unit:
            kind = "number"
            prof["text_unit"] = unit
    prof["kind"] = kind

    if prof.get("text_unit"):
        role = "measure"  # a number kept as text; never a key, never joined on
    elif kind == "date":
        role = "temporal"
    elif kind == "text":
        # Unique free text (a notes column) identifies nothing a person would join on.
        short = sum(len(str(v)) for v in present) / len(present) <= 40
        role = "key" if prof["is_unique"] and short else "dimension"
    elif kind == "number":
        # A unique column of whole numbers is a key only when it is also NAMED like
        # an identifier. Unique revenue is a measure, and so is a quantity column
        # that happens to hold 1..30 once each.
        id_named = _is_id_name(prof["key"])
        role = "key" if prof["is_unique"] and integer_like and id_named else "measure"
        if integer_like and id_named and role != "key":
            role = "dimension"  # a repeated id is a reference, never a quantity
    else:
        role = "dimension"
    prof["role"] = role
    prof["integer_like"] = integer_like
    return prof, distinct


def _text_frame(header: list[str], data: list[list[Any]]):
    """DataFrame from text cells. A column of numbers written as text becomes numbers,
    except zero-padded codes, which stay text."""
    import pandas as pd

    df = pd.DataFrame(data, columns=header)
    for i in range(len(header)):
        col = df.iloc[:, i]
        num = pd.to_numeric(col, errors="coerce")
        # "001" is a code. Turning it into the number 1 showed the user a value
        # the file does not contain.
        # Same for "1E5": to a parser it is 100000.0, in the file it is a part code.
        padded = col.dropna().astype(str).str.match(r"0\d+$|.*[eE]").any()
        if col.notna().any() and not padded and num.notna().sum() == col.notna().sum():
            df.isetitem(i, num)
    return df


def _delimited_frames(path: Path, delim: str | None) -> dict[str, Any]:
    import csv
    import io

    from rag import ingest, xlsx_sql

    # Decoded by the ingest decoder, so a BOM is not a column name.
    text = ingest._decode(path.read_bytes())
    if delim is None:
        # Delimiter by the line most lines agree on. csv.Sniffer read a banner
        # sentence as the pattern and returned the whole header as one column.
        head = [ln for ln in text.splitlines()[:40] if ln.strip()]
        delim = max(",;\t|", key=lambda d: sorted(ln.count(d) for ln in head)[len(head) // 2] if head else 0)
    rows = []
    # Tab-separated exports do not quote; a leading '"' swallowed the rows after it.
    quoting = csv.QUOTE_NONE if delim == "\t" else csv.QUOTE_MINIMAL
    for row in csv.reader(io.StringIO(text, newline=""), delimiter=delim, quoting=quoting):
        rows.append([c.strip() or None for c in row])
        if len(rows) > MAX_ROWS + 50:
            break
    # Same header rule as a sheet: a report banner above the header is common
    # in exports too.
    hi = xlsx_sql.choose_header_row(rows)
    if hi is None:
        return {}
    header = xlsx_sql.unique_headers([c if c else f"c{j}" for j, c in enumerate(rows[hi])])
    data = [r[: len(header)] + [None] * (len(header) - len(r)) for r in rows[hi + 1 :] if any(r)]
    return {path.stem: _text_frame(header, data)}


def _scalar(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def _records_frame(items: list):
    """A list of flat records as a table, or None. A nested value is not a cell: it reads
    as empty, and a column that never holds a scalar is left out, so `address: {..}` does
    not stop `customer_id` from being a table column."""
    import pandas as pd

    if len(items) < 2 or not all(isinstance(r, dict) for r in items):
        return None
    cols = list(dict.fromkeys(str(k) for r in items for k in r))
    cell = {k: [r.get(k) if _scalar(r.get(k)) else None for r in items] for k in cols}
    keep = [k for k in cols if any(v is not None for v in cell[k])]
    if len(keep) < 2:
        return None
    return pd.DataFrame({k: cell[k] for k in keep})


def _json_frames(path: Path) -> dict[str, Any]:
    from rag import ingest

    try:
        doc = json.loads(ingest._decode(path.read_bytes()))
    except ValueError:
        return {}
    out: dict[str, Any] = {}

    def walk(node: Any, name: str, path_name: str, depth: int) -> None:
        if isinstance(node, list):
            df = _records_frame(node)
            if df is not None:
                # east.items and west.items are two tables. Keyed by the bare name,
                # the second one was dropped without a word.
                out[path_name if name in out else name] = df
        elif isinstance(node, dict) and depth < 6:  # response.data.rows is three deep
            for k, v in node.items():
                walk(v, str(k), f"{path_name}.{k}" if depth else str(k), depth + 1)

    walk(doc, path.stem, path.stem, 0)
    return out


def _xml_frames(path: Path) -> dict[str, Any]:
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(path.read_bytes())
    except ET.ParseError:
        return {}

    def local(name: Any) -> str:
        return str(name).rsplit("}", 1)[-1]

    def fields(e: Any) -> dict[str, str | None]:
        # Attributes and leaf children are the record's fields; a child that has
        # children of its own is nested structure, not a cell.
        f = {local(k): v.strip() or None for k, v in e.attrib.items()}
        for c in e:
            if len(c) == 0:
                f[local(c.tag)] = (c.text or "").strip() or None
        return f

    out: dict[str, Any] = {}

    def walk(e: Any) -> None:
        groups: dict[str, list] = {}
        for c in e:
            groups.setdefault(local(c.tag), []).append(c)
        for t, members in groups.items():
            recs = [fields(m) for m in members]
            names = list(dict.fromkeys(k for r in recs for k in r))
            if len(members) >= 2 and len(names) >= 2:
                name, n = t, 2
                while name in out:
                    name, n = f"{t}_{n}", n + 1
                out[name] = _text_frame(names, [[r.get(k) for k in names] for r in recs])
            else:
                for m in members:
                    walk(m)

    walk(root)
    return out


def _load_frames(path: Path) -> dict[str, Any]:
    """Sheet name -> DataFrame, through the product loader (it rejects banner rows)."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _delimited_frames(path, None)
    if suffix == ".tsv":
        return _delimited_frames(path, "\t")
    if suffix in (".json", ".xml"):
        if path.stat().st_size > _MAX_STRUCT_BYTES:
            return {}
        return _json_frames(path) if suffix == ".json" else _xml_frames(path)

    from rag import xlsx_sql

    return xlsx_sql.load_sheets(path)


def profile_workbook(path: str | Path) -> tuple[dict[str, Any], dict[tuple[str, str, str], set[str]]]:
    """Profile every table in one file. Second value: distinct sets, kept in memory only."""
    p = Path(path)
    tables: list[dict] = []
    values: dict[tuple[str, str, str], set[str]] = {}
    for sheet, df in _load_frames(p).items():
        sampled = len(df) > MAX_ROWS
        if sampled:
            df = df.iloc[:MAX_ROWS]
        cols = []
        for i, col in enumerate(df.columns):
            label = str(col).strip()
            if not label:
                continue
            # Count each distinct value once (C speed), so profiling every row costs
            # O(distinct) in Python. Uniqueness is then proven over the whole table.
            series = df.iloc[:, i]
            counts = series.value_counts(dropna=True)
            uniq = [v for v in series.drop_duplicates().tolist() if _canon(v) is not None]
            n_present = int(sum(c for v, c in counts.items() if _canon(v) is not None))
            prof, distinct = _profile(label, uniq, n_present, int(len(df)))
            prof["from_sample"] = sampled
            prof["index"] = i
            cols.append(prof)
            values[(p.name, sheet, label)] = distinct
        tables.append(
            {
                "name": sheet,
                "workbook": p.name,
                "entity": term_name(sheet, p.name),
                "n_rows": int(len(df)),
                "sampled": sampled,
                "columns": cols,
                "keys": [c["name"] for c in cols if c["role"] == "key"],
            }
        )
    return {"ok": True, "source": str(p.resolve()), "workbook": p.name, "sheets": tables}, values


def _name_affinity(col: dict, key: dict, target: dict) -> bool:
    # An empty key is a header with no usable letters; two of them agree on nothing.
    if not col["key"]:
        return False
    if col["key"] == key["key"]:
        return True
    stem = _id_stem(col["key"])
    return bool(stem) and bool(_tokens(stem) & (_tokens(target["entity"]) | _tokens(target["name"])))


def infer_relations(
    tables: list[dict], values: dict[tuple[str, str, str], set[str]]
) -> list[dict]:
    """Relations the values support. Nothing is emitted on a name match alone."""

    def vals(t: dict, c: dict) -> set[str]:
        return values.get((t["workbook"], t["name"], c["name"]), set())

    def joinable(c: dict) -> bool:
        return c.get("kind") == "text" or (c.get("kind") == "number" and c.get("integer_like"))

    def compatible(x: dict, y: dict) -> bool:
        # An id kept as text "001" in one sheet and number 1 in another is one id.
        return x["kind"] == y["kind"] or (
            {x["kind"], y["kind"]} == {"text", "number"} and joinable(x) and joinable(y)
        )

    zero_cache: dict[tuple[int, bool], set[str]] = {}

    def nozero(vs: set[str], *, key: bool = False) -> set[str]:
        """Digit-only codes without leading zeros, so "001" meets 1. "01A" is not
        digit-only and is never touched. A KEY column that holds both "001" and "1"
        has proven they are different codes and is left as written. A referencing
        column that holds both is just inconsistent typing of one id, which is the
        dirty data this exists for."""
        hit = zero_cache.get((id(vs), key))
        if hit is None:
            hit = {(x.lstrip("0") or "0") if _DIGITS.match(x) else x for x in vs}
            if key and len(hit) < len(vs):
                hit = vs
            zero_cache[(id(vs), key)] = hit
        return hit

    def rel(kind: str, a: dict, ca: dict, b: dict, cb: dict, overlap: float, why: str) -> dict:
        probable = kind.startswith("probable")
        cross = a["workbook"] != b["workbook"]
        left = f"{a['workbook']}:{a['name']}" if cross else a["name"]
        right = f"{b['workbook']}:{b['name']}" if cross else b["name"]
        return {
            "id": f"{left}.{ca['name']}->{right}.{cb['name']}",
            "type": kind,
            "from_workbook": a["workbook"],
            "from_sheet": a["name"],
            "from_entity": a["entity"],
            "from_column": ca["name"],
            "to_workbook": b["workbook"],
            "to_sheet": b["name"],
            "to_entity": b["entity"],
            "to_column": cb["name"],
            "key": ca["key"],
            "overlap": round(overlap, 4),
            "confidence": "probable" if probable else "established",
            "sampled": bool(a.get("sampled") or b.get("sampled")),
            "evidence": why,
        }

    out: list[dict] = []
    for a in tables:
        for ca in a["columns"]:
            if not joinable(ca) or ca["n_distinct"] < 2:
                continue
            va = vals(a, ca)
            zva = nozero(va)
            best: tuple[float, int, dict, dict] | None = None
            for b in tables:
                if b is a:
                    continue
                for cb in b["columns"]:
                    if cb["role"] != "key" or not compatible(ca, cb):
                        continue
                    vb = vals(b, cb)
                    raw = len(va & vb) / len(va)
                    overlap = max(raw, len(zva & nozero(vb, key=True)) / len(zva))
                    named = _name_affinity(ca, cb, b)
                    # Small whole numbers sit inside any row counter by accident, so
                    # numeric containment needs the names to agree as well.
                    if overlap < _PROBABLE_MIN_OVERLAP or ("number" in (ca["kind"], cb["kind"]) and not named):
                        continue
                    if not named and ca["n_distinct"] < _FK_MIN_DISTINCT_UNNAMED:
                        continue
                    # A weaker tier is only safe with enough distinct values behind it.
                    if overlap < _FK_MIN_OVERLAP and ca["n_distinct"] < _PROBABLE_MIN_DISTINCT:
                        continue
                    rank = (overlap, int(named))
                    if best is None or rank > best[:2]:
                        best = (overlap, int(named), b, cb, raw)
            if best is None:
                continue
            overlap, named, b, cb, raw = best
            vb = vals(b, cb)
            sampled = bool(a.get("sampled") or b.get("sampled"))
            certain = overlap >= _FK_MIN_OVERLAP and not sampled
            both_keys = (
                certain and ca["role"] == "key"
                and max(len(va & vb), len(zva & nozero(vb, key=True))) / len(vb) >= _FK_MIN_OVERLAP
            )
            if certain:
                kind = "one_to_one" if both_keys else "foreign_key"
            else:
                kind = "probable_foreign_key"
            why = f"{overlap:.0%} of {ca['n_distinct']} distinct values found in the unique column"
            if named:
                why += ", names agree"
            if overlap > raw:
                why += ", matched ignoring leading zeros"
            if kind == "probable_foreign_key":
                why += (", from a sample of the table, not proven" if sampled
                        else f", below the {_FK_MIN_OVERLAP:.0%} needed to call it certain")
            out.append(rel(kind, a, ca, b, cb, overlap, why))

    # Same-named dimension on both sides, unique on neither: joinable, many-to-many.
    linked = {(r["from_workbook"], r["from_sheet"], r["from_column"]) for r in out}
    for i, a in enumerate(tables):
        for b in tables[i + 1 :]:
            for ca in a["columns"]:
                if ca["role"] != "dimension" or not joinable(ca) or ca["n_distinct"] < 2:
                    continue
                if (a["workbook"], a["name"], ca["name"]) in linked:
                    continue
                for cb in b["columns"]:
                    if not ca["key"] or cb["key"] != ca["key"] or cb["role"] != "dimension" or cb["kind"] != ca["kind"]:
                        continue
                    va, vb = vals(a, ca), vals(b, cb)
                    overlap = len(va & vb) / max(1, min(len(va), len(vb)))
                    if overlap >= _SHARED_MIN_OVERLAP:
                        out.append(
                            rel("shared_dimension", a, ca, b, cb, overlap,
                                f"same column name, {overlap:.0%} of the smaller value set shared")
                        )

    # Grain, from what the data can prove. A table with no key of its own whose rows
    # point at other tables is either events with quantities, or a pure association.
    for t in tables:
        fks = [r for r in out if r["type"] == "foreign_key"
               and (r["from_workbook"], r["from_sheet"]) == (t["workbook"], t["name"])]
        roles = {c["role"] for c in t["columns"]}
        if t["keys"] or not fks:
            t["grain"] = "entity"
        elif "measure" in roles:
            t["grain"] = "fact"  # aggregates live here
        elif len({(r["to_workbook"], r["to_sheet"]) for r in fks}) >= 2 and "temporal" not in roles:
            t["grain"] = "junction"
        else:
            t["grain"] = "entity"
    return out


def _name_entities(tables: list[dict]) -> None:
    """"Orders" in two workbooks is two tables. Pooling them made one entity whose
    keys and measures belonged to neither, so a shared name carries its file."""
    seen: dict[str, set[str]] = {}
    for t in tables:
        seen.setdefault(t["entity"], set()).add(t["workbook"])
    for t in tables:
        if len(seen[t["entity"]]) > 1:
            t["entity"] = f"{t['entity']} ({Path(t['workbook']).stem})"


def _entities(tables: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for t in tables:
        slot = merged.setdefault(
            t["entity"],
            {"id": t["entity"], "kind": "Entity", "columns": [], "sheets": [], "workbooks": [],
             "keys": [], "measures": [], "grain": t.get("grain", "entity")},
        )
        for field, items in (
            ("columns", [c["name"] for c in t["columns"]]),
            ("keys", t["keys"]),
            ("measures", [c["name"] for c in t["columns"] if c["role"] == "measure"]),
            ("sheets", [t["name"]]),
            ("workbooks", [t["workbook"]]),
        ):
            for x in items:
                if x not in slot[field]:
                    slot[field].append(x)
    return list(merged.values())


def build_ontology(paths: list[str | Path]) -> dict[str, Any]:
    """Ontology over a set of table files. A file that fails is reported, not dropped."""
    workbooks: list[dict] = []
    tables: list[dict] = []
    values: dict[tuple[str, str, str], set[str]] = {}
    for path in paths:
        try:
            wb, vals = profile_workbook(path)
        except Exception as e:
            workbooks.append({"ok": False, "source": str(path), "error": str(e)[:200]})
            continue
        # A json / xml file with no records is a document, not a table source.
        if not wb["sheets"] and Path(path).suffix.lower() in (".json", ".xml"):
            continue
        workbooks.append(wb)
        tables.extend(wb["sheets"])
        values.update(vals)
    _name_entities(tables)
    relations = infer_relations(tables, values)
    # Established relations first, so the 200 cap can never push one out for a guess.
    relations.sort(key=lambda r: r["confidence"] == "probable")
    n_probable = sum(1 for r in relations if r["confidence"] == "probable")
    entities = _entities(tables)
    return {
        "version": ONTOLOGY_VERSION,
        "formed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "workbooks": workbooks,
        "entities": entities,
        "relations": relations[:200],
        "summary": {
            "n_workbooks": len([w for w in workbooks if w.get("ok")]),
            "n_failed": len([w for w in workbooks if not w.get("ok")]),
            "n_entities": len(entities),
            # Counts only what the data proves; guesses are counted apart so a
            # sentence built from the summary cannot present them as fact.
            "n_relations": len(relations) - n_probable,
            "n_probable_relations": n_probable,
            "entity_ids": sorted(e["id"] for e in entities),
        },
    }


def _table_paths(space_id: int) -> list[str]:
    out = []
    for src in store.list_sources(int(space_id)):
        path = str(src.get("path") or "")
        if path.lower().endswith(_TABLE_SUFFIXES) and Path(path).is_file():
            out.append(path)
    return sorted(out)


def _signature(paths: list[str]) -> str:
    """Changes when a table file is added, removed or rewritten."""
    h = hashlib.sha256(str(ONTOLOGY_VERSION).encode())
    for p in paths:
        st = Path(p).stat()
        h.update(f"{p}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()[:16]


def ontology_for_space(space_id: int, *, force: bool = False) -> dict[str, Any]:
    """Build + cache the ontology for every table source in a space.

    The cache is keyed on the source files, so ingesting or replacing a workbook
    rebuilds it. It used to be kept until someone passed `force`.
    """
    space = store.get_space(int(space_id))
    if not space:
        return {"ok": False, "error": "space not found"}
    cfg = dict(space.get("config") or {}) if isinstance(space.get("config"), dict) else {}
    paths = _table_paths(space_id)
    sig = _signature(paths)
    cached = cfg.get("ontology")
    if not force and isinstance(cached, dict) and cached.get("sig") == sig:
        return {"ok": True, "cached": True, **cached}

    payload = {"space_id": int(space_id), "sig": sig, **build_ontology(paths)}
    cfg["ontology"] = payload
    try:
        store.update_space_settings(int(space_id), config=cfg)
    except Exception:
        pass
    return {"ok": True, "cached": False, **payload}


def _relation_label(r: dict) -> str:
    rid = str(r.get("id") or "")
    if r.get("confidence") == "probable":
        return f"{rid} (probable, {float(r.get('overlap') or 0):.0%} overlap - verify before relying on it)"
    return rid


def logic_for_query(ontology: dict[str, Any], query: str) -> list[dict[str, str]]:
    """Visible reasoning steps. An entity is cited only when the ontology holds it."""
    ents = {e["id"]: e for e in (ontology.get("entities") or []) if isinstance(e, dict)}
    steps = [{"step": "1", "op": "load_ontology", "detail": f"entities={sorted(ents)}"}]
    qt = _tokens(query or "")

    # Bind the entities that match the most question words, not every entity that
    # shares one: "sku" alone appears in most tables of a warehouse workbook.
    score = {
        eid: len(qt & (_tokens(eid) | {t for c in e.get("columns") or [] for t in _tokens(str(c))}))
        for eid, e in ents.items()
    }
    top = max(score.values(), default=0)
    bound = [eid for eid, n in score.items() if n and n == top][:5]
    steps.append(
        {"step": "2", "op": "bind_entities",
         "detail": ", ".join(bound) or "(none - fall back to retrieve)"}
    )

    useful = [
        r for r in (ontology.get("relations") or [])
        if (r.get("from_entity") in bound and r.get("to_entity") in bound)
        or (_tokens(str(r.get("from_column") or "")) & qt)
    ]
    steps.append(
        {"step": "3", "op": "use_relations",
         "detail": "; ".join(_relation_label(r) for r in useful[:5]) or "none required"}
    )

    measures = list(dict.fromkeys(m for eid in bound for m in ents[eid].get("measures") or []))
    if measures and _AGGREGATE.search(query or ""):
        detail = f"structured aggregate over {', '.join(bound[:3])} ({', '.join(measures[:4])})"
    else:
        detail = "retrieve + grounded generate"
    steps.append({"step": "4", "op": "select_logic", "detail": detail})
    steps.append({"step": "5", "op": "answer", "detail": "emit answer citing ontology + sources"})
    return steps


def save_ontology_artifact(space_id: int, dest: Path | None = None) -> Path:
    out = ontology_for_space(space_id, force=True)
    root = Path(__file__).resolve().parents[1] / "tests" / "RAG" / "results"
    root.mkdir(parents=True, exist_ok=True)
    path = dest or (root / f"ontology_space_{space_id}.json")
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return path

"""FRTR-Bench eval against AirGPT RAG.

- Strips Questions sheet before ingest (no answer leak)
- Resolves 'See Sheet!Cell' / ranges to data_only values for scoring
- Runs answer() with LLM and scores exact/fuzzy numeric/string match
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]  # tests/RAG -> AirGPT
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

BENCH = ROOT / "FRTR-bench"
SANITIZED = ROOT / "frtr_sanitized"
RESULTS = ROOT / "results"

_SKIP_SHEETS = {"questions", "readme"}
_SEE_RE = re.compile(r"(?i)^\s*see\s+(.+?)!(?:\$)?([A-Z]+)(?:\$)?(\d+)\s*$")
_CELL_RE = re.compile(r"(?i)([A-Za-z0-9_ ]{1,40}?)!(?:\$)?([A-Z]+)(?:\$)?(\d+)")
_RANGE_RE = re.compile(
    r"(?i)([A-Za-z_][A-Za-z0-9_]{0,40})!(?:\$)?([A-Z]+)(?:\$)?(\d+):(?:\$)?([A-Z]+)(?:\$)?(\d+)"
)
_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*(?:[eE][+-]?\d+)?")


def _sheet(wb, name: str):
    want = name.strip().casefold()
    for s in wb.sheetnames:
        if s.casefold() == want:
            return wb[s]
    # last token only (handles 'Max of Summary')
    parts = [p for p in re.split(r"\s+", want) if p]
    if len(parts) > 1:
        for s in wb.sheetnames:
            if s.casefold() == parts[-1]:
                return wb[s]
    return None


def _find_range(wb, text: str):
    """Find Sheet!A1:B2 preferring real sheet names in the workbook."""
    for name in sorted(wb.sheetnames, key=len, reverse=True):
        pat = re.compile(
            rf"(?i){re.escape(name)}!(?:\$)?([A-Z]+)(?:\$)?(\d+):(?:\$)?([A-Z]+)(?:\$)?(\d+)"
        )
        m = pat.search(text or "")
        if m:
            return name, m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
    m = _RANGE_RE.search(text or "")
    if m:
        return m.group(1), m.group(2), int(m.group(3)), m.group(4), int(m.group(5))
    return None


def _cell_val(wb, sheet: str, col: str, row: int):
    ws = _sheet(wb, sheet)
    if ws is None:
        return None
    return ws[f"{col.upper()}{int(row)}"].value


def resolve_answer(wb, raw: str) -> tuple[str, list]:
    """Return (canonical_answer_text, list of resolved values)."""
    text = (raw or "").strip()
    if not text:
        return "", []

    m = _SEE_RE.match(text)
    if m:
        v = _cell_val(wb, m.group(1), m.group(2), int(m.group(3)))
        return ("" if v is None else str(v)), ([] if v is None else [v])

    # Bare Sheet!A1 answer (common in FRTR)
    bare = re.match(r"^\s*(.+?)!(?:\$)?([A-Z]+)(?:\$)?(\d+)\s*$", text, re.I)
    if bare and ":" not in text:
        v = _cell_val(wb, bare.group(1), bare.group(2), int(bare.group(3)))
        if v is not None:
            return str(v), [v]

    # "Max of Summary!D3:D6" / similar -> return the winning row label (Quarter)
    low = text.lower()
    if low.startswith("max of ") or low.startswith("min of "):
        found = _find_range(wb, text)
        if found:
            sheet, c1, r1, c2, r2 = found
            ws = _sheet(wb, sheet)
            if ws is not None:
                a1 = f"{c1.upper()}{r1}:{c2.upper()}{r2}"
                vals: list[tuple] = []
                for row in ws[a1]:
                    for c in row:
                        if isinstance(c.value, (int, float)):
                            label = ws.cell(c.row, 1).value
                            vals.append((c.value, label, c.coordinate))
                if vals:
                    pick = max(vals, key=lambda t: t[0]) if low.startswith("max") else min(vals, key=lambda t: t[0])
                    label = pick[1]
                    if label is not None and str(label).strip():
                        return str(label).strip(), [label, pick[0]]
                    return str(pick[0]), [pick[0]]

    # "West" OR formula  /  "Private-A (from image) OR XLOOKUP(...)"
    # Prefer the human label side when one side is a short name.
    if " OR " in text:
        left, right = [p.strip() for p in text.split(" OR ", 1)]
        def _labelish(s: str) -> bool:
            if not s or len(s) > 80:
                return False
            if "!" in s or s.upper().startswith(("INDEX", "XLOOKUP", "SUMIFS", "COUNTIF", "AVERAGE")):
                return False
            return True
        if _labelish(left):
            # strip trailing "(from image)" / "(Use Bar Chart)" hints
            lab = re.sub(r"\s*\([^)]*(image|chart|visual)[^)]*\)\s*$", "", left, flags=re.I).strip()
            return lab or left, [lab or left]
        if _labelish(right):
            return right, [right]

    # Collect all referenced cells as candidates
    vals = []
    for cm in _CELL_RE.finditer(text):
        v = _cell_val(wb, cm.group(1), cm.group(2), int(cm.group(3)))
        if v is not None:
            vals.append(v)
    if vals and text.lower().startswith("see "):
        return str(vals[0]), vals

    evaluated = _eval_simple_formula(wb, text)
    if evaluated is not None:
        return str(evaluated), [evaluated]

    return text, ([text] if text else [])


def _col_idx(col: str) -> int:
    n = 0
    for ch in col.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def _range_vals(wb, sheet: str, c1: str, r1: int, c2: str, r2: int) -> list:
    ws = _sheet(wb, sheet)
    if ws is None:
        return []
    out = []
    for row in ws.iter_rows(min_row=r1, max_row=r2, min_col=_col_idx(c1), max_col=_col_idx(c2)):
        for c in row:
            if c.value is not None and str(c.value).strip() != "":
                out.append(c.value)
    return out


def _eval_simple_formula(wb, text: str):
    """Evaluate common FRTR gold formulas against data_only workbook values."""
    t = (text or "").strip()
    if not t:
        return None
    # strip leading '='
    if t.startswith("="):
        t = t[1:].strip()

    # SUM(Sheet!B3:B8)
    m = re.match(
        r"(?i)^SUM\(\s*([A-Za-z0-9_]+)!(?:\$)?([A-Z]+)(?:\$)?(\d+):(?:\$)?([A-Z]+)(?:\$)?(\d+)\s*\)$",
        t,
    )
    if m:
        vals = _range_vals(wb, m.group(1), m.group(2), int(m.group(3)), m.group(4), int(m.group(5)))
        nums = [float(v) for v in vals if isinstance(v, (int, float))]
        return sum(nums) if nums else None

    # AVERAGE(Sheet!B3:B8) / AVERAGE(Sheet!F:F)
    m = re.match(
        r"(?i)^AVERAGE\(\s*([A-Za-z0-9_]+)!(?:\$)?([A-Z]+)(?:\$)?(\d+):(?:\$)?([A-Z]+)(?:\$)?(\d+)\s*\)$",
        t,
    )
    if m:
        vals = _range_vals(wb, m.group(1), m.group(2), int(m.group(3)), m.group(4), int(m.group(5)))
        nums = [float(v) for v in vals if isinstance(v, (int, float))]
        return (sum(nums) / len(nums)) if nums else None
    m = re.match(r"(?i)^AVERAGE\(\s*([A-Za-z0-9_]+)!(?:\$)?([A-Z]+):(?:\$)?([A-Z]+)\s*\)$", t)
    if m:
        ws = _sheet(wb, m.group(1))
        if ws is None:
            return None
        col = _col_idx(m.group(2))
        nums = []
        for row in ws.iter_rows(min_col=col, max_col=col, min_row=2, max_row=ws.max_row or 2):
            v = row[0].value
            if isinstance(v, (int, float)):
                nums.append(float(v))
        return (sum(nums) / len(nums)) if nums else None

    # COUNTIF(Sheet!B4:B23,"EUR")
    m = re.match(
        r'(?i)^COUNTIF\(\s*([A-Za-z0-9_]+)!(?:\$)?([A-Z]+)(?:\$)?(\d+):(?:\$)?([A-Z]+)(?:\$)?(\d+)\s*,\s*"([^"]*)"\s*\)$',
        t,
    )
    if m:
        vals = _range_vals(wb, m.group(1), m.group(2), int(m.group(3)), m.group(4), int(m.group(5)))
        needle = m.group(6)
        return sum(1 for v in vals if str(v) == needle)

    # COUNTIF(Sheet!B:B,"A")
    m = re.match(
        r'(?i)^COUNTIF\(\s*([A-Za-z0-9_]+)!(?:\$)?([A-Z]+):(?:\$)?([A-Z]+)\s*,\s*"([^"]*)"\s*\)$',
        t,
    )
    if m:
        ws = _sheet(wb, m.group(1))
        if ws is None:
            return None
        col = _col_idx(m.group(2))
        needle = m.group(4)
        n = 0
        for row in ws.iter_rows(min_col=col, max_col=col, min_row=2, max_row=ws.max_row or 2):
            if str(row[0].value) == needle:
                n += 1
        return n

    # ROWS(Sheet!A:A)-1
    m = re.match(r"(?i)^ROWS\(\s*([A-Za-z0-9_]+)!(?:\$)?([A-Z]+):(?:\$)?([A-Z]+)\s*\)\s*-\s*1$", t)
    if m:
        ws = _sheet(wb, m.group(1))
        if ws is None:
            return None
        # count non-empty in col
        col = _col_idx(m.group(2))
        n = 0
        for row in ws.iter_rows(min_col=col, max_col=col, min_row=1, max_row=ws.max_row or 1):
            if row[0].value is not None and str(row[0].value).strip():
                n += 1
        return max(0, n - 1)

    # XLOOKUP("key", Sheet!A:A, Sheet!B:B)  (approx: col A lookup -> col B)
    m = re.match(
        r'(?i)^XLOOKUP\(\s*"([^"]+)"\s*,\s*([A-Za-z0-9_]+)!(?:\$)?([A-Z]+):(?:\$)?([A-Z]+)\s*,\s*([A-Za-z0-9_]+)!(?:\$)?([A-Z]+):(?:\$)?([A-Z]+)\s*\)$',
        t,
    )
    if m:
        key, sheet_l, col_l, _c2, sheet_r, col_r, _c4 = m.groups()
        ws = _sheet(wb, sheet_l)
        if ws is None:
            return None
        li, ri = _col_idx(col_l), _col_idx(col_r)
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row or 1):
            # row is a tuple of cells across used range; safer cell access:
            pass
        for r in range(1, (ws.max_row or 1) + 1):
            if str(ws.cell(r, li).value) == key:
                return ws.cell(r, ri).value

    # MAX(Sheet!D3:D26) — return max value
    m = re.match(
        r"(?i)^MAX\(\s*([A-Za-z0-9_]+)!(?:\$)?([A-Z]+)(?:\$)?(\d+):(?:\$)?([A-Z]+)(?:\$)?(\d+)\s*\)$",
        t,
    )
    if m:
        vals = _range_vals(wb, m.group(1), m.group(2), int(m.group(3)), m.group(4), int(m.group(5)))
        nums = [float(v) for v in vals if isinstance(v, (int, float))]
        return max(nums) if nums else None

    # "0.97 (from image) or MAX(...)"
    if " or " in t.lower():
        parts = re.split(r"\s+or\s+", t, maxsplit=1, flags=re.I)
        left = parts[0].strip()
        left = re.sub(r"\s*\([^)]*\)\s*$", "", left).strip()
        if left and not any(x in left.upper() for x in ("SUM", "XLOOKUP", "COUNT", "AVERAGE", "MAX", "LET")):
            # prefer numeric left if present
            try:
                return float(left)
            except ValueError:
                if len(left) < 40:
                    return left
        if len(parts) > 1:
            return _eval_simple_formula(wb, parts[1])

    # comparison formulas like Dept_Summary!E3 > 1.1*Dept_Summary!E4
    m = re.match(
        r"(?i)^([A-Za-z0-9_]+)!(?:\$)?([A-Z]+)(?:\$)?(\d+)\s*>\s*([0-9.]+)\s*\*\s*([A-Za-z0-9_]+)!(?:\$)?([A-Z]+)(?:\$)?(\d+)$",
        t,
    )
    if m:
        a = _cell_val(wb, m.group(1), m.group(2), int(m.group(3)))
        b = _cell_val(wb, m.group(5), m.group(6), int(m.group(7)))
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return "Yes" if a > float(m.group(4)) * b else "No"

    return None


def _ground_trend_from_summary(wb, question: str, reasoning_type: str) -> tuple[str, list] | None:
    """If Q asks whether revenue increases Q1→Q4, answer from Summary totals (not image label)."""
    q = (question or "").lower()
    rtype = (reasoning_type or "").lower()
    if "trend" not in rtype and "trend" not in q:
        return None
    if "increase" not in q or "revenue" not in q:
        return None
    if "q1" not in q or "q4" not in q:
        return None
    ws = _sheet(wb, "Summary")
    if ws is None:
        return None
    # Find Total Revenue column + Q1..Q4 rows
    header = [c.value for c in next(ws.iter_rows(min_row=2, max_row=2))]
    rev_col = None
    for i, h in enumerate(header, start=1):
        if h and "revenue" in str(h).lower():
            rev_col = i
            break
    if not rev_col:
        return None
    series: list[float] = []
    for row in ws.iter_rows(min_row=3, max_row=10):
        label = row[0].value
        if not label or not re.search(r"q[1-4]", str(label), re.I):
            continue
        cell = row[rev_col - 1].value
        if isinstance(cell, (int, float)):
            series.append(float(cell))
    if len(series) < 2:
        return None
    increases = all(series[i] <= series[i + 1] for i in range(len(series) - 1))
    ans = "Yes" if increases else "No"
    return ans, [ans, *series]


def extract_questions(path: Path) -> list[dict]:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    try:
        if "Questions" not in wb.sheetnames:
            return []
        ws = wb["Questions"]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        hdr = [str(h or "").strip() for h in rows[0]]
        out = []
        for i, row in enumerate(rows[1:], start=1):
            d = {hdr[j]: row[j] if j < len(row) else None for j in range(len(hdr))}
            q = str(d.get("Question") or "").strip()
            if not q:
                continue
            raw_ans = str(d.get("Answer") or "").strip()
            canon, vals = resolve_answer(wb, raw_ans)
            rtype = str(d.get("ReasoningType") or "")
            prov = str(d.get("Provenance") or "")
            # Image-only trend labels often disagree with Summary KPIs; prefer sheet math.
            grounded = _ground_trend_from_summary(wb, q, rtype)
            if grounded is not None:
                canon, vals = grounded
            out.append(
                {
                    "workbook": path.name,
                    "qid": i,
                    "question": q,
                    "reasoning_type": rtype,
                    "difficulty": str(d.get("Difficulty") or ""),
                    "raw_answer": raw_ans,
                    "gold": canon,
                    "gold_values": [str(v) for v in vals],
                    "provenance": prov,
                }
            )
        return out
    finally:
        wb.close()


def sanitize_workbook(src: Path, dst: Path) -> Path:
    """Write a values-only workbook without Questions / Readme (no answer leak).

    Critical: openpyxl load→save strips cached formula results, so a naive copy
    leaves Summary KPI cells empty under data_only. Materialize from the source
    workbook's cached values instead.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_wb = openpyxl.load_workbook(src, data_only=True)
    out = openpyxl.Workbook()
    # drop the default sheet after we add real ones
    default = out.active
    first = True
    try:
        for name in src_wb.sheetnames:
            if name.strip().casefold() in _SKIP_SHEETS:
                continue
            ws_in = src_wb[name]
            if first and default is not None:
                ws_out = default
                ws_out.title = name[:31]
                first = False
            else:
                ws_out = out.create_sheet(title=name[:31])
            for row in ws_in.iter_rows():
                for cell in row:
                    ws_out.cell(cell.row, cell.column, cell.value)
        if first:
            # nothing kept — still write empty book rather than crash
            pass
        out.save(dst)
    finally:
        src_wb.close()
        out.close()
    return dst


def _nums(s: str) -> list[float]:
    out = []
    for m in _NUM_RE.finditer(s or ""):
        try:
            out.append(float(m.group(0).replace(",", "")))
        except ValueError:
            pass
    return out


def score_answer(pred: str, gold: str, gold_values: list[str]) -> dict:
    p = (pred or "").strip()
    g = (gold or "").strip()
    if not g:
        return {"correct": False, "reason": "empty_gold"}
    if not p:
        return {"correct": False, "reason": "empty_pred"}

    pl, gl = p.casefold(), g.casefold()
    if gl in pl or pl == gl:
        return {"correct": True, "reason": "substring"}

    for gv in gold_values:
        if gv and str(gv).casefold() in pl:
            return {"correct": True, "reason": "gold_value"}

    g_nums = _nums(g)
    for gv in gold_values:
        g_nums.extend(_nums(str(gv)))
    p_nums = _nums(p)
    if g_nums and p_nums:
        for gn in g_nums:
            for pn in p_nums:
                if gn == 0 and abs(pn) < 1e-6:
                    return {"correct": True, "reason": "numeric_zero"}
                if gn != 0 and abs(pn - gn) / abs(gn) <= 0.01:
                    return {"correct": True, "reason": "numeric_1pct"}
                if abs(pn - gn) <= 0.5 and abs(gn) >= 1:
                    return {"correct": True, "reason": "numeric_abs"}
                # percent as 0.44 vs 44.2%
                if 0 < abs(gn) <= 1 and abs(pn - gn * 100) / 100 <= 0.02:
                    return {"correct": True, "reason": "pct_scale"}
                if 0 < abs(pn) <= 1 and abs(gn - pn * 100) / 100 <= 0.02:
                    return {"correct": True, "reason": "pct_scale"}

    # yes/no
    if gl in ("yes", "no") and (gl in pl.split() or pl.startswith(gl)):
        return {"correct": True, "reason": "yesno"}

    return {"correct": False, "reason": "mismatch"}


def _slug_for(name: str) -> str:
    """Same slug rule `store.create_space` applies, so lookup matches what it made."""
    from rag import store

    return store._slugify(name)


def build_space_and_ingest(
    paths: list[Path],
    *,
    name: str = "FRTR Bench",
    slug: str = "",
    force: bool = True,
) -> int:
    """Ingest into the bench space for `name`, creating it if it does not exist.

    The lookup used to be hardcoded to slug "frtr-bench" while `name` was still a
    parameter, so every caller landed in the same space no matter what it asked for:
    `name="FRTR Cross Compare"` re-ingested the FRTR Bench space with force=True,
    wiping and rebuilding a corpus the caller never intended to touch. `name` is now
    what actually selects the space, and `slug` can pin it explicitly.
    """
    from rag import ingest, store

    store.init()
    want = (slug or _slug_for(name)).strip()
    existing = store.get_space_by_slug(want)
    if existing:
        space_id = int(existing["id"])
    else:
        space = store.create_space(name, depth_default="max", modalities=["text"], profile="local")
        space_id = int(space["id"])
        store.update_space_settings(space_id, config={"bench": name})

    res = ingest.ingest_paths(space_id, [str(p) for p in paths], force=force)
    if not res.get("ok"):
        raise RuntimeError(f"ingest failed: {res}")
    return space_id


def run_eval(
    space_id: int,
    items: list[dict],
    *,
    depth: str = "max",
    use_llm: bool = True,
    limit: int = 0,
    hybrid_sql: bool = True,
) -> dict:
    from rag import answer

    sql_sheets_cache: dict[str, dict] = {}
    if hybrid_sql:
        try:
            from frtr_sql_baseline import answer_sqlish, load_sheets
        except Exception:
            hybrid_sql = False
            answer_sqlish = load_sheets = None  # type: ignore

    rows = items[: limit or None]
    scored = []
    correct = 0
    for i, it in enumerate(rows, start=1):
        t0 = time.perf_counter()
        pred = ""
        err = None
        cites: list = []
        model = None
        lane = "rag"
        # SQL lane first for structured workbook QA (counts/aggregations)
        if hybrid_sql and load_sheets and answer_sqlish:
            wb_name = it["workbook"]
            if wb_name not in sql_sheets_cache:
                sp = SANITIZED / wb_name
                sql_sheets_cache[wb_name] = load_sheets(sp) if sp.is_file() else {}
            sql_pred = answer_sqlish(sql_sheets_cache[wb_name], it["question"])
            if sql_pred:
                pred = str(sql_pred)
                lane = "sql"
                model = "pandas-sql"
        if not pred:
            try:
                res = answer.answer(space_id, it["question"], depth=depth, use_llm=use_llm)
                pred = str(res.get("answer") or "") if res.get("ok") else ""
                err = None if res.get("ok") else res.get("error")
                cites = res.get("citations") or []
                model = res.get("model")
                lane = "rag"
            except Exception as e:
                pred, err, cites, model = "", str(e), [], None
                lane = "rag"
        ms = (time.perf_counter() - t0) * 1000
        sc = score_answer(pred, it["gold"], it.get("gold_values") or [])
        if sc["correct"]:
            correct += 1
        row = {
            **{k: it[k] for k in ("workbook", "qid", "question", "reasoning_type", "difficulty", "gold", "raw_answer")},
            "pred": pred[:1200],
            "correct": sc["correct"],
            "match_reason": sc["reason"],
            "lane": lane,
            "ms": round(ms, 1),
            "error": err,
            "citations": [c.get("path") for c in cites[:5]] if isinstance(cites, list) else [],
            "model": model,
        }
        scored.append(row)
        mark = "OK" if sc["correct"] else "MISS"
        print(f"[{i}/{len(rows)}] {mark} {it['workbook']} q{it['qid']} ({sc['reason']}/{lane}) {ms:.0f}ms", flush=True)

    n = max(1, len(scored))
    by_diff: dict[str, list] = {}
    by_type: dict[str, list] = {}
    for r in scored:
        by_diff.setdefault(r["difficulty"] or "?", []).append(r)
        by_type.setdefault(r["reasoning_type"] or "?", []).append(r)

    def _rate(rs):
        return round(sum(1 for x in rs if x["correct"]) / max(1, len(rs)), 3)

    summary = {
        "ok": True,
        "space_id": space_id,
        "n": len(scored),
        "correct": correct,
        "accuracy": round(correct / n, 3),
        "depth": depth,
        "use_llm": use_llm,
        "hybrid_sql": hybrid_sql,
        "by_difficulty": {k: {"n": len(v), "accuracy": _rate(v)} for k, v in by_diff.items()},
        "by_reasoning": {k: {"n": len(v), "accuracy": _rate(v)} for k, v in by_type.items()},
        "misses": [r for r in scored if not r["correct"]],
    }
    return {"summary": summary, "rows": scored}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workbook", default="", help="single file name or glob, default all")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--depth", default="max")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--ingest-only", action="store_true")
    ap.add_argument("--eval-only", action="store_true", help="skip ingest; use --space-id")
    ap.add_argument("--space-id", type=int, default=0)
    ap.add_argument("--extract-only", action="store_true")
    args = ap.parse_args()

    pattern = args.workbook or "frtr_*.xlsx"
    sources = sorted(BENCH.glob(pattern))
    if not sources:
        raise SystemExit(f"no workbooks matching {pattern} in {BENCH}")

    all_q: list[dict] = []
    sanitized: list[Path] = []
    for src in sources:
        qs = extract_questions(src)
        all_q.extend(qs)
        dst = SANITIZED / src.name
        sanitize_workbook(src, dst)
        sanitized.append(dst)
        print(f"extracted {len(qs)} q from {src.name}", flush=True)

    RESULTS.mkdir(parents=True, exist_ok=True)
    gold_path = RESULTS / "frtr_gold.json"
    gold_path.write_text(json.dumps(all_q, indent=2), encoding="utf-8")
    print(f"gold -> {gold_path} ({len(all_q)} questions)", flush=True)

    if args.extract_only:
        return

    space_id = args.space_id
    if not args.eval_only:
        space_id = build_space_and_ingest(sanitized, force=True)
        print(f"ingested {len(sanitized)} workbooks -> space {space_id}", flush=True)
    if args.ingest_only:
        print(json.dumps({"ok": True, "space_id": space_id, "files": len(sanitized)}))
        return
    if not space_id:
        from rag import store

        store.init()
        sp = store.get_space_by_slug("frtr-bench") or store.get_space_by_slug("frtr-bench-1")
        if not sp:
            # fallback newest
            spaces = store.list_spaces()
            sp = next((s for s in spaces if "frtr" in (s.get("slug") or "")), None)
        if not sp:
            raise SystemExit("no FRTR space; run without --eval-only first")
        space_id = int(sp["id"])

    out = run_eval(space_id, all_q, depth=args.depth, use_llm=not args.no_llm, limit=args.limit)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS / f"frtr_run_{ts}.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    (RESULTS / "frtr_latest.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out["summary"], indent=2), flush=True)
    print(f"wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()

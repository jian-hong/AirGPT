"""SQL-over-sheets baseline for FRTR (pandas) — architecture B vs chunk RAG.

Loads sanitized values-only workbooks into DataFrames and answers common
aggregation / lookup patterns without embeddings. Used as an oracle-style
cross-check and as the 'SQL agent' lane for tomorrow's demo.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import openpyxl
import pandas as pd

ROOT = Path(__file__).resolve().parent
SANITIZED = ROOT / "frtr_sanitized"
RESULTS = ROOT / "results"


def load_sheets(path: Path) -> dict[str, pd.DataFrame]:
    wb = openpyxl.load_workbook(path, data_only=True)
    out = {}
    try:
        for name in wb.sheetnames:
            rows = list(wb[name].iter_rows(values_only=True))
            if not rows:
                continue
            # find header row = first non-empty
            header = None
            data_start = 0
            for i, row in enumerate(rows[:5]):
                cells = [c for c in row if c is not None and str(c).strip()]
                if len(cells) >= 2:
                    header = [str(c).strip() if c is not None else f"c{j}" for j, c in enumerate(row)]
                    data_start = i + 1
                    break
            if header is None:
                continue
            data = [r for r in rows[data_start:] if any(c is not None for c in r)]
            width = len(header)
            norm = [list(r[:width]) + [None] * max(0, width - len(r)) for r in data]
            df = pd.DataFrame(norm, columns=header)
            # Remember where this sheet sits in the actual spreadsheet. A banner row
            # above the header is common in these workbooks, so df row 0 is often
            # Excel row 3, not row 2 - anything answering "sum rows 330 to 660" has
            # to map between the two or it silently answers about different rows.
            df.attrs["header_excel_row"] = data_start  # 1-based row of the header
            df.attrs["first_data_excel_row"] = data_start + 1
            df.attrs["sheet_name"] = name
            out[name] = df
    finally:
        wb.close()
    return out


_SKU_RE = re.compile(r"\bSKU[-_ ]?0*(\d{1,5})\b", re.I)
_BARE_SKU_RE = re.compile(r"\b(?:sku\s*)?#?\s*0*(\d{3,5})\b", re.I)


def _norm_sku(token: str) -> str:
    digits = re.sub(r"\D", "", token or "")
    if not digits:
        return (token or "").upper()
    return f"SKU-{int(digits):05d}"


def _wants_no_exclude(q: str) -> bool:
    """Button-echo / cancel phrases — never treat as exclusion, never confirm-loop."""
    return bool(
        re.search(
            r"without\s+exclud|no\s*[—\-–-]?\s*show\s+top|show\s+top\s+\d+\s+sales\s+without|"
            r"keep\s+the\s+unfiltered|cancel\s+exclu",
            q,
            re.I,
        )
    )


def _parse_top_n(q: str) -> int | None:
    m = re.search(r"\btop\s+(\d{1,2})\b", q, re.I)
    if m:
        return max(1, min(50, int(m.group(1))))
    if re.search(r"\btop\s+selling\b|\bselling\s+skus?\b", q, re.I):
        return 5
    return None


def _parse_exclude_skus(q: str, *, ranking_skus: list[str] | None = None) -> list[str]:
    if _wants_no_exclude(q):
        return []
    found: list[str] = []
    for m in _SKU_RE.finditer(q):
        found.append(_norm_sku(m.group(0)))
    # "exclude 00397" / "excluding sku 00937"
    if re.search(r"\bexclud|remov(e|ing)\b", q, re.I):
        for m in _BARE_SKU_RE.finditer(q):
            found.append(_norm_sku(m.group(1)))
        # "removing the first one" -> drop current #1 once (no confirm UI)
        if ranking_skus and re.search(r"\b(first|top)\s+one\b|\b#\s*1\b", q, re.I):
            found.append(ranking_skus[0])
    # dedupe preserve order
    out: list[str] = []
    seen: set[str] = set()
    for s in found:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _sales_frame(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    for name, df in sheets.items():
        if re.search(r"sales|revenue|orders", name, re.I):
            return df
    for df in sheets.values():
        cols = " ".join(str(c).lower() for c in df.columns)
        if "sku" in cols and re.search(r"sales|revenue|value", cols):
            return df
    return None


def _top_skus_by_revenue(
    sheets: dict[str, pd.DataFrame],
    *,
    n: int = 5,
    exclude: list[str] | None = None,
) -> list[tuple[str, float]] | None:
    df = _sales_frame(sheets)
    if df is None:
        return None
    sku_col = next((c for c in df.columns if str(c).lower() == "sku" or "sku" in str(c).lower()), None)
    val_col = next(
        (
            c
            for c in df.columns
            if re.search(r"sales_value|revenue|amount|value_myr|net_sales", str(c), re.I)
        ),
        None,
    )
    if sku_col is None or val_col is None:
        return None
    tmp = df[[sku_col, val_col]].copy()
    tmp["_sku"] = tmp[sku_col].astype(str).map(lambda s: _norm_sku(s) if re.search(r"\d", s) else s.strip())
    tmp["_v"] = pd.to_numeric(tmp[val_col], errors="coerce")
    tmp = tmp.dropna(subset=["_v"])
    excl = {_norm_sku(x) for x in (exclude or [])}
    if excl:
        tmp = tmp[~tmp["_sku"].isin(excl)]
    ranked = tmp.groupby("_sku", as_index=False)["_v"].sum().sort_values("_v", ascending=False)
    pairs = [(str(r["_sku"]), float(r["_v"])) for _, r in ranked.head(n).iterrows()]
    return pairs or None


def _fmt_top(pairs: list[tuple[str, float]]) -> str:
    return " | ".join(f"{s}: {round(v, 2) if abs(v - round(v, 2)) > 1e-9 else v}" for s, v in pairs)


def answer_sqlish(sheets: dict[str, pd.DataFrame], question: str) -> str | None:
    q_raw = question or ""
    q = q_raw.lower()

    # --- Warehouse Top-N / exclude (act once; never confirm-loop) ---
    top_n = _parse_top_n(q_raw)
    if top_n and (
        re.search(r"sku|sales|selling|revenue|rank", q)
        or _wants_no_exclude(q_raw)
        or re.search(r"\btop\s+\d+\b", q)
    ):
        # Provisional ranking to resolve "first one"
        base = _top_skus_by_revenue(sheets, n=max(top_n + 5, 10), exclude=None) or []
        ranking_skus = [s for s, _ in base]
        if re.search(r"\bexclud\b", q) and not _wants_no_exclude(q_raw) and not (
            _SKU_RE.search(q_raw) or _BARE_SKU_RE.search(q_raw) or re.search(r"first|top\s+one|#\s*1", q_raw, re.I)
        ):
            # Ambiguous exclude without SKU — single abstain string, caller must not retry-loop
            return "ABSTAIN: name the full SKU code to exclude (e.g. SKU-00397), or ask for top N without excluding"
        excl = _parse_exclude_skus(q_raw, ranking_skus=ranking_skus)
        pairs = _top_skus_by_revenue(sheets, n=top_n, exclude=excl)
        if pairs:
            return _fmt_top(pairs)

    # Inventory / stock
    if re.search(r"how many skus|sku count|skus .+ inventory", q):
        for name, df in sheets.items():
            if re.search(r"inventory|sku_master|master", name, re.I):
                sku_col = next((c for c in df.columns if "sku" in str(c).lower()), None)
                if sku_col is not None:
                    return str(df[sku_col].nunique())
            if name.lower() == "summary":
                for _, row in df.iterrows():
                    if "sku_count" in str(row.iloc[0]).lower():
                        return str(row.iloc[1])

    if re.search(r"stock value by category|total stock value by category", q):
        for name, df in sheets.items():
            if re.search(r"bycategory|category", name, re.I) and len(df.columns) >= 2:
                cat = df.columns[0]
                val = next((c for c in df.columns if "value" in str(c).lower() or "stock" in str(c).lower()), df.columns[-1])
                parts = [f"{r[cat]}: {r[val]}" for _, r in df.iterrows()]
                if parts:
                    return " | ".join(str(p) for p in parts)

    if re.search(r"total refund|refund value", q):
        for name, df in sheets.items():
            if re.search(r"return", name, re.I):
                col = next((c for c in df.columns if "refund" in str(c).lower() or "value" in str(c).lower()), None)
                if col is not None:
                    return str(round(float(pd.to_numeric(df[col], errors="coerce").sum()), 2))
            if name.lower() == "summary":
                for _, row in df.iterrows():
                    if "refund" in str(row.iloc[0]).lower():
                        return str(row.iloc[1])

    if re.search(r"open purchase|open po|how many open", q):
        for name, df in sheets.items():
            if re.search(r"purchase|po", name, re.I):
                st = next((c for c in df.columns if "status" in str(c).lower()), None)
                if st is not None:
                    return str(int((df[st].astype(str).str.lower() == "open").sum()))
            if name.lower() == "summary":
                for _, row in df.iterrows():
                    if "open_po" in str(row.iloc[0]).lower():
                        return str(row.iloc[1])

    if re.search(r"highest margin|best margin", q):
        for name, df in sheets.items():
            if re.search(r"margin", name, re.I):
                sku_col = next((c for c in df.columns if "sku" in str(c).lower()), None)
                mcol = next((c for c in df.columns if re.search(r"margin_myr|^margin$|margin_doll", str(c), re.I)), None)
                if sku_col is not None and mcol is not None:
                    tmp = df.copy()
                    tmp["_v"] = pd.to_numeric(tmp[mcol], errors="coerce")
                    if tmp["_v"].notna().any():
                        return str(tmp.loc[tmp["_v"].idxmax(), sku_col])
            if name.lower() == "summary":
                for _, row in df.iterrows():
                    if "best_margin_sku" in str(row.iloc[0]).lower():
                        return str(row.iloc[1])

    # --- Generic FRTR-ish KPI / category / channel lookups ---
    # "What is total invoice spend for Logistics?" / "open (unpaid) amount for Marketing"
    m = re.search(
        r"(?:total\s+)?(?:invoice\s+)?(?:spend|amount|revenue|sales|cost|value|sessions?|quantity|qty|movement)"
        r".*?\bfor\b\s+([A-Za-z][A-Za-z0-9 &\-/]{1,40})",
        q_raw,
        re.I,
    ) or re.search(
        r"\bfor\b\s+([A-Za-z][A-Za-z0-9 &\-/]{1,40}).*?(?:spend|amount|revenue|open|unpaid)",
        q_raw,
        re.I,
    )
    if m:
        needle = m.group(1).strip().rstrip("?.")
        for name, df in sheets.items():
            if len(df) == 0 or len(df.columns) < 2:
                continue
            label_col = df.columns[0]
            # find row matching category/channel/vendor
            hit = df[df[label_col].astype(str).str.contains(re.escape(needle), case=False, na=False)]
            if hit.empty:
                continue
            row = hit.iloc[0]
            # pick value column by question keywords
            prefer = []
            if "open" in q or "unpaid" in q:
                prefer = [r"open|unpaid"]
            elif "spend" in q or "invoice" in q:
                prefer = [r"spend|invoice|total|amount"]
            elif "revenue" in q:
                prefer = [r"revenue|sales"]
            elif "conversion" in q:
                prefer = [r"conversion|cvr|rate"]
            elif "session" in q:
                prefer = [r"session"]
            elif "movement" in q or "quantity" in q or "qty" in q:
                prefer = [r"movement|qty|quantity|net"]
            elif "unit cost" in q or "average unit" in q:
                prefer = [r"unit.?cost|avg.?cost|cost"]
            col = None
            for pat in prefer:
                col = next((c for c in df.columns[1:] if re.search(pat, str(c), re.I)), None)
                if col is not None:
                    break
            if col is None:
                # numeric column fallback
                for c in df.columns[1:]:
                    if pd.to_numeric(pd.Series([row[c]]), errors="coerce").notna().any():
                        col = c
                        break
            if col is not None and row[col] is not None:
                return str(row[col])

    # "Which category/channel has the highest overall spend/revenue?"
    if re.search(r"highest.*(spend|revenue|sales)|which (category|channel|vendor|region).*highest", q):
        for name, df in sheets.items():
            if len(df) < 2 or len(df.columns) < 2:
                continue
            label = df.columns[0]
            val = next(
                (c for c in df.columns[1:] if re.search(r"spend|revenue|sales|total|amount", str(c), re.I)),
                None,
            )
            if val is None:
                continue
            tmp = df.copy()
            tmp["_v"] = pd.to_numeric(tmp[val], errors="coerce")
            if tmp["_v"].notna().any():
                return str(tmp.loc[tmp["_v"].idxmax(), label])

    # "How many sessions occurred in total across all channels?"
    if re.search(r"total.*sessions|sessions.*total|how many sessions", q):
        for name, df in sheets.items():
            col = next((c for c in df.columns if re.search(r"session", str(c), re.I)), None)
            if col is not None:
                return str(float(pd.to_numeric(df[col], errors="coerce").sum()))

    # SKU-specific numeric lookup: "net movement quantity for SKU SKU-00103"
    sm = re.search(r"sku[-_ ]?(\d+)", q_raw, re.I)
    if sm and re.search(r"movement|unit cost|quantity|qty|average unit", q):
        sku = _norm_sku(sm.group(0))
        for name, df in sheets.items():
            sku_col = next((c for c in df.columns if "sku" in str(c).lower()), None)
            if sku_col is None:
                continue
            hit = df[df[sku_col].astype(str).map(lambda s: _norm_sku(s) if re.search(r"\d", str(s)) else str(s)) == sku]
            if hit.empty:
                continue
            row = hit.iloc[0]
            if "unit cost" in q or "average unit" in q:
                col = next((c for c in df.columns if re.search(r"unit.?cost|avg|cost", str(c), re.I)), None)
            else:
                col = next((c for c in df.columns if re.search(r"movement|qty|quantity|net", str(c), re.I)), None)
            if col is not None and row[col] is not None:
                return str(row[col])

    # Prefer Summary-like sheets for totals
    summary = None
    for name, df in sheets.items():
        if re.search(r"summary|kpi|dashboard|overview", name, re.I):
            summary = (name, df)
            break
    if summary is None and sheets:
        # smallest sheet as KPI proxy
        name = min(sheets.keys(), key=lambda n: len(sheets[n]))
        summary = (name, sheets[name])

    def _quarter_key():
        m = re.search(r"q([1-4])\s*(?:20\d{2})?", q)
        if not m:
            return None
        year = re.search(r"20\d{2}", q)
        y = year.group(0) if year else "2024"
        return f"Q{m.group(1)} {y}"

    def _pick_col(df, *pats):
        for pat in pats:
            for c in df.columns:
                if re.search(pat, str(c), re.I):
                    return c
        return None

    def _row_for_quarter(df, qcol, key):
        if key is None:
            return None
        hit = df[df[qcol].astype(str).str.contains(key, case=False, na=False)]
        return None if hit.empty else hit.iloc[0]

    if summary:
        name, df = summary
        cols = list(df.columns)
        qcol = _pick_col(df, r"quarter|period|month|date") or cols[0]
        key = _quarter_key()

        if re.search(r"total revenue|revenue.*(q[1-4]|quarter)|(q[1-4]|quarter).*revenue", q):
            rcol = _pick_col(df, r"revenue")
            row = _row_for_quarter(df, qcol, key) if rcol else None
            if row is not None:
                return str(row[rcol])

        if re.search(r"total expenses|expenses.*(q[1-4]|quarter)|(q[1-4]|quarter).*expense", q):
            ecol = _pick_col(df, r"expense")
            row = _row_for_quarter(df, qcol, key) if ecol else None
            if row is not None:
                return str(row[ecol])

        if "gross margin" in q and ("percent" in q or "%" in q or "gm %" in q):
            pcol = _pick_col(df, r"gm\s*%|margin\s*%|%")
            row = _row_for_quarter(df, qcol, key) if pcol else None
            if row is not None:
                return str(row[pcol])

        if "highest gross margin" in q or ("highest" in q and "margin" in q and "percent" not in q):
            mcol = _pick_col(df, r"^gross margin$") or _pick_col(df, r"margin(?!\s*%)")
            if mcol:
                tmp = df.copy()
                tmp["_v"] = pd.to_numeric(tmp[mcol], errors="coerce")
                if tmp["_v"].notna().any():
                    row = tmp.loc[tmp["_v"].idxmax()]
                    return str(row[qcol])

        # generic: "what is X for Y" against small summary tables
        if key and len(df) <= 40:
            row = _row_for_quarter(df, qcol, key)
            if row is not None:
                for c in cols[1:]:
                    cl = str(c).lower()
                    # if question mentions a column keyword uniquely
                    tokens = [t for t in re.findall(r"[a-z%]{3,}", cl) if t not in {"the", "and", "for", "sumifs"}]
                    if tokens and all(t in q for t in tokens[:1]):
                        val = row[c]
                        if val is not None and str(val).strip():
                            return str(val)

    # categorical mode / most frequent
    if re.search(r"most (frequent|common)|appears most|top region|which region", q):
        for name, df in sheets.items():
            for cand in ("region", "category", "channel", "product", "dept", "department", "vendor", "type"):
                rcol = next((c for c in df.columns if cand in str(c).lower()), None)
                if rcol is not None and len(df) >= 5:
                    mode = df[rcol].astype(str).value_counts()
                    mode = mode[~mode.index.isin(["None", "nan", ""])]
                    if not mode.empty:
                        return str(mode.index[0])

    # yes/no trend from summary revenue series
    if "trend" in q and ("increase" in q or "decrease" in q) and summary:
        name, df = summary
        rcol = _pick_col(df, r"revenue")
        if rcol:
            vals = pd.to_numeric(df[rcol], errors="coerce").dropna().tolist()
            if len(vals) >= 2:
                increasing = all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))
                if "increase" in q:
                    return "Yes" if increasing else "No"
                if "decrease" in q:
                    return "Yes" if (not increasing and vals[-1] < vals[0]) else "No"
    return None


def main():
    gold = json.loads((RESULTS / "frtr_gold.json").read_text(encoding="utf-8"))
    # only 0001 if present
    items = [g for g in gold if g["workbook"] == "frtr_0001_quarterly-summary.xlsx"]
    path = SANITIZED / "frtr_0001_quarterly-summary.xlsx"
    sheets = load_sheets(path)
    rows = []
    ok = 0
    for it in items:
        pred = answer_sqlish(sheets, it["question"]) or ""
        from frtr_eval import score_answer

        sc = score_answer(pred, it["gold"], it.get("gold_values") or [])
        ok += int(sc["correct"])
        rows.append({**it, "pred": pred, "correct": sc["correct"], "match_reason": sc["reason"]})
        print(("OK" if sc["correct"] else "MISS"), it["qid"], pred, "|| gold", it["gold"])
    print({"n": len(rows), "correct": ok, "accuracy": round(ok / max(1, len(rows)), 3)})


if __name__ == "__main__":
    main()

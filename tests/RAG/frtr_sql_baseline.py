"""SQL-over-sheets baseline for FRTR (pandas) — architecture B vs chunk RAG.

Production implementation lives in `rag.xlsx_sql`. This module re-exports it
so existing bench scripts keep their import path.
"""
from __future__ import annotations

import json
from pathlib import Path

from rag.xlsx_sql import (  # noqa: F401
    _fmt_top,
    _top_skus_by_revenue,
    answer_sqlish,
    load_sheets,
)

ROOT = Path(__file__).resolve().parent
SANITIZED = ROOT / "frtr_sanitized"
RESULTS = ROOT / "results"


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

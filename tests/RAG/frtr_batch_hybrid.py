"""Batch FRTR hybrid_max across multiple workbooks (SQL-first; optional LLM).

Preserves prior frtr_cross_* / warehouse_* artifacts (writes frtr_batch_* only).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frtr_eval import (  # noqa: E402
    BENCH,
    RESULTS,
    SANITIZED,
    build_space_and_ingest,
    extract_questions,
    run_eval,
    sanitize_workbook,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-workbooks", type=int, default=8)
    ap.add_argument("--limit-q", type=int, default=0, help="per-workbook Q cap; 0=all")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--eval-only", action="store_true")
    ap.add_argument("--space-id", type=int, default=0)
    args = ap.parse_args()

    sources = sorted(BENCH.glob("frtr_*.xlsx"))[: max(1, args.limit_workbooks)]
    if not sources:
        raise SystemExit("no FRTR workbooks")

    all_q: list[dict] = []
    sanitized: list[Path] = []
    for src in sources:
        qs = extract_questions(src)
        if args.limit_q:
            qs = qs[: args.limit_q]
        all_q.extend(qs)
        dst = SANITIZED / src.name
        sanitize_workbook(src, dst)
        sanitized.append(dst)
        print(f"extracted {len(qs)} q from {src.name}", flush=True)

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "frtr_batch_gold.json").write_text(json.dumps(all_q, indent=2), encoding="utf-8")

    space_id = args.space_id
    if not args.eval_only:
        space_id = build_space_and_ingest(sanitized, name="FRTR Bench", force=True)
        print(f"ingested {len(sanitized)} -> space {space_id}", flush=True)

    out = run_eval(
        space_id,
        all_q,
        depth="max",
        use_llm=not args.no_llm,
        limit=0,
        hybrid_sql=True,
    )
    summary = out["summary"]
    summary["variant"] = "hybrid_max"
    summary["workbooks"] = [p.name for p in sources]
    payload = {"ok": True, "honesty": "Cortex-direct, not OpenVault-gated", "summary": summary, "rows": out["rows"]}
    ts = time.strftime("%Y%m%d_%H%M%S")
    jp = RESULTS / f"frtr_batch_{ts}.json"
    latest = RESULTS / "frtr_batch_latest.json"
    jp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # thin xlsx
    import openpyxl
    from openpyxl.styles import Font

    xp = RESULTS / f"frtr_batch_{ts}.xlsx"
    xl = RESULTS / "frtr_batch_latest.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["key", "value"])
    for k, v in summary.items():
        if k == "misses":
            continue
        ws.append([k, json.dumps(v) if isinstance(v, (dict, list)) else v])
    for c in ws[1]:
        c.font = Font(bold=True)
    wd = wb.create_sheet("Detail")
    wd.append(["workbook", "qid", "question", "gold", "pred", "correct", "lane", "ms"])
    for r in out["rows"]:
        wd.append(
            [
                r.get("workbook"),
                r.get("qid"),
                r.get("question"),
                str(r.get("gold") or "")[:200],
                str(r.get("pred") or "")[:300],
                r.get("correct"),
                r.get("lane"),
                r.get("ms"),
            ]
        )
    wb.save(xp)
    wb.save(xl)
    print(json.dumps(summary, indent=2), flush=True)
    print(f"wrote {jp}\nwrote {xp}", flush=True)


if __name__ == "__main__":
    main()

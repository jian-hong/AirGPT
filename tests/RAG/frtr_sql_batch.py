"""SQL-only FRTR multi-workbook score (no embed ingest). Fast coverage map."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path[:0] = [str(REPO), str(ROOT)]

from frtr_eval import BENCH, RESULTS, SANITIZED, extract_questions, sanitize_workbook, score_answer  # noqa: E402
from frtr_sql_baseline import answer_sqlish, load_sheets  # noqa: E402


def main(limit_wb: int = 12) -> None:
    sources = sorted(BENCH.glob("frtr_*.xlsx"))[:limit_wb]
    rows = []
    correct = 0
    by_wb: dict[str, list] = {}
    for src in sources:
        qs = extract_questions(src)
        dst = SANITIZED / src.name
        try:
            sanitize_workbook(src, dst)
            sheets = load_sheets(dst)
        except Exception as e:
            print(f"WARN sanitize/load {src.name}: {e}; using bench data_only", flush=True)
            try:
                sheets = load_sheets(src)
            except Exception as e2:
                print(f"SKIP {src.name}: {e2}", flush=True)
                continue
        print(f"{src.name}: {len(qs)} q", flush=True)
        for it in qs:
            t0 = time.perf_counter()
            pred = answer_sqlish(sheets, it["question"]) or ""
            sc = score_answer(pred, it.get("gold") or "", it.get("gold_values") or [])
            correct += int(sc["correct"])
            row = {
                "workbook": src.name,
                "qid": it["qid"],
                "question": it["question"],
                "gold": it.get("gold"),
                "pred": pred[:500],
                "correct": sc["correct"],
                "match_reason": sc["reason"],
                "lane": "sql" if pred else "miss",
                "ms": round((time.perf_counter() - t0) * 1000, 1),
                "difficulty": it.get("difficulty"),
                "reasoning_type": it.get("reasoning_type"),
            }
            rows.append(row)
            by_wb.setdefault(src.name, []).append(row)
            mark = "OK" if sc["correct"] else "MISS"
            print(f"  [{mark}] q{it['qid']} {sc['reason']}", flush=True)

    n = max(1, len(rows))
    summary = {
        "variant": "hybrid_sql_only",
        "n": len(rows),
        "correct": correct,
        "accuracy": round(correct / n, 3),
        "workbooks": len(sources),
        "by_workbook": {
            k: {
                "n": len(v),
                "correct": sum(1 for x in v if x["correct"]),
                "accuracy": round(sum(1 for x in v if x["correct"]) / max(1, len(v)), 3),
            }
            for k, v in by_wb.items()
        },
    }
    payload = {"ok": True, "honesty": "Cortex-direct demo path", "summary": summary, "rows": rows}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "frtr_batch_latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["workbook", "n", "correct", "accuracy"])
    for k, v in summary["by_workbook"].items():
        ws.append([k, v["n"], v["correct"], v["accuracy"]])
    ws.append([])
    ws.append(["TOTAL", summary["n"], summary["correct"], summary["accuracy"]])
    for c in ws[1]:
        c.font = Font(bold=True)
    wd = wb.create_sheet("Detail")
    wd.append(["workbook", "qid", "question", "gold", "pred", "correct", "lane"])
    for r in rows:
        wd.append([r["workbook"], r["qid"], r["question"], str(r["gold"])[:200], r["pred"][:300], r["correct"], r["lane"]])
    xp = RESULTS / "frtr_batch_latest.xlsx"
    wb.save(xp)
    print(json.dumps(summary, indent=2), flush=True)
    print(f"wrote {xp}", flush=True)


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    main(lim)

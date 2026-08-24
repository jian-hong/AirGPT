"""Run SQL-lane only across all FRTR gold questions (no RAG embed)."""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

from frtr_eval import RESULTS, SANITIZED, extract_questions, score_answer, BENCH
from frtr_sql_baseline import answer_sqlish, load_sheets


def main():
    all_q = []
    for p in sorted(BENCH.glob("frtr_*.xlsx")):
        all_q.extend(extract_questions(p))
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "frtr_gold.json").write_text(json.dumps(all_q, indent=2), encoding="utf-8")

    cache: dict[str, dict] = {}
    rows = []
    t0 = time.perf_counter()
    for i, it in enumerate(all_q, 1):
        wb = it["workbook"]
        if wb not in cache:
            sp = SANITIZED / wb
            cache[wb] = load_sheets(sp) if sp.is_file() else {}
        pred = answer_sqlish(cache[wb], it["question"]) or ""
        sc = score_answer(pred, it["gold"], it.get("gold_values") or [])
        rows.append({**it, "pred": pred, "correct": sc["correct"], "match_reason": sc["reason"], "lane": "sql"})
        if i % 20 == 0 or not sc["correct"]:
            mark = "OK" if sc["correct"] else "MISS"
            print(f"[{i}/{len(all_q)}] {mark} {wb} q{it['qid']} gold={str(it['gold'])[:40]} pred={pred[:40]}", flush=True)

    n = len(rows)
    correct = sum(1 for r in rows if r["correct"])
    by_r = Counter(r["reasoning_type"] for r in rows if r["correct"])
    miss_r = Counter(r["reasoning_type"] for r in rows if not r["correct"])
    summary = {
        "ok": True,
        "lane": "sql_only",
        "n": n,
        "correct": correct,
        "accuracy": round(correct / max(1, n), 3),
        "seconds": round(time.perf_counter() - t0, 1),
        "ok_by_reasoning": dict(by_r),
        "miss_by_reasoning": dict(miss_r),
        "misses": [
            {"workbook": r["workbook"], "qid": r["qid"], "q": r["question"], "gold": r["gold"], "pred": r["pred"], "type": r["reasoning_type"]}
            for r in rows
            if not r["correct"]
        ][:40],
    }
    out = {"summary": summary, "rows": rows}
    path = RESULTS / "frtr_sql_full.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print("wrote", path)


if __name__ == "__main__":
    main()

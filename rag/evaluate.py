"""Offline mode benchmark — score each depth tier per task type.

Seed for adaptive routing: run a golden set against basic/high/max on the same
space and report recall@k / MRR / rounds / latency per task type, plus a
per-task recommendation. Deterministic (extractive path, no LLM required).
"""
from __future__ import annotations

import time

from rag import answer, store


def _score_query(space_id: int, query: str, expect_path: str, depth: str, k: int) -> dict:
    t0 = time.perf_counter()
    res = answer.answer(space_id, query, depth=depth)
    ms = (time.perf_counter() - t0) * 1000.0
    rank = 0
    if res.get("ok") and expect_path:
        for i, c in enumerate((res.get("citations") or [])[:k], start=1):
            if expect_path in str(c.get("path") or ""):
                rank = i
                break
    return {
        "hit": 1 if rank else 0,
        "rr": (1.0 / rank) if rank else 0.0,
        "rounds": int(res.get("rounds") or 1),
        "coverage": float(res.get("coverage") or 0.0),
        "ms": ms,
    }


def _aggregate(rows: list[dict]) -> dict:
    n = max(1, len(rows))
    return {
        "n": len(rows),
        "recall_at_k": round(sum(r["hit"] for r in rows) / n, 3),
        "mrr": round(sum(r["rr"] for r in rows) / n, 3),
        "avg_rounds": round(sum(r["rounds"] for r in rows) / n, 2),
        "avg_coverage": round(sum(r["coverage"] for r in rows) / n, 3),
        "avg_ms": round(sum(r["ms"] for r in rows) / n, 1),
    }


def benchmark_modes(
    space_id: int,
    golden: list[dict],
    *,
    depths: tuple[str, ...] = ("basic", "high", "max"),
    k: int = 5,
) -> dict:
    """golden: [{query, expect_path, task_type}] → per-depth × per-task metrics."""
    space = store.get_space(space_id)
    if not space:
        return {"ok": False, "error": "space not found"}
    if not golden:
        return {"ok": False, "error": "golden set required"}

    results: dict[str, dict] = {}
    for depth in depths:
        d = str(depth).lower()
        if d not in ("basic", "high", "max", "manual"):
            continue
        all_rows: list[dict] = []
        per_task: dict[str, list[dict]] = {}
        for g in golden[:50]:
            query = str(g.get("query") or "").strip()
            if not query:
                continue
            row = _score_query(space_id, query, str(g.get("expect_path") or ""), d, k)
            task = str(g.get("task_type") or "general")
            per_task.setdefault(task, []).append(row)
            all_rows.append(row)
        results[d] = {
            "overall": _aggregate(all_rows),
            "tasks": {task: _aggregate(rows) for task, rows in per_task.items()},
        }

    # Recommendation per task: best recall, tie-broken by MRR then latency.
    tasks: set[str] = set()
    for r in results.values():
        tasks.update(r["tasks"].keys())
    recommend: dict[str, str] = {}
    for task in tasks:
        ranked = sorted(
            results.items(),
            key=lambda kv: (
                -kv[1]["tasks"].get(task, {}).get("recall_at_k", 0.0),
                -kv[1]["tasks"].get(task, {}).get("mrr", 0.0),
                kv[1]["tasks"].get(task, {}).get("avg_ms", 1e9),
            ),
        )
        if ranked:
            recommend[task] = ranked[0][0]

    return {
        "ok": True,
        "space_id": int(space_id),
        "k": int(k),
        "depths": [d for d in results],
        "results": results,
        "recommend": recommend,
    }

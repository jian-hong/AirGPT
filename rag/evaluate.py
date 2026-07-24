"""Offline mode benchmark — score each depth tier per task type.

Seed for adaptive routing: run a golden set against basic/high/max on the same
space and report recall@k / MRR / rounds / latency per task type, plus a
per-task recommendation. Deterministic (extractive path, no LLM required).
"""
from __future__ import annotations

import time

import random
import re
from pathlib import Path

from rag import answer, sira, store


def _score_query(space_id: int, query: str, expect_path: str, depth: str, k: int) -> dict:
    t0 = time.perf_counter()
    # Scoring measures RETRIEVAL quality (recall@k / MRR over citations) — generation
    # is irrelevant here, so skip the LLM: deterministic and dramatically faster.
    res = answer.answer(space_id, query, depth=depth, use_llm=False)
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

    store.update_space_settings(
        space_id,
        config={
            "adaptive_recommend": recommend,
            "adaptive_benchmark_at": time.time(),
        },
    )
    return {
        "ok": True,
        "space_id": int(space_id),
        "k": int(k),
        "depths": [d for d in results],
        "results": results,
        "recommend": recommend,
    }


_STOP = {
    "the", "and", "for", "that", "this", "with", "from", "into", "are", "was", "were",
    "you", "your", "our", "has", "have", "not", "but", "all", "can", "will", "use",
    "used", "using", "how", "what", "when", "which", "where", "they", "them", "its",
}


def _task_type(path: str) -> str:
    p = (path or "").lower()
    if re.search(r"\.(py|js|ts|tsx|jsx|go|rs|java|c|h|cpp|hpp|sql|sh|ps1)$", p):
        return "code_find"
    if "chat_" in p:
        return "chat_recall"
    if "url_" in p:
        return "web_fact"
    return "doc_fact"


def autogenerate_golden(space_id: int, *, n: int = 12, seed: int = 7, hard: bool = False) -> list[dict]:
    """Build test cases from the corpus itself, expecting the source file.

    difficulty:
    - easy (default): query = heading + the chunk's rarest/most distinctive tokens
      → trivially matched by FTS/file-level search. Good smoke, saturates fast.
    - hard: DROP the heading (file-level search would trivially match it) and use
      MID-frequency body tokens (present in the target but also elsewhere), so the
      retriever must *rank* on distributed signal rather than a single rare hit.
      This is where a weak embedder / diluted fusion actually shows up.

    No LLM — deterministic, so scoring is reproducible.
    """
    store.init()
    with store._conn() as conn:
        rows = conn.execute(
            "SELECT id, text, path, heading FROM chunks WHERE space_id=? AND kind='child' "
            "AND length(text) > 40 LIMIT 1500",
            (int(space_id),),
        ).fetchall()
    if not rows:
        return []

    # Corpus document-frequency over chunks — the difficulty lever.
    df: dict[str, int] = {}
    for r in rows:
        for t in set(sira.tokenize(str(r["text"] or ""))):
            df[t] = df.get(t, 0) + 1
    ndocs = len(rows)
    hi_ceiling = max(2, int(ndocs * 0.4))

    rng = random.Random(seed)
    by_file: dict[str, list] = {}
    for r in rows:
        by_file.setdefault(str(r["path"] or ""), []).append(r)
    picks = [rng.choice(v) for v in by_file.values()]
    rng.shuffle(picks)
    extras = [r for r in rows if r not in picks]
    rng.shuffle(extras)
    picks = (picks + extras)[: max(1, n)]

    golden: list[dict] = []
    for r in picks:
        text = str(r["text"] or "")
        heading = str(r["heading"] or "").strip()
        toks = [t for t in dict.fromkeys(sira.tokenize(text)) if len(t) >= 4 and t not in _STOP]
        if hard:
            band = [t for t in toks if 2 <= df.get(t, 0) <= hi_ceiling]
            salient = band[:6] or toks[:6]
            include_heading = False
        else:
            salient = toks[:6]
            include_heading = bool(heading and len(heading) < 60)
        if not salient:
            continue
        q = ((heading + " ") if include_heading else "") + " ".join(salient[:5])
        golden.append({
            "query": q.strip()[:160],
            "expect_path": Path(str(r["path"] or "")).name,
            "task_type": _task_type(str(r["path"] or "")),
        })
    return golden


def self_score(space_id: int, *, n: int = 12, k: int = 5, depths=("basic", "high", "max"), hard: bool = False) -> dict:
    """Auto-generate test cases from the corpus and score retrieval per mode.

    Returns per-mode metrics, per-task recommendation, and a headline recall so
    the UI can show "retrieval quality" and flag whether the RAG is world-class.
    Pass hard=True for adversarial mid-frequency queries (real discrimination).
    """
    space = store.get_space(space_id)
    if not space:
        return {"ok": False, "error": "space not found"}
    golden = autogenerate_golden(space_id, n=n, hard=hard)
    if not golden:
        return {"ok": False, "error": "no chunks to score — build the index first"}
    bench = benchmark_modes(space_id, golden, depths=tuple(depths), k=k)
    if not bench.get("ok"):
        return bench
    bench["difficulty"] = "hard" if hard else "easy"
    best = max(
        ((d, r["overall"]["recall_at_k"]) for d, r in bench["results"].items()),
        key=lambda kv: kv[1],
        default=("high", 0.0),
    )
    bench["golden_size"] = len(golden)
    bench["headline"] = {"best_mode": best[0], "best_recall_at_k": best[1]}
    bench["sample_cases"] = golden[:5]
    return bench

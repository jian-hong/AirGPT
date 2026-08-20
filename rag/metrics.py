"""Retrieval metrics that mean what their names say (RAG-BENCH-15).

The repo reports `recall_at_k` (rag/evaluate.py:43) computed as the fraction of
queries where the expected path appeared in the top k. That is **success@k**, not
recall. With one relevant document per query the two happen to coincide, so the
number was never wrong - the name was, and it stopped being harmless the moment
precision-recall was asked for by name.

Three things this module refuses to do:

1. Report precision@k without its ceiling. With one relevant document, precision@10
   cannot exceed 0.1. Printing "precision@10 = 0.09" next to "success@10 = 0.90"
   invites the reader to conclude the system is bad at 10 when it is at the maximum
   the qrels allow.
2. Report MAP and MRR as independent evidence when they are arithmetically identical
   (again, one relevant document each).
3. Silently accept an empty relevance set. A query with no known-relevant document
   scores 0 on everything and drags an average down while measuring nothing, so it
   is counted and excluded rather than folded in.

Full precision-recall curves and PR-AUC need graded, multi-document relevance
judgments (qrels). The repo has gold ANSWERS, not per-document judgments, so PR-AUC
is deliberately absent here rather than approximated from a single label.
"""
from __future__ import annotations

from typing import Iterable, Sequence

DEFAULT_KS = (1, 3, 5, 10)


def _norm(items: Iterable) -> list[str]:
    return [str(x) for x in items]


def _rel_set(relevant: Iterable) -> set[str]:
    return {str(x) for x in relevant if str(x).strip()}


def _hits(ranked: Sequence, relevant: Iterable, k: int) -> int:
    rel = _rel_set(relevant)
    return sum(1 for d in _norm(ranked)[:k] if d in rel)


def precision_at_k(ranked: Sequence, relevant: Iterable, k: int) -> float:
    """Of the k returned, what fraction are relevant. Denominator is k, always -
    shrinking it to len(ranked) flatters a run that returned too few results."""
    if k <= 0:
        return 0.0
    return _hits(ranked, relevant, k) / k


def precision_ceiling(relevant: Iterable, k: int) -> float:
    """Highest precision@k these judgments permit. Report it beside precision or the
    number reads as a failure when it is a property of the labels."""
    n_rel = len(_rel_set(relevant))
    if k <= 0 or not n_rel:
        return 0.0
    return min(n_rel, k) / k


def recall_at_k(ranked: Sequence, relevant: Iterable, k: int) -> float:
    """Of everything relevant, what fraction was returned in the top k."""
    rel = _rel_set(relevant)
    if not rel:
        return 0.0
    return _hits(ranked, relevant, k) / len(rel)


def success_at_k(ranked: Sequence, relevant: Iterable, k: int) -> float:
    """1.0 if ANY relevant document is in the top k. This is what the repo has been
    calling recall@k."""
    return 1.0 if _hits(ranked, relevant, k) else 0.0


def reciprocal_rank(ranked: Sequence, relevant: Iterable) -> float:
    rel = _rel_set(relevant)
    for i, d in enumerate(_norm(ranked), start=1):
        if d in rel:
            return 1.0 / i
    return 0.0


def average_precision(ranked: Sequence, relevant: Iterable, k: int | None = None) -> float:
    """Mean of precision@i over the ranks where a relevant document appears.

    Divided by the number of relevant documents, not by the number found, so a run
    that retrieves one of three relevant documents cannot score 1.0.
    """
    rel = _rel_set(relevant)
    if not rel:
        return 0.0
    docs = _norm(ranked)[: k] if k else _norm(ranked)
    found = 0
    acc = 0.0
    for i, d in enumerate(docs, start=1):
        if d in rel:
            found += 1
            acc += found / i
    return acc / len(rel)


def score_query(ranked: Sequence, relevant: Iterable, ks: Sequence[int] = DEFAULT_KS) -> dict:
    """All metrics for one query, plus the ceilings that make them readable."""
    rel = _rel_set(relevant)
    out: dict = {
        "n_relevant": len(rel),
        "n_returned": len(_norm(ranked)),
        "mrr": reciprocal_rank(ranked, relevant),
        "ap": average_precision(ranked, relevant),
        "scorable": bool(rel),
    }
    for k in ks:
        out[f"precision@{k}"] = precision_at_k(ranked, relevant, k)
        out[f"precision_ceiling@{k}"] = precision_ceiling(relevant, k)
        out[f"recall@{k}"] = recall_at_k(ranked, relevant, k)
        out[f"success@{k}"] = success_at_k(ranked, relevant, k)
    return out


def aggregate(rows: Sequence[dict], ks: Sequence[int] = DEFAULT_KS) -> dict:
    """Mean over scorable queries, with the caveats a reader needs to not misread it.

    Queries with no relevance judgment are EXCLUDED, not scored as zero, and the
    count is reported. Averaging in unlabelled queries would understate every metric
    while claiming a larger n than was actually measured (R-0010: n has to be the
    number of things actually observed).
    """
    scorable = [r for r in rows if r.get("scorable")]
    skipped = len(rows) - len(scorable)
    n = len(scorable)
    if not n:
        return {"n": 0, "skipped_unlabelled": skipped,
                "caveats": ["no query carried a relevance judgment - nothing was measured"]}

    out: dict = {"n": n, "skipped_unlabelled": skipped}
    out["map"] = round(sum(r["ap"] for r in scorable) / n, 4)
    out["mrr"] = round(sum(r["mrr"] for r in scorable) / n, 4)
    for k in ks:
        for name in (f"precision@{k}", f"recall@{k}", f"success@{k}", f"precision_ceiling@{k}"):
            out[name] = round(sum(r.get(name, 0.0) for r in scorable) / n, 4)

    caveats: list[str] = []
    max_rel = max(r.get("n_relevant", 0) for r in scorable)
    if max_rel <= 1:
        caveats.append(
            "every query has at most ONE relevant document: recall@k == success@k, "
            "and MAP == MRR. These are not four independent numbers."
        )
        for k in ks:
            if k > 1:
                caveats.append(
                    f"precision@{k} cannot exceed {round(1 / k, 4)} with one relevant "
                    f"document - compare against precision_ceiling@{k}, not against 1.0"
                )
                break
    if skipped:
        caveats.append(
            f"{skipped} quer{'y' if skipped == 1 else 'ies'} had no relevance judgment "
            f"and were excluded, not scored zero"
        )
    caveats.append(
        "PR-AUC is not reported: it needs graded multi-document qrels, and this corpus "
        "carries gold answers rather than per-document judgments"
    )
    out["caveats"] = caveats
    return out


def format_summary(agg: dict, ks: Sequence[int] = DEFAULT_KS) -> str:
    """Block a human can read without opening the JSON."""
    if not agg.get("n"):
        return "no scorable queries"
    lines = [f"n = {agg['n']}" + (f" ({agg['skipped_unlabelled']} unlabelled, excluded)"
                                  if agg.get("skipped_unlabelled") else "")]
    lines.append(f"  MAP {agg['map']:.4f}   MRR {agg['mrr']:.4f}")
    lines.append(f"  {'k':>3}  {'precision':>10} {'ceiling':>8}  {'recall':>7}  {'success':>7}")
    for k in ks:
        lines.append(
            f"  {k:>3}  {agg.get(f'precision@{k}', 0):>10.4f} "
            f"{agg.get(f'precision_ceiling@{k}', 0):>8.4f}  "
            f"{agg.get(f'recall@{k}', 0):>7.4f}  {agg.get(f'success@{k}', 0):>7.4f}"
        )
    for c in agg.get("caveats", []):
        lines.append(f"  note: {c}")
    return "\n".join(lines)

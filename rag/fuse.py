"""Generic reciprocal-rank fusion for AirGPT RAG (ported from CortexOS listing fuser)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RankedHit:
    doc_id: str
    score: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FusedHit:
    doc_id: str
    fused_score: float
    payload: dict[str, Any] = field(default_factory=dict)
    channel_scores: dict[str, float] = field(default_factory=dict)


def rrf_fuse(
    rank_lists: list[list[str]],
    *,
    k: int = 60,
    top_n: int = 30,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = defaultdict(float)
    for rank_list in rank_lists:
        for idx, doc_id in enumerate(rank_list):
            if not doc_id:
                continue
            scores[str(doc_id)] += 1.0 / (k + idx + 1)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return ranked[:top_n]


def fuse_channels(
    channels: dict[str, list[RankedHit]],
    *,
    k: int = 60,
    top_n: int = 30,
    weights: dict[str, float] | None = None,
) -> list[FusedHit]:
    """Fuse named retrieval channels (dense/sparse/file) via RRF.

    `weights` scales a channel's vote. Plain RRF counts every channel once, so one
    confident channel always loses to two lukewarm ones.
    """
    rank_scores: dict[str, float] = defaultdict(float)
    payloads: dict[str, dict[str, Any]] = {}
    channel_scores: dict[str, dict[str, float]] = defaultdict(dict)

    for name, hits in channels.items():
        w = float((weights or {}).get(name, 1.0))
        for idx, hit in enumerate(hits, start=1):
            doc_id = str(hit.doc_id)
            if not doc_id:
                continue
            rank_scores[doc_id] += w / (k + idx)
            channel_scores[doc_id][name] = float(hit.score)
            if doc_id not in payloads and hit.payload:
                payloads[doc_id] = dict(hit.payload)

    # Rounded so float noise cannot reorder near-equal scores. The sort is stable, so
    # ties keep first-seen order: the keyword channel is read first, which makes its
    # rank the tie-break. Each channel's own order is fixed by its query.
    ranked = sorted(rank_scores.items(), key=lambda x: -round(x[1], 9))[:top_n]
    return [
        FusedHit(
            doc_id=doc_id,
            fused_score=float(score),
            payload=payloads.get(doc_id, {}),
            channel_scores=dict(channel_scores.get(doc_id, {})),
        )
        for doc_id, score in ranked
    ]

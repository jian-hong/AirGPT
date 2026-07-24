"""Optional cross-encoder rerank after RRF (feature-flagged).

Enable with AIRGPT_RERANK=1. Falls back to RRF order when the
sentence-transformers CrossEncoder is missing or fails to load.
Default OFF to avoid surprise model downloads.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_MODEL: Any | None = None
_LOAD_FAILED = False
_MODEL_NAME = os.environ.get("AIRGPT_RERANK_MODEL") or "BAAI/bge-reranker-v2-m3"


def rerank_enabled() -> bool:
    raw = (os.environ.get("AIRGPT_RERANK") or "0").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _get_model() -> Any | None:
    global _MODEL, _LOAD_FAILED
    if _LOAD_FAILED:
        return None
    if _MODEL is not None:
        return _MODEL
    try:
        from sentence_transformers import CrossEncoder

        _MODEL = CrossEncoder(_MODEL_NAME)
        return _MODEL
    except Exception as exc:
        log.debug("reranker unavailable (%s); keeping RRF order", exc)
        _LOAD_FAILED = True
        return None


def _doc_text(hit: dict[str, Any]) -> str:
    text = str(hit.get("text") or hit.get("excerpt") or "").strip()
    if text:
        return text
    parts = [hit.get("heading"), hit.get("path"), hit.get("title")]
    return " ".join(str(p) for p in parts if p).strip()


def rerank_hits(
    query: str,
    hits: list[dict[str, Any]],
    *,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Rerank chunk hit dicts. Returns same shape with score/rerank_score updated."""
    if not hits or not rerank_enabled():
        return list(hits)
    n = int(top_n) if top_n is not None else len(hits)
    model = _get_model()
    if model is None:
        out = list(hits)
        for h in out:
            h.setdefault("rerank_score", 0.0)
            h["reranked"] = False
        return out[:n]

    pairs = [(query, _doc_text(h) or " ") for h in hits]
    try:
        raw = model.predict(pairs, show_progress_bar=False)
        scores = [float(x) for x in list(raw)]
    except Exception as exc:
        log.debug("rerank predict failed (%s)", exc)
        out = list(hits)
        for h in out:
            h.setdefault("rerank_score", 0.0)
            h["reranked"] = False
        return out[:n]

    ranked = sorted(zip(scores, hits), key=lambda x: x[0], reverse=True)
    out: list[dict[str, Any]] = []
    for score, hit in ranked[:n]:
        row = dict(hit)
        row["rerank_score"] = float(score)
        row["score"] = float(score)
        row["reranked"] = True
        out.append(row)
    return out


__all__ = ["rerank_enabled", "rerank_hits"]

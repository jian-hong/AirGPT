"""Rerank soft-fail preserves RRF order when model missing."""
from __future__ import annotations

from rag import rerank


def test_rerank_disabled_passthrough(monkeypatch):
    monkeypatch.setenv("AIRGPT_RERANK", "0")
    hits = [{"doc_id": "1", "text": "alpha", "score": 0.9}, {"doc_id": "2", "text": "beta", "score": 0.5}]
    out = rerank.rerank_hits("q", hits)
    assert [h["doc_id"] for h in out] == ["1", "2"]


def test_rerank_fallback_when_model_missing(monkeypatch):
    monkeypatch.setenv("AIRGPT_RERANK", "1")
    monkeypatch.setattr(rerank, "_LOAD_FAILED", True)
    monkeypatch.setattr(rerank, "_MODEL", None)
    hits = [{"doc_id": "a", "text": "one", "score": 1.0}, {"doc_id": "b", "text": "two", "score": 0.5}]
    out = rerank.rerank_hits("q", hits, top_n=1)
    assert len(out) == 1
    assert out[0]["doc_id"] == "a"
    assert out[0].get("reranked") is False

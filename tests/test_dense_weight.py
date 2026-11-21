"""The vector channel counts for less when the built-in hash embedder is active.

Measured on tests/RAG/paraphrase_bench.py (r@5 of 256 questions, seeds 1/2/3):
dense 1.0 -> 175/175/173, 0.5 -> 202/197/194, 0.25 -> 220/220/217, 0.0 -> 221/221/221.
Seed 1 picked the weight; seeds 2 and 3 are held out and agree.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "RAG"))
sys.path.insert(0, str(ROOT))

import paraphrase_bench as pb  # noqa: E402
from rag import embed, retrieve  # noqa: E402


def test_weight_follows_the_active_embedder(monkeypatch):
    monkeypatch.setattr(embed, "backend_name", lambda: "hash")
    assert 0 < retrieve.dense_weight() < 1.0
    monkeypatch.setattr(embed, "backend_name", lambda: "model")
    assert retrieve.dense_weight() == 1.0


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_paraphrase_total_beats_equal_weight_on_held_out_seeds(seed):
    res = pb.run(seed=seed)
    total = sum(res["styles"][s]["recall_at_5"] for s in pb.STYLES)
    assert total >= 210, f"seed {seed}: {total}/256 (equal weights scored 173-175)"


def test_trace_says_which_weight_was_used():
    import tempfile
    import rag.store as store
    from rag import ingest

    embed.reset_embedder_cache()
    saved = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        root = Path(tmp.name)
        store.RAG_DIR = root / "rag"
        store.DB_PATH = store.RAG_DIR / "rag.db"
        store.BLOB_DIR = store.RAG_DIR
        store.init()
        sid = int(store.create_space("w", depth_default="high")["id"])
        f = root / "a.txt"
        f.write_text("The retention period for invoices is seven years.\n", encoding="utf-8")
        ingest.ingest_paths(sid, [f])
        out = retrieve.search(sid, "retention period invoices", depth="high", top_k=3, debug=True)
        assert out["debug"]["dense_weight"] == retrieve.DENSE_WEIGHT_HASH
        assert "quarter" in out["debug"]["fusion_note"]
    finally:
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = saved
        embed.reset_embedder_cache()
        tmp.cleanup()

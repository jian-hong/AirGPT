"""Per-file-type retrieval gate (live, not a retained artifact).

Runs tests/RAG/filetype_bench.py at n=10 per type: generate a fixture for each
type, ingest all of them into one space, ask for every planted fact. It went
red on the code before this gate existed: json/csv/xlsx found 0 of 30, python
8 of 30, and html/docx/pdf/eml cited no location (see CHANGELOG 2026-11-12).

Floors are exact counts on a seeded set, not rates. n=110 bounds nothing about
real documents; it proves each lane ingests, retrieves and cites a place.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "RAG"))
sys.path.insert(0, str(ROOT))

import filetype_bench as fb  # noqa: E402


@pytest.fixture(scope="module")
def board():
    return fb.run(n=10, seed=1)["types"]


@pytest.mark.parametrize("kind", list(fb.TYPES))
def test_type_ingests_retrieves_and_cites(board, kind):
    row = board[kind]
    assert row["ingested"], f"{kind}: {row['reason']}"
    assert row["recall_at_5"] == row["n"], f"{kind}: missed {row['misses']}"
    assert row["recall_at_1"] >= row["n"] - 2, f"{kind}: top hit wrong {row['recall_at_1']}/{row['n']}"
    assert row["locator_ok"] == row["locator_n"], f"{kind}: {row['locator_ok']}/{row['locator_n']} cite a place"


def test_types_with_a_place_are_scored_for_it(board):
    """A locator column that silently scores nobody would pass the test above."""
    for kind in ("md", "html", "xlsx", "py", "docx", "pptx", "pdf", "eml", "xml", "log", "ipynb"):
        assert board[kind]["locator_n"] == board[kind]["n"], kind


def test_identifier_terms_are_names_and_codes_only():
    from rag import retrieve

    assert retrieve.identifier_terms("What is the escalation code for the Halvorsen account?") == ["Halvorsen"]
    assert retrieve.identifier_terms('status of ZQ-4471 and "net thirty" terms') == ["net thirty", "ZQ-4471"]
    assert retrieve.identifier_terms("how do we handle angry customers") == []


def test_common_term_gets_no_exact_boost(tmp_path, monkeypatch):
    """A capitalised word that is everywhere proves nothing and must not be pinned."""
    monkeypatch.setenv("AIRGPT_RAG_EMBED", "hash")
    import rag.store as store
    from rag import embed, ingest, retrieve

    embed.reset_embedder_cache()
    for name in ("RAG_DIR", "BLOB_DIR"):
        monkeypatch.setattr(store, name, tmp_path / "rag")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "rag" / "rag.db")
    store.init()
    sid = int(store.create_space("exact")["id"])
    docs = tmp_path / "docs"
    docs.mkdir()
    for i in range(8):
        (docs / f"n{i}.md").write_text(f"# Note {i}\n\nAcme renewed plan {i} this quarter.\n", encoding="utf-8")
    (docs / "one.md").write_text("# Rare\n\nThe Zorvath contract is void.\n", encoding="utf-8")
    ingest.ingest_paths(sid, sorted(docs.iterdir()))

    assert retrieve.exact_term_search(sid, "what did Acme renew") == []
    rare = retrieve.exact_term_search(sid, "is the Zorvath contract valid")
    assert len(rare) == 1 and "Zorvath" in rare[0].payload["text"]
    embed.reset_embedder_cache()


def test_offline_answer_quotes_the_value_not_the_chunk_head():
    """The offline answer clipped each chunk at 180 chars, so a value further down
    the chunk never reached the user. Look-alike sentences must not ride along."""
    from rag import answer

    filler = "The support tier for the Lonophnim account is SP-306005. " * 5
    hits = [
        {"path": "a.pdf", "heading": "Page 2",
         "text": "## Page 2\n" + filler + "The discount band for the Sarkelgan account is QJ-202807."},
        {"path": "b.md", "heading": "Region 2", "text": "The discount band for the Ulaquisar account is KT-397107."},
    ]
    out = answer.extractive_answer("What is the discount band for the Sarkelgan account?", hits)
    assert "QJ-202807" in out and "[1] (a.pdf · Page 2)" in out
    assert "KT-397107" not in out
    # No name in the question: both look-alikes are legitimate evidence.
    out = answer.extractive_answer("what is the discount band", hits)
    assert "QJ-202807" in out and "KT-397107" in out


def test_equal_scores_rank_in_a_defined_order():
    """Ranking must not depend on how a database build returns equal scores. Every
    ORDER BY on a score names a second key, and fusion rounds before it sorts."""
    import re

    from rag import fuse, retrieve

    src = Path(retrieve.__file__).read_text(encoding="utf-8")
    orders = re.findall(r"ORDER BY ([^\n]+)", src)
    assert orders and all("rowid" in o or "id" in o.split(",")[-1] for o in orders if "score" in o), orders
    a = fuse.RankedHit("7", 1.0, {"t": 1})
    b = fuse.RankedHit("3", 1.0, {"t": 2})
    # one channel each at the same rank: equal fused score, first-seen order wins
    out = fuse.fuse_channels({"sparse": [a], "dense": [b]})
    assert [h.doc_id for h in out] == ["7", "3"]

"""RAG-BENCH-17: stamp, drift compare, and the real-document pack shape.

Does not re-run the benches. CI job rag-benches does that and fails on drift.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAG = ROOT / "tests" / "RAG"
sys.path.insert(0, str(RAG))
sys.path.insert(0, str(ROOT))

import bench_stamp  # noqa: E402
import real_doc_bench as rdb  # noqa: E402
import regen_latest  # noqa: E402


def test_ndcg_at_10_is_not_success():
    assert rdb.ndcg_at_10(0) == 1.0
    assert abs(rdb.ndcg_at_10(1) - (1.0 / math.log2(3))) < 1e-12
    assert rdb.ndcg_at_10(9) > 0
    assert rdb.ndcg_at_10(10) == 0.0
    assert rdb.ndcg_at_10(None) == 0.0


def test_canonical_drops_volatile_fields_and_machine_paths():
    raw = {
        "commit_sha": "a" * 40,
        "generated_at": "2026-11-27T00:00:00Z",
        "ms": 12.5,
        "n": 3,
        "note": r"see D:\a\AirGPT\tests\RAG\fixtures\x.txt",
        "rows": [{"path": r"D:\a\AirGPT\tests\RAG\fixtures\x.txt", "ok": True, "ms": 1}],
    }
    got = bench_stamp.canonical(raw)
    assert got == {
        "n": 3,
        "note": "see tests/RAG/fixtures/x.txt",
        "rows": [{"ok": True}],
    }


def test_stamp_requires_sha_and_zulu_time():
    bench_stamp.require_stamp(
        {"commit_sha": "ab" * 20, "generated_at": "2026-11-27T01:02:03Z"},
        label="sample",
    )
    try:
        bench_stamp.require_stamp({"commit_sha": "nope", "generated_at": "yesterday"}, label="sample")
    except ValueError as exc:
        assert "commit_sha" in str(exc)
    else:
        raise AssertionError("bad stamp was accepted")


def test_every_latest_json_has_a_regenerator():
    gap = regen_latest.missing_from_registry()
    assert gap == [], gap
    assert "real_doc_bench_latest.json" in regen_latest.COMMANDS
    assert "oracle_cross_primary50.json" in regen_latest.COMMANDS


def test_real_doc_gold_is_value_level_and_at_least_200():
    rows = rdb.questions()
    assert len(rows) >= 200
    values = [r["value"] for r in rows]
    assert len(values) == len(set(values))
    styles = {r["style"] for r in rows}
    assert styles == {"verbatim", "synonym", "cross_file"}
    for r in rows:
        assert r["value"] and r["value"] not in r["question"]
        assert r["question"] and r["file"]
    cross = [r for r in rows if r["style"] == "cross_file"]
    assert len(cross) >= 80
    # The city question must not carry the desk number or the code.
    for r in cross:
        assert str(r["desk"]) not in r["question"]
        assert r["value"] not in r["question"]


def test_metrics_module_calls_bench_recall_fields_success_at_k():
    text = (ROOT / "rag" / "metrics.py").read_text(encoding="utf-8")
    assert "success@k" in text
    assert "recall_at_1" in text
    assert "ndcg_at_10" in text
    assert "not success@k" in text or "It is not success@k" in text or "not\nsuccess@k" in text


def test_stamp_sha_that_is_a_parent_counts_when_merge_base_cannot_see_it():
    """A depth-1 PR checkout has the merge commit but not its parent objects.

    The suite job uses that checkout, so this test must not ask git for the
    real parents: `git rev-parse HEAD^@` returns nothing there.
    """
    import subprocess

    parent = "9118e72f7250d85768fd4a3802c6fe82c3ed32e2"
    real = subprocess.run

    class Proc:
        def __init__(self, code, out):
            self.returncode = code
            self.stdout = out
            self.stderr = ""

    def hidden_parent(cmd, **kwargs):
        args = list(cmd)
        if args[:3] == ["git", "merge-base", "--is-ancestor"]:
            return Proc(1, "")
        if args[:2] == ["git", "rev-parse"] and str(args[2]).endswith("^@"):
            return Proc(0, parent + "\n")
        return real(cmd, **kwargs)

    subprocess.run = hidden_parent
    try:
        assert bench_stamp.is_ancestor(parent, "HEAD")
        assert bench_stamp.is_ancestor("a" * 40, "HEAD") is False
    finally:
        subprocess.run = real


def test_committed_real_doc_artifact_is_harder_than_a_saturated_board():
    """The paraphrase board is already success@5 on every question. This pack must not be."""
    path = RAG / "results" / "real_doc_bench_latest.json"
    assert path.is_file(), "run tests/RAG/real_doc_bench.py and commit the JSON"
    data = json.loads(path.read_text(encoding="utf-8"))
    bench_stamp.require_stamp(data, label=path.name)
    n = data["success_at_5"]["n"]
    hit = data["success_at_5"]["hit"]
    assert n >= 200
    assert data["success_at_1"]["n"] == n
    assert hit < n, f"success@5 {hit}/{n} is saturated; the pack is not harder than paraphrase"
    assert 0.0 <= data["ndcg_at_10"] <= 1.0
    assert "success@k" in data["metric_note"]
    gold = json.loads((RAG / "real_docs" / "gold.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in gold] == [r["id"] for r in rdb.questions()]

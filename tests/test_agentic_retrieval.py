"""Agentic retrieval without a model: the bridge hop, contextual chunks, and depth.

Each test names the defect it pins and fails on commit fce33bf.
  * property questions ("the account whose headquarters city is Tromso") need two pieces
    of evidence; a second look for the name the first passage holds finds the second
  * a deeper search never finds less than a shallower one (the file boost came and went
    with the depth and lifted every chunk of a favoured file over the answer)
  * a chunk is indexed with the headings above it but cited with its own words
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "RAG"))
sys.path.insert(0, str(ROOT))

import paraphrase_bench as pb  # noqa: E402
from rag import embed, index_fingerprint, ingest, retrieve  # noqa: E402
import rag.store as store  # noqa: E402


@contextmanager
def space(files: dict[str, str]):
    embed.reset_embedder_cache()
    saved = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        root = Path(tmp.name)
        store.RAG_DIR = root / "rag"
        store.DB_PATH = store.RAG_DIR / "rag.db"
        store.BLOB_DIR = store.RAG_DIR
        store.init()
        sid = int(store.create_space("agentic", depth_default="high")["id"])
        paths = []
        for name, body in files.items():
            p = root / name
            p.write_text(body, encoding="utf-8")
            paths.append(p)
        ingest.ingest_paths(sid, paths)
        yield sid
    finally:
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = saved
        embed.reset_embedder_cache()
        tmp.cleanup()


NAMES = ["Zerbruwex", "Halvorsen", "Quisenbru", "Ophzertas", "Wexdovula", "Mikophhal", "Fenquidov", "Lontasoph"]
CITIES = ["Tromso", "Kragero", "Lillesand", "Haugesund", "Odense", "Aalborg", "Esbjerg", "Vaasa"]


def _register() -> str:
    parts = ["# Account register", ""]
    for i, n in enumerate(NAMES):
        parts += [f"## Region {i} accounts", "", f"The retention period for the {n} account is ZQ-{4400 + i}.",
                  f"The billing cycle for the {n} account is monthly-{i}.", ""]
    parts += ["# Offices", ""]
    for n, c in zip(NAMES, CITIES):
        parts += [f"The headquarters city for the {n} account is {c}.", ""]
    return "\n".join(parts)


def test_property_question_is_answered_by_a_second_look():
    with space({"register.md": _register()}) as sid:
        for n, c, i in zip(NAMES, CITIES, range(len(NAMES))):
            q = f"What is the retention period for the account whose headquarters city is {c}?"
            out = retrieve.search(sid, q, depth="high", top_k=5, debug=True)
            assert f"ZQ-{4400 + i}" in out["hits"][0]["text"], (q, out["hits"][0]["text"][:120])
            said = out["debug"]["extra_search"]
            assert said and n in said[0] and c in said[0] and "register.md" in said[0], said


def test_the_second_look_is_adaptive_and_depth_limited():
    with space({"register.md": _register()}) as sid:
        q = "What is the retention period for the account whose headquarters city is Tromso?"
        assert retrieve.search(sid, q, depth="basic", debug=True)["debug"]["extra_search"] == []
        # a question the first pass already answers makes no second search
        plain = "What is the retention period for the Halvorsen account?"
        assert retrieve.search(sid, plain, depth="high", debug=True)["debug"]["extra_search"] == []
        assert retrieve.search(sid, plain, depth="max", debug=True)["debug"]["extra_search"] == []


def test_two_hops_only_at_max():
    doc = "\n\n".join(
        [f"Person{i} Surname{i} is based in City{i}." for i in range(6)]
        + [f"Person{i} Surname{i} manages the Acct{i}x account." for i in range(6)]
        + [f"The retention period for the Acct{i}x account is ZQ-{7000 + i}." for i in range(6)]
    )
    q = "What is the retention period for the account run by the manager based in City3?"
    with space({"staff.md": doc}) as sid:
        high = retrieve.search(sid, q, depth="high", top_k=3, debug=True)
        mx = retrieve.search(sid, q, depth="max", top_k=3, debug=True)
    assert len(mx["debug"]["extra_search"]) >= len(high["debug"]["extra_search"])
    assert "ZQ-7003" in mx["hits"][0]["text"]


def test_no_time_left_means_no_second_look_and_no_error(monkeypatch):
    monkeypatch.setattr(retrieve, "BRIDGE_BUDGET_S", -1.0)
    with space({"register.md": _register()}) as sid:
        q = "What is the retention period for the account whose headquarters city is Tromso?"
        out = retrieve.search(sid, q, depth="max", top_k=5, debug=True)
        assert out["ok"] and out["debug"]["extra_search"] == []


@pytest.mark.parametrize("seed", [1, 2])
def test_a_deeper_search_never_finds_less(seed):
    top5, top1 = {}, {}
    for d in ("basic", "high", "max"):
        res = pb.run(seed=seed, depth=d)
        top5[d] = sum(res["styles"][s]["recall_at_5"] for s in pb.STYLES)
        top1[d] = sum(res["styles"][s]["recall_at_1"] for s in pb.STYLES)
    assert top5["basic"] <= top5["high"] <= top5["max"], top5
    assert top1["basic"] <= top1["high"] <= top1["max"], top1


def test_property_questions_are_found_at_rank_one_at_high_and_max():
    for d in ("high", "max"):
        res = pb.run(seed=1, depth=d)
        cell = res["styles"]["property"]
        assert cell["recall_at_1"] >= 60 and cell["recall_at_5"] == cell["n"], (d, cell)


# --- contextual chunks -----------------------------------------------------------------

def _policies() -> str:
    kinds = ["Vendor", "Customer", "Partner", "Employee", "Contractor", "Visitor", "Student", "Member"]
    days = [11, 23, 37, 41, 53, 67, 79, 83]
    out = []
    for k, d in zip(kinds, days):
        out += [f"# {k} policy", "", "## Security", "", "### Retention", "", f"Logs are kept for {d} days."]
    return "\n".join(out)


def test_a_chunk_is_found_by_the_headings_above_it():
    """Eight policies each have "### Retention"; only the heading chain tells them apart."""
    kinds = ["vendor", "customer", "partner", "employee", "contractor", "visitor", "student", "member"]
    days = [11, 23, 37, 41, 53, 67, 79, 83]
    with space({"handbook.md": _policies()}) as sid:
        first, top3 = 0, 0
        for k, d in zip(kinds, days):
            q = f"How long are logs kept under the {k} policy?"
            want = f"kept for {d} days"
            first += want in retrieve.sparse_search(sid, q, k=5)[0].payload["text"]
            top3 += any(want in h["text"] for h in retrieve.search(sid, q, depth="high", top_k=3)["hits"])
        assert first == 8, first
        assert top3 == 8, top3


def test_the_cited_text_is_the_original_text_not_the_context():
    with space({"handbook.md": _policies()}) as sid:
        out = retrieve.search(sid, "How long are logs kept under the vendor policy?", depth="high", top_k=3)
        for c in out["citations"]:
            assert "Vendor policy >" not in c["excerpt"] and " > Security" not in c["excerpt"]
        con = sqlite3.connect(store.DB_PATH)
        try:
            texts = [r[0] for r in con.execute("SELECT text FROM chunks WHERE kind='child'")]
        finally:
            con.close()
        assert texts and not any(" > " in t for t in texts)
        assert any("Logs are kept for 11 days." in t for t in texts)


def test_a_space_indexed_without_context_keeps_working():
    """Rows written before schema 3 have no context in the keyword index or in meta."""
    with space({"a.txt": "The sky is blue on clear days.\n"}) as sid:
        cid = store.insert_chunk(space_id=sid, source_id=0, revision_id=0, text="Zebras have stripes.",
                                 kind="child", path="old.txt", heading="")
        assert cid
        out = retrieve.search(sid, "zebras stripes", depth="high", top_k=3)
        assert any("Zebras" in h["text"] for h in out["hits"])


def test_the_vector_index_reads_context_only_for_a_real_embedding_model(monkeypatch):
    monkeypatch.setattr(embed, "backend_name", lambda: "hash")
    assert ingest.child_vector_text("Handbook", "Handbook > Security", "Security", "Body.") == "Security\nBody."
    monkeypatch.setattr(embed, "backend_name", lambda: "model")
    assert ingest.child_vector_text("Handbook", "Handbook > Security", "Security", "Body.") == (
        "Handbook > Handbook > Security\nSecurity\nBody."
    )


def test_the_title_is_made_of_words():
    assert ingest._title_words("q3_Travel-Budget.xlsx") == "q3 Travel Budget"
    assert ingest._title_words("EmployeeHandbook.docx") == "Employee Handbook"


def test_the_fingerprint_says_the_chunk_context_changed_the_index():
    assert index_fingerprint.SCHEMA_VERSION >= 3
    old = index_fingerprint.fingerprint()
    old = {**old, "schema_version": 2}
    old["id"] = index_fingerprint._hash_fields(old)
    ok, reasons = index_fingerprint.comparable(index_fingerprint.fingerprint(), old)
    assert not ok and any("schema" in r for r in reasons)


@pytest.mark.parametrize("depth", ["high", "max"])
def test_the_hash_weight_is_not_worse_than_full_weight_and_gains_at_rank_one(depth, monkeypatch):
    """With the bridge hop the top five is full either way, so rank 1 tells the weights apart."""

    def points(seed):
        res = pb.run(seed=seed, depth=depth)
        return (sum(res["styles"][s]["recall_at_5"] for s in pb.STYLES),
                sum(res["styles"][s]["recall_at_1"] for s in pb.STYLES))

    gain = 0
    for seed in (1, 2, 3):
        low5, low1 = points(seed)
        monkeypatch.setattr(retrieve, "dense_weight", lambda: 1.0)
        eq5, eq1 = points(seed)
        monkeypatch.undo()
        assert low5 >= eq5 and low1 >= eq1, (seed, depth, (low5, low1), (eq5, eq1))
        gain += (low5 - eq5) + (low1 - eq1)
    assert gain > 0, (depth, gain)


def test_the_second_look_stays_inside_the_files_the_user_chose():
    """A search scoped to one file must not read the other files, or name them in the trace."""
    other = "# Notes\n\nThe Halvorsen account note: payload ZZ-9999 stays here. Zerbruwex lives in Tromso vault.\n"
    q = "What is the retention period for the account whose headquarters city is Tromso?"
    with space({"register.md": _register(), "other.md": other}) as sid:
        with store._conn() as conn:
            rows = conn.execute("SELECT id, path FROM sources WHERE space_id=?", (sid,)).fetchall()
        only_other = [int(r["id"]) for r in rows if "other" in str(r["path"])]
        only_reg = [int(r["id"]) for r in rows if "register" in str(r["path"])]
        out = retrieve.search(sid, q, depth="high", top_k=5, debug=True, source_ids=only_other)
        assert out["debug"]["extra_search"] == []
        assert all("ZQ-44" not in h["text"] for h in out["hits"])
        out = retrieve.search(sid, q, depth="high", top_k=5, debug=True, source_ids=only_reg)
        assert out["debug"]["extra_search"] and all("other.md" not in n for n in out["debug"]["extra_search"])
        assert "ZQ-4400" in out["hits"][0]["text"]

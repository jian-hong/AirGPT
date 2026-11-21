"""Seams: file scope, packs and overlapping uploads meet the table lane and ingest.

Each test asserts what the user receives (the answer text, the source list, the notice).
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import test_rag_document_tables as T  # noqa: E402


@pytest.fixture()
def env():
    os.environ["AIRGPT_RAG_EMBED"] = "hash"
    import rag.store as store
    from rag import embed

    embed.reset_embedder_cache()
    saved = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    root = Path(tmp.name)
    store.RAG_DIR = root / "rag"
    store.DB_PATH = store.RAG_DIR / "rag.db"
    store.BLOB_DIR = store.RAG_DIR
    store.init()
    try:
        yield root
    finally:
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = saved
        embed.reset_embedder_cache()
        tmp.cleanup()


def _space():
    import rag.store as store

    return int(store.create_space("t", depth_default="high")["id"])


def _ask(sid, q, **kw):
    from rag import answer

    return answer.answer(sid, q, use_llm=False, **kw)


def test_table_maths_stays_inside_the_file_scope(env):
    import rag.store as store
    from rag import ingest

    root = env
    sid = _space()
    (root / "north.csv").write_text("Region,Revenue\nNorth,100\nNorth,200\n", encoding="utf-8")
    (root / "south.csv").write_text("Region,Revenue\nSouth,5000\nSouth,7000\n", encoding="utf-8")
    T.write_docx(root / "memo.docx", [])
    ingest.ingest_paths(sid, [root / "north.csv", root / "south.csv", root / "memo.docx"])
    ids = {s["title"]: int(s["id"]) for s in store.list_sources(sid)}
    got = _ask(sid, "What is the total Revenue?", source_ids=[ids["north.csv"]])["answer"]
    assert T.has(got, 300), got
    assert not T.has(got, 12000) and not T.has(got, 12300), got
    assert "south" not in got.lower() and "memo" not in got.lower(), got
    got = _ask(sid, "What is the total Revenue?", source_ids=[ids["south.csv"]])["answer"]
    assert T.has(got, 12000), got
    assert not T.has(got, 12300), got


def test_pack_says_document_tables_travel_as_text(env):
    from rag import export_import, ingest

    root = env
    sid = _space()
    for n, w in T.WRITERS.items():
        w(root / n)
    ingest.ingest_paths(sid, [root / n for n in T.WRITERS])
    out = export_import.import_pack(export_import.export_space(sid, include_chats=False), name="imp")
    named = " ".join(out.get("spreadsheets_as_text") or [])
    for n in T.WRITERS:
        assert n in named, out
    assert "cannot be calculated" in out.get("notice", ""), out


def test_repeated_column_note_survives_a_pack(env):
    import openpyxl

    from rag import export_import, ingest

    root = env
    sid = _space()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Main"
    ws.append(["Name", "Score", "Score"])
    for r in [("a", 1, 10), ("b", 2, 20), ("c", 3, 30)]:
        ws.append(r)
    wb.save(root / "book.xlsx")
    ingest.ingest_paths(sid, [root / "book.xlsx"])
    before = _ask(sid, "What is the total of Score?")["answer"]
    assert "2 columns called Score" in before, before
    r = export_import.import_pack(export_import.export_space(sid, include_chats=False), name="imp")
    nid = int(r["space"]["id"])
    after = _ask(nid, "What is the total of Score?")["answer"]
    assert "2 columns called Score" in after, after
    assert T.has(_ask(nid, "What is the total Score__2?")["answer"], 60)


def test_overlapping_uploads_of_one_file_make_one_source(env):
    import rag.store as store
    from rag import ingest

    root = env
    sid = _space()
    body = "# Doc\n\n" + "\n\n".join(f"## Part {i}\n\nThe Quixotic fact number {i} is stored here with detail." for i in range(12))
    (root / "d.md").write_text(body, encoding="utf-8")
    errs = []
    gate = threading.Barrier(6)

    def go():
        try:
            gate.wait()
            r = ingest.ingest_paths(sid, [root / "d.md"])
            if not r.get("ok"):
                errs.append(r)
        except Exception as e:  # pragma: no cover
            errs.append(repr(e))

    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs, errs
    assert len(store.list_sources(sid)) == 1
    c = sqlite3.connect(store.DB_PATH)
    per = c.execute("select source_id,count(*) from chunks group by source_id").fetchall()
    assert len(per) == 1, per
    cites = _ask(sid, "Quixotic fact number 3").get("citations", [])
    assert len({c_.get("title") or c_.get("path") for c_ in cites}) == 1


def test_rebuild_of_a_row_whose_original_is_gone_replaces_it(env):
    import rag.store as store
    from rag import ingest

    root = env
    sid = _space()
    old_text = "Alpha line one\rAlpha line two about Quixotic widgets\rend"
    (root / "cr.txt").write_bytes((old_text + "\r").encode())
    ingest.ingest_paths(sid, [root / "cr.txt"])
    cr = store.list_sources(sid)[0]
    with store._conn() as conn:
        conn.execute("update sources set content_hash=? where id=?", (hashlib.sha256(old_text.encode()).hexdigest(), cr["id"]))
    Path(cr["meta"]["blob"]).write_text(old_text, encoding="utf-8", newline="\n")
    (root / "cr.txt").unlink()
    ingest.ingest_paths(sid, ingest.rebuild_source_paths(store.list_sources(sid)), force=True)
    srcs = store.list_sources(sid)
    assert len(srcs) == 1, [s["title"] for s in srcs]
    assert "Quixotic" in _ask(sid, "Quixotic widgets")["answer"]

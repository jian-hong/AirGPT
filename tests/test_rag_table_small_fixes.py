"""Small table fixes: a repeated column name says which copy was used; a workbook's banner
row is not the sheet's first line (a CSV already had this)."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture()
def space():
    os.environ["AIRGPT_RAG_EMBED"] = "hash"
    import rag.store as store
    from rag import embed, ingest

    embed.reset_embedder_cache()
    saved = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    root = Path(tmp.name)
    store.RAG_DIR = root / "rag"
    store.DB_PATH = store.RAG_DIR / "rag.db"
    store.BLOB_DIR = store.RAG_DIR
    store.init()
    sid = int(store.create_space("small", depth_default="high")["id"])
    try:
        yield sid, root, lambda *paths: ingest.ingest_paths(sid, list(paths))
    finally:
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = saved
        embed.reset_embedder_cache()
        tmp.cleanup()


def _ask(sid, q):
    from rag import answer

    return answer.answer(sid, q, use_llm=False)["answer"]


def test_repeated_csv_column_says_which_copy_it_used(space):
    sid, root, ingest_ = space
    p = root / "dup.csv"
    p.write_text("name,score,score\nAna,10,1\nBo,20,2\nCy,30,3\n", encoding="utf-8")
    ingest_(p)
    df = pd.read_csv(p)  # pandas calls the second copy score.1
    first, second = df["score"].sum(), df["score.1"].sum()
    got = _ask(sid, "What is the total score?")
    assert re.match(rf"\s*{first:g}\b", got), got
    assert "2 columns called score" in got and "score__2" in got, got
    # naming the other copy reads the other copy, and needs no note
    got = _ask(sid, "What is the total score__2?")
    assert re.match(rf"\s*{second:g}\b", got), got
    assert "columns called" not in got


def test_xlsx_banner_row_is_not_the_first_line_of_the_sheet():
    import openpyxl

    from rag import ingest

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        p = Path(d) / "export.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Stock"
        ws.append(["Monthly stock report - confidential"])
        ws.append(["id", "name", "units"])
        for i in range(12):
            ws.append([f"P{i}", f"part {i}", i * 2])
        wb.save(p)
        text = ingest._xlsx_text(p)
    body = text.split("## Sheet: Stock\n", 1)[1]
    assert body.splitlines()[0] == "id | name | units"
    assert "Monthly stock report" in text.split("## Sheet: Stock")[0]  # kept, in the index

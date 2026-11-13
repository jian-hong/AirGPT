"""Re-ingest behaviour, the new text types, and two small docx/html defects.

Every fixture is built by hand (zip + XML, raw bytes) so none of this depends on
the libraries the extractors replace.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag import chunking, ingest  # noqa: E402


@pytest.fixture()
def space(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRGPT_RAG_EMBED", "hash")
    import rag.store as store
    from rag import embed

    embed.reset_embedder_cache()
    for name in ("RAG_DIR", "BLOB_DIR"):
        monkeypatch.setattr(store, name, tmp_path / "rag")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "rag" / "rag.db")
    store.init()
    sid = int(store.create_space("more")["id"])
    yield sid, store
    embed.reset_embedder_cache()


def _chunks(store, sid):
    con = sqlite3.connect(store.DB_PATH)
    try:
        return [r[0] for r in con.execute("select text from chunks where space_id=? and kind='child'", (sid,))]
    finally:
        con.close()


# --- 1. re-ingest ---------------------------------------------------------------

def test_same_file_twice_adds_nothing(space, tmp_path):
    sid, store = space
    f = tmp_path / "a.md"
    f.write_text("# Sec\n\nThe code for Zorvath is AB-1234.\n", encoding="utf-8")
    ingest.ingest_paths(sid, [f])
    first = _chunks(store, sid)
    out = ingest.ingest_paths(sid, [f])
    assert out["ok"]
    assert _chunks(store, sid) == first  # was two copies: a duplicate hit and citation
    assert len(store.list_sources(sid)) == 1


def test_changed_file_replaces_its_old_chunks(space, tmp_path):
    sid, store = space
    f = tmp_path / "a.md"
    f.write_text("# Sec\n\nThe code for Zorvath is AB-1234.\n", encoding="utf-8")
    ingest.ingest_paths(sid, [f])
    f.write_text("# Sec\n\nThe code for Zorvath is CD-9999.\n", encoding="utf-8")
    ingest.ingest_paths(sid, [f])
    text = "\n".join(_chunks(store, sid))
    assert "CD-9999" in text and "AB-1234" not in text
    assert len(store.list_sources(sid)) == 1


def test_same_name_in_two_folders_stays_two_files(space, tmp_path):
    sid, store = space
    for d, code in (("one", "AA-1111"), ("two", "BB-2222")):
        (tmp_path / d).mkdir()
        (tmp_path / d / "README.md").write_text(f"# R\n\nThe code is {code}.\n", encoding="utf-8")
    ingest.ingest_paths(sid, [tmp_path / "one", tmp_path / "two"])
    text = "\n".join(_chunks(store, sid))
    assert "AA-1111" in text and "BB-2222" in text


def test_force_rebuild_still_reindexes(space, tmp_path):
    sid, store = space
    f = tmp_path / "a.md"
    f.write_text("# Sec\n\nThe code for Zorvath is AB-1234.\n", encoding="utf-8")
    ingest.ingest_paths(sid, [f])
    ingest.ingest_paths(sid, [f], force=True)
    assert len(_chunks(store, sid)) == 1


# --- 2. new types -----------------------------------------------------------------

def test_new_suffixes_are_accepted():
    for suf in (".tsv", ".xml", ".log", ".ipynb", ".rtf"):
        assert suf in ingest.TEXT_SUFFIXES


def test_tsv_is_a_sheet_with_a_header(tmp_path):
    p = tmp_path / "t.tsv"
    p.write_text("name\tcode\nAlpha\tX-1\nBeta\t\n", encoding="utf-8")
    text, _ = ingest.read_text_file(p)
    assert "## Sheet: t" in text and "Alpha | X-1" in text and "Beta" in text
    assert ingest.is_table_text(p, text)


def test_xml_keeps_records_whole_and_names_the_path(tmp_path):
    p = tmp_path / "r.xml"
    p.write_text(
        '<?xml version="1.0"?><reg xmlns="urn:x"><region name="North">'
        "<account><name>Zorvath</name><value>AB-1</value></account>"
        "<account><name>Quill</name><value>CD-2</value></account>"
        "</region></reg>",
        encoding="utf-8",
    )
    text, _ = ingest.read_text_file(p)
    assert "## reg/region" in text
    assert "reg/region/account[1]/value: AB-1" in text
    assert "reg/region/@name: North" in text
    first = text.split("\n\n")
    rec = next(b for b in first if "Zorvath" in b)
    assert "AB-1" in rec and "CD-2" not in rec  # one record per paragraph


def test_broken_xml_falls_back_to_raw_text(tmp_path):
    p = tmp_path / "bad.xml"
    p.write_text("<a><b>still here", encoding="utf-8")
    assert "still here" in ingest.read_text_file(p)[0]


def test_log_stack_trace_stays_with_its_record_and_dates_head_sections(tmp_path):
    p = tmp_path / "app.log"
    p.write_text(
        "2026-03-01 09:00:00 INFO start ok\n"
        "2026-03-01 09:00:05 ERROR job failed for Zorvath\n"
        "Traceback (most recent call last):\n"
        '  File "w.py", line 4, in run\n'
        "\n"
        "ValueError: bad\n"
        "2026-03-02 10:00:00 INFO next day\n",
        encoding="utf-8",
    )
    text, _ = ingest.read_text_file(p)
    assert "## 2026-03-01" in text and "## 2026-03-02" in text
    rec = next(b for b in text.split("\n\n") if "job failed" in b)
    assert "Traceback" in rec and "ValueError: bad" in rec
    assert "next day" not in rec


def test_log_without_records_is_left_as_text(tmp_path):
    p = tmp_path / "plain.log"
    # Bytes, with CRLF: write_text makes these on Windows and plain "\n" elsewhere,
    # so the text form of this test only failed on the Windows runner.
    p.write_bytes(b"just some words\r\nmore words\r\n")
    assert ingest.read_text_file(p)[0] == "just some words\nmore words"


def test_ipynb_headings_code_and_skipped_outputs(tmp_path):
    nb = {
        "cells": [
            {"cell_type": "markdown", "source": ["# Analysis\n", "Intro text"]},
            {"cell_type": "code", "source": ["# a comment\n", "x = 1"],
             "outputs": [{"output_type": "stream", "text": ["HUGE-OUTPUT-MARKER"]}]},
            {"cell_type": "markdown", "source": "## Results"},
        ],
        "nbformat": 4,
    }
    p = tmp_path / "n.ipynb"
    p.write_text(json.dumps(nb), encoding="utf-8")
    text, _ = ingest.read_text_file(p)
    assert "HUGE-OUTPUT-MARKER" not in text
    assert "    x = 1" in text
    assert chunking.extract_headings(text) == ["Analysis", "Results"]  # the code comment is no heading


def test_rtf_strips_control_words_and_keeps_text(tmp_path):
    p = tmp_path / "d.rtf"
    p.write_bytes(
        b"{\\rtf1\\ansi\\ansicpg1252{\\fonttbl{\\f0 Arial;}}{\\colortbl;\\red0;}{\\*\\generator X;}"
        b"\\pard\\b Heading\\b0\\par Caf\\'e9 and \\u8364? sign \\{ok\\}\\par second line}"
    )
    text, _ = ingest.read_text_file(p)
    assert "Arial" not in text and "generator" not in text and "\\" not in text
    assert text.splitlines()[0] == "Heading"
    assert "Café and € sign {ok}" in text
    assert text.splitlines()[-1] == "second line"
    assert "rtf1" not in text and "pard" not in text


def test_new_types_ingest_through_the_pipeline(space, tmp_path):
    sid, store = space
    (tmp_path / "d.rtf").write_bytes(b"{\\rtf1 The vault code is ZQ-7788.\\par}")
    (tmp_path / "t.tsv").write_text("k\tv\nvault\tZQ-1\n", encoding="utf-8")
    out = ingest.ingest_paths(sid, [tmp_path / "d.rtf", tmp_path / "t.tsv"])
    assert out["ok"] and out["sources"] == 2 and not out["skipped"]


# --- 3. docx nested table, html heading ---------------------------------------------

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(path: Path, body: str) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{_W}"><w:body>{body}</w:body></w:document>')


def _p(t: str) -> str:
    return f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>"


def _tc(inner: str) -> str:
    return f"<w:tc>{inner}</w:tc>"


def test_docx_nested_table_rows_get_their_own_lines(tmp_path):
    inner = "<w:tbl><w:tr>" + _tc(_p("Inner1")) + _tc(_p("Inner2")) + "</w:tr></w:tbl>"
    outer = "<w:tbl><w:tr>" + _tc(_p("Outer1")) + _tc(_p("Cell") + inner) + "</w:tr></w:tbl>"
    p = tmp_path / "n.docx"
    _docx(p, outer)
    lines = ingest._docx_text(p).splitlines()
    assert "Outer1 | Cell" in lines
    assert "Inner1 | Inner2" in lines


def test_html_heading_with_a_line_break_stays_on_one_line():
    _, text = ingest.html_to_text("<h1>Hello <b>big</b>\n world</h1><p>Body</p>")
    assert text.splitlines()[0] == "# Hello big world"
    _, text = ingest.html_to_text("<h2>Two<br>lines</h2><p>Body</p>")
    assert text.splitlines()[0] == "## Two lines"


def test_changing_one_of_two_identical_files_keeps_the_other(tmp_path, monkeypatch):
    """Identical files share one source row. Editing one copy used to delete that
    row, and the untouched copy's content left the index with it."""
    monkeypatch.setenv("AIRGPT_RAG_EMBED", "hash")
    import rag.store as store
    from rag import embed, ingest, retrieve

    embed.reset_embedder_cache()
    monkeypatch.setattr(store, "RAG_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "BLOB_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "rag" / "rag.db")
    store.init()
    sid = int(store.create_space("twins")["id"])
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    for f in (a, b):
        f.write_text("The Orion contract renewal fee is 4400 dollars per year.\n", encoding="utf-8")
    ingest.ingest_paths(sid, [a])
    ingest.ingest_paths(sid, [b])
    b.write_text("The Orion contract renewal fee is 9900 dollars per year.\n", encoding="utf-8")
    ingest.ingest_paths(sid, [b])

    text = " ".join(str(h.get("text")) for h in retrieve.search(sid, "Orion contract renewal fee", top_k=5)["hits"])
    assert "9900" in text and "4400" in text
    # and when the last copy changes too, the old content does go
    a.write_text("The Orion contract renewal fee is 1200 dollars per year.\n", encoding="utf-8")
    ingest.ingest_paths(sid, [a])
    text = " ".join(str(h.get("text")) for h in retrieve.search(sid, "Orion contract renewal fee", top_k=5)["hits"])
    assert "1200" in text and "9900" in text and "4400" not in text
    embed.reset_embedder_cache()


def test_xml_tail_tsv_quote_rtf_codepage_and_v3_heading():
    from pathlib import Path as _P

    from rag import ingest

    assert "7421 today" in ingest._xml_text(b"<doc><p>The vault code is <b>bold</b> 7421 today</p></doc>")
    tsv = ingest._csv_text(_P("p.tsv"), 'id\tpart\tqty\n1\t"Bolt M5\t10\n2\tNut\t20\n3\tWasher\t30\n', "\t")
    assert '1 | "Bolt M5 | 10' in tsv and "3 | Washer | 30" in tsv
    rtf = rb"{\rtf1\ansi\ansicpg1251 Name: \'cf\'f0\'e8\'e2\'e5\'f2}"
    assert "Привет" in ingest._rtf_text(rtf)
    nb = '{"worksheets":[{"cells":[{"cell_type":"heading","level":2,"source":["Q3 results"]},' \
         '{"cell_type":"markdown","source":["Revenue 55"]}]}]}'
    assert ingest._ipynb_text(nb).startswith("## Q3 results")

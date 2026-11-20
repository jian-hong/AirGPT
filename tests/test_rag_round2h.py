"""Last RAG round: pack round trip of spreadsheets, follow-up handling, blank groups,
unknown 'by' columns, web goals and the binary check.

Every expected figure is computed here with pandas from the rows written into the files.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

SALES = [
    ("North", "Widget", "Jan", 5000), ("South", "Widget", "Jan", 11596), ("East", "Gadget", "Feb", 900),
    ("West", "Gizmo", "Mar", 1200), ("North", "Gizmo", "Feb", 2436), ("South", "Gizmo", "Mar", 2436),
    ("North", "Gadget", "Mar", 700),
]
STAFF = [("Ann", "HR", 50000), ("Bob", "HR", 40000), ("Cy", "IT", 60000), ("Di", "IT", 55000),
         ("Eve", "Ops", 57696), ("Fay", "", 10000), ("Gus", "", 9000), ("Hal", "", 8000)]


@pytest.fixture()
def space(tmp_path, monkeypatch):
    from rag import store, ingest

    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(store, "RAG_DIR", root / "rag")
    monkeypatch.setattr(store, "DB_PATH", root / "rag" / "rag.db")
    monkeypatch.setattr(store, "BLOB_DIR", root / "rag")
    store.init()
    src = tmp_path / "files"
    src.mkdir()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Region", "Product", "Month", "Amount"])
    for r in SALES:
        ws.append(list(r))
    wb.properties.creator = "SECRET-AUTHOR"
    ws["F1"] = "=SUM(D2:D8)"
    wb.save(src / "sales.xlsx")
    (src / "staff.csv").write_text(
        "Name,Dept,Salary\n" + "\n".join(f"{n},{d},{s}" for n, d, s in STAFF) + "\n", encoding="utf-8")
    (src / "notes.txt").write_text("The warehouse in Penang stores 4500 pallets of rice.\n", encoding="utf-8")
    (src / "leave.txt").write_text("The leave policy for sick days: staff get 12 days of paid sick leave each year.\n", encoding="utf-8")
    sp = store.create_space("T", depth_default="high")
    out = ingest.ingest_paths(int(sp["id"]), [src / "sales.xlsx", src / "staff.csv", src / "notes.txt", src / "leave.txt"], force=True)
    assert out.get("ok"), out
    return int(sp["id"])


def ask(sid, q, history=None, **kw):
    from rag import answer

    done = None
    for ev in answer.answer_events(sid, q, use_llm=False, history=history if history is not None else [], **kw):
        if ev.get("type") == "done":
            done = ev
        if ev.get("type") == "error":
            raise AssertionError(ev)
    assert done is not None
    return done


def turn(history, q, done):
    history += [{"role": "user", "content": q},
                {"role": "assistant", "content": done.get("answer") or "", "provenance": done.get("provenance") or {}}]


# ---- pm-rag.0 ---------------------------------------------------------------------

def test_exported_space_still_calculates_after_import(space):
    from rag import export_import

    df = pd.DataFrame(STAFF, columns=["Name", "Dept", "Salary"])
    want_salary = int(df[df.Dept != "HR"].Salary.sum())
    sdf = pd.DataFrame(SALES, columns=["Region", "Product", "Month", "Amount"])
    want_amount = int(sdf[sdf.Region.isin(["North", "South"])].Amount.sum())
    q1, q2 = "total Salary excluding HR", "total Amount for North and South"
    for q, want in ((q1, want_salary), (q2, want_amount)):
        assert str(want) in ask(space, q)["answer"].replace(",", "")
    pack = export_import.export_space(space, include_chats=False)
    zf = zipfile.ZipFile(io.BytesIO(pack))
    # the pack holds cell values only: no author, no formula text
    blob = b"".join(zf.read(n) for n in zf.namelist())
    assert b"SECRET-AUTHOR" not in blob and b"SUM(D2" not in blob
    out = export_import.import_pack(pack, name="Copy")
    assert out["ok"] and not out.get("spreadsheets_as_text")
    new = int(out["space"]["id"])
    for q, want in ((q1, want_salary), (q2, want_amount)):
        d = ask(new, q)
        assert str(want) in d["answer"].replace(",", ""), d["answer"]
        assert d.get("lane") == "sql" or d["provenance"].get("sql")
    d = ask(new, q2)
    assert d["provenance"]["workbook"] == "sales.xlsx" and d["provenance"]["sheet"] == "Sales"
    assert any(c.get("title") == "sales.xlsx" for c in d["citations"])
    d = ask(new, q1)
    assert d["provenance"]["workbook"] == "staff.csv" and d["provenance"]["sheet"] == "staff"


def test_import_says_when_a_spreadsheet_could_only_come_back_as_text(space):
    from rag import export_import, store

    for s in store.list_sources(space):
        if s["title"] == "staff.csv":
            p = Path(s["meta"].get("docs_path") or "")
            if p.is_file():
                p.unlink()
            Path(s["path"]).unlink()
    out = export_import.import_pack(export_import.export_space(space, include_chats=False))
    assert out["ok"] and out["spreadsheets_as_text"] == ["staff.csv"]
    assert "cannot be calculated" in out["notice"]


# ---- pm-rag.1: a question is merged with the last one only when it reads as a follow-up --

def test_standalone_query_merges_only_real_followups():
    from rag import answer

    hist = [{"role": "user", "content": "Who manages the warehouse Wang Fang?"}]
    assert answer.standalone_query("how many pallets in Penang", hist) == "how many pallets in Penang"
    assert answer.standalone_query("total Amount by Region", hist) == "total Amount by Region"
    assert "Wang Fang" in answer.standalone_query("and for South?", hist)
    assert "Wang Fang" in answer.standalone_query("what about it", hist)
    assert "Wang Fang" in answer.standalone_query("why?", hist)


def test_second_question_in_a_chat_answers_like_a_fresh_chat(space):
    fresh = ask(space, "how many pallets in Penang")
    assert "4500 pallets" in fresh["answer"] and not fresh["abstained"]
    hist: list = []
    first = ask(space, "Who manages the warehouse Wang Fang?", hist)
    turn(hist, "Who manages the warehouse Wang Fang?", first)
    second = ask(space, "how many pallets in Penang", hist)
    assert second["answer"] == fresh["answer"] and not second["abstained"]
    # and the other way round: the gap note names only words of the question just asked
    hist = []
    turn(hist, "how many pallets in Penang", fresh)
    third = ask(space, "Who manages the warehouse Wang Fang?", hist)
    alone = ask(space, "Who manages the warehouse Wang Fang?")
    assert third["answer"] == alone["answer"]
    assert "many" not in third["answer"].split("Closest")[0]


def test_whole_question_after_a_calculation_is_not_taken_for_a_follow_up(space):
    """"how many ..." is an aggregate word, not a follow-up: after a calculation it must answer
    as it does in a fresh chat, at any position in the chat."""
    fresh = ask(space, "how many pallets in Penang")
    hist: list = []
    for q in ("total Amount in North", "total Salary excluding HR", "total Amount by Region"):
        turn(hist, q, ask(space, q, hist))
        got = ask(space, "how many pallets in Penang", hist)
        assert got["answer"] == fresh["answer"], (q, got["answer"][:200])
        assert not got["answer"].startswith("Following on")
    # real follow-ups still carry
    hist = []
    turn(hist, "total Amount in North", ask(space, "total Amount in North", hist))
    for q, want in (("and for South?", "South"), ("and the average?", "average"), ("the average?", "average"),
                    ("how many rows there?", "how many"), ("what about East?", "East")):
        d = ask(space, q, hist)
        assert d["answer"].startswith("Following on") and want in d["answer"], (q, d["answer"][:200])


@pytest.mark.parametrize("q", ["total Amount in North by end of March", "total Amount in North by Friday",
                               "total Amount in North by December", "total Amount in North by Q2"])
def test_by_a_time_is_not_a_missing_column(space, q):
    d = ask(space, q)
    assert "no " not in d["answer"].split("\n")[0].lower() or "column" not in d["answer"].split("\n")[0]
    assert "could not group by it" not in d["answer"]


# ---- pm-rag.2: a follow-up that cannot be applied says so ------------------------------

def test_short_followup_after_a_passage_answer_is_not_silently_repeated(space):
    hist: list = []
    q1 = "what is the leave policy for sick days?"
    d1 = ask(space, q1, hist)
    assert "12 days" in d1["answer"]
    turn(hist, q1, d1)
    d2 = ask(space, "and the average?", hist)
    assert "could not apply" in d2["answer"] and d2["provenance"].get("followup_not_applied")
    assert d2["answer"].count("12 days") == d1["answer"].count("12 days")
    # a follow-up that does change the answer is not flagged
    d3 = ask(space, "and the warehouse in Penang?", hist)
    assert "could not apply" not in d3["answer"] and "4500" in d3["answer"]


# ---- pm-rag.3: a ranking carries like a total ------------------------------------------

def test_followup_after_a_ranking_is_calculated(space):
    sdf = pd.DataFrame(SALES, columns=["Region", "Product", "Month", "Amount"])
    hist: list = []
    q1 = "which Product has the highest total Amount in North"
    d1 = ask(space, q1, hist)
    north = sdf[sdf.Region == "North"].groupby("Product").Amount.sum()
    assert north.idxmax() in d1["answer"] and str(int(north.max())) in d1["answer"].replace(",", "")
    turn(hist, q1, d1)
    d2 = ask(space, "and for South?", hist)
    south = sdf[sdf.Region == "South"].groupby("Product").Amount.sum()
    assert d2.get("lane") == "sql" and not d2["provenance"].get("followup_not_calculated"), d2["answer"]
    assert south.idxmax() in d2["answer"] and str(int(south.max())) in d2["answer"].replace(",", "")
    # and a lowest-ranking carries its direction
    q3 = "which Product has the lowest total Amount in North"
    d3 = ask(space, q3, [])
    h3: list = []
    turn(h3, q3, d3)
    d4 = ask(space, "and for South?", h3)
    assert f"{south.idxmin()} has the lowest" in d4["answer"] and str(int(south.min())) in d4["answer"].replace(",", "")


# ---- pm-rag.4: a blank group key has a name --------------------------------------------

def test_blank_group_is_labelled(space):
    df = pd.DataFrame(STAFF, columns=["Name", "Dept", "Salary"])
    blank = int(df[df.Dept == ""].Salary.sum())
    d = ask(space, "total Salary by Dept")
    assert f"(blank): {blank}" in d["answer"].replace(",", "")
    assert ": :" not in d["answer"] and "; :" not in d["answer"]
    assert {"group": "(blank)", "value": blank} in d["provenance"]["groups"]
    d = ask(space, "average Salary by Dept")
    assert "(blank): " in d["answer"]


# ---- g-rag.5: 'by X' where X is no column ----------------------------------------------

def test_group_by_a_column_that_does_not_exist_is_said(space):
    sdf = pd.DataFrame(SALES, columns=["Region", "Product", "Month", "Amount"])
    north = int(sdf[sdf.Region == "North"].Amount.sum())
    d = ask(space, "total Amount by Colour in North")
    assert "no Colour column" in d["answer"]
    assert "could not group" in d["answer"].lower()
    assert str(north) in d["answer"].replace(",", "")  # the plain total is still given, labelled
    # a real column and a real value after 'by' are unaffected
    assert "no column" not in ask(space, "total Amount by Product in North")["answer"]
    assert "no column" not in ask(space, "total Amount by Region")["answer"]
    # 'by' with a cell value or arithmetic is ordinary text, not a missing column
    assert "no Fay column" not in ask(space, "total Salary entered by Fay")["answer"]
    assert "column" not in ask(space, "total Amount multiplied by two")["answer"].split("\n")[0]


# ---- pm-rag.6: web goals keep only the user's topic ------------------------------------

@pytest.mark.parametrize("ask_text,want", [
    ("search the internet for cognition", ["cognition"]),
    ("look up on the web: world models and cognition in LeCun JEPA", ["world models and cognition in LeCun JEPA"]),
    ("find online information about the Penang launch and JEPA", ["the Penang launch and JEPA"]),
    ("Please google JEPA vs transformers and also cognition in infants",
     ["JEPA vs transformers", "cognition in infants"]),
])
def test_web_goals_are_the_users_topic(ask_text, want):
    from rag import answer

    assert answer.split_web_goals(ask_text) == want


# ---- pm-security.2 + sr.7: the binary check decodes ------------------------------------

import os as _os
import random as _random

_RNG = _random.Random(7)
_JUNK = bytes(_RNG.randrange(256) for _ in range(6000))
_HIGH = bytes(_RNG.randrange(128, 256) for _ in range(6000))
_SENTENCE = "Quarterly review: revenue grew and the Penang warehouse shipped 4500 pallets. "
_LONG = (_SENTENCE * 200)


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return p


@pytest.mark.parametrize("name,data", [
    ("plain_random.txt", _JUNK),
    ("bom_random.txt", b"\xff\xfe" + _JUNK),
    ("bom_be_random.txt", b"\xfe\xff" + _JUNK),
    ("high_only.txt", _HIGH),
    ("late_nul.txt", b"A" * 9000 + _JUNK),
    ("late_nul_big.txt", b"A" * (6 * 1024 * 1024) + b"\x00" * 100 + b"tail" * 1000),
    ("nul_padding.txt", b"A" * 8192 + b"\x00" * 100),
    ("elf.txt", b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 200 + _JUNK),
    ("png.json", b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + _JUNK),
    ("utf8_bom_random.txt", b"\xef\xbb\xbf" + _JUNK),
])
def test_junk_is_refused_as_binary(tmp_path, name, data):
    from rag import ingest

    assert ingest.looks_binary(_write(tmp_path, name, data)) is True


@pytest.mark.parametrize("name,data", [
    ("utf8.txt", _LONG.encode("utf-8")),
    ("utf8_bom.txt", b"\xef\xbb\xbf" + _LONG.encode("utf-8")),
    ("utf16_bom.txt", _LONG.encode("utf-16")),
    ("utf16_le_nobom.txt", _LONG.encode("utf-16-le")),
    ("utf16_be_nobom.txt", _LONG.encode("utf-16-be")),
    ("utf16_cjk_bom.txt", ("今季の売上は伸びた。倉庫は四千五百パレットを出荷した。" * 80).encode("utf-16")),
    ("cp1252.txt", ("Café menu: crème brûlée, piña colada. " * 100).encode("cp1252")),
    ("chinese_utf8.md", ("本季度收入增长，槟城仓库出货四千五百托盘。\n" * 100).encode("utf-8")),
    ("ansi_log.log", (b"\x1b[32mOK\x1b[0m job finished\n" * 300)),
    ("big_text.txt", _LONG.encode("utf-8") * 400),
    ("big_cjk_utf8.txt", ("本季度收入增长，槟城仓库出货四千五百托盘。\n" * 120000).encode("utf-8")),
    ("big_cjk_utf16.txt", ("今季の売上は伸びた。倉庫は四千五百パレットを出荷した。" * 60000).encode("utf-16")),
    ("big_utf16_nobom.txt", (_SENTENCE * 40000).encode("utf-16-le")),
    ("cp1252_curly.txt", ("\u201cQuoted\u201d \u2013 the manager\u2019s note, caf\u00e9 \u20ac5\n" * 100).encode("cp1252")),
    ("tiny.txt", b"hi"),
    ("empty.txt", b""),
])
def test_real_text_is_accepted(tmp_path, name, data):
    from rag import ingest

    assert ingest.looks_binary(_write(tmp_path, name, data)) is False


def test_real_utf16_without_bom_is_indexed_and_junk_is_refused_in_a_space(tmp_path, monkeypatch):
    from rag import ingest, store

    root = tmp_path / "d"
    root.mkdir()
    monkeypatch.setattr(store, "RAG_DIR", root / "rag")
    monkeypatch.setattr(store, "DB_PATH", root / "rag" / "rag.db")
    monkeypatch.setattr(store, "BLOB_DIR", root / "rag")
    store.init()
    sid = int(store.create_space("B", depth_default="high")["id"])
    good = _write(tmp_path, "wide.txt", "The Penang warehouse stores 4500 pallets of rice.".encode("utf-16-le"))
    bad = _write(tmp_path, "bom_junk.txt", b"\xff\xfe" + _JUNK)
    out = ingest.ingest_paths(sid, [good, bad], force=True)
    skipped = {s["path"]: s["reason"] for s in out.get("skipped", [])}
    assert skipped == {"bom_junk.txt": "Looks like a binary file, not text"}, out
    assert out["chunks"] >= 1


# ---- pm-rag.5: what a reopened chat needs is saved with the answer -----------------------

def test_saved_answer_keeps_the_calculation_and_the_steps(space):
    from rag import answer, store

    cid = int(store.create_chat(space, "t")["id"])
    out = answer.answer(space, "total Salary excluding HR", chat_id=cid, use_llm=False)
    assert out["ok"]
    saved = [m for m in store.list_messages(cid) if m["role"] == "assistant"][-1]["provenance"]
    assert saved["sql"].startswith("SELECT SUM(Salary)") and saved["workbook"] == "staff.csv"
    steps = saved["reasoning"]["steps"]
    assert steps and all(s["title"] and s["detail"] for s in steps) and saved["reasoning"]["lane"]
    # a passage answer keeps its steps too
    answer.answer(space, "how many pallets in Penang", chat_id=cid, use_llm=False)
    last = [m for m in store.list_messages(cid) if m["role"] == "assistant"][-1]["provenance"]
    assert last["reasoning"]["steps"]


def test_two_sheet_workbook_round_trips_with_each_sheet_named(tmp_path, monkeypatch):
    from rag import export_import, ingest, store

    root = tmp_path / "d"
    root.mkdir()
    monkeypatch.setattr(store, "RAG_DIR", root / "rag")
    monkeypatch.setattr(store, "DB_PATH", root / "rag" / "rag.db")
    monkeypatch.setattr(store, "BLOB_DIR", root / "rag")
    store.init()
    wb = openpyxl.Workbook()
    a = wb.active
    a.title = "Q1"
    b = wb.create_sheet("Q2")
    q1, q2 = [("North", 1000), ("South", 250)], [("North", 1300), ("East", 3500)]
    for ws, rows in ((a, q1), (b, q2)):
        ws.append(["Region", "Revenue"])
        for r in rows:
            ws.append(list(r))
    f = tmp_path / "quarters.xlsx"
    wb.save(f)
    sid = int(store.create_space("Q", depth_default="high")["id"])
    assert ingest.ingest_paths(sid, [f], force=True)["ok"]
    new = int(export_import.import_pack(export_import.export_space(sid, include_chats=False))["space"]["id"])
    want = pd.DataFrame(q1 + q2, columns=["Region", "Revenue"]).query("Region == 'North'").Revenue.sum()
    d = ask(new, "total Revenue for North")
    assert str(int(want)) in d["answer"].replace(",", "")
    assert {s["sheet"] for s in d["provenance"]["sheets"]} == {"Q1", "Q2"}
    assert d["provenance"]["workbook"] == "quarters.xlsx"

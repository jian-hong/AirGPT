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
    sp = store.create_space("T", depth_default="high")
    out = ingest.ingest_paths(int(sp["id"]), [src / "sales.xlsx", src / "staff.csv", src / "notes.txt"], force=True)
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


# ---- pm-rag.2: a follow-up that cannot be applied says so ------------------------------

def test_short_followup_after_a_passage_answer_is_not_silently_repeated(space):
    hist: list = []
    q1 = "how many pallets in Penang"
    d1 = ask(space, q1, hist)
    turn(hist, q1, d1)
    d2 = ask(space, "and the average?", hist)
    assert "could not" in d2["answer"].lower() and d2["provenance"].get("followup_not_applied")
    # a follow-up that does change the answer is not flagged
    assert not ask(space, "and the warehouse in Penang?", hist)["answer"].lower().startswith("i could not")


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
    assert "lowest" in d4["answer"] and south.idxmin() in d4["answer"].split("\n")[0]


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

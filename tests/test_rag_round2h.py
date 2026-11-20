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

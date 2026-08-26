"""#23 / #24 F15 AirGPT half: identify workbook + Copilot pack + honest handoff.

Does not drive Pointer or Excel Copilot. Pack is a DMS cross-check candidate.
Handoff without a posted result path stays awaiting_dms_receipt (R-0011).
"""
from __future__ import annotations

from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from rag import xlsx_orch  # noqa: E402

F15_ASK = (
    "OnTime=true average cost, export a separate xlsx, and a chart for PPT "
    "on frtr_00027 supply-chain regional"
)


def _xlsx(path: Path, title: str, header: list, rows: list[list]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    ws.append(header)
    for row in rows:
        ws.append(row)
    wb.save(str(path))
    wb.close()
    return path


def _frtr(path: Path, *, name: str = "frtr_00027_supply-chain-regional.xlsx") -> Path:
    return _xlsx(
        path / name,
        "Carriers",
        ["Carrier", "Region", "OnTime", "Cost", "BaseRate"],
        [
            ["Acme", "APAC", True, 310.0, 1.2],
            ["Beta", "EMEA", False, 200.0, 0.9],
            ["Gamma", "APAC", True, 290.0, 1.1],
        ],
    )


def _payroll(path: Path) -> Path:
    return _xlsx(
        path / "messy_payroll_ops.xlsx",
        "Payroll_RAW",
        ["Emp ID", "Name", "Base Salary", "Notes"],
        [["E-0012", "Ada Ng", 50000.0, ""]],
    )


def _result_wb(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    wb.active.title = "Cover"
    wb.create_sheet("OnTime Export")
    wb.create_sheet("Analysis")
    wb.create_sheet("Presentation Chart")
    dest = path / "copilot_result.xlsx"
    wb.save(str(dest))
    wb.close()
    return dest


@pytest.fixture()
def orch_dir(tmp_path, monkeypatch):
    d = tmp_path / "orch"
    monkeypatch.setattr(xlsx_orch, "PACK_DIR", d)
    return d


def test_identifies_ontime_workbook_not_payroll(tmp_path, orch_dir):
    frtr = _frtr(tmp_path)
    pay = _payroll(tmp_path)
    sources = [
        {"path": str(pay), "title": pay.name, "meta": {}},
        {"path": str(frtr), "title": frtr.name, "meta": {}},
    ]
    out = xlsx_orch.identify_and_pack(ask=F15_ASK, sources=sources)
    assert out["ok"] and out["status"] == "identified", out
    assert "00027" in out["workbook"]["title"]
    assert "payroll" not in out["workbook"]["title"].lower()
    pack = out["pack"]
    assert pack["airgpt_role"] == "candidate_pack_only"
    assert pack["paste_owner"] == "pointer"
    assert pack["cross_check_owner"] == "dms"
    sheets = [s["sheet"] for s in pack["steps"]]
    assert sheets == ["Cover", "OnTime Export", "Analysis", "Presentation Chart"]
    blob = " ".join(s["intent"] + " " + s["formula_hint"] for s in pack["steps"]).upper()
    assert "ONTIME" in blob and "AVERAGEIF" in blob and "FILTER" in blob
    assert "CHART" in blob
    assert pack["workbook"]["ontime_col"] == "OnTime"
    assert pack["workbook"]["cost_col"] == "Cost"
    assert "pointer_paste" in pack["not_doing"]
    assert out["handoff"]["status"] == "awaiting_dms_receipt"
    assert "No DMS receipt wire" in out["handoff"]["honesty"]


def test_no_match_does_not_guess_the_only_xlsx(tmp_path, orch_dir):
    pay = _payroll(tmp_path)
    out = xlsx_orch.identify_and_pack(
        ask=F15_ASK,
        sources=[{"path": str(pay), "title": pay.name, "meta": {}}],
    )
    assert out["status"] == "no_match", out
    assert out.get("pack") is None
    assert "not proposing" in out["prompt"].lower() or "no ingested" in out["prompt"].lower()


def test_ambiguous_two_ontime_books_are_not_silently_picked(tmp_path, orch_dir):
    header = ["Carrier", "Region", "OnTime", "Cost"]
    rows = [["Zed", "NA", True, 1.0]]
    a = _xlsx(tmp_path / "frtr_aa_carriers.xlsx", "Carriers", header, rows)
    b = _xlsx(tmp_path / "frtr_bb_carriers.xlsx", "Carriers", header, rows)
    out = xlsx_orch.identify_workbook(
        ask="OnTime=true average cost and a chart",
        sources=[
            {"path": str(a), "title": a.name, "meta": {}},
            {"path": str(b), "title": b.name, "meta": {}},
        ],
    )
    assert out["status"] == "ambiguous", out
    assert len(out["candidates"]) >= 2
    assert "silently" in out["prompt"].lower() or "too close" in out["prompt"].lower()


def test_handoff_without_path_stays_awaiting(tmp_path, orch_dir):
    frtr = _frtr(tmp_path)
    identified = xlsx_orch.identify_and_pack(
        ask=F15_ASK,
        sources=[{"path": str(frtr), "title": frtr.name, "meta": {}}],
    )
    pack_id = identified["pack_id"]
    hand = xlsx_orch.consume_result(pack_id=pack_id)
    assert hand["status"] == "awaiting_dms_receipt"
    assert hand.get("result_path") in (None, "")
    miss = xlsx_orch.reveal_handoff(pack_id=pack_id, which="result")
    assert miss["ok"] is False
    assert "awaiting_dms_receipt" in (miss.get("error") or "") or miss.get("status") == "awaiting_dms_receipt"


def test_posted_result_workbook_inspects_sheet_families(tmp_path, orch_dir, monkeypatch):
    frtr = _frtr(tmp_path)
    identified = xlsx_orch.identify_and_pack(
        ask=F15_ASK,
        sources=[{"path": str(frtr), "title": frtr.name, "meta": {}}],
    )
    result = _result_wb(tmp_path)
    hand = xlsx_orch.consume_result(pack_id=identified["pack_id"], result_path=str(result))
    assert hand["status"] == "received", hand
    fam = hand["result_sheets"]["families"]
    assert fam["cover"] == "Cover"
    assert fam["ontime_export"] == "OnTime Export"
    assert fam["analysis"] == "Analysis"
    assert fam["chart"] == "Presentation Chart"

    seen = {}

    def _fake_reveal(path: str):
        seen["path"] = path
        return {"ok": True, "path": path, "action": "test_stub"}

    monkeypatch.setattr("rag.reveal.reveal_path", _fake_reveal)
    out = xlsx_orch.reveal_handoff(pack_id=identified["pack_id"], which="result")
    assert out["ok"] is True
    assert Path(seen["path"]).name == "copilot_result.xlsx"

    src = xlsx_orch.reveal_handoff(pack_id=identified["pack_id"], which="source")
    assert src["ok"] is True
    assert "00027" in Path(seen["path"]).name


def test_incomplete_result_workbook_is_flagged_not_green(tmp_path, orch_dir):
    thin = _xlsx(tmp_path / "only_cover.xlsx", "Cover", ["Note"], [["hi"]])
    hand = xlsx_orch.consume_result(result_path=str(thin))
    assert hand["status"] == "received_incomplete_sheets"
    assert "ontime_export" in hand["result_sheets"]["missing"]
    assert hand.get("warning")


def test_index_html_calls_xlsx_orch_routes():
    html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
    for needle in (
        "/api/rag/xlsx-orch/identify",
        "/api/rag/xlsx-orch/handoff",
        "/api/rag/xlsx-orch/reveal",
        "ragOrchIdentify",
        "awaiting DMS receipt",
    ):
        assert needle in html, needle
    assert "Pointer paste" in html
    assert "does not run Copilot" in html

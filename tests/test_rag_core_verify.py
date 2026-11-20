"""Round-2 verifier checks for the rag-core lane (page still works with the new /sources rule,
web intent does not fire on ordinary business words, ops amend finds a tidy-able key)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_page_never_asks_the_sources_route_to_clear():
    """The server now answers 400 to force:true on /sources. The create-space wizard used to send
    force:!ingested when it had chats or a host path but no uploaded files, so the space was made
    empty and the failure was swallowed."""
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    for m in re.finditer(r"'/sources'\s*,\s*\{method:'POST',body:JSON\.stringify\(([^)]*)\)", html):
        assert "force:true" not in m.group(1)
    assert "const body={force:!ingested" not in html


@pytest.mark.parametrize("q", [
    "find online orders for East in Q2",
    "how many online orders did we get",
    "search the web server config in my notes",
    "find the web page template in my files",
    "what does the news about the launch say in our minutes",
    "find the online store refund rule",
])
def test_business_words_do_not_send_the_question_to_the_web(q):
    from rag.answer import wants_web

    assert not wants_web(q), q


@pytest.mark.parametrize("q", [
    "search the web for llama news",
    "search online for the latest laptop prices",
    "find the capital of France online",
    "look it up on the internet",
    "google it online please",
    "latest news on AI",
    "/search penang weather",
    "web search penang weather",
    "find that on the web.",
])
def test_explicit_web_asks_still_work(q):
    from rag.answer import wants_web

    assert wants_web(q), q


def test_ops_amend_finds_key_with_stray_spaces_and_lowercase(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from rag import ops_amend as O

    p = tmp_path / "pay.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Payroll_RAW"
    ws.append(["Emp ID", "Name", "Base Salary", "Notes"])
    ws.append([" e-0001 ", "Alice", 1000, None])
    ws.append(["E-0002", "Bob", 2000, None])
    wb.save(p)
    r = O.identify_employee(p, "salary raise for E-0001")
    assert r.get("pending"), r
    t = r["pending"]["token"]
    O.confirm_identity(t, True)
    O.propose_amend(t, new_salary=1500)
    assert O.confirm_amend(t, True).get("status") == "written"
    ws2 = openpyxl.load_workbook(p)["Payroll_RAW"]
    assert ws2["C2"].value == 1500 and ws2["C3"].value == 2000

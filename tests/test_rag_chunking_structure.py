"""Chunking structure: header on every row window, sentence cuts, per-script size.

Each test names the defect it pins and fails on the chunker of commit 37c6bfc.
Fixtures are strings or hand-built xlsx; nothing depends on a line-ending write.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag import chunking, index_fingerprint  # noqa: E402
from rag.chunking import parent_child_chunk  # noqa: E402

HEADER = "Account | Region | Balance"


def _sheet(n: int, header: str = HEADER) -> str:
    rows = "\n".join(f"acct{i} | R{i % 5} | {1000 + i}.50" for i in range(n))
    return f"## Sheet: Balances\n{header}\n{rows}"


def test_every_row_window_carries_the_header():
    _, children, _ = parent_child_chunk(_sheet(400), table=True)
    assert len(children) > 5
    assert all(HEADER in c.text.splitlines() for c in children)
    # rows stay whole: every line is the header, the heading, or a complete row
    for c in children:
        for ln in c.text.splitlines():
            assert ln in (HEADER,) or ln.startswith("##") or re.fullmatch(r"acct\d+ \| R\d \| \d+\.50", ln), ln


def test_header_is_repeated_once_not_twice_on_the_first_window():
    _, children, _ = parent_child_chunk(_sheet(400), table=True)
    assert children[0].text.splitlines().count(HEADER) == 1


def test_parent_windows_of_a_big_sheet_carry_the_header_too():
    parents, _, _ = parent_child_chunk(_sheet(2000), table=True, parent_max_tokens=300)
    assert len(parents) > 3
    assert all(HEADER in p.text.splitlines() for p in parents)


def test_a_first_row_of_numbers_is_not_taken_for_a_header():
    body = "## Sheet: Dump\n" + "\n".join(f"{i} | {i * 2} | 3.5" for i in range(300))
    _, children, _ = parent_child_chunk(body, table=True)
    assert chunking._table_header("Sheet: Dump", body) == ""
    assert not any(c.text.splitlines()[0] == "0 | 0 | 3.5" for c in children[1:])


def test_a_banner_row_or_repeated_labels_are_not_a_header():
    banner = "## Sheet: S\nQuarterly report\na | b | c\n1 | 2 | 3"
    assert chunking._table_header("Sheet: S", banner) == ""
    dup = "## Sheet: S\nname | name | x\na | b | c"
    assert chunking._table_header("Sheet: S", dup) == ""


def test_index_section_and_prose_get_no_header():
    assert chunking._table_header("Spreadsheet index", "## Spreadsheet index\n- A (3 rows)\n- B (4 rows)") == ""
    _, children, _ = parent_child_chunk("## Notes\nfirst line | of | words\nsecond | line | here", table=False)
    assert all("first line" in c.text or "second" in c.text for c in children)


def test_xlsx_keeps_empty_cells_in_their_column(tmp_path):
    import openpyxl

    from rag import ingest

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "T"
    ws.append(["name", "city", "age", "note"])
    ws.append(["Ann", None, 30, None])      # blank city, trailing blank note
    ws.append([None, None, None, None])     # all blank: no row
    ws.append(["Bo", "Oslo", None, "a\nb"])  # line break inside a cell
    p = tmp_path / "t.xlsx"
    wb.save(p)
    lines = ingest._xlsx_text(p).splitlines()
    assert "Ann |  | 30" in lines
    assert "Bo | Oslo |  | a b" in lines
    assert "name | city | age | note" in lines
    assert sum(1 for ln in lines if ln.startswith("Ann")) == 1
    assert "" not in [ln for ln in lines[lines.index("## Sheet: T") + 1:]]


def _page(sentences: list[str], width: int = 95) -> str:
    """Running prose hard-wrapped like a PDF page: one paragraph, single newlines."""
    words, lines, cur = " ".join(sentences).split(" "), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return "\n".join(lines + [cur])


def test_long_pdf_page_is_cut_at_sentence_ends_and_a_long_fact_survives():
    filler = [f"Warehouse {i} finished its routine stock count in month {i % 12 + 1} under unit {i * 7}." for i in range(60)]
    fact = ("The Halvorsen account is held by the Ostrava branch and was opened after a full review "
            "of the signed mandate. Its retention period is ZQ-4471, confirmed by the audit team in writing.")
    sents = filler[:30] + [fact] + filler[30:]
    text = "## Page 1\n" + _page(sents)
    _, children, _ = parent_child_chunk(text)
    assert len(children) > 3
    flat = lambda t: re.sub(r"\s+", " ", t)
    for c in children:
        assert flat(c.text).endswith("."), c.text[-40:]
    assert any(flat(fact) in flat(c.text) for c in children), "fact split across chunks"


def test_cjk_and_arabic_sentence_marks_end_a_chunk():
    zh = "".join(f"第{i}号仓库在{i % 12 + 1}月完成了例行盘点，负责人编号{i * 13}。" for i in range(120))
    ar = " ".join(f"تم الانتهاء من جرد المستودع رقم {i} في الشهر {i % 12 + 1}؟" for i in range(120))
    for text, end in ((zh, "。"), (ar, "؟")):
        _, children, _ = parent_child_chunk(text)
        assert len(children) > 3
        assert all(c.text.rstrip().endswith(end) for c in children), [c.text[-6:] for c in children]


def test_dense_script_chunks_respect_the_token_budget():
    zh = "".join(f"第{i}号仓库在{i % 12 + 1}月完成了例行盘点，负责人编号{i * 13}。" for i in range(200))
    _, children, _ = parent_child_chunk(zh, child_tokens=200)
    # old: 800 characters (about 800 tokens of Chinese) per chunk
    assert max(chunking.estimate_tokens(c.text) for c in children) <= 205
    assert max(len(c.text) for c in children) < 300


def test_one_sentence_over_budget_is_cut_at_a_space_not_mid_word():
    words = [f"word{i:04d}" for i in range(900)]
    text = " ".join(words) + "."
    _, children, _ = parent_child_chunk(text, child_tokens=100)
    assert len(children) > 3
    for c in children:
        assert all(re.fullmatch(r"word\d{4}\.?", w) for w in c.text.split()), c.text[:60]


def test_decimals_and_abbreviations_are_not_sentence_ends():
    body = "The rate was 4410.5 per unit, e.g. in Tallinn, approx. half overall. Next sentence starts here."
    units = chunking._sentence_units(body)
    assert [body[a:b].strip() for a, b in units] == [
        "The rate was 4410.5 per unit, e.g. in Tallinn, approx. half overall.",
        "Next sentence starts here.",
    ]


def test_code_keeps_every_line_as_a_unit():
    code = "def f(x):\n    total = x + 1\n    return total\n\ndef g(y):\n    value = y * 2\n    return value\n"
    _, children, _ = parent_child_chunk(code, code=True)
    assert "def g(y):" in "".join(c.text for c in children)
    units = chunking._sentence_units("a = 1\nb = 2\nc = 3\n", lines_are_units=True)
    assert len(units) == 3


def test_index_identity_changes_so_old_scores_are_not_comparable():
    new = index_fingerprint.fingerprint()
    old = dict(new, schema_version=1, chunker=dict(new["chunker"], name="parent_child"), id="old")
    ok, reasons = index_fingerprint.comparable(new, old)
    assert not ok
    assert any("schema" in r for r in reasons) and any("chunker.name" in r for r in reasons)


def test_wide_rows_year_headers_and_near_identical_rows():
    """Adversary findings on the header-carrying chunker, plus one it exposed:
    - a row wider than the budget produced chunks holding only the header;
    - "Item | 2024 | 2025" was read as data, so later windows had no column names;
    - rows that differ only in an id were demoted as near-duplicates and left search."""
    from rag.chunking import parent_child_chunk

    body = "## Sheet: S\nid | text\n" + "\n".join(f"{i} | " + "word " * 400 for i in range(5))
    kids = parent_child_chunk(body, table=True)[1]
    data = [[ln for ln in k.text.split("\n") if ln.strip() and not ln.startswith("#") and ln.strip() != "id | text"]
            for k in kids]
    assert all(data), "a chunk holds nothing but the header"
    assert all(any(f"\n{i} | word" in "\n" + k.text for k in kids) for i in range(5)), "a row left the index"
    assert len({k.text for k in kids}) == len(kids)

    rows = [["Item", "2024", "2025"]] + [[f"a{i}", str(i), str(i + 1)] for i in range(400)]
    kids = parent_child_chunk("## Sheet: S\n" + "\n".join(" | ".join(r) for r in rows), table=True)[1]
    assert all("Item | 2024 | 2025" in k.text for k in kids)

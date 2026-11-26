"""Defects five independent adversaries reproduced against the 2026-11-12 RAG work.

Each test is the user-visible failure, stated as what the user must get. Fixtures
are hand-built (zip + XML, raw PDF) so no test depends on an optional library.
"""
from __future__ import annotations

import sys
import zipfile
from email.message import EmailMessage
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "RAG"))
sys.path.insert(0, str(ROOT))

import filetype_bench as fb  # noqa: E402
from rag import ingest, ontology  # noqa: E402

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
PR = ('xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
RELS = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'


def _zip(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
    return path


# --- pdf -------------------------------------------------------------------

def test_pdf_page_text_cannot_replace_the_page_heading(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(fb.pdf_bytes([["# Intro", "alpha fact"], ["## Page 9", "beta fact"]]))
    text = ingest._pdf_text(p)
    assert "## Page 1\n\\# Intro" in text and "## Page 2\n\\## Page 9" in text


def test_pdf_past_page_200_is_indexed(tmp_path):
    p = tmp_path / "long.pdf"
    p.write_bytes(fb.pdf_bytes([[f"line on sheet {i}"] for i in range(1, 231)]))
    assert "## Page 230\nline on sheet 230" in ingest._pdf_text(p)


def test_pdf_failures_say_what_failed(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 truncated")
    assert ingest._pdf_text(bad) == ""
    assert "corrupt" in ingest._pdf_text.last_error
    empty = tmp_path / "blank.pdf"
    empty.write_bytes(fb.pdf_bytes([[""]]))
    assert ingest._pdf_text(empty) == "" and ingest._pdf_text.last_error == ""


# --- pptx ------------------------------------------------------------------

def _deck(path: Path) -> Path:
    def slide(text, extra=""):
        return f'<p:sld {PR} {A}{extra}><p:sp><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:sp></p:sld>'

    return _zip(path, {
        # shown order: slide2.xml first, then slide1.xml
        "ppt/presentation.xml": f'<p:presentation {PR}><p:sldIdLst><p:sldId id="257" r:id="rId2"/>'
                                '<p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": f'<Relationships {RELS}><Relationship Id="rId1" Target="slides/slide1.xml"/>'
                                           '<Relationship Id="rId2" Target="slides/slide2.xml"/></Relationships>',
        "ppt/slides/slide1.xml": slide("made first", ' show="0"'),
        "ppt/slides/slide2.xml": slide("made second"),
        "ppt/slides/_rels/slide2.xml.rels": f'<Relationships {RELS}><Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" '
            'Target="../notesSlides/notesSlide1.xml"/></Relationships>',
        "ppt/notesSlides/notesSlide1.xml": f'<p:notes {PR} {A}>'
            '<p:sp><p:nvSpPr><p:nvPr><p:ph type="sldNum"/></p:nvPr></p:nvSpPr><a:p><a:r><a:t>7</a:t></a:r></a:p></p:sp>'
            '<p:sp><a:p><a:r><a:t>2025</a:t></a:r></a:p></p:sp></p:notes>',
    })


def test_pptx_slide_number_is_the_shown_order_and_notes_keep_numbers(tmp_path):
    text = ingest._pptx_text(_deck(tmp_path / "d.pptx"))
    assert text.index("## Slide 1\nmade second") < text.index("## Slide 2 (hidden)\nmade first")
    assert "Speaker notes: 2025" in text and "Speaker notes: 7" not in text


# --- docx ------------------------------------------------------------------

def test_docx_tabs_textbox_custom_heading_and_footer(tmp_path):
    def p(text, style=""):
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"

    box = "<w:p><w:r><w:t>BOX</w:t></w:r></w:p>"
    body = (
        p("Kapitel Eins", "Kapitel")
        + "<w:p><w:r><w:t>Col1</w:t><w:tab/><w:t>Col2</w:t><w:br/><w:t>next</w:t></w:r></w:p>"
        + f'<w:p><w:r><mc:AlternateContent xmlns:mc="x"><mc:Choice>{box}</mc:Choice>'
          f"<mc:Fallback>{box}</mc:Fallback></mc:AlternateContent></w:r></w:p>"
    )
    doc = _zip(tmp_path / "a.docx", {
        "word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>",
        "word/styles.xml": f'<w:styles {W}><w:style w:styleId="Heading2"><w:name w:val="heading 2"/></w:style>'
                           '<w:style w:styleId="Kapitel"><w:name w:val="Kapitel"/><w:basedOn w:val="Heading2"/></w:style></w:styles>',
        "word/footer1.xml": f"<w:ftr {W}>{p('Contract ref FT-77')}</w:ftr>",
    })
    text = ingest._docx_text(doc)
    assert "## Kapitel Eins" in text
    assert "Col1 Col2 next" in text
    assert text.count("BOX") == 1
    assert "Contract ref FT-77" in text


# --- html / csv / decode / eml ---------------------------------------------

def test_html_skipped_heading_leaves_no_bare_hash_and_cells_are_separated():
    _, text = ingest.html_to_text(
        "<body><nav><h2>Menu</h2></nav><h2></h2><h2>Parts</h2>"
        "<table><tr><th>Name</th><th>Qty</th></tr><tr><td>Bolt</td><td>5</td></tr></table></body>"
    )
    assert "Menu" not in text
    assert all(line.strip("# ") for line in text.splitlines() if line.startswith("#"))
    assert "## Parts" in text and "Name | Qty" in text and "Bolt | 5" in text


def test_csv_empty_cell_stays_in_its_column_and_cell_newlines_do_not_split():
    text = ingest._csv_text(Path("e.csv"), 'id,name,age\n1,,30\n2,Bob,\n3,"multi\n\nline",9\n')
    assert "1 |  | 30" in text and "3 | multi line | 9" in text


def test_bom_is_not_part_of_the_text():
    assert ingest._decode(b"\xef\xbb\xbfid,name") == "id,name"
    assert ingest._decode("id,name".encode("utf-16")) == "id,name"


def test_eml_unknown_charset_and_forwarded_message():
    raw = (b"Subject: x\r\nFrom: a@x\r\nContent-Type: text/plain; charset=x-unknown-foo\r\n\r\nbody text here\r\n")
    assert "body text here" in ingest._eml_text(raw)
    inner = EmailMessage()
    inner["Subject"] = "Inner"
    inner.set_content("Inner body secret text")
    outer = EmailMessage()
    outer["Subject"] = "Fwd only"
    outer.set_content("see below")
    outer.add_attachment(inner)
    text = ingest._eml_text(outer.as_bytes())
    assert "# Fwd only" in text and "## Inner" in text and "Inner body secret text" in text


# --- fusion ----------------------------------------------------------------

@pytest.fixture()
def space(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRGPT_RAG_EMBED", "hash")
    import rag.store as store
    from rag import embed

    embed.reset_embedder_cache()
    monkeypatch.setattr(store, "RAG_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "BLOB_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "rag" / "rag.db")
    store.init()
    sid = int(store.create_space("adv")["id"])

    def load(files: dict[str, str]):
        d = tmp_path / "c"
        d.mkdir(exist_ok=True)
        for name, body in files.items():
            (d / name).write_text(body, encoding="utf-8")
        ingest.ingest_paths(sid, sorted(d.iterdir()))
        return sid

    yield load
    embed.reset_embedder_cache()


def _top(sid, q):
    from rag import retrieve

    return Path(retrieve.search(sid, q, top_k=1)["hits"][0]["path"]).name


def test_rare_place_name_or_year_does_not_hijack_the_answer(space):
    topics = ["onboarding", "vacation", "parking", "benefits"]
    files = {
        f"doc{i:02}.md": f"# {topics[i % 4]} guide {i}\n\nThis explains the {topics[i % 4]} process: file a form, "
                         "get approval from a manager, wait for confirmation.\n"
        for i in range(40)
    }
    files["right.md"] = ("# Expense policy\n\nThe maximum reimbursement for meals during travel is 75 dollars "
                         "per day, with receipts required.\n")
    files["place.md"] = "# Misc\n\nThe office in Tromso hosts a small team. Only coffee and a quiet room.\n"
    files["year.md"] = "# News\n\nThe new office opened in 2024 and the team celebrated with cake.\n"
    sid = space(files)
    assert _top(sid, "What is the maximum reimbursement for meals during travel in Tromso?").endswith("right.md")
    assert _top(sid, "What was the 2024 reimbursement for meals during travel?").endswith("right.md")


# --- ontology --------------------------------------------------------------

def test_small_shared_value_set_is_not_a_join_and_a_quantity_run_is_not_a_key(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    g = wb.create_sheet("Grades")
    g.append(["student", "grade", "qty"])
    for i in range(30):
        g.append([f"s{i}", "ABC"[i % 3], i + 1])
    c = wb.create_sheet("Colors")
    c.append(["code", "colour"])
    for code, name in zip("ABCDEF", ["red", "blue", "green", "pink", "grey", "teal"]):
        c.append([code, name])
    wb.save(tmp_path / "g.xlsx")
    ont = ontology.build_ontology([tmp_path / "g.xlsx"])
    assert ont["relations"] == []
    roles = {col["name"]: col["role"] for w in ont["workbooks"] for t in w["sheets"] for col in t["columns"]}
    assert roles["qty"] == "measure"


def test_csv_banner_and_bom_do_not_become_columns(tmp_path):
    p = tmp_path / "export.csv"
    p.write_bytes("﻿Monthly stock report - confidential\nid;name;units\n".encode("utf-8")
                  + "".join(f"P{i};part {i};{i * 2}\n" for i in range(12)).encode())
    cols = [c["name"] for w in ontology.build_ontology([p])["workbooks"] for t in w["sheets"] for c in t["columns"]]
    assert cols == ["id", "name", "units"]


def test_same_sheet_name_in_two_workbooks_is_two_entities(tmp_path):
    import openpyxl

    for stem, measure in (("north", "amount"), ("south", "total")):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Orders"
        ws.append(["ref", measure])
        for i in range(5):
            ws.append([f"{stem}-{i}", i * 1.5])
        wb.save(tmp_path / f"{stem}.xlsx")
    ont = ontology.build_ontology([tmp_path / "north.xlsx", tmp_path / "south.xlsx"])
    assert sorted(e["id"] for e in ont["entities"]) == ["Orders (north)", "Orders (south)"]
    assert all(len(e["measures"]) == 1 for e in ont["entities"])

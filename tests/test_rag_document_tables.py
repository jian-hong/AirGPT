"""Tables inside Word, web pages and PDFs get the same exact maths a CSV gets.

One table is written as .docx, .html and .pdf (hand-built files, no extra packages) and
asked a sum, an average, a filtered count, a group-by and a filtered sum; every figure is
checked against pandas on the same data. Tables that cannot be read with confidence
(merged cells, rows of different widths, a PDF whose columns do not line up, a table that
continues on a page without its header) are declined in plain words instead of totalled.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HEAD = ["Region", "Product", "Units", "Revenue", "Status"]
DATA = [
    ["North", "Gear", "82", "3,613.93", "Active"],
    ["South", "Bolt", "279", "937.76", "Pending"],
    ["East", "Bolt", "264", "2,010.81", "Active"],
    ["West", "Valve", "219", "721.71", "Active"],
    ["North", "Pump", "222", "626.08", "Pending"],
    ["South", "Bolt", "119", "5,712.57", "Closed"],
    ["East", "Nut", "300", "5,311.32", "Active"],
    ["West", "Nut", "28", "5,054.32", "Closed"],
]
DF = pd.DataFrame(DATA, columns=HEAD)
DF["Units"] = DF["Units"].astype(float)
DF["Revenue"] = DF["Revenue"].str.replace(",", "").astype(float)


# --- writers ---------------------------------------------------------------------------

def write_docx(path: Path, tables: list[str], *, merged: bool = False) -> None:
    def tc(text, span=1):
        pr = f'<w:tcPr><w:gridSpan w:val="{span}"/></w:tcPr>' if span > 1 else ""
        return f'<w:tc>{pr}<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p></w:tc>'

    def tbl(rows, merge_header=False):
        out = []
        for i, r in enumerate(rows):
            if merge_header and i == 0:
                cells = "".join(tc(c) for c in r[:-2]) + tc(r[-2] + " " + r[-1], 2)
            else:
                cells = "".join(tc(c) for c in r)
            out.append(f"<w:tr>{cells}</w:tr>")
        return "<w:tbl>" + "".join(out) + "</w:tbl>"

    body = ['<w:p><w:r><w:t>Quarterly memo</w:t></w:r></w:p>']
    body.append(tbl([["Item", "Owner"], ["Pricing", "Ana"], ["Stock", "Raj"]]))
    body.append('<w:p><w:r><w:t>Sales by line</w:t></w:r></w:p>')
    body.append(tbl([HEAD] + DATA, merge_header=merged))
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="xml" ContentType="application/xml"/></Types>')
        z.writestr("word/document.xml", f'<w:document xmlns:w="{ns}"><w:body>{"".join(body)}</w:body></w:document>')


def write_html(path: Path, *, merged: bool = False) -> None:
    def tbl(rows, merge=False):
        s = "<table>"
        for i, r in enumerate(rows):
            tag = "th" if i == 0 else "td"
            if merge and i == 0:
                s += "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in r[:-2]) + f"<{tag} colspan='2'>{r[-2]}</{tag}></tr>"
            else:
                s += "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in r) + "</tr>"
        return s + "</table>"

    path.write_text("<html><head><title>Sales page</title></head><body><h1>Sales</h1>"
                    + tbl([["Home", "About"]]) + tbl([HEAD] + DATA, merged) + "</body></html>", encoding="utf-8")


def pdf_bytes(pages: list[list[tuple[int, int, str]]]) -> bytes:
    """A text PDF (Helvetica); each item is (x, y, text) in points."""
    objs: list[bytes] = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for items in pages:
        ops = "".join(
            f"BT /F1 10 Tf {x} {y} Td ({t.replace(chr(92), chr(92) * 2).replace('(', chr(92) + '(').replace(')', chr(92) + ')')}) Tj ET\n"
            for x, y, t in items
        ).encode("latin-1")
        objs.append(b"<< /Length %d >>\nstream\n" % len(ops) + ops + b"endstream")
        content = len(objs)
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content)
        kids.append(len(objs))
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, b in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + b + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


XS = [50, 120, 200, 260, 350]


def grid_items(rows, y0=740, xs=XS):
    items = [(50, y0 + 24, "Sales by line")]
    for k, r in enumerate(rows):
        for x, v in zip(xs, r):
            if v:
                items.append((x, y0 - 16 * k, v))
    return items


def write_pdf(path: Path, rows=None, pages=None) -> None:
    path.write_bytes(pdf_bytes(pages or [grid_items(rows or ([HEAD] + DATA))]))


# --- a space with the files -------------------------------------------------------------

@pytest.fixture()
def build():
    os.environ["AIRGPT_RAG_EMBED"] = "hash"
    import rag.store as store
    from rag import answer, embed, ingest

    embed.reset_embedder_cache()
    saved = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    root = Path(tmp.name)
    store.RAG_DIR = root / "rag"
    store.DB_PATH = store.RAG_DIR / "rag.db"
    store.BLOB_DIR = store.RAG_DIR
    store.init()

    def make(files: dict):
        sid = int(store.create_space("tables", depth_default="high")["id"])
        paths = []
        for name, writer in files.items():
            p = root / name
            writer(p)
            paths.append(p)
        ingest.ingest_paths(sid, paths)
        return sid

    def ask(sid, q):
        return answer.answer(sid, q, use_llm=False)

    try:
        yield make, ask
    finally:
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = saved
        embed.reset_embedder_cache()
        tmp.cleanup()


def numbers(text: str) -> list[float]:
    return [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", text)]


def has(text: str, value: float, tol: float = 0.006) -> bool:
    return any(abs(v - value) <= tol for v in numbers(text))


WRITERS = {
    "memo.docx": lambda p: write_docx(p, []),
    "page.html": lambda p: write_html(p),
    "report.pdf": lambda p: write_pdf(p),
}


@pytest.mark.parametrize("name", list(WRITERS))
def test_same_maths_as_a_csv_for_docx_html_and_pdf_tables(build, name):
    make, ask = build
    sid = make({name: WRITERS[name]})
    got = ask(sid, "What is the total Revenue?")["answer"]
    assert has(got, DF.Revenue.sum()), got
    got = ask(sid, "What is the average Units?")["answer"]
    assert has(got, DF.Units.mean()), got
    got = ask(sid, "How many rows have Status Active?")["answer"]
    assert has(got, float((DF.Status == "Active").sum()), 0.1), got
    got = ask(sid, "What is the total Revenue where Region is North?")["answer"]
    assert has(got, DF[DF.Region == "North"].Revenue.sum()), got
    got = ask(sid, "What is the total Revenue by Region?")["answer"]
    for region, v in DF.groupby("Region").Revenue.sum().items():
        assert re.search(rf"{region}\D+{re.escape(f'{v:,.2f}')}", got), (region, got)


def test_provenance_names_the_file_and_the_table(build):
    make, ask = build
    sid = make({"memo.docx": WRITERS["memo.docx"]})
    out = ask(sid, "What is the total Revenue?")
    assert "table 2 of memo.docx" in out["answer"]
    assert out["provenance"]["workbook"] == "memo.docx" and out["provenance"]["sheet"] == "table 2"
    # the small first table is table 1, whether or not it can be asked about
    out = ask(sid, "What is the total Owner?")
    assert "table 1 of memo.docx" in out["answer"]


@pytest.mark.parametrize("name,writer", [
    ("merged.docx", lambda p: write_docx(p, [], merged=True)),
    ("merged.html", lambda p: write_html(p, merged=True)),
])
def test_merged_cells_are_declined_in_plain_words(build, name, writer):
    make, ask = build
    sid = make({name: writer})
    out = ask(sid, f"What is the total Revenue in {name}?")["answer"]
    assert "could not read it as a table" in out and name in out and "merged cells" in out, out
    assert not has(out, DF.Revenue.sum()), "a figure was given from a table that was not read"


def test_naming_the_file_does_not_total_another_files_table(build):
    make, ask = build
    sid = make({"memo.docx": WRITERS["memo.docx"], "merged.html": lambda p: write_html(p, merged=True)})
    out = ask(sid, "What is the total Revenue in merged.html?")["answer"]
    assert "merged.html" in out and "could not read it as a table" in out
    out = ask(sid, "What is the total Revenue in memo.docx?")["answer"]
    assert has(out, DF.Revenue.sum()) and "memo.docx" in out


def test_pdf_with_columns_that_do_not_line_up_is_declined(build):
    make, ask = build
    ragged = [HEAD] + [r[:] for r in DATA]
    ragged[3][4] = ""  # an empty cell: one row has four cells, the others five
    sid = make({"ragged.pdf": lambda p: write_pdf(p, rows=ragged)})
    out = ask(sid, "What is the total Revenue?")["answer"]
    assert "could not read it as a table" in out and "ragged.pdf" in out, out
    assert not has(out, DF.Revenue.sum())


def test_pdf_page_that_continues_a_table_without_its_header_is_declined(build):
    make, ask = build
    pages = [grid_items([HEAD] + DATA[:4]), grid_items(DATA[4:])]
    sid = make({"two.pdf": lambda p: write_pdf(p, pages=pages)})
    out = ask(sid, "What is the total Revenue?")["answer"]
    # the first page is a clean table of 4 rows, read as table 1; the continuation is not
    assert "table 1 of two.pdf" in out and has(out, DF.Revenue[:4].sum())
    assert not has(out, DF.Revenue.sum())


def test_pdf_prose_is_not_mistaken_for_a_table():
    from rag import ingest

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        p = Path(d) / "prose.pdf"
        p.write_bytes(pdf_bytes([[(50, 700, "North sold many bolts last quarter."),
                                  (50, 680, "Pending orders will ship next week to West customers."),
                                  (50, 660, "Closed orders were few and revenue was strong.")]]))
        assert ingest.document_tables(p) == []


def test_refusal_names_the_table_the_question_is_about_not_the_biggest_sheet():
    from rag import sheet_sql

    big = pd.DataFrame({"Sku": [str(i) for i in range(500)], "Price": ["1.5"] * 500})
    small = pd.DataFrame({"Item": ["a", "b", "c"], "Headcount": ["x", "y", "z"]})
    frames = {("stock.xlsx", "Data"): big, ("memo.docx", "table 1"): small}
    out = sheet_sql.explain_no_plan("What is the total Headcount?", frames)
    assert out and out["workbook"] == "memo.docx" and "table 1 of memo.docx" in out["answer"]
    assert "stock.xlsx" not in out["answer"]

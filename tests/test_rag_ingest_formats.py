"""RAG ingest must extract real text from Office formats, not raw zip bytes.

Regression for the bug where uploaded .xlsx/.docx surfaced as
"largely unreadable characters" because they fell through to a raw byte
decode of the ZIP container.
"""
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import chunking, ingest

ZIP_GARBAGE = ("PK\x03\x04", "[Content_Types]", "word/document.xml", "\x00")


def _make_docx(path, paras):
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paras)
    doc = f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", doc)


def _make_pptx(path, slides):
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        for i, texts in enumerate(slides, 1):
            runs = "".join(f"<a:t>{t}</a:t>" for t in texts)
            z.writestr(f"ppt/slides/slide{i}.xml", f'<?xml version="1.0"?><sld xmlns:a="{A}"><b>{runs}</b></sld>')


def _no_garbage(text):
    return not any(g in text for g in ZIP_GARBAGE)


def test_xlsx_extracts_cells(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Measurements"
    ws.append(["Frequency_Hz", "Noise_nV", "Notes"])
    ws.append([1000, 4.7, "RS622XK baseline"])
    p = tmp_path / "lab.xlsx"
    wb.save(str(p))
    text, digest = ingest.read_text_file(p)
    assert digest
    for marker in ("Measurements", "Frequency_Hz", "4.7", "RS622XK baseline"):
        assert marker in text, f"missing {marker!r}"
    assert _no_garbage(text)


def test_docx_extracts_paragraphs(tmp_path):
    p = tmp_path / "doc.docx"
    _make_docx(p, ["Technical Webinar on Noise", "Flicker noise dominates at low frequency."])
    text, _ = ingest.read_text_file(p)
    assert "Technical Webinar on Noise" in text
    assert "Flicker noise dominates" in text
    assert _no_garbage(text)


def test_pptx_extracts_slides(tmp_path):
    p = tmp_path / "deck.pptx"
    _make_pptx(p, [["Roadmap Q3", "Edge AI rollout"], ["Latency under 120ms"]])
    text, _ = ingest.read_text_file(p)
    for marker in ("Roadmap Q3", "Edge AI rollout", "Latency under 120ms", "Slide 2"):
        assert marker in text, f"missing {marker!r}"
    assert _no_garbage(text)


def test_office_suffixes_are_ingestable():
    for suf in (".xlsx", ".xlsm", ".docx", ".pptx"):
        assert suf in ingest.TEXT_SUFFIXES


def test_extracted_xlsx_chunks(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Frequency_Hz", "Noise_nV"])
    for i in range(1, 60):
        ws.append([i * 1000, round(5 - i * 0.05, 2)])
    p = tmp_path / "big.xlsx"
    wb.save(str(p))
    text, _ = ingest.read_text_file(p)
    parents, children = chunking.parent_child_chunk(text)
    assert children, "extracted spreadsheet produced no chunks"
    assert any("Frequency_Hz" in c.text for c in parents + children)


def test_unknown_binary_does_not_crash(tmp_path):
    # A non-office binary must not raise; it may yield empty or replacement text.
    p = tmp_path / "blob.bin"
    p.write_bytes(bytes(range(256)) * 8)
    text, digest = ingest.read_text_file(p)
    assert digest
    assert isinstance(text, str)

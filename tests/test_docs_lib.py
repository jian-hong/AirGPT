"""Safe docs library + canvas fence detection."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docs_lib import has_canvas, list_docs, read_doc, title_from_md  # noqa: E402
from rag.answer import _good_theme, heuristic_space_blurb  # noqa: E402


def test_list_includes_canvas_doc():
    d = list_docs()
    assert d["ok"]
    paths = [x["path"] for x in d["docs"]]
    assert "netie-clicks-jul26.md" in paths
    row = next(x for x in d["docs"] if x["path"] == "netie-clicks-jul26.md")
    assert row["has_canvas"] is True


def test_read_doc_and_canvas_fence():
    r = read_doc("netie-clicks-jul26.md")
    assert r["ok"]
    assert r["has_canvas"]
    assert "Netie Clicks" in r["title"]
    assert has_canvas(r["markdown"])


def test_path_traversal_blocked():
    assert read_doc("../clipdrop.py")["ok"] is False
    assert read_doc("..\\env.local")["ok"] is False


def test_title_from_heading():
    assert title_from_md("# Hello\n\nbody", "x") == "Hello"


def test_heuristic_blurb_filters_weak_themes():
    assert not _good_theme("Slide 1")
    assert not _good_theme("Sheet: Measurements")
    assert not _good_theme("Weekly sync")
    assert _good_theme("How do resistors work?")
    space = {"name": "Demo"}
    sources = [{"title": "a.md"}, {"title": "b.md"}]
    chunks = [
        {"heading": "Slide 1", "text": "x" * 50},
        {"heading": "How do resistors work?", "text": "y" * 50},
    ]
    blurb = heuristic_space_blurb(space, chunks, sources)
    assert "Sources:" in blurb
    assert "1. a.md" in blurb
    assert "Slide 1" not in blurb
    assert "resistors" in blurb.lower()
    assert "Recurring themes" not in blurb

"""RAG-BENCH-15: a downed binary extractor must SAY so, never index silence.

The defect: `_xlsx_text` returns "" when openpyxl is absent, `ingest_paths` dropped
any file whose text was empty, and the space then answered as if the spreadsheet had
never been uploaded. An install missing the package is indistinguishable from a user
who asked about something genuinely absent - which is the lie R-0011 forbids.
"""
from __future__ import annotations

import builtins
import contextlib
import sys

import pytest

from rag import ingest, store


@contextlib.contextmanager
def block_openpyxl():
    """Simulate a deploy that never installed openpyxl, then put it back."""
    real_import = builtins.__import__
    cached = {m: sys.modules[m] for m in list(sys.modules) if m == "openpyxl" or m.startswith("openpyxl.")}

    def blocked(name, *args, **kwargs):
        if name == "openpyxl" or name.startswith("openpyxl."):
            raise ImportError("No module named 'openpyxl'")
        return real_import(name, *args, **kwargs)

    for mod in cached:
        del sys.modules[mod]
    builtins.__import__ = blocked
    try:
        yield
    finally:
        builtins.__import__ = real_import
        sys.modules.update(cached)


@pytest.fixture()
def no_openpyxl():
    with block_openpyxl():
        yield


def _make_xlsx(path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Sample", "Result"])
    ws.append(["RS622XK", "PASS 41.2"])
    wb.save(str(path))
    return path


def test_xlsx_supported_reports_truthfully(no_openpyxl):
    assert ingest.xlsx_supported() is False


def test_extractor_gap_names_the_missing_package(no_openpyxl):
    gap = ingest.extractor_gap(".xlsx")
    assert gap, "a downed xlsx lane must produce a stated reason"
    assert "openpyxl" in gap
    assert ingest.extractor_gap(".xlsm") == gap


def test_extractor_gap_is_empty_when_the_lane_is_healthy():
    pytest.importorskip("openpyxl")
    assert ingest.extractor_gap(".xlsx") == ""


def test_stdlib_lanes_are_never_gated():
    # .docx/.pptx extract with zipfile + ElementTree, so they cannot go missing.
    for suffix in (".docx", ".pptx", ".md", ".txt"):
        assert ingest.extractor_gap(suffix) == ""


def test_ingest_states_the_lane_instead_of_indexing_nothing(tmp_path, monkeypatch):
    """The acceptance criterion: never a silent empty success on the xlsx lane."""
    monkeypatch.setattr(store, "BLOB_DIR", tmp_path / "blobs", raising=False)
    space = store.create_space("gate-check")
    xlsx = tmp_path / "upload" / "lab.xlsx"
    xlsx.parent.mkdir(parents=True)
    # Build the workbook with the real package, then ingest as if it were absent.
    _make_xlsx(xlsx)

    with block_openpyxl():
        out = ingest.ingest_paths(int(space["id"]), [str(xlsx)], force=True)

    assert out.get("ok") is False, "a run that indexed nothing must not report success"
    assert "openpyxl" in str(out.get("error") or ""), out
    reasons = [s.get("reason") for s in out.get("skipped") or []]
    assert any("openpyxl" in str(r) for r in reasons), out
    assert all(s.get("path") for s in out.get("skipped") or []), "name the file that was dropped"


def test_healthy_lane_still_indexes_the_spreadsheet(tmp_path, monkeypatch):
    """R-0005: the gate must not refuse work that a healthy install can do."""
    pytest.importorskip("openpyxl")
    monkeypatch.setattr(store, "BLOB_DIR", tmp_path / "blobs", raising=False)
    space = store.create_space("healthy-lane")
    xlsx = tmp_path / "upload" / "lab.xlsx"
    xlsx.parent.mkdir(parents=True)
    _make_xlsx(xlsx)

    out = ingest.ingest_paths(int(space["id"]), [str(xlsx)], force=True)

    assert out.get("ok") is True, out
    assert int(out.get("sources") or 0) >= 1
    assert not out.get("lanes_unavailable"), out


def test_blank_file_is_reported_separately_from_a_downed_lane(tmp_path, monkeypatch):
    """A genuinely empty file is not a broken lane - the two must not collapse."""
    monkeypatch.setattr(store, "BLOB_DIR", tmp_path / "blobs", raising=False)
    space = store.create_space("blank-file")
    blank = tmp_path / "blank.md"
    blank.write_text("   \n\n", encoding="utf-8")

    out = ingest.ingest_paths(int(space["id"]), [str(blank)], force=True)

    skipped = out.get("skipped") or []
    assert skipped, "an unindexable file must still be named"
    assert all(not s.get("lane_unavailable") for s in skipped), skipped
    assert out.get("ok") is True, "no lane is down, so this is not a lane failure"

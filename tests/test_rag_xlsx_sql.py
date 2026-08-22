"""xlsx/KPI lane is production code, and banners are not headers.

Two D01 defects:
1. rag/answer.py used to put tests/RAG on sys.path and import frtr_sql_baseline.
   A deploy without tests/ returned None for the whole xlsx lane (R-0011).
2. The loader took the first row with >=2 nonempty cells as the header, so
   Messy_RAW's banner (RAW, sheet, em dash, skip) beat the real header.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from rag.xlsx_sql import (  # noqa: E402
    answer_sqlish,
    choose_header_row,
    load_sheets,
    unique_headers,
)


def _write_xlsx(path: Path, title: str, rows: list[list]) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    for row in rows:
        ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return path


def test_choose_header_skips_banner_row():
    banner = ("RAW", "sheet", "—", "skip")
    header = ("sku", "sales_value_myr", "qty", "notes")
    data = ("SKU-00001", 120.5, 3, "ok")
    idx = choose_header_row([banner, header, data])
    assert idx == 1


def test_clean_header_stays_first_row():
    header = ("date", "sku", "sales_value_myr")
    data = ("2024-01-15", "SKU-00001", 10.0)
    assert choose_header_row([header, data]) == 0


def test_label_value_summary_still_picks_first_row():
    # KPI rollup: first row is the header, second is a label/value pair.
    # Must not fall through to treating the data row as names.
    rows = [
        ("metric", "value"),
        ("sku_count_master", 42),
        ("total_sales_myr", 1000.0),
    ]
    assert choose_header_row(rows) == 0


def test_unique_headers_suffix_collisions():
    assert unique_headers(["sku", "sales_value_myr", "sku"]) == [
        "sku",
        "sales_value_myr",
        "sku__2",
    ]


def _messy_raw_rows():
    return [
        ["RAW", "sheet", "—", "skip"],
        ["sku", "sales_value_myr", "qty", "sku"],
        ["SKU-00001", 100.0, 2, "dup-a"],
        ["SKU-00002", 250.0, 5, "dup-b"],
        ["SKU-00001", 50.0, 1, "dup-c"],
    ]


def test_messy_raw_uses_real_header_not_banner(tmp_path):
    path = _write_xlsx(tmp_path / "messy.xlsx", "Messy_RAW", _messy_raw_rows())
    sheets = load_sheets(path)
    assert "Messy_RAW" in sheets
    df = sheets["Messy_RAW"]
    cols = [str(c) for c in df.columns]
    assert "sales_value_myr" in cols
    assert "sku" in cols
    assert "skip" not in cols
    assert "—" not in cols
    assert "RAW" not in cols
    assert df.attrs["header_excel_row"] == 2
    assert df.attrs["first_data_excel_row"] == 3
    assert str(df.iloc[0]["sku"]).startswith("SKU-")
    # Duplicate name on the real header is kept, not merged away.
    assert "sku__2" in cols
    assert len(df) == 3


def test_answer_sqlish_on_messy_raw(tmp_path):
    path = _write_xlsx(tmp_path / "messy.xlsx", "Messy_RAW", _messy_raw_rows())
    sheets = load_sheets(path)
    pred = answer_sqlish(sheets, "top 2 selling skus")
    assert pred is not None
    assert "SKU-00001" in pred
    assert "SKU-00002" in pred
    # 100 + 50 on SKU-00001, 250 on SKU-00002
    assert "250" in pred
    assert "150" in pred


def test_product_lane_does_not_import_from_tests():
    from rag import answer

    src = inspect.getsource(answer._try_hybrid_sql_lane)
    assert "frtr_sql_baseline" not in src
    assert "tests" not in src
    assert "xlsx_sql" in src
    assert "sys.path" not in src


def test_xlsx_lane_answers_when_tests_dir_is_gone(tmp_path, monkeypatch):
    """A checkout without tests/ must still load sheets and answer SQL-ish asks."""
    repo_tests = Path(__file__).resolve().parent
    cleaned = [
        p
        for p in sys.path
        if Path(p).resolve() != repo_tests and "tests/RAG" not in p.replace("\\", "/")
    ]
    monkeypatch.setattr(sys, "path", cleaned)
    sys.modules.pop("frtr_sql_baseline", None)

    path = _write_xlsx(
        tmp_path / "sales.xlsx",
        "Sales",
        [
            ["date", "sku", "sales_value_myr"],
            ["2024-01-15", "SKU-00010", 40.0],
            ["2024-01-16", "SKU-00020", 90.0],
            ["2024-01-17", "SKU-00010", 10.0],
        ],
    )
    with pytest.raises(ImportError):
        import frtr_sql_baseline  # noqa: F401

    sheets = load_sheets(path)
    pred = answer_sqlish(sheets, "top 2 selling skus")
    assert pred is not None
    assert "SKU-00020" in pred
    assert "SKU-00010" in pred

    import rag.store as store
    from rag.answer import _try_hybrid_sql_lane

    monkeypatch.setattr(store, "RAG_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "rag" / "rag.db")
    monkeypatch.setattr(store, "BLOB_DIR", tmp_path / "rag")
    store.init()
    space = store.create_space("KPI ship")
    sid = int(space["id"])
    store.add_source(sid, path=str(path), title="sales.xlsx")
    hit = _try_hybrid_sql_lane(sid, "top 2 selling skus")
    assert hit is not None, "xlsx lane returned None without tests/"
    assert "SKU-00020" in hit["answer"]

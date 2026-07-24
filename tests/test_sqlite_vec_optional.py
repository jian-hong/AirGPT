"""sqlite-vec optional install path reports fallback mode."""
from __future__ import annotations

from rag import sqlite_vec_install, vectors


def test_vectors_available_reports_mode():
    info = vectors.available()
    assert info.get("ok") is True
    assert info.get("mode") in ("sqlite_vec", "blob_cosine")
    assert "sqlite_vec" in info


def test_sqlite_vec_check_shape():
    info = sqlite_vec_install.check()
    assert "installed" in info
    assert "import_ok" in info
    if not info["installed"]:
        assert "pip install sqlite-vec" in (info.get("hint") or "")

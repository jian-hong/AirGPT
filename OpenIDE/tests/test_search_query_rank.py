"""Query-not-grep: rank files by tokens, not first glob substring hit."""

from __future__ import annotations

from pathlib import Path

import OpenIDE.workspace_api as wa


def test_empty_query_is_not_match_everything() -> None:
    assert wa.query_tokens("") == ()
    assert wa.query_tokens("  ") == ()
    assert wa.score_text((), "login token") == 0


def test_two_tokens_outrank_one(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "aaa.py").write_text("token only here\n", encoding="utf-8")
    (root / "zzz.py").write_text("authenticate token in login flow\n", encoding="utf-8")
    monkeypatch.setattr(wa, "WORKSPACE_FILE", tmp_path / "workspace.json")
    monkeypatch.setattr(wa, "DATA_DIR", tmp_path)
    wa.open_workspace(str(root), name="ws")

    out = wa.search_files("authenticate token")
    assert out["ok"] is True
    paths = [m["path"] for m in out["matches"]]
    assert paths[0] == "zzz.py"
    assert "aaa.py" in paths


def test_empty_search_box_returns_no_hits(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.py").write_text("hello\n", encoding="utf-8")
    monkeypatch.setattr(wa, "WORKSPACE_FILE", tmp_path / "workspace.json")
    monkeypatch.setattr(wa, "DATA_DIR", tmp_path)
    wa.open_workspace(str(root), name="ws")
    assert wa.search_files("")["matches"] == []

"""Composer paste: detect a GitHub repo URL. Clone dest cannot escape parent."""

from __future__ import annotations

from pathlib import Path

import OpenIDE.workspace_api as wa


def test_detects_https_and_ignores_issue_paths() -> None:
    assert (
        wa.detect_github_repo_url("see https://github.com/Netie-AI/Cortex please")
        == "https://github.com/Netie-AI/Cortex"
    )
    assert wa.detect_github_repo_url("https://github.com/Netie-AI/Cortex.git") == (
        "https://github.com/Netie-AI/Cortex"
    )
    assert wa.detect_github_repo_url("https://github.com/Netie-AI/issues") == ""
    assert wa.detect_github_repo_url("paste a sentence with no url") == ""


def test_clone_destination_stays_under_parent(tmp_path: Path) -> None:
    out = wa.clone_destination(str(tmp_path), "https://github.com/Netie-AI/Cortex")
    assert out["ok"] is True
    assert out["slug"] == "Cortex"
    assert Path(out["dest"]) == (tmp_path.resolve() / "Cortex")
    assert "never types credentials" in out["push_help"]


def test_clone_destination_refuses_non_repo() -> None:
    assert wa.clone_destination("D:\\AirGPT", "not a url")["ok"] is False

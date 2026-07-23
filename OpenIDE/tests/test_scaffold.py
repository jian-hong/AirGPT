"""OpenIDE Create-App scaffold + prompt trends."""

from __future__ import annotations

from pathlib import Path

import OpenIDE.workspace_api as wa
from OpenIDE import prompt_trends, scaffold


def test_pick_template_heuristics() -> None:
    assert scaffold._pick_template("build a todo website", "auto") == "static"
    assert scaffold._pick_template("make a json api backend", "auto") == "node-api"
    assert scaffold._pick_template("fastapi health endpoint", "auto") == "fastapi"
    assert scaffold._pick_template("anything", "static") == "static"


def test_scaffold_static_under_apps_home(tmp_path: Path, monkeypatch) -> None:
    apps = tmp_path / "openide-apps"
    apps.mkdir()
    monkeypatch.setattr(scaffold, "APPS_HOME", apps)
    monkeypatch.setattr(wa, "WORKSPACE_FILE", tmp_path / "workspace.json")
    monkeypatch.setattr(wa, "DATA_DIR", tmp_path)
    # Force no prior workspace so ensure_apps_workspace binds APPS_HOME
    wa.open_workspace(str(apps), name="openide-apps")

    r = scaffold.scaffold(prompt="Build a local todo app with dark theme", name="todo-demo")
    assert r["ok"] is True, r
    assert r["template"] == "static"
    assert r["app_path"] == "apps/todo-demo"
    assert (apps / "apps" / "todo-demo" / "index.html").is_file()
    assert (apps / "apps" / "todo-demo" / "AGENTS.md").is_file()
    assert "Complete the scaffolded app" in r["seed_prompt"]
    assert r["preview_hint"].startswith("http://")


def test_prompt_trends_advice(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(prompt_trends, "TRENDS_FILE", tmp_path / "prompt_trends.json")
    monkeypatch.setattr(prompt_trends, "DATA_DIR", tmp_path)
    for _ in range(3):
        prompt_trends.record_and_advise("please stress test the buttons and polish ui")
    last = prompt_trends.record_and_advise("stress test ui polish again")
    assert last["ok"] is True
    assert last["advice"]

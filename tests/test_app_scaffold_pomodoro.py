"""DR-0002: app_scaffold produces the pomodoro from a one-line ask."""
from __future__ import annotations

from pathlib import Path

import agent_tools
import apps_hub
import config


def test_one_line_ask_scaffolds_a_timer(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(apps_hub, "REGISTRY_FILE", tmp_path / "apps_registry.json")
    monkeypatch.setattr(apps_hub, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(apps_hub, "next_free_port", lambda start=9100: 19191)
    monkeypatch.setattr(apps_hub, "register_app", lambda entry: {"ok": True, "app": entry})
    monkeypatch.setattr(apps_hub, "set_app_state", lambda *_a, **_k: None)
    monkeypatch.setattr(apps_hub, "registry", lambda: {"apps": []})

    out = agent_tools.scaffold_from_ask("make a pomodoro timer")
    assert out.get("ok"), out
    html = Path(out["cwd"]) / "index.html"
    js = Path(out["cwd"]) / "app.js"
    assert html.is_file()
    body = html.read_text(encoding="utf-8")
    assert "25:00" in body
    assert "Start" in body
    assert "25*60" in js.read_text(encoding="utf-8")
    assert not (Path(config.ROOT) / "pomodoro.html").exists()


def test_handwritten_pomodoro_fixture_is_gone():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "pomodoro.html").exists()
    src = (root / "clipdrop.py").read_text(encoding="utf-8")
    assert '"/pomodoro"' not in src
    assert '"/tomato"' not in src

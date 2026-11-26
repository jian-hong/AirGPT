"""OpenFree must not pretend to start where it cannot (first use on Linux or macOS)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import openfree  # noqa: E402


@pytest.fixture()
def closed_port(monkeypatch):
    monkeypatch.setattr(openfree, "_port_open", lambda timeout=0.4: False)


def _no_launch(monkeypatch):
    def boom(*a, **k):  # what the real call did on a box with no powershell
        raise FileNotFoundError(2, "No such file or directory: 'powershell'")
    monkeypatch.setattr(openfree.subprocess, "Popen", boom)


def test_no_powershell_gives_one_plain_sentence(monkeypatch, closed_port):
    monkeypatch.setattr(openfree.sys, "platform", "linux")
    monkeypatch.setattr(openfree.shutil, "which", lambda name: None)
    _no_launch(monkeypatch)
    r = openfree.enable()
    assert r["ok"] is False and r.get("unsupported") is True
    text = r["error"]
    assert "powershell" not in text.lower().replace("powershell 7", "")
    assert "Errno" not in text and "launch failed" not in text
    assert text.endswith("Paste an API key instead.")
    st = openfree.status()
    assert st["can_run"] is False and st["why"] == text


def test_pwsh_is_used_where_it_exists(monkeypatch, closed_port):
    monkeypatch.setattr(openfree.sys, "platform", "linux")
    monkeypatch.setattr(openfree.shutil, "which", lambda name: "/usr/bin/pwsh" if name == "pwsh" else None)
    seen = {}

    class P:
        def __init__(self, cmd, **k):
            seen["cmd"] = cmd
    monkeypatch.setattr(openfree.subprocess, "Popen", P)
    r = openfree.enable()
    assert r["ok"] is True and r["phase"] == "installing"
    assert seen["cmd"][0] == "/usr/bin/pwsh"
    assert openfree.status()["can_run"] is True


def test_unsupported_route_leaves_settings_alone(monkeypatch, closed_port):
    """The HTTP route must say no before it flips OMNIROUTE_ENABLED."""
    src = (Path(__file__).resolve().parents[1] / "clipdrop.py").read_text(encoding="utf-8")
    i = src.index('if path == "/api/openfree/enable":')
    block = src[i:i + 1200]
    assert block.index("cannot_run()") < block.index("update_settings(")

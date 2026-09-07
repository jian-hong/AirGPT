"""OpenVault mesh bridge — handshake against live or mocked endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from OpenIDE import openvault_bridge


def test_ensure_local_config(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "OpenVault"
    root.mkdir()
    (root / "openvault.local.example.json").write_text(
        json.dumps({"schema": "openvault.local.config/v1", "services": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(openvault_bridge, "OPENVAULT_ROOT", root)
    monkeypatch.setattr(openvault_bridge, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(openvault_bridge, "_file_env", lambda _key: "")
    monkeypatch.delenv("OPENIDE_URL", raising=False)
    monkeypatch.delenv("OPENVAULT_ROOT", raising=False)
    monkeypatch.delenv("OPENVAULT_HOME", raising=False)
    r = openvault_bridge.ensure_local_config()
    assert r["ok"] is True
    written = Path(r["path"])
    assert written == tmp_path / "data" / "openvault.local.json"
    assert not (root / "openvault.local.json").exists()
    cfg = json.loads(written.read_text(encoding="utf-8"))
    assert "8765" in cfg["services"]["openide"]["url"]
    assert cfg["services"]["openvault"]["root"] == str(root)


def test_looks_like_openvault(tmp_path: Path) -> None:
    assert openvault_bridge.looks_like_openvault(tmp_path) is False
    cli = tmp_path / "apps" / "cli"
    cli.mkdir(parents=True)
    (cli / "openvault_cli.py").write_text("#", encoding="utf-8")
    assert openvault_bridge.looks_like_openvault(tmp_path) is True


def test_resolve_openvault_root_prefers_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENVAULT_ROOT", str(tmp_path))
    assert openvault_bridge.resolve_openvault_root() == tmp_path


def test_mesh_build_check_tree_only(tmp_path: Path, monkeypatch) -> None:
    cli = tmp_path / "apps" / "cli"
    cli.mkdir(parents=True)
    (cli / "openvault_cli.py").write_text("#", encoding="utf-8")
    monkeypatch.setattr(openvault_bridge, "OPENVAULT_ROOT", tmp_path)
    monkeypatch.setattr(openvault_bridge, "_file_env", lambda _key: "")
    monkeypatch.delenv("OPENVAULT_HOME", raising=False)
    out = openvault_bridge.mesh_build_check(live=False)
    assert out["tree_ok"] is True
    assert out["ok"] is True
    assert out["root"] == str(tmp_path)
    assert "health_ok" not in out


def test_handshake_live_or_skip() -> None:
    p = openvault_bridge.ping()
    if not p.get("ok"):
        return  # OpenVault not running — bridge still importable
    openvault_bridge.ensure_local_config()
    r = openvault_bridge.handshake(name="AirGPT OpenIDE pytest")
    assert r.get("ok") is True
    assert r.get("openide_url")
    assert r.get("handshake")

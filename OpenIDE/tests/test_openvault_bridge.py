"""OpenVault mesh bridge — handshake against live or mocked endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import openvault_bridge


def test_ensure_local_config(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "OpenVault"
    root.mkdir()
    (root / "openvault.local.example.json").write_text(
        json.dumps({"schema": "openvault.local.config/v1", "services": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(openvault_bridge, "OPENVAULT_ROOT", root)
    monkeypatch.setattr(openvault_bridge, "DATA_DIR", tmp_path / "data")
    r = openvault_bridge.ensure_local_config()
    assert r["ok"] is True
    cfg = json.loads(Path(r["path"]).read_text(encoding="utf-8"))
    assert cfg["services"]["openide"]["url"].endswith(":8765") or "8765" in cfg["services"]["openide"]["url"]


def test_handshake_live_or_skip() -> None:
    p = openvault_bridge.ping()
    if not p.get("ok"):
        return  # OpenVault not running — bridge still importable
    openvault_bridge.ensure_local_config()
    r = openvault_bridge.handshake(name="AirGPT OpenIDE pytest")
    assert r.get("ok") is True
    assert r.get("openide_url")
    assert r.get("handshake")

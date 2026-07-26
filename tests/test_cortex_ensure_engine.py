"""AirGPT cortex_client ensure_engine / spawn helpers (no live Cortex required)."""
from __future__ import annotations

import cortex_client as cc


def test_autospawn_disabled_skips_spawn(monkeypatch):
    monkeypatch.setenv("CORTEX_AUTOSPAWN", "0")
    monkeypatch.setattr(cc, "available", lambda: False)
    monkeypatch.setattr(
        cc,
        "spawn_engine",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not spawn")),
    )
    out = cc.ensure_engine()
    assert out["ok"] is False
    assert "AUTOSPAWN" in (out.get("error") or "")


def test_ensure_engine_live_short_circuits(monkeypatch):
    monkeypatch.setattr(cc, "available", lambda: True)
    monkeypatch.setattr(cc, "_cfg", lambda: ("http://127.0.0.1:8010", ""))
    out = cc.ensure_engine()
    assert out["ok"] is True
    assert out["status"] == "live"
    assert out.get("spawned") is False


def test_spawn_missing_script(monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "available", lambda: False)
    monkeypatch.setattr(cc, "_cortex_root", lambda: tmp_path)
    with cc._spawn_lock:
        cc._spawn_state.update({"attempted": False, "ok": False, "error": None})
    out = cc.spawn_engine(wait_sec=0.1)
    assert out["ok"] is False
    assert "missing launcher" in (out.get("error") or "")

"""App update path: honest when no signed release channel exists."""
from __future__ import annotations

import license as app_license


def test_check_update_names_missing_channel(monkeypatch):
    monkeypatch.setattr(
        "ai_engine.load_env",
        lambda: {},
    )
    out = app_license.check_update()
    assert out["ok"] is True
    assert out["update"] is False
    assert out["reason"] == "no_update_server"
    assert out["current"]
    assert "download-safe" in (out.get("hint") or "").lower() or "signed" in (out.get("hint") or "").lower()


def test_check_update_compares_versions(monkeypatch):
    monkeypatch.setattr("ai_engine.load_env", lambda: {"AIRGPT_API_BASE": "http://example.invalid"})

    class _Resp:
        def read(self):
            return b'{"version":"9.9.9","url":"https://example.invalid/app"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp())
    out = app_license.check_update()
    assert out["ok"] is True
    assert out["update"] is True
    assert out["latest"] == "9.9.9"
    assert out["reason"] == "update_available"

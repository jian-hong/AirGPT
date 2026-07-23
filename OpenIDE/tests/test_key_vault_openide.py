"""Key vault registry + OpenIDE ready preflight."""

from __future__ import annotations

import key_vault


def test_snapshot_includes_netie_omniroute_cursor() -> None:
    snap = key_vault.snapshot(include_status=False)
    by_id = {p["id"]: p for p in snap["providers"]}
    assert "netie_official" in by_id
    assert "omniroute" in by_id
    assert by_id["omniroute"].get("label") == "OpenFree"
    assert "cursor" in by_id
    assert by_id["cursor"].get("ui_hidden") is True
    assert by_id["ollama"].get("ui_hidden") is True
    assert by_id["vllm"].get("ui_hidden") is True
    assert "groq" in by_id
    assert "github_cli" in by_id
    assert "openship" in by_id
    assert by_id["github_cli"].get("group") == "cli"
    assert by_id["openship"].get("group") == "deploy"
    assert snap.get("product_name") == "OpenVault Key Vault"
    assert "free_fallback_order" in snap
    assert "ollama" not in snap["free_fallback_order"]


def test_ready_cursor_needs_cursor_key() -> None:
    r = key_vault.ready_for_backend("cursor_local")
    assert r["backend"] == "cursor_local"
    assert "need" in r
    assert "CURSOR_API_KEY" in r["need"]

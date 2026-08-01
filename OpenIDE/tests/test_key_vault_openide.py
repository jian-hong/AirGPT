"""Key vault registry + OpenIDE ready preflight."""

from __future__ import annotations

import key_vault


def test_snapshot_includes_netie_omniroute_cursor() -> None:
    snap = key_vault.snapshot(include_status=False)
    by_id = {p["id"]: p for p in snap["providers"]}
    assert "netie_official" in by_id
    assert "omniroute" in by_id
    # The label is branding owned by OpenVault and resolved live through
    # openvault_bridge.keyvault_snapshot() — it currently ships "FreeRoute" where the
    # static default here still says "OpenFree". Pinning the string made this test fail
    # whenever OpenVault rebrands or is simply running. Assert the structural fact.
    assert by_id["omniroute"].get("label")
    assert "cursor" in by_id
    # Cards AirGPT deliberately hides must stay hidden whether or not OpenVault is
    # running. When OV is live it supplies its own cursor/ollama cards without the flag,
    # and index.html filters on `!p.ui_hidden` — so losing this leaked them into the UI.
    # A card OV omits entirely (vllm) is equally hidden, hence the absent-or-hidden form.
    for pid in ("cursor", "ollama", "vllm"):
        assert by_id.get(pid, {}).get("ui_hidden", True) is True, f"{pid} must not surface in the Key Vault UI"
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

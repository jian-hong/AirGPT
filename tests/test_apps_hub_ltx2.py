"""Smoke tests — apps registry uniqueness + LTX2 mock generate."""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_registry_unique_ports():
    reg = json.loads((ROOT / "apps_registry.json").read_text(encoding="utf-8"))
    # Surfaces may share AirGPT's port; TCP services must be unique
    ports = [int(a["port"]) for a in reg["apps"] if a.get("kind") != "surface"]
    assert len(ports) == len(set(ports)), f"duplicate ports: {ports}"
    by_id = {a["id"]: a["port"] for a in reg["apps"]}
    assert by_id["airgpt"] == 8765
    assert by_id["dms-v1"] == 3000
    assert by_id["dms-v2"] == 8010
    assert by_id["ltx2"] == 8020
    assert by_id["vllm"] == 8001
    assert by_id["colibri"] == 8002
    assert by_id["openide"] == 8765
    assert by_id["openforge"] == 8765


def test_apps_hub_status():
    import apps_hub

    st = apps_hub.status()
    assert st["ok"] is True
    assert not st["port_conflicts_in_registry"]
    ids = {a["id"] for a in st["apps"]}
    assert {"airgpt", "dms-v2", "ltx2"} <= ids


def test_ltx2_mock_generate():
    import ltx2_video

    cap = ltx2_video.capability()
    assert cap["ok"] is True
    r = ltx2_video.submit("AirGPT mock plate test", duration=2, mode="mock")
    assert r["ok"] is True and r["id"]
    deadline = time.time() + 90
    while time.time() < deadline:
        st = ltx2_video.status(r["id"])
        if st.get("status") in ("completed", "failed"):
            break
        time.sleep(0.2)
    assert st.get("status") == "completed", st
    res = ltx2_video.result(r["id"])
    assert res["ok"] is True
    assert Path(res["path"]).exists()

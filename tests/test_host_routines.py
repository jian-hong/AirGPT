"""SHELL-02: host clock fires when Cortex has no /api/routines."""
import time

import host_routines


def test_interval_daily():
    assert host_routines.interval_from_goal("Morning news brief daily") == 86400
    assert host_routines.interval_from_goal("Weekly memory digest Mondays") == 7 * 86400


def test_create_tick_advances(tmp_path, monkeypatch):
    monkeypatch.setattr(host_routines, "STORE", tmp_path / "host_routines.json")
    monkeypatch.setattr(host_routines, "DATA_DIR", tmp_path)
    out = host_routines.create("Morning news brief daily")
    assert out["ok"] is True
    assert str(out["routine_id"]).startswith("hr-")
    assert out["scheduler"] == "airgpt_host"
    rid = out["routine_id"]
    with host_routines._lock:
        rows = host_routines._load()
        rows[0]["next_run_at"] = 1.0
        host_routines._save(rows)
    now = 1_700_000_000.0
    tick = host_routines.tick(now=now)
    assert rid in tick["fired"]
    row = host_routines.list_routines()["routines"][0]
    assert row["next_run_at"] > now
    assert row["last_status"] == "fired_no_agent"
    assert row["last_run_at"] == now

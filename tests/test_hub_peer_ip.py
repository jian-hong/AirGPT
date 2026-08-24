"""Hub peer IP normalize / kick must not spawn URL-encoded ghosts."""
from __future__ import annotations

import tempfile
from pathlib import Path
from urllib.parse import quote

import db
import hub


def test_normalize_peer_ip_unquotes_ipv6():
    raw = "2a02:26f7:c6c0:49e3:0:1000:0:1"
    enc = quote(raw, safe="")
    enc2 = quote(enc, safe="")
    assert "%" in enc
    assert "%25" in enc2
    assert hub.normalize_peer_ip(enc) == hub.normalize_peer_ip(raw)
    assert hub.normalize_peer_ip(enc2) == hub.normalize_peer_ip(raw)
    assert "%" not in hub.normalize_peer_ip(enc)


def test_kick_encoded_ipv6_does_not_create_ghost(monkeypatch):
    tmp = Path(tempfile.mkdtemp()) / "t.db"
    monkeypatch.setattr(db, "DB_PATH", tmp)
    db.init_db()

    real = "2a02:26f7:c6c0:49e3:0:1000:0:1"
    db.upsert_hub_peer(real, display_name="Guest", join_method="lan", logged_in=True)
    assert db.get_hub_peer(real)

    # Simulate old frontend path segment (encodeURIComponent) hitting kick.
    enc = quote(real, safe="")
    r = hub.kick_peer(enc)
    assert r.get("ok")
    assert db.get_hub_peer(real) is None
    assert db.get_hub_peer(enc) is None
    # No ghost with double encoding either
    assert db.get_hub_peer(quote(enc, safe="")) is None


def test_purge_junk_and_snapshot_hides_encoded(monkeypatch):
    tmp = Path(tempfile.mkdtemp()) / "t2.db"
    monkeypatch.setattr(db, "DB_PATH", tmp)
    db.init_db()

    real = "10.1.7.39"
    db.upsert_hub_peer(real, display_name="LAN", join_method="lan", logged_in=True)
    # Plant ghosts the old bug created
    with db._lock, db._connect() as conn:
        conn.execute(
            "INSERT INTO hub_peers(ip,device_id,display_name,access_level,join_method,"
            "logged_in,admin_name,chat_sessions,created_at,updated_at,last_seen) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                "2a02%3A26f7%3Ac6c0%3A49e3%3A0%3A1000%3A0%3A1",
                "x", "Guest", "read_write", "lan", 0, "", "", 1, 1, 1,
            ),
        )
        conn.execute(
            "INSERT INTO hub_peers(ip,device_id,display_name,access_level,join_method,"
            "logged_in,admin_name,chat_sessions,created_at,updated_at,last_seen) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                "2a02%253A26f7%253Ac6c0%253A49e3%253A0%253A1000%253A0%253A1",
                "y", "Guest", "read_write", "lan", 0, "", "", 1, 1, 1,
            ),
        )
        conn.commit()

    snap = hub.get_hub_snapshot(host_ip="127.0.0.1")
    ips = [p["ip"] for p in snap["peers"]]
    assert real in ips
    assert all("%" not in ip for ip in ips)
    assert snap["host"]["icon"] == "laptop"
    assert snap["host"]["role"] == "host"
    # Host loopback must not also appear as a Guest peer
    assert all(p.get("role") != "host" for p in snap["peers"])


def test_upsert_rejects_percent_ip(monkeypatch):
    tmp = Path(tempfile.mkdtemp()) / "t3.db"
    monkeypatch.setattr(db, "DB_PATH", tmp)
    db.init_db()
    assert db.upsert_hub_peer("2a02%3Afoo") == {}

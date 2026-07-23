"""Coherent Access Hub — host roster, join codes, peer ACL, disconnect history."""
from __future__ import annotations

import socket
import time
from typing import Any

import db

ONLINE_WINDOW_SEC = 300  # 5 min
ACL_LEVELS = ("read_only", "read_write", "use_host_ai", "use_own_ai", "limited")


def _hostname() -> str:
    try:
        return socket.gethostname()[:80]
    except Exception:
        return "host"


def _device_icon(name: str, ua: str = "") -> str:
    blob = f"{name} {ua}".lower()
    if any(x in blob for x in ("iphone", "android", "mobile", "phone")):
        return "phone"
    if any(x in blob for x in ("ipad", "tablet")):
        return "tablet"
    if any(x in blob for x in ("laptop", "macbook")):
        return "laptop"
    return "desktop"


def _peer_role(peer: dict, host_ip: str) -> str:
    ip = peer.get("ip") or ""
    method = (peer.get("join_method") or "").lower()
    if ip in ("127.0.0.1", "::1", host_ip):
        return "host"
    if method == "team":
        return "guest_team"
    if method in ("qr", "share"):
        return "guest_qr"
    if peer.get("logged_in"):
        return "sub"
    return "guest"


def _is_online(last_seen: float | None) -> bool:
    if not last_seen:
        return False
    return (time.time() - float(last_seen)) < ONLINE_WINDOW_SEC


def get_hub_snapshot(
    *,
    host_ip: str = "127.0.0.1",
    business: bool = False,
    join_url: str = "",
    join_code: str = "",
) -> dict:
    import auth

    ws = auth.status()
    devices = db.list_devices()
    peers_db = {p["ip"]: p for p in db.list_hub_peers(80)}
    now = time.time()
    host_name = ws.get("host_email", "").split("@")[0] or _hostname()

    host_node = {
        "id": "host",
        "role": "host",
        "label": "Host",
        "username": host_name,
        "ip": host_ip,
        "icon": "desktop",
        "logged_in": True,
        "online": True,
        "access_level": "host",
        "join_method": "host",
        "chat_sessions": "",
    }

    peer_nodes: list[dict[str, Any]] = []
    seen_ips: set[str] = set()

    for dev in devices:
        ip = dev.get("ip") or ""
        if not ip or ip in seen_ips:
            continue
        seen_ips.add(ip)
        meta = peers_db.get(ip, {})
        last_seen = float(dev.get("last_seen") or meta.get("last_seen") or 0)
        online = _is_online(last_seen)
        display = meta.get("display_name") or meta.get("admin_name") or dev.get("name") or ip
        peer = {
            "id": meta.get("device_id") or ip,
            "ip": ip,
            "username": display,
            "icon": _device_icon(display, dev.get("user_agent") or ""),
            "logged_in": bool(meta.get("logged_in")),
            "online": online,
            "access_level": meta.get("access_level") or "read_write",
            "join_method": meta.get("join_method") or "lan",
            "chat_sessions": meta.get("chat_sessions") or "",
            "admin_name": meta.get("admin_name") or "",
            "last_seen": last_seen,
            "dull": not online,
        }
        peer["role"] = _peer_role(peer, host_ip)
        peer["label"] = {
            "host": "Host",
            "sub": "sub",
            "guest_team": "Guest (Team)",
            "guest_qr": "Guest (QR)",
            "guest": "Guest",
        }.get(peer["role"], "Guest")
        peer_nodes.append(peer)

    # Include historical peers not in recent devices list
    for ip, meta in peers_db.items():
        if ip in seen_ips:
            continue
        last_seen = float(meta.get("last_seen") or 0)
        online = _is_online(last_seen)
        peer = {
            "id": meta.get("device_id") or ip,
            "ip": ip,
            "username": meta.get("display_name") or meta.get("admin_name") or ip,
            "icon": _device_icon(meta.get("display_name") or ""),
            "logged_in": bool(meta.get("logged_in")),
            "online": online,
            "access_level": meta.get("access_level") or "read_write",
            "join_method": meta.get("join_method") or "lan",
            "chat_sessions": meta.get("chat_sessions") or "",
            "admin_name": meta.get("admin_name") or "",
            "last_seen": last_seen,
            "dull": not online,
        }
        peer["role"] = _peer_role(peer, host_ip)
        peer["label"] = {
            "sub": "sub",
            "guest_team": "Guest (Team)",
            "guest_qr": "Guest (QR)",
        }.get(peer["role"], "Guest")
        peer_nodes.append(peer)

    online_count = sum(1 for p in peer_nodes if p.get("online"))
    codes = auth._load_join_codes() if hasattr(auth, "_load_join_codes") else {}
    active_code = join_code or (next(iter(codes.keys()), "") if codes else "")

    out: dict[str, Any] = {
        "ok": True,
        "title": "Coherent Access Hub",
        "host": host_node,
        "peers": peer_nodes,
        "online_count": online_count,
        "total_peers": len(peer_nodes),
        "join_url": join_url,
        "join_code": active_code,
        "access_levels": list(ACL_LEVELS),
        "business": business,
        "personal_mode": not business,
    }
    if business:
        out["events"] = db.list_hub_events(50)
        out["activity"] = db.device_activity_stats()[:20]
    return out


def touch_peer(
    ip: str,
    *,
    device_id: str = "",
    display_name: str = "",
    join_method: str = "",
    logged_in: bool = True,
    access_level: str = "",
) -> dict:
    existing = db.get_hub_peer(ip) or db.find_hub_peer_by_device_id(device_id)
    name = display_name
    if not name and existing:
        name = existing.get("display_name") or existing.get("admin_name") or ""
    level = access_level or (existing or {}).get("access_level") or "read_write"
    method = join_method or (existing or {}).get("join_method") or "lan"
    peer = db.upsert_hub_peer(
        ip,
        device_id=device_id or (existing or {}).get("device_id") or ip,
        display_name=name,
        access_level=level,
        join_method=method,
        logged_in=logged_in,
    )
    if existing and not existing.get("last_seen"):
        db.log_hub_event(ip, "connect", f"joined via {method}", device_id=device_id)
    return peer


def set_peer_acl(ip: str, access_level: str, *, admin_name: str = "") -> dict:
    level = (access_level or "read_write").strip().lower()
    if level not in ACL_LEVELS:
        return {"ok": False, "error": f"access_level must be one of {ACL_LEVELS}"}
    peer = db.upsert_hub_peer(ip, access_level=level, admin_name=admin_name)
    db.log_hub_event(ip, "acl_change", level)
    return {"ok": True, "peer": peer}


def rename_peer(ip: str, display_name: str) -> dict:
    name = (display_name or "").strip()[:120]
    if not name:
        return {"ok": False, "error": "display_name required"}
    peer = db.upsert_hub_peer(ip, display_name=name, admin_name=name)
    db.log_hub_event(ip, "rename", name)
    return {"ok": True, "peer": peer}


def kick_peer(ip: str) -> dict:
    import auth

    peer = db.get_hub_peer(ip)
    db.upsert_hub_peer(ip, logged_in=False)
    db.log_hub_event(ip, "kick", "disconnected by host")
    return {"ok": True, "peer": peer, "note": "Peer marked offline; revoke active tokens separately if needed"}


def create_join_code(
    access_level: str = "read_write",
    *,
    host_token: str | None = None,
    host_verified: bool = False,
) -> dict:
    import auth

    return auth.issue_join_code(
        access_level,
        host_token=host_token,
        host_verified=host_verified,
    )


def redeem_join_code(code: str, ip: str = "", device_id: str = "", display_name: str = "") -> dict:
    import auth

    r = auth.redeem_join_code(code)
    if r.get("ok") and ip:
        touch_peer(
            ip,
            device_id=device_id,
            display_name=display_name,
            join_method="team",
            logged_in=True,
            access_level=r.get("access_level", "read_write"),
        )
        db.log_hub_event(ip, "join_team", code[:6], device_id=device_id)
    return r

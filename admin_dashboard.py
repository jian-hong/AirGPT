"""Admin workforce dashboard — real SQLite aggregates + optional Cortex merge."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from config import DATA_DIR, ROOT

try:
    import audit as app_audit
except ImportError:
    app_audit = None  # type: ignore

try:
    import db
except ImportError:
    db = None  # type: ignore

try:
    import cortex_client
except ImportError:
    cortex_client = None  # type: ignore

try:
    import access_policy
except ImportError:
    access_policy = None  # type: ignore

try:
    import license as app_license
except ImportError:
    app_license = None  # type: ignore

ADMIN_STATE = DATA_DIR / "admin_state.json"


def _load_state() -> dict:
    if not ADMIN_STATE.is_file():
        return {"validations": {}}
    try:
        return json.loads(ADMIN_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"validations": {}}


def _save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ADMIN_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _vault_count() -> int:
    vault = DATA_DIR / "vault"
    if not vault.is_dir():
        return 0
    return sum(1 for _ in vault.rglob("*.md"))


def _fmt_minutes(m: int) -> str:
    m = max(0, int(m))
    if m < 60:
        return f"{m}m"
    h, r = divmod(m, 60)
    return f"{h}h {r}m" if r else f"{h}h"


def _worker_id(ip: str) -> str:
    return f"d-{ip.replace('.', '-')}"


def _audit_events() -> list[dict]:
    events: list[dict] = []
    if cortex_client:
        try:
            if cortex_client.health().get("ok"):
                events.extend(cortex_client.audit_tail(30))
        except Exception:
            pass
    if app_audit:
        try:
            events.extend(app_audit.tail(40))
        except Exception:
            pass
    return events


def _activities_for_ip(ip: str, events: list[dict], limit: int = 8) -> list[dict]:
    acts: list[dict] = []
    for e in events:
        eip = (e.get("ip") or e.get("actor") or "").strip()
        if eip and eip != ip:
            continue
        if not eip and ip not in ("127.0.0.1", "localhost"):
            continue
        ts = e.get("ts") or e.get("at")
        try:
            tstr = datetime.fromtimestamp(float(ts)).strftime("%H:%M") if ts else "—"
        except (TypeError, ValueError, OSError):
            tstr = "—"
        acts.append({
            "time": tstr,
            "action": str(e.get("action") or e.get("event_type") or "event")[:40],
            "detail": str(e.get("detail") or e.get("payload") or "")[:160],
        })
        if len(acts) >= limit:
            break
    return acts


def _device_workers() -> list[dict]:
    """Build workers from real devices + per-device message aggregates."""
    if not db:
        return []
    devices = db.list_devices() if hasattr(db, "list_devices") else []
    stats_by_ip = {s["ip"]: s for s in (db.device_activity_stats() if hasattr(db, "device_activity_stats") else [])}
    state = _load_state()
    validations = state.get("validations") or {}
    audit_events = _audit_events()
    workers: list[dict] = []
    seen_ips: set[str] = set()

    for i, d in enumerate(devices[:40]):
        ip = d.get("ip") or d.get("device_ip") or f"dev-{i}"
        seen_ips.add(ip)
        name = d.get("name") or d.get("device_name") or ip
        st = stats_by_ip.get(ip, {})
        sess_n = int(st.get("sessions") or 0)
        screenshots = int(st.get("screenshots") or 0)
        clipboard_events = int(st.get("clipboard_events") or 0)
        ai_minutes = int(st.get("ai_minutes") or 0)
        last = float(st.get("last_seen") or d.get("last_seen") or time.time())
        last_s = datetime.fromtimestamp(last).strftime("%H:%M") if last else "—"
        active_minutes = int(min(480, sess_n * 8 + screenshots * 2 + 5))
        vid = _worker_id(ip)
        val = validations.get(vid, {})
        status = val.get("status", "safe")
        workers.append({
            "id": vid,
            "name": name,
            "department": "Local workspace",
            "status": status,
            "role": "Member",
            "active_minutes": active_minutes,
            "active_display": _fmt_minutes(active_minutes),
            "ai_minutes": ai_minutes,
            "ai_display": _fmt_minutes(ai_minutes),
            "sessions": sess_n,
            "screenshots": screenshots,
            "vault_notes": _vault_count() if i == 0 else 0,
            "clipboard_events": clipboard_events,
            "last_active": last_s,
            "device": name,
            "ip": ip,
            "validated": bool(val.get("at")),
            "summary": f"{name} · {sess_n} sessions · {screenshots} captures · last {last_s}",
            "activities": _activities_for_ip(ip, audit_events),
            "files": [],
        })

    for ip, st in stats_by_ip.items():
        if ip in seen_ips:
            continue
        name = st.get("name") or ip
        sess_n = int(st.get("sessions") or 0)
        screenshots = int(st.get("screenshots") or 0)
        clipboard_events = int(st.get("clipboard_events") or 0)
        ai_minutes = int(st.get("ai_minutes") or 0)
        last = float(st.get("last_seen") or time.time())
        last_s = datetime.fromtimestamp(last).strftime("%H:%M")
        active_minutes = int(min(480, sess_n * 8 + screenshots * 2 + 5))
        vid = _worker_id(ip)
        val = validations.get(vid, {})
        workers.append({
            "id": vid,
            "name": name,
            "department": "Local workspace",
            "status": val.get("status", "safe"),
            "role": "Member",
            "active_minutes": active_minutes,
            "active_display": _fmt_minutes(active_minutes),
            "ai_minutes": ai_minutes,
            "ai_display": _fmt_minutes(ai_minutes),
            "sessions": sess_n,
            "screenshots": screenshots,
            "vault_notes": 0,
            "clipboard_events": clipboard_events,
            "last_active": last_s,
            "device": name,
            "ip": ip,
            "validated": bool(val.get("at")),
            "summary": f"{name} · {sess_n} sessions · last {last_s}",
            "activities": _activities_for_ip(ip, audit_events),
            "files": [],
        })

    if not workers:
        sessions = db.list_sessions(80) if hasattr(db, "list_sessions") else []
        workers.append({
            "id": "host",
            "name": "This PC",
            "department": "Local",
            "status": "safe",
            "role": "Host",
            "active_minutes": 0,
            "active_display": "0m",
            "ai_minutes": 0,
            "ai_display": "0m",
            "sessions": len(sessions),
            "screenshots": 0,
            "vault_notes": _vault_count(),
            "clipboard_events": 0,
            "last_active": datetime.now().strftime("%H:%M"),
            "device": "localhost",
            "ip": "127.0.0.1",
            "validated": False,
            "summary": "Host workspace — real session & vault counts",
            "activities": _activities_for_ip("127.0.0.1", audit_events),
            "files": [],
        })
    return workers


def _cortex_block() -> dict:
    if not cortex_client:
        return {"mode": "optional", "status": "standby", "cloud": "Cortex DMS-v2 sidecar not installed", "local": "AirGPT"}
    h = cortex_client.health()
    audit = cortex_client.audit_tail(10) if h.get("ok") else []
    verify = cortex_client.verify_ledger() if h.get("ok") else {}
    return {
        "mode": "sidecar",
        "status": h.get("status", "standby"),
        "url": h.get("url"),
        "ok": h.get("ok"),
        "local": "AirGPT :8765",
        "ledger_verify": verify,
        "audit_sample": audit[:5],
        "cloud": "Netie Cortex DMS-v2 (optional)",
    }


def overview(include_files: bool = False) -> dict:
    workers = _device_workers()
    state = _load_state()
    validations = state.get("validations") or {}
    safe = sum(1 for w in workers if w.get("status") == "safe")
    suspicious = sum(1 for w in workers if w.get("status") == "suspicious")
    concern = sum(1 for w in workers if w.get("status") == "concern")
    total_active = sum(int(w.get("active_minutes") or 0) for w in workers)
    total_ai = sum(int(w.get("ai_minutes") or 0) for w in workers)
    audit_events = _audit_events()
    lic = app_license.get_status() if app_license else {}
    policy = access_policy.get_policy() if access_policy else {}
    return {
        "ok": True,
        "demo": False,
        "sku": lic.get("sku", "personal"),
        "business": bool(lic.get("business_features")),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "validated_at": datetime.now().strftime("%H:%M") if validations else None,
        "stats": {
            "workers": len(workers),
            "safe": safe,
            "suspicious": suspicious,
            "concern": concern,
            "vault_notes": _vault_count(),
            "vault_files": _vault_count(),
            "sessions": len(db.list_sessions(200)) if db else 0,
            "pending_access": len(policy.get("pending") or []),
            "total_active_display": _fmt_minutes(total_active),
            "total_ai_display": _fmt_minutes(total_ai),
        },
        "workers": workers,
        "audit_tail": audit_events[:50],
        "cortex": _cortex_block(),
        "access_policy": {
            "mode": policy.get("mode", "open"),
            "approved": len(policy.get("approved") or []),
            "pending": policy.get("pending") or [],
            "denied": len(policy.get("denied") or []),
        },
        "safety": {
            "emphasis": "Business: IP allowlists, download approval, Cortex harness",
            "personal": "Personal free — local clipboard & WiFi; upgrade for org safety",
        },
    }


def worker_detail(wid: str) -> dict | None:
    for w in _device_workers():
        if w["id"] == wid:
            return w
    return None


def validate_worker(wid: str, status: str = "safe", note: str = "") -> dict:
    state = _load_state()
    state.setdefault("validations", {})[wid] = {
        "status": status if status in ("safe", "suspicious", "concern") else "safe",
        "note": note[:200],
        "at": time.time(),
    }
    _save_state(state)
    return {"ok": True, "id": wid, "status": status}


def validate_all() -> dict:
    state = _load_state()
    vals = state.setdefault("validations", {})
    for w in _device_workers():
        vals.setdefault(w["id"], {"status": "safe", "note": "auto", "at": time.time()})
    _save_state(state)
    return {"ok": True, "count": len(vals)}

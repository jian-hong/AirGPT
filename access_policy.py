"""Business IP / device allowlist for download & guest file access."""
from __future__ import annotations

import json
import time
from pathlib import Path

from config import DATA_DIR

POLICY_FILE = DATA_DIR / "access_policy.json"


def _load() -> dict:
    if not POLICY_FILE.is_file():
        return {"mode": "open", "approved": [], "pending": [], "denied": []}
    try:
        return json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"mode": "open", "approved": [], "pending": [], "denied": []}


def _save(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    POLICY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_policy() -> dict:
    return _load()


def set_mode(mode: str) -> dict:
    data = _load()
    data["mode"] = mode if mode in ("open", "allowlist", "business") else "open"
    _save(data)
    return data


def approve(ip: str, name: str = "") -> dict:
    ip = (ip or "").strip()
    if not ip:
        return {"ok": False, "error": "ip required"}
    data = _load()
    data["pending"] = [p for p in data.get("pending", []) if p.get("ip") != ip]
    data["denied"] = [d for d in data.get("denied", []) if d != ip]
    entries = data.setdefault("approved", [])
    if not any(e.get("ip") == ip for e in entries):
        entries.append({"ip": ip, "name": name[:80], "approved_at": time.time()})
    _save(data)
    return {"ok": True, "policy": data}


def deny(ip: str) -> dict:
    ip = (ip or "").strip()
    data = _load()
    data["approved"] = [e for e in data.get("approved", []) if e.get("ip") != ip]
    data["pending"] = [p for p in data.get("pending", []) if p.get("ip") != ip]
    denied = data.setdefault("denied", [])
    if ip and ip not in denied:
        denied.append(ip)
    _save(data)
    return {"ok": True, "policy": data}


def request_access(ip: str, name: str = "") -> dict:
    ip = (ip or "").strip()
    data = _load()
    if any(e.get("ip") == ip for e in data.get("approved", [])):
        return {"ok": True, "status": "approved"}
    pending = data.setdefault("pending", [])
    if not any(p.get("ip") == ip for p in pending):
        pending.append({"ip": ip, "name": name[:80], "requested_at": time.time()})
        _save(data)
    return {"ok": True, "status": "pending"}


def is_download_allowed(ip: str, *, is_local: bool, business: bool) -> bool:
    """Personal: open. Business allowlist mode: local always, else approved IPs only."""
    if is_local:
        return True
    data = _load()
    mode = data.get("mode", "open")
    if not business or mode == "open":
        return True
    if ip in data.get("denied", []):
        return False
    approved = {e.get("ip") for e in data.get("approved", [])}
    return ip in approved

"""AirGPT Personal (free) + Business (paid) licensing with optional online verify."""
from __future__ import annotations

import json
import time
import urllib.request

from config import API_STARTER_CREDIT_USD, LICENSE_FILE, SUBSCRIPTION_PRICE_USD, TRIAL_DAYS

STRIPE_ENABLED = False
# NEXT UPDATE: fully online Personal AI pay-to-continue — stub only
ONLINE_PERSONAL_PAYWALL_STUB = False


def _load() -> dict:
    if not LICENSE_FILE.is_file():
        return {}
    try:
        return json.loads(LICENSE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LICENSE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def ensure_trial() -> dict:
    data = _load()
    if not data.get("trial_started"):
        data["trial_started"] = time.time()
        data["subscribed"] = False
        data["licensed"] = False
        data["sku"] = "personal"
        data["email"] = data.get("email", "")
        _save(data)
    data.setdefault("sku", "business" if data.get("subscribed") or data.get("licensed") else "personal")
    return data


def _is_business(data: dict) -> bool:
    return bool(data.get("subscribed") or data.get("licensed") or data.get("sku") == "business")


def _verify_online(key: str, email: str = "") -> dict | None:
    """Soft online verify against control-plane (optional)."""
    try:
        from ai_engine import load_env
        base = (load_env().get("AIRGPT_API_BASE") or "").rstrip("/")
        if not base:
            return None
        body = json.dumps({"key": key, "email": email, "sku": "business"}).encode()
        req = urllib.request.Request(
            f"{base}/v1/license/verify",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def get_status() -> dict:
    data = ensure_trial()
    business = _is_business(data)
    netie = {}
    try:
        import netie_id

        netie = netie_id.status()
        # Prefer shared Netie email when local license email empty
        if not data.get("email") and netie.get("email"):
            data["email"] = netie["email"]
            _save(data)
    except Exception:
        pass
    # Personal is free forever for local clipboard / WiFi / BYOK
    return {
        "app": "AirGPT",
        "sku": "business" if business else "personal",
        "subscribed": business,
        "licensed": business,
        "trial_active": False,
        "trial_days_left": 0,
        "trial_expired": False,
        "subscription_price_usd": SUBSCRIPTION_PRICE_USD,
        "license_price_usd": SUBSCRIPTION_PRICE_USD,
        "api_credit_usd": API_STARTER_CREDIT_USD,
        "email": data.get("email", ""),
        "stripe_ready": STRIPE_ENABLED,
        "can_use_ai": True,  # BYOK / local — Personal free
        "can_use_tunnel": True,  # Personal free WiFi+tunnel for connectivity
        "local_only": False,
        "business_features": business,
        "paywall_message": (
            ""
            if business
            else "AirGPT Personal (free). Upgrade to Business for org safety, IP allowlists & admin."
        ),
        # NEXT UPDATE stub
        "online_personal_ai": ONLINE_PERSONAL_PAYWALL_STUB,
        "online_personal_note": "NEXT UPDATE: hosted AI + pay-to-continue tiers",
        "netie_account": {
            "signed_in": bool(netie.get("signed_in")),
            "email": netie.get("email") or data.get("email") or "",
            "products": netie.get("products") or {},
        },
    }


def activate_license(key: str, email: str = "") -> dict:
    key = (key or "").strip()
    if len(key) < 8:
        return {"ok": False, "error": "invalid license key"}
    online = _verify_online(key, email)
    if online is not None and not online.get("ok"):
        return {"ok": False, "error": online.get("error", "license rejected by server")}
    data = ensure_trial()
    data["subscribed"] = True
    data["licensed"] = True
    data["sku"] = "business"
    data["license_key"] = key[:64]
    data["activated_at"] = time.time()
    if email:
        data["email"] = email[:120]
    if online and online.get("org_id"):
        data["org_id"] = online["org_id"]
    data["entitlement_cache"] = {
        "verified_at": time.time(),
        "features": (online or {}).get("features", ["dashboard", "allowlist", "cortex"]),
        "grace_until": time.time() + 72 * 3600,
    }
    _save(data)
    try:
        import netie_id

        netie_id.link_local(
            email=str(data.get("email") or email or ""),
            product="airgpt",
            sku="business",
        )
    except Exception:
        pass
    return {"ok": True, "status": get_status()}


def generate_license_key(email: str = "") -> str:
    import secrets
    parts = [secrets.token_hex(2).upper() for _ in range(4)]
    key = "-".join(parts)
    data = ensure_trial()
    data["subscribed"] = True
    data["licensed"] = True
    data["sku"] = "business"
    data["license_key"] = key
    data["activated_at"] = time.time()
    if email:
        data["email"] = email[:120]
    _save(data)
    return key


def set_email(email: str) -> dict:
    data = ensure_trial()
    data["email"] = (email or "").strip()[:120]
    _save(data)
    try:
        import netie_id

        netie_id.link_local(email=data["email"], product="airgpt", sku=str(data.get("sku") or "personal"))
    except Exception:
        pass
    return {"ok": True, "email": data["email"]}


def heartbeat() -> dict:
    """Call on start when Business — refresh entitlement cache if online."""
    data = ensure_trial()
    if not _is_business(data):
        return {"ok": True, "sku": "personal"}
    key = data.get("license_key", "")
    online = _verify_online(key, data.get("email", "")) if key else None
    if online and online.get("ok"):
        data["entitlement_cache"] = {
            "verified_at": time.time(),
            "features": online.get("features", []),
            "grace_until": time.time() + 72 * 3600,
            "revoked": False,
        }
        _save(data)
        return {"ok": True, "sku": "business", "online": True}
    cache = data.get("entitlement_cache") or {}
    if cache.get("revoked"):
        return {"ok": False, "sku": "business", "error": "revoked"}
    if cache.get("grace_until", 0) > time.time():
        return {"ok": True, "sku": "business", "online": False, "grace": True}
    return {"ok": True, "sku": "business", "online": False, "stale": True}

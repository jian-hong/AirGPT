"""Shared Netie account identity across AirGPT, Netie Space, and netie.ai.

Single local account file under %LOCALAPPDATA%/Netie/account.json so installing
AirGPT (which also ships Netie Space) and signing in once links both apps.

Optional online sync via NETIE_ID_API (defaults to Space license-api base or AIRGPT_API_BASE).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

SCHEMA = 1
PRODUCTS = ("airgpt", "space", "web")


def _local_appdata() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "Netie"


ACCOUNT_FILE = _local_appdata() / "account.json"


def _default() -> dict:
    return {
        "schema": SCHEMA,
        "email": "",
        "session_token": "",
        "products": {p: {"linked": False, "sku": "personal"} for p in PRODUCTS},
        "updated_at": 0.0,
        "source": "",
    }


def load() -> dict:
    if not ACCOUNT_FILE.is_file():
        return _default()
    try:
        data = json.loads(ACCOUNT_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _default()
        out = _default()
        out.update({k: data.get(k, out.get(k)) for k in out})
        products = out.get("products") or {}
        for p in PRODUCTS:
            products.setdefault(p, {"linked": False, "sku": "personal"})
        out["products"] = products
        return out
    except Exception:
        return _default()


def save(data: dict) -> dict:
    ACCOUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data or {})
    data["schema"] = SCHEMA
    data["updated_at"] = time.time()
    ACCOUNT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def status() -> dict:
    data = load()
    return {
        "ok": True,
        "path": str(ACCOUNT_FILE),
        "email": data.get("email") or "",
        "signed_in": bool(data.get("session_token") or data.get("email")),
        "products": data.get("products") or {},
        "updated_at": data.get("updated_at") or 0,
        "api": _api_base(),
    }


def link_local(*, email: str = "", product: str = "airgpt", sku: str = "personal", session_token: str = "") -> dict:
    """Write/merge local Netie identity after AirGPT or Space login/activate."""
    product = (product or "airgpt").lower().strip()
    if product not in PRODUCTS:
        return {"ok": False, "error": f"unknown product {product}"}
    data = load()
    email = (email or data.get("email") or "").strip()[:160]
    if email:
        data["email"] = email
    if session_token:
        data["session_token"] = session_token[:512]
    data["source"] = product
    products = data.setdefault("products", {})
    products[product] = {
        "linked": True,
        "sku": (sku or "personal").lower(),
        "linked_at": time.time(),
    }
    # AirGPT installer also ships Space — mark Space personal-linked when AirGPT links
    if product == "airgpt":
        products.setdefault("space", {"linked": False, "sku": "personal"})
        if not products["space"].get("linked"):
            products["space"] = {
                "linked": True,
                "sku": products["space"].get("sku") or "personal",
                "linked_at": time.time(),
                "via": "airgpt_bundle",
            }
    save(data)
    return {"ok": True, "account": status()}


def clear_session() -> dict:
    data = load()
    data["session_token"] = ""
    for p in PRODUCTS:
        if p in (data.get("products") or {}):
            data["products"][p]["linked"] = False
    save(data)
    return {"ok": True, "account": status()}


def _api_base() -> str:
    for key in ("NETIE_ID_API", "NETIE_LICENSE_API", "AIRGPT_API_BASE"):
        v = (os.environ.get(key) or "").strip().rstrip("/")
        if v:
            return v
    try:
        from config import ENV_FILE

        if ENV_FILE.is_file():
            for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
                if "=" not in line or line.strip().startswith("#"):
                    continue
                k, val = line.split("=", 1)
                if k.strip() in ("NETIE_ID_API", "NETIE_LICENSE_API", "AIRGPT_API_BASE"):
                    return val.strip().rstrip("/")
    except Exception:
        pass
    return ""


def login_online(email: str, password: str) -> dict:
    """POST /v1/login against Netie Space license-api (or compatible control plane)."""
    base = _api_base()
    if not base:
        # Offline: still link email locally so both apps share host identity
        return link_local(email=email, product="airgpt", sku="personal")
    body = json.dumps({"email": email, "password": password}).encode()
    req = urllib.request.Request(
        f"{base}/v1/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            payload = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode())
        except Exception:
            detail = {"error": str(e)}
        return {"ok": False, "error": detail.get("error") or detail.get("message") or str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

    token = str(payload.get("token") or payload.get("session_token") or "")
    sku = str(payload.get("sku") or "personal")
    linked = link_local(email=email, product="airgpt", sku=sku, session_token=token)
    linked["online"] = True
    linked["raw"] = {k: payload.get(k) for k in ("ok", "email", "sku") if k in payload}
    return linked

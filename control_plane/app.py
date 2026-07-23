"""
Light AirGPT Business license control plane.

Run:  uvicorn control_plane.app:app --host 0.0.0.0 --port 8787
Env:  AIRGPT_LICENSE_SECRET (signing), optional STRIPE keys later.

Personal clients do not require this. Business keys verify here when AIRGPT_API_BASE is set.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
except ImportError:
    FastAPI = None  # type: ignore
    BaseModel = object  # type: ignore

ROOT = Path(__file__).resolve().parent
STORE = ROOT / "data" / "licenses.json"
STORE.parent.mkdir(parents=True, exist_ok=True)

if FastAPI:
    app = FastAPI(title="AirGPT Control Plane", version="0.1.0")
else:
    app = None


def _load() -> dict:
    if not STORE.is_file():
        return {"keys": {}, "devices": {}}
    return json.loads(STORE.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")


class VerifyIn(BaseModel):
    key: str = ""
    email: str = ""
    sku: str = "business"
    device_id: str = ""


class RegisterIn(BaseModel):
    device_id: str = ""
    sku: str = "personal"
    fingerprint: str = ""


if app:

    @app.get("/health")
    def health():
        return {"ok": True, "service": "airgpt-control-plane"}

    @app.post("/v1/devices/register")
    def register(body: RegisterIn):
        data = _load()
        did = body.device_id or secrets.token_hex(8)
        data.setdefault("devices", {})[did] = {
            "sku": body.sku,
            "fingerprint": body.fingerprint[:128],
            "registered_at": time.time(),
        }
        _save(data)
        return {"ok": True, "device_id": did}

    @app.post("/v1/license/verify")
    def verify(body: VerifyIn):
        key = (body.key or "").strip()
        if len(key) < 8:
            raise HTTPException(400, "invalid key")
        data = _load()
        rec = data.get("keys", {}).get(key)
        if rec is None:
            # Dev mode: accept any 8+ char key and mint Business entitlement
            rec = {
                "sku": "business",
                "org_id": "org_" + hashlib.sha256(key.encode()).hexdigest()[:10],
                "seats": 5,
                "features": ["dashboard", "allowlist", "cortex"],
                "email": body.email,
                "created_at": time.time(),
            }
            data.setdefault("keys", {})[key] = rec
            _save(data)
        if rec.get("revoked"):
            return {"ok": False, "error": "revoked"}
        return {
            "ok": True,
            "sku": rec.get("sku", "business"),
            "org_id": rec.get("org_id"),
            "seats": rec.get("seats", 5),
            "features": rec.get("features", []),
            "expires": rec.get("expires"),
        }

    @app.post("/v1/org/heartbeat")
    def heartbeat(body: VerifyIn):
        out = verify(body)
        out["ts"] = int(time.time())
        return out

    @app.post("/v1/admin/mint")
    def mint(email: str = "", seats: int = 5):
        secret = os.environ.get("AIRGPT_LICENSE_SECRET", "dev")
        key = "-".join(secrets.token_hex(2).upper() for _ in range(4))
        data = _load()
        data.setdefault("keys", {})[key] = {
            "sku": "business",
            "org_id": "org_" + secrets.token_hex(4),
            "seats": seats,
            "features": ["dashboard", "allowlist", "cortex"],
            "email": email,
            "created_at": time.time(),
            "mint_secret_hash": hashlib.sha256(secret.encode()).hexdigest()[:16],
        }
        _save(data)
        return {"ok": True, "key": key}


# NEXT UPDATE: Stripe Checkout for Personal online AI pay-to-continue — not implemented here.

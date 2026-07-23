"""OpenVault mesh bridge — connect AirGPT OpenIDE to D:\\OpenVault (:5000).

Handshake + connect-pack per OpenVault OpenMW local_mesh protocol.
Keys SoT is OpenVault (/api/keyvault/*, /api/keys*); this module only talks
loopback HTTP. See PRODUCT_ROLES.md.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from config import DATA_DIR, ROOT

OPENVAULT_ROOT = Path(os.environ.get("OPENVAULT_ROOT") or r"D:\OpenVault")
DEFAULT_OV_URL = "http://127.0.0.1:5000"
PACK_CACHE = DATA_DIR / "openvault_connect_pack.json"
LOCAL_CFG_CANDIDATES = (
    OPENVAULT_ROOT / "openvault.local.json",
    ROOT / "openvault.local.json",
    DATA_DIR / "openvault.local.json",
)


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def openvault_url() -> str:
    u = _env("OPENVAULT_URL")
    if u:
        return u.rstrip("/")
    for p in LOCAL_CFG_CANDIDATES:
        if p.is_file():
            try:
                cfg = json.loads(p.read_text(encoding="utf-8"))
                svc = (cfg.get("services") or {}).get("openvault") or {}
                if svc.get("url"):
                    return str(svc["url"]).rstrip("/")
            except Exception:
                pass
    return DEFAULT_OV_URL


def openide_public_url() -> str:
    """URL OpenVault should call back for this OpenIDE (AirGPT host)."""
    return (
        _env("OPENIDE_URL")
        or _env("AIRGPT_PUBLIC_URL")
        or "http://127.0.0.1:8765"
    ).rstrip("/")


def _http_json(method: str, url: str, body: dict | None = None, *, timeout: float = 8.0) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def ping() -> dict[str, Any]:
    base = openvault_url()
    try:
        health = _http_json("GET", f"{base}/api/healthz")
        return {
            "ok": health.get("status") == "ok",
            "openvault_url": base,
            "openvault_root": str(OPENVAULT_ROOT),
            "health": health,
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return {
            "ok": False,
            "openvault_url": base,
            "openvault_root": str(OPENVAULT_ROOT),
            "error": str(e)[:240],
            "hint": "Start OpenVault: powershell -File D:\\OpenVault\\scripts\\windows\\Start-LocalMesh.ps1 -OpenIdeUrl http://127.0.0.1:8765",
        }


def keyvault_snapshot() -> dict[str, Any]:
    """Prefer OpenVault SoT; callers fall back to local catalog if offline."""
    base = openvault_url()
    try:
        snap = _http_json("GET", f"{base}/api/keyvault/snapshot", timeout=5.0)
        snap["ok"] = True
        snap["openvault_url"] = base
        snap["source"] = snap.get("source") or "openvault"
        return snap
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return {"ok": False, "openvault_url": base, "error": str(e)[:240], "source": "offline"}


def keyvault_upsert(
    *,
    env_key: str = "",
    secret: str = "",
    secrets: dict[str, str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Write secrets to OpenVault (SoT). Caller may sync env.local cache."""
    base = openvault_url()
    body: dict[str, Any] = {"env_key": env_key, "secret": secret, **extra}
    if secrets:
        body["secrets"] = secrets
    try:
        return {"ok": True, "openvault_url": base, **_http_json("POST", f"{base}/api/keyvault/upsert", body)}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return {"ok": False, "openvault_url": base, "error": str(e)[:240]}


def gate_check(
    *,
    action: str = "run",
    project_path: str = "",
    destination: str = "",
    required_providers: list[str] | None = None,
) -> dict[str, Any]:
    """Ask OpenVault whether retrieve/run/deploy/leave may proceed."""
    base = openvault_url()
    body = {
        "action": action,
        "project_path": project_path,
        "destination": destination,
        "required_providers": required_providers or [],
    }
    try:
        return {"ok": True, "openvault_url": base, **_http_json("POST", f"{base}/api/gate/check", body)}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return {
            "ok": False,
            "allowed": False,
            "openvault_url": base,
            "error": str(e)[:240],
            "reasons": ["OpenVault offline — gate closed (PRODUCT_ROLES)"],
        }


def mesh() -> dict[str, Any]:
    base = openvault_url()
    try:
        return {"ok": True, "openvault_url": base, **_http_json("GET", f"{base}/api/local/mesh")}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return {"ok": False, "openvault_url": base, "error": str(e)[:240]}


def connect_pack(*, refresh: bool = True) -> dict[str, Any]:
    base = openvault_url()
    try:
        pack = _http_json("GET", f"{base}/api/local/connect-pack")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PACK_CACHE.write_text(json.dumps(pack, indent=2), encoding="utf-8")
        ov_home = OPENVAULT_ROOT / ".openvault"
        try:
            ov_home.mkdir(parents=True, exist_ok=True)
            (ov_home / "connect_pack.json").write_text(json.dumps(pack, indent=2), encoding="utf-8")
        except OSError:
            pass
        return {"ok": True, "pack": pack, "cached": str(PACK_CACHE)}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        if PACK_CACHE.is_file() and not refresh:
            try:
                return {
                    "ok": True,
                    "pack": json.loads(PACK_CACHE.read_text(encoding="utf-8")),
                    "cached": str(PACK_CACHE),
                    "stale": True,
                }
            except Exception:
                pass
        return {"ok": False, "error": str(e)[:240], "openvault_url": base}


def handshake(*, name: str = "AirGPT OpenIDE", auto_approve: bool = True) -> dict[str, Any]:
    """Announce this OpenIDE to OpenVault mesh and pull connect pack."""
    base = openvault_url()
    ide = openide_public_url()
    try:
        _http_json(
            "PUT",
            f"{base}/api/local/mesh/config",
            {
                "auto_approve_loopback": True,
                "openide_url": ide,
            },
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        pass

    try:
        hs = _http_json(
            "POST",
            f"{base}/api/local/handshake",
            {
                "peer_kind": "openide",
                "name": name,
                "base_url": ide,
                "capabilities": [
                    "signin",
                    "passkey",
                    "editor",
                    "scaffold",
                    "keyvault",
                    "airgpt",
                ],
                "auto_approve": auto_approve,
            },
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return {
            "ok": False,
            "error": str(e)[:240],
            "openvault_url": base,
            "openide_url": ide,
            "hint": "OpenVault must be running on :5000 (D:\\OpenVault).",
        }

    pack_body = hs.get("connect_pack") if isinstance(hs.get("connect_pack"), dict) else None
    if not pack_body:
        pack = connect_pack()
        pack_body = pack.get("pack") if pack.get("ok") else None
    if pack_body:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            PACK_CACHE.write_text(json.dumps(pack_body, indent=2), encoding="utf-8")
            ov_home = OPENVAULT_ROOT / ".openvault"
            ov_home.mkdir(parents=True, exist_ok=True)
            (ov_home / "connect_pack.json").write_text(json.dumps(pack_body, indent=2), encoding="utf-8")
        except OSError:
            pass

    status_s = ((hs.get("handshake") or {}).get("status") or "").lower()
    approved = status_s in ("approved", "online") or bool(
        (pack_body or {}).get("openide", {}).get("approved")
    )
    return {
        "ok": approved or status_s == "pending",
        "approved": approved,
        "handshake": hs.get("handshake") or hs,
        "openvault_url": base,
        "openide_url": ide,
        "openvault_root": str(OPENVAULT_ROOT),
        "connect_pack": pack_body,
        "connected_at": time.time(),
    }


def status() -> dict[str, Any]:
    p = ping()
    if not p.get("ok"):
        return {**p, "connected": False}
    pack_body: dict[str, Any] = {}
    if PACK_CACHE.is_file():
        try:
            pack_body = json.loads(PACK_CACHE.read_text(encoding="utf-8"))
        except Exception:
            pack_body = {}
    m = mesh()
    return {
        **p,
        "connected": True,
        "mesh": m if m.get("ok") else {"ok": False},
        "connect_pack": pack_body or None,
        "roles": "PRODUCT_ROLES.md — OpenVault owns keys/gate/deploy; AirGPT is thin shell",
    }


def ensure_local_config() -> dict[str, Any]:
    """Write/refresh openvault.local.json so mesh URLs stay aligned."""
    path = next(
        (p for p in LOCAL_CFG_CANDIDATES if p.parent.is_dir()),
        DATA_DIR / "openvault.local.json",
    )
    if path == DATA_DIR / "openvault.local.json":
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg: dict[str, Any] = {}
    if path.is_file():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    services = dict(cfg.get("services") or {})
    ov = dict(services.get("openvault") or {})
    ov["url"] = openvault_url()
    ov["root"] = str(OPENVAULT_ROOT)
    ov["console"] = (
        "cd OpenMW && uv run openmw console --cortex-url http://127.0.0.1:8000 "
        "--openide-url http://127.0.0.1:8765"
    )
    services["openvault"] = ov
    ide = dict(services.get("openide") or {})
    ide["url"] = openide_public_url()
    ide["announce"] = f"{openvault_url()}/api/local/handshake"
    ide["invoke"] = f"{openvault_url()}/api/openide/invoke"
    ide["connect_pack"] = f"{openvault_url()}/api/local/connect-pack"
    services["openide"] = ide
    cfg["services"] = services

    try:
        path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "path": str(path), "openide_url": ide["url"]}
    except OSError as e:
        alt = DATA_DIR / "openvault.local.json"
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        alt.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "path": str(alt), "warn": str(e)[:160], "openide_url": ide["url"]}

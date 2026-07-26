"""GitHub OAuth Device Flow for AirGPT (host-only).

Default scopes are minimal. Broad repo+org access is an explicit opt-in.
Tokens are written via app_settings into env.local (GH_TOKEN) — never logged.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Minimal: identity + commit status. Broad: full private repo R/W + org read.
GITHUB_SCOPES_MINIMAL = "read:user repo:status"
GITHUB_SCOPES_BROAD = "repo read:org read:user"

DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"


def client_id() -> str:
    return (os.environ.get("GITHUB_CLIENT_ID") or "").strip()


def scopes_for(*, broad: bool = False) -> str:
    return GITHUB_SCOPES_BROAD if broad else GITHUB_SCOPES_MINIMAL


def _post_form(url: str, data: dict[str, str], *, accept_json: bool = True) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json" if accept_json else "application/x-www-form-urlencoded",
        "User-Agent": "AirGPT-GitHubAuth/1.0",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except Exception:
        return dict(urllib.parse.parse_qsl(raw))


def _get_json(url: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "AirGPT-GitHubAuth/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def start_device_flow(*, broad: bool = False) -> dict[str, Any]:
    cid = client_id()
    if not cid:
        return {
            "ok": False,
            "error": "GITHUB_CLIENT_ID unset — add it to env.local (OAuth App client id)",
        }
    scope = scopes_for(broad=broad)
    try:
        data = _post_form(
            DEVICE_CODE_URL,
            {"client_id": cid, "scope": scope},
        )
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"GitHub device start failed ({e.code})"}
    except Exception as e:
        return {"ok": False, "error": f"GitHub device start failed: {str(e)[:120]}"}
    if data.get("error"):
        return {"ok": False, "error": str(data.get("error_description") or data.get("error"))[:200]}
    if not data.get("device_code") or not data.get("user_code"):
        return {"ok": False, "error": "GitHub did not return a device code"}
    return {
        "ok": True,
        "device_code": data["device_code"],
        "user_code": data["user_code"],
        "verification_uri": data.get("verification_uri") or "https://github.com/login/device",
        "expires_in": int(data.get("expires_in") or 900),
        "interval": int(data.get("interval") or 5),
        "scope": scope,
        "broad": bool(broad),
    }


def poll_device_flow(device_code: str) -> dict[str, Any]:
    cid = client_id()
    if not cid:
        return {"ok": False, "error": "GITHUB_CLIENT_ID unset"}
    code = (device_code or "").strip()
    if not code:
        return {"ok": False, "error": "device_code required"}
    try:
        data = _post_form(
            ACCESS_TOKEN_URL,
            {
                "client_id": cid,
                "device_code": code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
    except Exception as e:
        return {"ok": False, "pending": True, "error": str(e)[:120]}
    err = str(data.get("error") or "")
    if err == "authorization_pending":
        return {"ok": False, "pending": True}
    if err == "slow_down":
        return {"ok": False, "pending": True, "slow_down": True}
    if err == "expired_token":
        return {"ok": False, "error": "device code expired — start again"}
    if err == "access_denied":
        return {"ok": False, "error": "authorization denied"}
    if err:
        return {"ok": False, "error": str(data.get("error_description") or err)[:200]}
    token = str(data.get("access_token") or "").strip()
    if not token:
        return {"ok": False, "pending": True}
    scope = str(data.get("scope") or "")
    # Never include the raw token in the return payload for logging safety —
    # caller persists it then drops it.
    return {
        "ok": True,
        "access_token": token,
        "scope": scope,
        "token_type": str(data.get("token_type") or "bearer"),
    }


def stored_token() -> str:
    return (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()


def status() -> dict[str, Any]:
    token = stored_token()
    if not token:
        return {"ok": True, "connected": False, "login": None, "scopes": None}
    try:
        user = _get_json(USER_URL, token)
        login = user.get("login")
        return {
            "ok": True,
            "connected": bool(login),
            "login": login,
            "scopes": None,  # GitHub may omit X-OAuth-Scopes on this call
            "name": user.get("name"),
        }
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"ok": True, "connected": False, "login": None, "error": "token invalid or revoked"}
        return {"ok": False, "connected": False, "error": f"GitHub status failed ({e.code})"}
    except Exception as e:
        return {"ok": False, "connected": False, "error": str(e)[:120]}


def persist_token(token: str, app_settings: Any) -> dict[str, Any]:
    """Write GH_TOKEN via settings helper; reload env for this process."""
    tok = (token or "").strip()
    if not tok:
        return {"ok": False, "error": "empty token"}
    if app_settings is None:
        return {"ok": False, "error": "settings unavailable"}
    try:
        app_settings.update_settings({"GH_TOKEN": tok})
    except Exception as e:
        return {"ok": False, "error": f"persist failed: {str(e)[:120]}"}
    os.environ["GH_TOKEN"] = tok
    return {"ok": True}


def clear_token(app_settings: Any) -> dict[str, Any]:
    if app_settings is None:
        return {"ok": False, "error": "settings unavailable"}
    try:
        app_settings.update_settings({"GH_TOKEN": ""})
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}
    os.environ.pop("GH_TOKEN", None)
    os.environ.pop("GITHUB_TOKEN", None)
    return {"ok": True}

"""Local settings & API keys — secrets SoT is OpenVault; env.local is offline cache.

See PRODUCT_ROLES.md. Non-secret prefs (AI_AUTO) stay local.
"""
from __future__ import annotations

import re

from config import ENV_FILE, USER_SECRET_KEYS


def _parse_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_FILE.is_file():
        return env
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def _mask(val: str) -> str:
    if not val:
        return ""
    if len(val) <= 8:
        return "••••"
    return val[:4] + "…" + val[-4:]


def get_secret_keys_local() -> dict:
    """Return actual keys for host PC settings UI only (local cache)."""
    env = _parse_env()
    return {k: env.get(k, "") for k in USER_SECRET_KEYS if env.get(k)}


def get_public_settings() -> dict:
    env = _parse_env()
    keys = {k: _mask(env.get(k, "")) for k in USER_SECRET_KEYS if env.get(k)}
    custody = "local_cache"
    try:
        import openvault_bridge

        if openvault_bridge.ping().get("ok"):
            custody = "openvault"
    except Exception:
        pass
    return {
        "ai_auto": env.get("AI_AUTO", "1") in ("1", "true", "yes"),
        "keys_configured": keys,
        "has_any_key": bool(keys),
        "storage": custody,
        "env_path": str(ENV_FILE),
        "keys_sot": "openvault",
    }


def update_settings(updates: dict) -> dict:
    env = _parse_env()
    lines: list[str] = []
    if ENV_FILE.is_file():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()

    def set_key(k: str, v: str) -> None:
        env[k] = v
        pat = re.compile(rf"^{re.escape(k)}=")
        replaced = False
        for i, line in enumerate(lines):
            if pat.match(line.strip()):
                lines[i] = f"{k}={v}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{k}={v}")

    if "ai_auto" in updates:
        set_key("AI_AUTO", "1" if updates["ai_auto"] else "0")

    secret_batch: dict[str, str] = {}
    for k in USER_SECRET_KEYS:
        if k in updates and updates[k]:
            val = str(updates[k]).strip()
            if val and "…" not in val and not val.startswith("••"):
                secret_batch[k] = val
                set_key(k, val)  # offline cache for ai_engine

    ov_result: dict | None = None
    if secret_batch:
        try:
            import openvault_bridge

            ov_result = openvault_bridge.keyvault_upsert(secrets=secret_batch)
        except Exception as e:
            ov_result = {"ok": False, "error": str(e)[:200]}

    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    receipt = ENV_FILE.parent / "data" / "last_save.txt"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime

    receipt.write_text(
        f"Settings saved at {datetime.now().isoformat()}\n"
        f"File: {ENV_FILE.resolve()}\n"
        f"OpenVault: {(ov_result or {}).get('ok')}\n",
        encoding="utf-8",
    )
    out = {
        **get_public_settings(),
        "saved_to": str(ENV_FILE.resolve()),
        "receipt": str(receipt.resolve()),
        "openvault": ov_result,
    }
    if secret_batch and ov_result and not ov_result.get("ok"):
        out["warn"] = (
            "OpenVault offline — secrets cached in env.local only. "
            "Start OpenVault console (:5000) so custody is SoT."
        )
    return out

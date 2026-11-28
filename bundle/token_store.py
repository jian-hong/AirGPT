"""Local service token for the Netie bundle.

Stored in the OS keychain when that works, and always in a mode 0600 file
so DMS and OpenVault can read the same value. The token is never printed.
"""
from __future__ import annotations

import os
import secrets
import stat
import subprocess
from pathlib import Path

SERVICE = "netie-bundle"
USERNAME = "service-token"


def home_dir() -> Path:
    raw = (os.environ.get("NETIE_HOME") or "").strip()
    if raw:
        return Path(raw)
    return Path.home() / ".config" / "netie"


def token_path() -> Path:
    raw = (os.environ.get("NETIE_TOKEN_FILE") or "").strip()
    if raw:
        return Path(raw)
    return home_dir() / "service-token"


def _file_only() -> bool:
    return (os.environ.get("NETIE_TOKEN_STORE") or "").strip().lower() == "file"


def _keyring_get() -> str:
    if _file_only():
        return ""
    try:
        import keyring
    except Exception:
        return ""
    try:
        value = keyring.get_password(SERVICE, USERNAME)
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


def _keyring_set(token: str) -> bool:
    if _file_only():
        return False
    try:
        import keyring
    except Exception:
        return False
    try:
        keyring.set_password(SERVICE, USERNAME, token)
        got = keyring.get_password(SERVICE, USERNAME)
    except Exception:
        return False
    return got == token


def _tighten_windows(path: Path) -> None:
    user = os.environ.get("USERNAME") or ""
    if not user:
        return
    try:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(R,W)"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return


def write_file(token: str, path: Path | None = None) -> Path:
    dest = path or token_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(dest.parent, 0o700)
    fd = os.open(str(dest), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, token.encode("utf-8") + b"\n")
    finally:
        os.close(fd)
    if os.name != "nt":
        os.chmod(dest, 0o600)
    else:
        _tighten_windows(dest)
    return dest


def read_file(path: Path | None = None) -> str:
    dest = path or token_path()
    if not dest.is_file():
        return ""
    return dest.read_text(encoding="utf-8").strip()


def load_token() -> str:
    cached = _keyring_get()
    if cached:
        return cached
    return read_file()


def file_mode(path: Path | None = None) -> int | None:
    dest = path or token_path()
    if not dest.is_file():
        return None
    return stat.S_IMODE(dest.stat().st_mode)


def describe() -> dict:
    """Where the token lives. Never includes the token."""
    if _keyring_get():
        path = token_path()
        return {
            "stored": True,
            "where": "keyring",
            "path": str(path) if path.is_file() else "",
        }
    path = token_path()
    if path.is_file() and read_file(path):
        return {"stored": True, "where": "file", "path": str(path)}
    return {"stored": False, "where": "", "path": ""}


def ensure() -> dict:
    """Create the token once. Return the store location, not the token."""
    current = describe()
    if current["stored"]:
        if current["where"] == "keyring" and not token_path().is_file():
            secret = _keyring_get()
            if secret:
                write_file(secret)
                current = describe()
        return current
    secret = secrets.token_urlsafe(32)
    where = "file"
    if _keyring_set(secret):
        where = "keyring"
    path = write_file(secret)
    return {"stored": True, "where": where, "path": str(path)}

"""OpenFree sidecar control — start/status for AirGPT's bundled free gateway.

OpenFree = AirGPT's branding for the OmniRoute OpenAI-compatible free-tier gateway
(github.com/diegosouzapw/OmniRoute, MIT). This module launches it via
scripts/start_openfree.ps1 and reports live status; ai_engine routes to
OMNIROUTE_BASE_URL (127.0.0.1:20128/v1) once it is up.

Non-blocking: enable() kicks off a detached installer/launcher (first run pulls
~739 MB once) and returns immediately; the UI polls status().
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from config import DATA_DIR, ROOT

PORT = 20128
BASE_URL = f"http://127.0.0.1:{PORT}/v1"
_SCRIPT = ROOT / "scripts" / "start_openfree.ps1"
_STATE = DATA_DIR / "openfree" / "state.json"


def _port_open(timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=timeout):
            return True
    except OSError:
        return False


def _shell() -> str | None:
    """The PowerShell that can run the launcher here: Windows PowerShell on Windows,
    PowerShell 7 (pwsh) anywhere it is installed, otherwise None."""
    if sys.platform == "win32":
        return shutil.which("powershell") or shutil.which("pwsh") or "powershell"
    return shutil.which("pwsh")


def cannot_run() -> str:
    """Why OpenFree cannot start on this computer, in plain words; empty when it can."""
    if _shell() is None:
        return "OpenFree only runs on Windows for now. Paste an API key instead."
    if not _SCRIPT.is_file():
        return "OpenFree is not part of this copy of AirGPT. Paste an API key instead."
    return ""


def _read_state() -> dict:
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def status() -> dict:
    """Live status: {up, phase, msg}. phase ∈ installing|starting|up|error|idle."""
    up = _port_open()
    st = _read_state()
    phase = "up" if up else (st.get("phase") or "idle")
    return {
        "ok": True,
        "up": up,
        "phase": phase,
        "msg": st.get("msg", "OpenFree not started" if phase == "idle" else ""),
        "base_url": BASE_URL,
        "brand": "OpenFree",
        "can_run": up or not cannot_run(),
        "why": "" if up else cannot_run(),
    }


def enable() -> dict:
    """Launch the gateway in the background (detached). Idempotent if already up."""
    if _port_open():
        return {"ok": True, "up": True, "phase": "up", "msg": "OpenFree already running"}
    why = cannot_run()
    if why:
        return {"ok": False, "unsupported": True, "error": why}
    creationflags = 0
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP — survives the request thread.
        creationflags = 0x00000008 | 0x00000200
    try:
        subprocess.Popen(
            [_shell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(_SCRIPT)],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "OpenFree could not be started. Paste an API key instead.", "detail": str(e)[:200]}
    return {"ok": True, "up": False, "phase": "installing",
            "msg": "Starting OpenFree — first run downloads ~739 MB once", "base_url": BASE_URL}

"""OS reveal / open-containing-folder for RAG citation paths (Windows-first)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def reveal_path(path: str) -> dict:
    """Open Explorer with the file selected (or folder if directory)."""
    raw = (path or "").strip()
    if not raw:
        return {"ok": False, "error": "path required"}
    p = Path(raw).expanduser()
    try:
        p = p.resolve()
    except Exception:
        return {"ok": False, "error": "unresolvable path"}
    if not p.exists():
        return {"ok": False, "error": f"not found: {p}"}

    if os.name == "nt":
        target = str(p)
        try:
            # /select, must not have space after comma
            subprocess.Popen(["explorer", f"/select,{target}"])
            return {"ok": True, "path": target, "action": "explorer_select"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    # graceful non-Windows
    folder = str(p if p.is_dir() else p.parent)
    try:
        if sys_platform_open(folder):
            return {"ok": True, "path": folder, "action": "xdg_or_open"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": False, "error": "reveal unsupported on this OS"}


def sys_platform_open(folder: str) -> bool:
    import sys

    if sys.platform == "darwin":
        subprocess.Popen(["open", folder])
        return True
    subprocess.Popen(["xdg-open", folder])
    return True

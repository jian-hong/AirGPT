"""OS reveal / open-containing-folder for RAG citation paths (Windows-first)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _is_absolute_fs(path: str) -> bool:
    p = (path or "").strip()
    if not p or p.startswith(("http://", "https://")):
        return False
    if p.startswith("\\\\") or p.startswith("/"):
        return True
    return len(p) >= 3 and p[1] == ":" and p[2] in "\\/"


def reveal_best(candidates) -> dict:
    """Try absolute existing paths first, then any remaining candidate."""
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in candidates or []:
        p = str(raw or "").strip()
        if not p or p in seen:
            continue
        seen.add(p)
        ordered.append(p)
    abs_first = [p for p in ordered if _is_absolute_fs(p)]
    rest = [p for p in ordered if p not in abs_first]
    last = {"ok": False, "error": "path required"}
    for p in abs_first + rest:
        last = reveal_path(p)
        if last.get("ok"):
            return last
    return last


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
        if len(p.parts) == 1 or (os.name == "nt" and ":" not in raw and not raw.startswith("\\\\")):
            return {
                "ok": False,
                "error": (
                    f"not found: {p} (basename-only — need absolute path like "
                    r"D:\AirGPT\tests\RAG\warehouse\file.xlsx)"
                ),
            }
        return {"ok": False, "error": f"not found: {p}"}

    if os.name == "nt":
        target = str(p)
        folder = str(p if p.is_dir() else p.parent)
        errors: list[str] = []
        # 1) ShellExecuteW — most reliable from services / elevated hosts
        try:
            import ctypes

            rc = ctypes.windll.shell32.ShellExecuteW(
                None,
                "open",
                "explorer.exe",
                f'/select,"{target}"',
                None,
                1,  # SW_SHOWNORMAL
            )
            if int(rc) > 32:
                return {"ok": True, "path": target, "action": "shell_execute_select"}
            errors.append(f"ShellExecute={rc}")
        except Exception as e:
            errors.append(f"ShellExecute:{e}"[:80])

        # 2) Classic explorer /select,
        try:
            subprocess.Popen(
                ["explorer.exe", f"/select,{target}"],
                shell=False,
                close_fds=True,
            )
            return {"ok": True, "path": target, "action": "explorer_select"}
        except Exception as e:
            errors.append(f"explorer:{e}"[:80])

        # 3) Open parent folder (always visible even if select fails)
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
            return {
                "ok": True,
                "path": folder,
                "action": "startfile_folder",
                "note": "opened folder (select failed: " + "; ".join(errors) + ")",
            }
        except Exception as e:
            errors.append(f"startfile:{e}"[:80])
            return {"ok": False, "error": "; ".join(errors)[:240]}

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

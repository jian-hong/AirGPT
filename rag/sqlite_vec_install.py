"""Optional sqlite-vec install helper for AirGPT dense RAG.

Usage:
  python -m rag.sqlite_vec_install
  python -m rag.sqlite_vec_install --check

Never a hard dependency — vectors.py falls back to blob+cosine automatically.
"""
from __future__ import annotations

import argparse
import subprocess
import sys


def check() -> dict:
    info = {"installed": False, "import_ok": False, "hint": ""}
    try:
        import sqlite_vec  # type: ignore  # noqa: F401

        info["installed"] = True
        info["import_ok"] = True
        info["module"] = getattr(sqlite_vec, "__file__", "sqlite_vec")
    except Exception as exc:
        info["error"] = str(exc)[:200]
        info["hint"] = (
            "Install optional dense index: "
            f"{sys.executable} -m pip install sqlite-vec"
        )
    return info


def install() -> dict:
    cmd = [sys.executable, "-m", "pip", "install", "sqlite-vec"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        out = {"ok": r.returncode == 0, "cmd": cmd, "stdout": (r.stdout or "")[-500], "stderr": (r.stderr or "")[-500]}
    except Exception as exc:
        out = {"ok": False, "error": str(exc)[:200], "cmd": cmd}
    out["check"] = check()
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Optional sqlite-vec for AirGPT RAG")
    p.add_argument("--check", action="store_true", help="report status only")
    p.add_argument("--install", action="store_true", help="pip install sqlite-vec")
    args = p.parse_args(argv)
    if args.install:
        result = install()
        print(result)
        return 0 if result.get("ok") else 1
    result = check()
    print(result)
    # Always exit 0 on --check — missing package is expected fallback mode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

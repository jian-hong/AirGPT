"""Durable crash breadcrumbs for AirGPT.

`start.bat` runs `python clipdrop.py` with stderr going to a console window that
disappears the moment the process dies, so a real crash leaves no evidence behind —
which is why "the backend crashed under rate limit" was never diagnosable. This module
installs the three hooks Python offers for uncaught failures (main thread, worker
threads, unraisable destructors) and appends them to `data/crash.log`, plus `note()`
for structured breadcrumbs (provider 429s, autospawns, clean shutdowns).

Everything here is best-effort: logging must never be the thing that takes the app down.
"""
from __future__ import annotations

import atexit
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from config import DATA_DIR

MAX_BYTES = 2 * 1024 * 1024
_lock = threading.Lock()
_installed = False


def log_path() -> Path:
    return DATA_DIR / "crash.log"


def _rotate(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > MAX_BYTES:
            old = path.with_suffix(".log.1")
            if old.exists():
                old.unlink()
            path.rename(old)
    except OSError:
        pass


def _write(kind: str, payload: dict[str, Any], detail: str = "") -> None:
    line = {
        "ts": round(time.time(), 3),
        "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pid": os.getpid(),
        "kind": kind,
        **payload,
    }
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = log_path()
        with _lock:
            _rotate(path)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
                if detail:
                    fh.write(detail.rstrip() + "\n")
    except Exception:
        pass


def note(event: str, **fields: Any) -> None:
    """Structured breadcrumb — cheap enough to call on every provider failure."""
    _write("note", {"event": event, **fields})


def exception(event: str, exc: BaseException, **fields: Any) -> None:
    """Record a caught-but-notable exception with its traceback."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    _write("error", {"event": event, "error": f"{type(exc).__name__}: {exc}"[:400], **fields}, tb)


def install(app: str = "airgpt") -> None:
    """Route uncaught main-thread / worker-thread / unraisable errors to crash.log."""
    global _installed
    if _installed:
        return
    _installed = True

    prev_hook = sys.excepthook

    def _main_hook(exc_type, exc, tb):
        _write(
            "crash",
            {"app": app, "thread": "MainThread", "error": f"{exc_type.__name__}: {exc}"[:400]},
            "".join(traceback.format_exception(exc_type, exc, tb)),
        )
        prev_hook(exc_type, exc, tb)

    def _thread_hook(args):
        if args.exc_type is SystemExit:
            return
        name = getattr(args.thread, "name", "?")
        _write(
            "thread-crash",
            {"app": app, "thread": name, "error": f"{args.exc_type.__name__}: {args.exc_value}"[:400]},
            "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
        )
        # A dead worker (clipboard/screenshot/tunnel loop) is silent otherwise
        print(f"[crash] thread {name} died: {args.exc_type.__name__}: {args.exc_value}", file=sys.stderr)

    def _unraisable_hook(args):
        _write(
            "unraisable",
            {"app": app, "error": f"{getattr(args.exc_type, '__name__', args.exc_type)}: {args.exc_value}"[:400],
             "object": repr(getattr(args, "object", None))[:200]},
        )

    sys.excepthook = _main_hook
    threading.excepthook = _thread_hook
    sys.unraisablehook = _unraisable_hook
    atexit.register(lambda: _write("exit", {"app": app}))
    note("start", app=app, python=sys.version.split()[0], data_dir=str(DATA_DIR))


def tail(limit: int = 50) -> list[dict[str, Any]]:
    """Recent structured entries, newest last — used by /api/health diagnostics."""
    path = log_path()
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh.read().splitlines():
                if raw.startswith("{"):
                    try:
                        out.append(json.loads(raw))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return []
    return out[-limit:]

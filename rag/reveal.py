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


def resolve_source_path(src: dict) -> tuple[str | None, str]:
    """Best real, openable path for an ingested source row, and where it came from.

    A source row carries three path-ish things and only some of them are openable:
    ``meta.docs_path`` is the byte-faithful original kept under the space's ``Docs/``
    (RAG-BENCH-09 #20 - preferred once it lands), ``path`` is the host file as it was
    at ingest time, and ``meta.blob`` is the extracted ``.txt`` we embedded. The card
    in the UI may only know a basename, so resolution happens here rather than
    trusting whatever the client posts back.

    Returns ``(path, origin)``; ``path`` is None when nothing on disk still exists.
    """
    meta = src.get("meta") or {}
    if isinstance(meta, str):
        import json as _json

        try:
            meta = _json.loads(meta)
        except Exception:
            meta = {}

    for origin, raw in (
        ("docs", meta.get("docs_path")),
        ("host", src.get("path")),
        ("blob", meta.get("blob")),
    ):
        cand = str(raw or "").strip()
        if not cand:
            continue
        # A bare basename is not an openable path - ingest stores meta.original_path
        # as a basename, and reveal must never guess a directory for it.
        p = Path(cand).expanduser()
        if not p.is_absolute():
            continue
        try:
            if p.exists():
                return str(p), origin
        except OSError:
            continue
    return None, "none"


def reveal_source(src: dict) -> dict:
    """Reveal an ingested source, failing closed with the reason when it cannot."""
    target, origin = resolve_source_path(src)
    if not target:
        return {
            "ok": False,
            "error": "No file on disk for this source - it may have been moved or deleted since ingest.",
        }
    out = reveal_path(target)
    out["origin"] = origin
    return out


def sys_platform_open(folder: str) -> bool:
    import sys

    if sys.platform == "darwin":
        subprocess.Popen(["open", folder])
        return True
    subprocess.Popen(["xdg-open", folder])
    return True

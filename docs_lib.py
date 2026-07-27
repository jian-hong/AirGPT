"""In-app docs library — safe reads under AirGPT/docs for Netie Docs viewer."""
from __future__ import annotations

import re
from pathlib import Path

from config import ROOT

DOCS_DIR = Path(ROOT) / "docs"
_CANVAS_FENCE = re.compile(r"```canvas\s*\r?\n([\s\S]*?)```", re.I)


def _safe_rel(rel: str) -> Path | None:
    rel = (rel or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/") or rel.startswith("/"):
        return None
    if not rel.lower().endswith((".md", ".markdown", ".txt")):
        return None
    target = (DOCS_DIR / rel).resolve()
    try:
        target.relative_to(DOCS_DIR.resolve())
    except ValueError:
        return None
    return target if target.is_file() else None


def has_canvas(md: str) -> bool:
    m = _CANVAS_FENCE.search(md or "")
    if not m:
        return False
    body = (m.group(1) or "").strip()
    if not body.startswith("{"):
        return False
    try:
        import json

        json.loads(body)
        return True
    except Exception:
        return False


def title_from_md(md: str, fallback: str) -> str:
    for line in (md or "").splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()[:120] or fallback
    return fallback


def list_docs(*, limit: int = 80) -> dict:
    if not DOCS_DIR.is_dir():
        return {"ok": True, "docs": [], "root": str(DOCS_DIR)}
    rows: list[dict] = []
    for p in sorted(DOCS_DIR.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".md", ".markdown", ".txt"):
            continue
        if p.name.startswith("."):
            continue
        rel = p.relative_to(DOCS_DIR).as_posix()
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rows.append(
            {
                "id": rel,
                "path": rel,
                "title": title_from_md(text, p.stem),
                "has_canvas": has_canvas(text),
                "bytes": p.stat().st_size,
            }
        )
        if len(rows) >= limit:
            break
    return {"ok": True, "docs": rows, "root": str(DOCS_DIR)}


def read_doc(rel: str) -> dict:
    path = _safe_rel(rel)
    if not path:
        return {"ok": False, "error": "doc not found"}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}
    return {
        "ok": True,
        "path": path.relative_to(DOCS_DIR).as_posix(),
        "title": title_from_md(text, path.stem),
        "markdown": text,
        "has_canvas": has_canvas(text),
    }

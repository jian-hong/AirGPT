"""OpenResearch library — local arXiv-style drafts, papers, sources.

Lightweight folder control under data/research/. No heavy vector index.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from config import DATA_DIR

RESEARCH = DATA_DIR / "research"
PAPERS = RESEARCH / "papers"
DRAFTS = RESEARCH / "drafts"
FIGURES = RESEARCH / "figures"
SOURCES = RESEARCH / "sources"

_SLOP = [
    (re.compile(r"[—–―]+"), "-"),
    (re.compile(r"\bdelve into\b", re.I), "examine"),
    (re.compile(r"\blandscape of\b", re.I), "field of"),
    (re.compile(r"\brobust\b", re.I), "solid"),
    (re.compile(r"\bleverage\b", re.I), "use"),
    (re.compile(r"\bcutting-edge\b", re.I), "recent"),
    (re.compile(r"[✨🔥🚀💡⭐️]+"), ""),
]


def ensure() -> None:
    for d in (PAPERS, DRAFTS, FIGURES, SOURCES):
        d.mkdir(parents=True, exist_ok=True)


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (s or "note").lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return (s[:48] or "note")


def clean_prose(text: str) -> str:
    out = text or ""
    for pat, rep in _SLOP:
        out = pat.sub(rep, out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def arxiv_skeleton(title: str, body: str = "", *, abstract: str = "") -> str:
    title = (title or "Untitled").strip()
    abs_ = (abstract or body[:400] or "TBD").strip()
    return clean_prose(
        f"""# {title}

**arXiv-style draft** · {datetime.now().strftime("%Y-%m-%d")}

## Abstract
{abs_}

## 1. Introduction
{body[:800] if body else "State the problem and why it matters."}

## 2. Related Work
Cite prior art. Prefer primary sources.

## 3. Method
Describe the approach in clear steps.

## 4. Results
Report findings with numbers where possible.

## 5. Discussion
Limits, risks, and next experiments.

## References
1. Author. Title. Venue/Year. URL.
"""
    )


def save_draft(title: str, markdown: str, *, category: str = "general") -> dict:
    ensure()
    cat = _slug(category)
    folder = DRAFTS / cat
    folder.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = folder / f"{ts}-{_slug(title)}.md"
    text = clean_prose(markdown or arxiv_skeleton(title))
    path.write_text(text, encoding="utf-8")
    try:
        import vault as vault_mod

        vault_mod.write_drawer(
            project="research",
            title=title,
            body=text[:2000],
            room=cat,
            source="openresearch",
        )
    except Exception:
        pass
    return {"ok": True, "path": str(path).replace("\\", "/"), "category": cat}


def ingest_upload(filename: str, data: bytes, *, category: str = "papers") -> dict:
    ensure()
    cat = _slug(category)
    folder = PAPERS / cat
    folder.mkdir(parents=True, exist_ok=True)
    safe = _slug(Path(filename or "upload").stem) + Path(filename or ".bin").suffix[:8]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = folder / f"{ts}-{safe}"
    path.write_bytes(data)
    meta = {
        "ts": time.time(),
        "name": filename,
        "path": str(path).replace("\\", "/"),
        "category": cat,
        "bytes": len(data),
        "review": "pending",
    }
    meta_path = SOURCES / f"{ts}-{_slug(filename)}.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"ok": True, **meta}


def list_library(limit: int = 80) -> dict:
    ensure()
    drafts, papers, sources = [], [], []
    for p in sorted(DRAFTS.rglob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        drafts.append(
            {
                "name": p.name,
                "path": str(p).replace("\\", "/"),
                "category": p.parent.name,
                "mtime": p.stat().st_mtime,
            }
        )
    for p in sorted(PAPERS.rglob("*"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        if p.is_file():
            papers.append(
                {
                    "name": p.name,
                    "path": str(p).replace("\\", "/"),
                    "category": p.parent.name,
                    "mtime": p.stat().st_mtime,
                    "bytes": p.stat().st_size,
                }
            )
    for p in sorted(SOURCES.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            sources.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            sources.append({"path": str(p).replace("\\", "/")})
    return {"ok": True, "drafts": drafts, "papers": papers, "sources": sources, "root": str(RESEARCH).replace("\\", "/")}


def certify_source(path_or_name: str, *, note: str = "") -> dict:
    ensure()
    target = None
    for p in SOURCES.glob("*.json"):
        if path_or_name in p.name or path_or_name in p.read_text(encoding="utf-8", errors="ignore"):
            target = p
            break
    if not target:
        return {"ok": False, "error": "source not found"}
    data = json.loads(target.read_text(encoding="utf-8"))
    data["review"] = "certified"
    data["certified_at"] = time.time()
    data["note"] = (note or "")[:200]
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"ok": True, "source": data}


def seed_agents() -> dict:
    """Ensure OpenResearch and OpenVertex agents exist."""
    try:
        import agent_store

        agent_store.init()
        existing = {a.get("name") for a in agent_store.list_agents(50)}
        created = []
        if "OpenResearch" not in existing:
            pack = "idea-to-paper"
            try:
                import invoke_registry

                if not invoke_registry.load_skill("idea-to-paper"):
                    pack = "research"
            except Exception:
                pack = "research"
            a = agent_store.create_agent(
                "OpenResearch",
                kind="research",
                skill_pack=pack,
                tools=["web_search", "vault_read", "vault_write", "audit_append", "session_summarize"],
                config={"format": "arxiv", "anti_slop": True, "apa_check": True, "surface": "research", "pipeline": "idea_to_paper", "brain": "cortex"},
                pinned=True,
            )
            created.append(a.get("id"))
        if "OpenVertex" not in existing:
            a = agent_store.create_agent(
                "OpenVertex",
                kind="routing",
                skill_pack="research",
                tools=["vault_read", "vault_write", "audit_append"],
                config={"dual_brain": True, "verify": True, "surface": "research"},
                pinned=True,
            )
            created.append(a.get("id"))
        try:
            from rag.agents import seed_rag_agents

            rag_seed = seed_rag_agents()
            if rag_seed.get("created"):
                created.extend(rag_seed["created"])
        except Exception:
            pass
        return {"ok": True, "created": created}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}

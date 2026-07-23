"""Obsidian-style vault folders for categorized capture sessions.

MemPalace-inspired project wings: verbatim drawers under
`data/vault/{project}/rooms/{topic}/` (or AIRGPT_DATA_DIR/vault when overridden).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from config import DATA_DIR, ROOT

VAULT = DATA_DIR / "vault"


def slugify(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (name or "uncategorized").lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return (s[:56] or "uncategorized")


def wing_room_dir(project: str, room: str = "general") -> Path:
    """Return (and create) a project wing room directory for drawers."""
    p = VAULT / slugify(project) / "rooms" / slugify(room or "general")
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_drawer(
    *,
    project: str,
    title: str,
    body: str,
    room: str = "general",
    source: str = "cortex",
) -> str:
    """Write a verbatim memory drawer. Returns path relative to data/."""
    folder = wing_room_dir(project, room)
    now = datetime.now()
    fname = f"{now.strftime('%Y%m%d_%H%M%S')}-{slugify(title)[:36]}.md"
    path = folder / fname
    fm = (
        f"---\n"
        f"project: {project}\n"
        f"room: {room}\n"
        f"source: {source}\n"
        f"created: {now.strftime('%Y-%m-%d %H:%M')}\n"
        f"---\n\n"
    )
    path.write_text(fm + f"# {title}\n\n{(body or '').strip()}\n", encoding="utf-8")
    return str(path.relative_to(DATA_DIR)).replace("\\", "/")


def search_wings(query: str, project: str = "", k: int = 5) -> list[dict]:
    """Keyword search over wing drawers (verbatim). Prefer project scope when set."""
    if not query or len(query) < 2 or not VAULT.is_dir():
        return []
    terms = [t.lower() for t in re.findall(r"[a-zA-Z0-9_]{3,}", query)[:12]]
    if not terms:
        return []
    roots: list[Path] = []
    if project:
        pdir = VAULT / slugify(project)
        if pdir.is_dir():
            roots.append(pdir)
    if not roots:
        roots = [VAULT]
    hits: list[tuple[int, dict]] = []
    for base in roots:
        for path in base.rglob("*.md"):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            low = text.lower()
            score = sum(2 if t in low else 0 for t in terms)
            rel = str(path).replace("\\", "/")
            if "/rooms/" in rel:
                score += 2
            if project and slugify(project) in rel.lower():
                score += 3
            if score:
                hits.append(
                    (
                        score,
                        {
                            "path": str(path.relative_to(DATA_DIR)).replace("\\", "/"),
                            "name": path.name,
                            "excerpt": text[:420].replace("\n", " ").strip(),
                            "score": score,
                        },
                    )
                )
    hits.sort(key=lambda x: -x[0])
    return [h[1] for h in hits[:k]]


def goals_path(project: str) -> Path:
    p = VAULT / slugify(project)
    p.mkdir(parents=True, exist_ok=True)
    return p / "goals.json"


def get_goals(project: str) -> dict:
    """Project memory layer: current state, next goals, long-term goals."""
    path = goals_path(project)
    defaults = {
        "project": project,
        "current_state": "",
        "next_goals": "",
        "long_term": "",
        "updated_at": 0,
    }
    if not path.is_file():
        return defaults
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return defaults
        defaults.update({k: data.get(k, defaults[k]) for k in defaults})
        return defaults
    except Exception:
        return defaults


def set_goals(
    project: str,
    *,
    current_state: str | None = None,
    next_goals: str | None = None,
    long_term: str | None = None,
) -> dict:
    import json
    import time

    cur = get_goals(project)
    if current_state is not None:
        cur["current_state"] = str(current_state)[:4000]
    if next_goals is not None:
        cur["next_goals"] = str(next_goals)[:4000]
    if long_term is not None:
        cur["long_term"] = str(long_term)[:4000]
    cur["project"] = project
    cur["updated_at"] = time.time()
    path = goals_path(project)
    path.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    # Also mirror into wing drawers for MemPalace-style retrieval
    try:
        if cur["current_state"].strip():
            write_drawer(
                project=project,
                title="Current state",
                body=cur["current_state"],
                room="goals",
                source="memory_layer",
            )
        if cur["next_goals"].strip():
            write_drawer(
                project=project,
                title="Next goals",
                body=cur["next_goals"],
                room="goals",
                source="memory_layer",
            )
        if cur["long_term"].strip():
            write_drawer(
                project=project,
                title="Long-term goals",
                body=cur["long_term"],
                room="goals",
                source="memory_layer",
            )
    except Exception:
        pass
    return cur


def list_project_folders(project: str) -> list[dict]:
    """Folder icons for project rail — rooms under the wing."""
    base = VAULT / slugify(project) / "rooms"
    if not base.is_dir():
        return [{"id": "general", "name": "General", "count": 0}]
    out = []
    for d in sorted(base.iterdir()):
        if d.is_dir():
            n = len(list(d.glob("*.md")))
            out.append({"id": d.name, "name": d.name.replace("-", " ").title(), "count": n})
    return out or [{"id": "general", "name": "General", "count": 0}]


def list_wings(limit: int = 80) -> list[dict]:
    """List wing drawers and legacy vault notes for memory overview."""
    if not VAULT.is_dir():
        return []
    items: list[dict] = []
    for p in sorted(VAULT.rglob("*.md"))[: max(1, limit)]:
        try:
            rel = str(p.relative_to(DATA_DIR)).replace("\\", "/")
            parts = Path(rel).parts
            project = parts[1] if len(parts) > 1 else ""
            room = ""
            if len(parts) >= 4 and parts[2] == "rooms":
                room = parts[3]
            items.append(
                {
                    "path": rel,
                    "project": project,
                    "room": room,
                    "wing": bool(room),
                    "bytes": p.stat().st_size,
                    "mtime": p.stat().st_mtime,
                }
            )
        except Exception:
            pass
    return items


def write_session_note(
    *,
    project_slug: str,
    project_name: str,
    session_id: int,
    title: str,
    analysis: str,
    image_rel: str = "",
    source: str = "screenshot",
    related: str = "",
) -> str:
    """Write markdown note to vault. Returns relative path."""
    folder = VAULT / project_slug
    folder.mkdir(parents=True, exist_ok=True)
    fname = f"{session_id:04d}-{slugify(title)[:36]}.md"
    path = folder / fname
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    fm = (
        f"---\n"
        f"session_id: {session_id}\n"
        f"project: {project_name}\n"
        f"source: {source}\n"
        f"created: {now}\n"
        f"image: {image_rel}\n"
        f"related: {related}\n"
        f"---\n\n"
    )
    body = f"# {title}\n\n"
    if image_rel:
        body += f"![capture](../../{image_rel})\n\n"
    body += analysis.strip() + "\n"
    path.write_text(fm + body, encoding="utf-8")
    return str(path.relative_to(DATA_DIR)).replace("\\", "/")


def parse_vault_metadata(analysis: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in ("PROJECT", "SESSION_TITLE", "RELATED_TO", "CATEGORY"):
        m = re.search(rf"^\s*{key}:\s*(.+)$", analysis, re.MULTILINE | re.IGNORECASE)
        if m:
            val = m.group(1).strip().lower().split()[0] if key == "CATEGORY" else m.group(1).strip()
            out[key.lower()] = val
    if not out.get("project"):
        dm = re.search(r"\*\*Domain\*\*:\s*(.+)", analysis)
        if dm:
            out["project"] = dm.group(1).strip().split("(")[0].strip()
    return out

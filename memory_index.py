"""Chat memory index — MemPalace/mem0-style local layer.

Tiers (MEXT-inspired hot/warm/cold):
  hot   — next_action + session scratch in SQLite
  warm  — project goals + recent drawers
  cold  — vault wings on SSD + optional Chroma embeddings

Chroma is optional. Without it we use SQLite FTS + keyword wing search.
Never requires cloud mem0; local-first and Cortex-safe.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from config import DATA_DIR
from db import ClosingConnection  # commits and closes on leaving a with-block

MEM_DIR = DATA_DIR / "memory"
DB_PATH = MEM_DIR / "index.db"
CHROMA_DIR = MEM_DIR / "chroma"


def _conn() -> sqlite3.Connection:
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False, factory=ClosingConnection)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              kind TEXT NOT NULL,
              title TEXT DEFAULT '',
              body TEXT DEFAULT '',
              project TEXT DEFAULT '',
              session_id INTEGER DEFAULT 0,
              folder TEXT DEFAULT '',
              tags TEXT DEFAULT '[]',
              source TEXT DEFAULT 'user',
              created_at REAL,
              updated_at REAL,
              pinned INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_mem_sess ON memories(session_id);
            CREATE INDEX IF NOT EXISTS idx_mem_proj ON memories(project);
            CREATE INDEX IF NOT EXISTS idx_mem_kind ON memories(kind);
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
              title, body, folder, project, content='memories', content_rowid='id'
            );
            CREATE TABLE IF NOT EXISTS chat_folders (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id INTEGER NOT NULL,
              project TEXT DEFAULT '',
              name TEXT NOT NULL,
              path TEXT DEFAULT '',
              created_at REAL,
              UNIQUE(session_id, name)
            );
            """
        )


def _row(r: sqlite3.Row | None) -> dict | None:
    if not r:
        return None
    d = dict(r)
    try:
        d["tags"] = json.loads(d.get("tags") or "[]")
    except Exception:
        d["tags"] = []
    return d


# Credential shapes that must never be persisted. Deliberately NOT the whole
# pii_guard set: an email address or a phone number can be a legitimate durable fact
# ("my work email is ...") and refusing those would make the store useless. Only
# things that are secret by construction are rejected.
_ASSIGNED_SECRET_RE = re.compile(
    r"(?i)\b(?:pass(?:word|wd|phrase)|secret|api[_ -]?key|access[_ -]?token|"
    r"auth[_ -]?token|bearer|client[_ -]?secret|private[_ -]?key)\b"
    r"\s*[:=]\s*\S{6,}"
)
_PEM_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")


def _secret_kind(text: str) -> str:
    """Name the credential shape found in `text`, or "" if there is none.

    Returns a description rather than a bool so the refusal can say what it saw
    without ever echoing the value back.
    """
    s = text or ""
    if not s:
        return ""
    if _PEM_RE.search(s):
        return "private key"
    if _ASSIGNED_SECRET_RE.search(s):
        return "password or token assignment"
    try:
        import pii_guard

        # Use the pattern directly, not redact(): redact() is a no-op when the
        # PII toggle is off, and a credential must be refused either way.
        for name, pattern in pii_guard._PATTERNS:
            if name == "KEY" and pattern.search(s):
                return "provider API key"
    except Exception:
        # Fall back to the two most common prefixes rather than failing open.
        if re.search(r"\b(?:sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16})\b", s):
            return "provider API key"
    return ""


def add_memory(
    *,
    kind: str,
    title: str = "",
    body: str = "",
    project: str = "",
    session_id: int = 0,
    folder: str = "",
    tags: list | None = None,
    source: str = "user",
    pinned: bool = False,
) -> dict:
    init()

    # Fail closed on credentials, at the funnel rather than per caller.
    # Six code paths reach this function and none of them scrubbed anything;
    # pii_guard.redact ran only on the outbound cloud prompt. The likeliest route in
    # is POST /api/memory/ingest, which stores a dropped file byte-for-byte - a .env
    # or an exported key list lands verbatim. Memory is injected into later prompts,
    # so a secret stored once is a secret re-sent on every subsequent turn.
    # Refusing loudly, not redacting: a half-stored credential is still a leak, and a
    # silent redaction hides that the user's paste went somewhere it should not.
    leak = _secret_kind(f"{title}\n{body}")
    if leak:
        return {
            "ok": False,
            "refused": "secret",
            "error": (
                f"refused: this looks like a {leak}. Credentials belong in the vault, "
                "not in memory - memory is replayed into later prompts."
            ),
        }

    kind = (kind or "memory").strip()[:40]
    if kind not in ("memory", "next_action", "global_goal", "note", "file"):
        kind = "memory"
    now = time.time()
    title = (title or "").strip()[:200]
    body = (body or "").strip()[:8000]
    project = (project or "").strip()[:80]
    folder = (folder or "").strip()[:80]
    tags_s = json.dumps(tags or [])[:500]
    with _conn() as conn:
        # Single active next_action / global_goal per scope
        if kind == "next_action" and session_id:
            conn.execute(
                "DELETE FROM memories WHERE kind='next_action' AND session_id=?",
                (int(session_id),),
            )
        if kind == "global_goal" and project:
            conn.execute(
                "DELETE FROM memories WHERE kind='global_goal' AND project=? AND session_id=0",
                (project,),
            )
        cur = conn.execute(
            """INSERT INTO memories(kind,title,body,project,session_id,folder,tags,source,created_at,updated_at,pinned)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (kind, title, body, project, int(session_id or 0), folder, tags_s, source, now, now, 1 if pinned else 0),
        )
        mid = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO memories_fts(rowid,title,body,folder,project) VALUES(?,?,?,?,?)",
            (mid, title, body, folder, project),
        )
    item = get_memory(mid)
    _embed_upsert(item)
    # Mirror durable kinds into MemPalace wing drawers
    if kind in ("memory", "global_goal", "note") and project and body:
        try:
            import vault as vault_mod

            vault_mod.write_drawer(
                project=project,
                title=title or kind,
                body=body,
                room=folder or ("goals" if kind == "global_goal" else "general"),
                source="memory_index",
                session_id=int(session_id or 0),
            )
        except Exception:
            pass
    return {"ok": True, "item": item}


def get_memory(mid: int) -> dict | None:
    init()
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM memories WHERE id=?", (mid,)).fetchone())


def delete_memory(mid: int) -> dict:
    init()
    with _conn() as conn:
        conn.execute("DELETE FROM memories_fts WHERE rowid=?", (mid,))
        conn.execute("DELETE FROM memories WHERE id=?", (mid,))
    _embed_delete(mid)
    return {"ok": True}


def forget_session(session_ids: "set[int] | None") -> dict:
    """Remove everything the given chats left in memory: their rows, search entries,
    embeddings, folders and the vault notes written from them. None = every chat.
    Used when a chat is deleted or history is cleared, so nothing from it reaches
    the model again."""
    init()
    ids = None if session_ids is None else sorted({int(i) for i in session_ids if int(i) > 0})
    if ids is not None and not ids:
        return {"ok": True, "memories": 0, "notes": 0}
    with _conn() as conn:
        if ids is None:
            rows = conn.execute("SELECT id, body FROM memories WHERE session_id>0").fetchall()
        else:
            q = ",".join("?" * len(ids))
            rows = conn.execute(f"SELECT id, body FROM memories WHERE session_id IN ({q})", ids).fetchall()
    mids = [int(r["id"]) for r in rows]
    bodies = [r["body"] or "" for r in rows]
    for mid in mids:
        delete_memory(mid)
    with _conn() as conn:
        if ids is None:
            conn.execute("DELETE FROM chat_folders WHERE session_id>0")
        else:
            conn.execute(f"DELETE FROM chat_folders WHERE session_id IN ({q})", ids)
    import vault as vault_mod

    notes = vault_mod.delete_session_notes(None if ids is None else set(ids), bodies)
    return {"ok": True, "memories": len(mids), "notes": len(notes)}


def update_memory(mid: int, **fields: Any) -> dict:
    init()
    allowed = {"title", "body", "folder", "pinned", "tags"}
    sets = []
    vals: list[Any] = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "tags":
            v = json.dumps(v or [])
        if k == "pinned":
            v = 1 if v else 0
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return {"ok": False, "error": "nothing to update"}
    sets.append("updated_at=?")
    vals.append(time.time())
    vals.append(mid)
    with _conn() as conn:
        conn.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id=?", vals)
        row = conn.execute("SELECT * FROM memories WHERE id=?", (mid,)).fetchone()
        if row:
            conn.execute("DELETE FROM memories_fts WHERE rowid=?", (mid,))
            conn.execute(
                "INSERT INTO memories_fts(rowid,title,body,folder,project) VALUES(?,?,?,?,?)",
                (mid, row["title"], row["body"], row["folder"], row["project"]),
            )
    item = get_memory(mid)
    _embed_upsert(item)
    return {"ok": True, "item": item}


def list_memories(
    *,
    session_id: int = 0,
    project: str = "",
    kind: str = "",
    limit: int = 40,
) -> list[dict]:
    init()
    q = "SELECT * FROM memories WHERE 1=1"
    args: list[Any] = []
    if session_id:
        q += " AND (session_id=? OR (session_id=0 AND project=?))"
        args.extend([int(session_id), project or ""])
    elif project:
        q += " AND project=?"
        args.append(project)
    if kind:
        q += " AND kind=?"
        args.append(kind)
    q += " ORDER BY pinned DESC, updated_at DESC LIMIT ?"
    args.append(max(1, min(limit, 200)))
    with _conn() as conn:
        return [_row(r) for r in conn.execute(q, args).fetchall() if _row(r)]


# FTS5 treats ?, ', : and - as operators, so a natural question was a syntax error,
# not a miss: "what is my favourite pet?" raised `fts5: syntax error near "?"` and
# "dog: name" raised `no such column: dog`. Every one of those was swallowed by the
# bare `except` below and fell through to a scorer that returns unrelated drawers, so
# the store looked empty for exactly the phrasing people actually type.
_FTS_TOKEN_RE = re.compile(r"[0-9A-Za-z_]+|[一-鿿぀-ヿ가-힯]+")
_FTS_STOPWORDS = frozenset(
    "a an and are as at be by do does did for from had has have how i in is it its me "
    "my of on or our that the their them then there these this to was were what when "
    "where which who whom why will with you your".split()
)


def fts_query(text: str) -> str:
    """Turn free text into a valid FTS5 MATCH expression, or "" if nothing is usable.

    Every term is quoted, which neutralises the operator characters, and they are
    joined with OR because FTS5 defaults to AND - "who is my pet" found nothing purely
    because the row did not contain the word "who".
    """
    terms: list[str] = []
    for tok in _FTS_TOKEN_RE.findall(text or ""):
        low = tok.lower()
        if low in _FTS_STOPWORDS:
            continue
        if tok.isascii() and len(tok) < 2:
            continue
        terms.append(tok.replace('"', ""))
    if not terms:
        # All stopwords: keep the longest raw token rather than returning everything.
        raw = [t for t in _FTS_TOKEN_RE.findall(text or "") if t]
        if not raw:
            return ""
        terms = [max(raw, key=len)]
    unique = list(dict.fromkeys(terms))[:12]
    return " OR ".join(f'"{t}"' for t in unique)


def search(query: str, *, project: str = "", session_id: int = 0, k: int = 8) -> list[dict]:
    """Hybrid: Chroma if available, else FTS, else vault keyword."""
    query = (query or "").strip()
    if len(query) < 2:
        return []
    hits = _embed_search(query, project=project, k=k)
    if hits:
        return hits
    init()
    out: list[dict] = []
    match = fts_query(query)
    if match:
        try:
            with _conn() as conn:
                rows = conn.execute(
                    """SELECT m.* FROM memories_fts f
                       JOIN memories m ON m.id=f.rowid
                       WHERE memories_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (match, k),
                ).fetchall()
                out = [_row(r) for r in rows if _row(r)]
        except Exception:
            out = []
    if not out:
        try:
            import vault as vault_mod

            for w in vault_mod.search_wings(query, project=project, k=k):
                out.append(
                    {
                        "id": 0,
                        "kind": "wing",
                        "title": w.get("name") or "",
                        "body": w.get("excerpt") or "",
                        "path": w.get("path"),
                        "score": w.get("score"),
                        "source": "mempalace",
                    }
                )
        except Exception:
            pass
    return out[:k]


def attach_folder(*, session_id: int, name: str, project: str = "", path: str = "") -> dict:
    init()
    name = (name or "").strip()[:80]
    if not name or not session_id:
        return {"ok": False, "error": "session_id and name required"}
    now = time.time()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO chat_folders(session_id,project,name,path,created_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(session_id,name) DO UPDATE SET path=excluded.path""",
            (int(session_id), project or "", name, path or "", now),
        )
        # ensure wing room exists
        try:
            import vault as vault_mod

            vault_mod.wing_room_dir(project or "general", name)
        except Exception:
            pass
        rows = conn.execute(
            "SELECT * FROM chat_folders WHERE session_id=? ORDER BY created_at DESC",
            (int(session_id),),
        ).fetchall()
    return {"ok": True, "folders": [dict(r) for r in rows]}


def list_folders(session_id: int) -> list[dict]:
    init()
    if not session_id:
        return []
    with _conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM chat_folders WHERE session_id=? ORDER BY created_at DESC",
                (int(session_id),),
            ).fetchall()
        ]


def panel_payload(*, session_id: int = 0, project: str = "") -> dict:
    """Everything the chat glass panel needs in one shot."""
    init()
    project = project or "general"
    memories = [
        m
        for m in list_memories(session_id=session_id, project=project, limit=30)
        if m and m.get("kind") in ("memory", "note", "file")
    ]
    next_actions = [
        m
        for m in list_memories(session_id=session_id, project=project, kind="next_action", limit=5)
        if m
    ]
    # Prefer session next_action, else empty
    next_action = next((m for m in next_actions if m.get("session_id") == session_id), None) or (
        next_actions[0] if next_actions else None
    )
    goals_local = list_memories(project=project, kind="global_goal", limit=5)
    goals_file = {}
    try:
        import vault as vault_mod

        goals_file = vault_mod.get_goals(project)
        folders_wing = vault_mod.list_project_folders(project)
    except Exception:
        folders_wing = []
        goals_file = {}
    folders_chat = list_folders(session_id)
    engine = engine_status()
    return {
        "ok": True,
        "session_id": session_id,
        "project": project,
        "memories": memories[:20],
        "next_action": next_action,
        "global_goals": goals_local[:5],
        "goals": goals_file,
        "folders": folders_chat,
        "wing_folders": folders_wing,
        "engine": engine,
    }


def engine_status() -> dict:
    chroma = False
    try:
        import chromadb  # noqa: F401

        chroma = True
    except Exception:
        pass
    return {
        "backend": "chroma" if chroma else "sqlite_fts",
        "chroma": chroma,
        "mempalace": True,
        "mem0": False,  # cloud sync deferred; local index is mem0-shaped
        "path": str(MEM_DIR).replace("\\", "/"),
    }


def ingest_text(
    text: str,
    *,
    title: str = "",
    project: str = "",
    session_id: int = 0,
    folder: str = "inbox",
) -> dict:
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty"}
    return add_memory(
        kind="memory",
        title=title or text[:60].replace("\n", " "),
        body=text,
        project=project,
        session_id=session_id,
        folder=folder or "inbox",
        source="drop",
    )


# ---- Optional Chroma embeddings ----

def _chroma():
    try:
        import chromadb
        from chromadb.config import Settings

        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        return client.get_or_create_collection("airgpt_memories")
    except Exception:
        return None


def _embed_upsert(item: dict | None) -> None:
    if not item or not item.get("id"):
        return
    col = _chroma()
    if not col:
        return
    doc = f"{item.get('title') or ''}\n{item.get('body') or ''}".strip()
    if not doc:
        return
    mid = str(item["id"])
    try:
        col.upsert(
            ids=[mid],
            documents=[doc[:6000]],
            metadatas=[
                {
                    "kind": item.get("kind") or "",
                    "project": item.get("project") or "",
                    "session_id": int(item.get("session_id") or 0),
                    "folder": item.get("folder") or "",
                }
            ],
        )
    except Exception:
        pass


def _embed_delete(mid: int) -> None:
    col = _chroma()
    if not col:
        return
    try:
        col.delete(ids=[str(mid)])
    except Exception:
        pass


def _embed_search(query: str, *, project: str = "", k: int = 8) -> list[dict]:
    col = _chroma()
    if not col:
        return []
    try:
        where = {"project": project} if project else None
        res = col.query(query_texts=[query], n_results=k, where=where)
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        out = []
        for i, mid in enumerate(ids):
            try:
                item = get_memory(int(mid))
            except Exception:
                item = None
            if item:
                item = dict(item)
                item["score"] = 1.0 - float(dists[i] if i < len(dists) else 0)
                item["source"] = "chroma"
                out.append(item)
            else:
                out.append(
                    {
                        "id": mid,
                        "kind": (metas[i] or {}).get("kind") or "memory",
                        "title": "",
                        "body": docs[i] if i < len(docs) else "",
                        "project": (metas[i] or {}).get("project") or "",
                        "source": "chroma",
                    }
                )
        return out
    except Exception:
        return []


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def _relevance(query_terms: set[str], title: str, body: str) -> float:
    """Fraction of the query's terms present in this row. 0.0 when nothing matches."""
    if not query_terms:
        return 0.0
    hay = f"{title} {body}".lower()
    hit = sum(1 for t in query_terms if t in hay)
    return hit / len(query_terms)


def carry_pack(
    *, project: str = "", session_id: int = 0, max_chars: int = 1200, query: str = ""
) -> str:
    """Compressed hot/warm memory for prompt injection (JEPA-light carry).

    `query` makes this relevant rather than merely recent. Without it the function
    took the 12 newest rows and nothing else, and because retrieve_vault_snippets
    returns carry_pack early whenever it is non-empty, those 12 rows WERE the entire
    injected memory - FTS and Chroma were never consulted on the chat path. So twelve
    disposable exchanges could bury a durable fact, and no amount of filtering on the
    write side would surface it again.

    Recency still counts, and pinned rows still win, but a row that actually mentions
    what was asked now outranks a newer row that does not.
    """
    init()
    parts: list[str] = []
    terms = {
        t.lower()
        for t in _FTS_TOKEN_RE.findall(query or "")
        if t.lower() not in _FTS_STOPWORDS and (len(t) > 1 or not t.isascii())
    }
    with _conn() as conn:
        # Widen the candidate window when there is a query to rank within; the LIMIT
        # 12 below is applied after scoring, not before it.
        rows = conn.execute(
            """SELECT kind,title,body,pinned,updated_at FROM memories
               WHERE (?='' OR project=?) AND (?=0 OR session_id=? OR kind='global_goal')
               ORDER BY pinned DESC, updated_at DESC LIMIT ?""",
            (project, project, int(session_id or 0), int(session_id or 0), 60 if terms else 12),
        ).fetchall()

    if terms:
        newest = max((r["updated_at"] or 0) for r in rows) if rows else 0
        oldest = min((r["updated_at"] or 0) for r in rows) if rows else 0
        span = max(1.0, float(newest - oldest))

        def _rank(r) -> tuple:
            rel = _relevance(terms, r["title"] or "", r["body"] or "")
            recency = ((r["updated_at"] or 0) - oldest) / span
            # Pinned first, then relevance, then recency as the tie-break. Relevance
            # dominates recency so one on-topic row survives a burst of chatter.
            return (int(r["pinned"] or 0), rel, recency)

        rows = sorted(rows, key=_rank, reverse=True)[:12]

    used = 0
    for r in rows:
        kind = r["kind"] or "memory"
        title = (r["title"] or kind)[:80]
        body = (r["body"] or "").replace("\n", " ").strip()
        # Thin: keep short for non-pinned
        limit = 220 if r["pinned"] else 120
        snippet = body[:limit]
        line = f"- [{kind}] {title}: {snippet}"
        if used + len(line) > max_chars:
            break
        parts.append(line)
        used += len(line) + 1
    return "\n".join(parts)


def thin_memories(*, older_than_days: float = 14, keep_pinned: bool = True) -> dict:
    """Demote old memories to short cold summaries (forget mechanism)."""
    init()
    cutoff = time.time() - float(older_than_days) * 86400
    thinned = 0
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id,title,body,pinned FROM memories WHERE updated_at<? AND kind IN ('memory','note')",
            (cutoff,),
        ).fetchall()
        for r in rows:
            if keep_pinned and r["pinned"]:
                continue
            body = (r["body"] or "").strip()
            if len(body) <= 160:
                continue
            summary = body[:140].rsplit(" ", 1)[0] + "…"
            conn.execute(
                "UPDATE memories SET body=?, updated_at=?, source='thinned' WHERE id=?",
                (summary, time.time(), r["id"]),
            )
            conn.execute(
                "INSERT INTO memories_fts(memories_fts, rowid, title, body, folder, project) VALUES('delete', ?, NULL, NULL, NULL, NULL)",
                (r["id"],),
            )
            try:
                conn.execute(
                    "INSERT INTO memories_fts(rowid,title,body,folder,project) SELECT id,title,body,folder,project FROM memories WHERE id=?",
                    (r["id"],),
                )
            except Exception:
                pass
            thinned += 1
    return {"ok": True, "thinned": thinned}


def forget_memories(*, older_than_days: float = 90, keep_pinned: bool = True) -> dict:
    """Hard-delete cold unpinned memories past retention."""
    init()
    cutoff = time.time() - float(older_than_days) * 86400
    deleted = 0
    with _conn() as conn:
        q = "SELECT id FROM memories WHERE updated_at<? AND kind IN ('memory','note','file')"
        if keep_pinned:
            q += " AND pinned=0"
        ids = [int(r["id"]) for r in conn.execute(q, (cutoff,)).fetchall()]
    for mid in ids:
        delete_memory(mid)
        deleted += 1
    return {"ok": True, "deleted": deleted}

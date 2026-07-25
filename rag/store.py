"""SQLite system of record for RAG knowledge spaces (personal / local-first)."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from config import DATA_DIR

RAG_DIR = DATA_DIR / "rag"
DB_PATH = RAG_DIR / "rag.db"
BLOB_DIR = RAG_DIR


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=60)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=60000")
    except Exception:
        pass
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init() -> None:
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS knowledge_spaces (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              slug TEXT NOT NULL UNIQUE,
              depth_default TEXT DEFAULT 'high',
              modalities TEXT DEFAULT '["text"]',
              profile TEXT DEFAULT 'local',
              status TEXT DEFAULT 'ready',
              config TEXT DEFAULT '{}',
              archived INTEGER DEFAULT 0,
              created_at REAL,
              updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS sources (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              space_id INTEGER NOT NULL,
              path TEXT DEFAULT '',
              title TEXT DEFAULT '',
              content_hash TEXT DEFAULT '',
              mime TEXT DEFAULT 'text/plain',
              bytes INTEGER DEFAULT 0,
              meta TEXT DEFAULT '{}',
              status TEXT DEFAULT 'pending',
              created_at REAL,
              updated_at REAL,
              FOREIGN KEY(space_id) REFERENCES knowledge_spaces(id)
            );
            CREATE INDEX IF NOT EXISTS idx_sources_space ON sources(space_id);
            CREATE INDEX IF NOT EXISTS idx_sources_hash ON sources(content_hash);

            CREATE TABLE IF NOT EXISTS chunks (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              space_id INTEGER NOT NULL,
              source_id INTEGER NOT NULL,
              revision_id INTEGER DEFAULT 0,
              parent_id INTEGER DEFAULT 0,
              kind TEXT DEFAULT 'child',
              text TEXT NOT NULL,
              path TEXT DEFAULT '',
              heading TEXT DEFAULT '',
              page INTEGER DEFAULT 0,
              span_start INTEGER DEFAULT 0,
              span_end INTEGER DEFAULT 0,
              token_est INTEGER DEFAULT 0,
              meta TEXT DEFAULT '{}',
              created_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_space ON chunks(space_id);
            CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
            CREATE INDEX IF NOT EXISTS idx_chunks_parent ON chunks(parent_id);

            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
              text, path, heading, chunk_id UNINDEXED
            );

            CREATE TABLE IF NOT EXISTS file_index (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              space_id INTEGER NOT NULL,
              source_id INTEGER NOT NULL,
              path TEXT DEFAULT '',
              title TEXT DEFAULT '',
              phrases TEXT DEFAULT '[]',
              headings TEXT DEFAULT '[]',
              created_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_file_space ON file_index(space_id);

            CREATE VIRTUAL TABLE IF NOT EXISTS file_index_fts USING fts5(
              path, title, phrases, headings, file_id UNINDEXED
            );

            CREATE TABLE IF NOT EXISTS revisions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              space_id INTEGER NOT NULL,
              status TEXT DEFAULT 'building',
              profile TEXT DEFAULT 'local_hybrid_high',
              chunk_count INTEGER DEFAULT 0,
              source_count INTEGER DEFAULT 0,
              metrics TEXT DEFAULT '{}',
              created_at REAL,
              published_at REAL
            );

            CREATE TABLE IF NOT EXISTS ingest_jobs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              space_id INTEGER NOT NULL,
              stage TEXT DEFAULT 'queued',
              status TEXT DEFAULT 'running',
              detail TEXT DEFAULT '',
              counts TEXT DEFAULT '{}',
              error TEXT DEFAULT '',
              created_at REAL,
              updated_at REAL
            );

            CREATE TABLE IF NOT EXISTS rag_chats (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              space_id INTEGER NOT NULL,
              title TEXT DEFAULT 'New chat',
              created_at REAL,
              updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS rag_messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              chat_id INTEGER NOT NULL,
              role TEXT NOT NULL,
              content TEXT DEFAULT '',
              citations TEXT DEFAULT '[]',
              trace_id TEXT DEFAULT '',
              depth TEXT DEFAULT 'high',
              created_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_rag_msg_chat ON rag_messages(chat_id);

            CREATE TABLE IF NOT EXISTS traces (
              id TEXT PRIMARY KEY,
              space_id INTEGER NOT NULL,
              chat_id INTEGER DEFAULT 0,
              query TEXT DEFAULT '',
              depth TEXT DEFAULT 'high',
              template_id TEXT DEFAULT '',
              payload TEXT DEFAULT '{}',
              created_at REAL
            );
            """
        )


def _row(r: sqlite3.Row | None) -> dict | None:
    if not r:
        return None
    d = dict(r)
    for key in ("modalities", "config", "meta", "metrics", "counts", "citations", "phrases", "headings", "payload"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key] or ("{}" if key in ("config", "meta", "metrics", "counts", "payload") else "[]"))
            except Exception:
                pass
    return d


def _slugify(name: str) -> str:
    s = "".join(ch.lower() if ch.isalnum() else "-" for ch in (name or "rag").strip())
    while "--" in s:
        s = s.replace("--", "-")
    return (s.strip("-") or "rag")[:80]


def create_space(
    name: str,
    *,
    depth_default: str = "high",
    modalities: list | None = None,
    profile: str = "local",
    config: dict | None = None,
) -> dict:
    init()
    now = time.time()
    base = _slugify(name)
    slug = base
    depth = (depth_default or "high").lower()
    if depth not in ("basic", "high", "max", "manual"):
        depth = "high"
    with _conn() as conn:
        n = 1
        while conn.execute("SELECT 1 FROM knowledge_spaces WHERE slug=?", (slug,)).fetchone():
            n += 1
            slug = f"{base}-{n}"
        cur = conn.execute(
            "INSERT INTO knowledge_spaces(name,slug,depth_default,modalities,profile,status,config,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                (name or "RAG")[:120],
                slug,
                depth,
                json.dumps(modalities or ["text"]),
                (profile or "local")[:40],
                "ready",
                json.dumps(config or {}),
                now,
                now,
            ),
        )
        blob = BLOB_DIR / str(cur.lastrowid)
        blob.mkdir(parents=True, exist_ok=True)
        (blob / "sources").mkdir(exist_ok=True)
        (blob / "artifacts").mkdir(exist_ok=True)
        row = conn.execute("SELECT * FROM knowledge_spaces WHERE id=?", (cur.lastrowid,)).fetchone()
        return _row(row)  # type: ignore[return-value]


def list_spaces(*, include_archived: bool = False, limit: int = 100) -> list[dict]:
    init()
    with _conn() as conn:
        if include_archived:
            rows = conn.execute(
                "SELECT * FROM knowledge_spaces ORDER BY updated_at DESC LIMIT ?",
                (min(limit, 200),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM knowledge_spaces WHERE archived=0 ORDER BY updated_at DESC LIMIT ?",
                (min(limit, 200),),
            ).fetchall()
        out = []
        for r in rows:
            d = _row(r)
            assert d is not None
            sc = conn.execute(
                "SELECT COUNT(*) AS c FROM sources WHERE space_id=?", (d["id"],)
            ).fetchone()
            cc = conn.execute(
                "SELECT COUNT(*) AS c FROM rag_chats WHERE space_id=?", (d["id"],)
            ).fetchone()
            d["source_count"] = int(sc["c"] if sc else 0)
            d["chat_count"] = int(cc["c"] if cc else 0)
            out.append(d)
        return out


def get_space(space_id: int) -> dict | None:
    init()
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM knowledge_spaces WHERE id=?", (int(space_id),)
        ).fetchone()
        return _row(row)


def get_space_by_slug(slug: str) -> dict | None:
    init()
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM knowledge_spaces WHERE slug=?", ((slug or "").strip(),)
        ).fetchone()
        return _row(row)


def rename_space(space_id: int, name: str) -> dict | None:
    init()
    with _conn() as conn:
        conn.execute(
            "UPDATE knowledge_spaces SET name=?, updated_at=? WHERE id=?",
            ((name or "RAG")[:120], time.time(), int(space_id)),
        )
        return _row(conn.execute("SELECT * FROM knowledge_spaces WHERE id=?", (int(space_id),)).fetchone())


def update_space_settings(
    space_id: int,
    *,
    name: str | None = None,
    depth_default: str | None = None,
    profile: str | None = None,
    config: dict | None = None,
) -> dict | None:
    """Partial settings update: rename, default depth, storage profile, merged config."""
    init()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM knowledge_spaces WHERE id=?", (int(space_id),)).fetchone()
        if not row:
            return None
        new_name = (str(name)[:120]) if name else row["name"]
        depth = str(depth_default or row["depth_default"] or "high").lower()
        if depth not in ("basic", "high", "max", "manual"):
            depth = row["depth_default"] or "high"
        new_profile = str(profile).strip().lower() if profile is not None else (row["profile"] or "local")
        if new_profile in ("local+", "local_plus", "local-qdrant"):
            new_profile = "local_qdrant"
        if new_profile not in ("local", "local_qdrant", "business"):
            new_profile = row["profile"] or "local"
        cfg_raw = row["config"] or "{}"
        if isinstance(config, dict):
            try:
                cur = json.loads(cfg_raw)
            except Exception:
                cur = {}
            cur.update(config)
            cfg_raw = json.dumps(cur)
        conn.execute(
            "UPDATE knowledge_spaces SET name=?, depth_default=?, profile=?, config=?, updated_at=? WHERE id=?",
            (new_name, depth, new_profile[:40], cfg_raw, time.time(), int(space_id)),
        )
        return _row(conn.execute("SELECT * FROM knowledge_spaces WHERE id=?", (int(space_id),)).fetchone())


def delete_source(source_id: int) -> dict:
    """Remove a source and its chunks / FTS rows / file index / dense vectors."""
    init()
    with _conn() as conn:
        src = conn.execute("SELECT * FROM sources WHERE id=?", (int(source_id),)).fetchone()
        if not src:
            return {"ok": False, "error": "source not found"}
        ids = [int(r["id"]) for r in conn.execute("SELECT id FROM chunks WHERE source_id=?", (int(source_id),))]
        if ids:
            q = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM chunks_fts WHERE chunk_id IN ({q})", ids)
            try:  # dense vectors — tables exist only once rag.vectors has run
                conn.execute(f"DELETE FROM chunk_vectors WHERE chunk_id IN ({q})", ids)
                conn.execute(f"DELETE FROM chunk_vec_idx WHERE chunk_id IN ({q})", ids)
            except Exception:
                pass
        conn.execute("DELETE FROM chunks WHERE source_id=?", (int(source_id),))
        fids = [int(r["id"]) for r in conn.execute("SELECT id FROM file_index WHERE source_id=?", (int(source_id),))]
        if fids:
            q = ",".join("?" * len(fids))
            conn.execute(f"DELETE FROM file_index_fts WHERE file_id IN ({q})", fids)
        conn.execute("DELETE FROM file_index WHERE source_id=?", (int(source_id),))
        conn.execute("DELETE FROM sources WHERE id=?", (int(source_id),))
        conn.execute(
            "UPDATE knowledge_spaces SET updated_at=? WHERE id=?",
            (time.time(), int(src["space_id"])),
        )
        return {"ok": True, "space_id": int(src["space_id"]), "chunks_removed": len(ids)}


def archive_space(space_id: int) -> dict | None:
    init()
    with _conn() as conn:
        conn.execute(
            "UPDATE knowledge_spaces SET archived=1, updated_at=? WHERE id=?",
            (time.time(), int(space_id)),
        )
        return _row(conn.execute("SELECT * FROM knowledge_spaces WHERE id=?", (int(space_id),)).fetchone())


def touch_space(space_id: int, *, status: str | None = None) -> None:
    init()
    with _conn() as conn:
        if status:
            conn.execute(
                "UPDATE knowledge_spaces SET status=?, updated_at=? WHERE id=?",
                (status[:40], time.time(), int(space_id)),
            )
        else:
            conn.execute(
                "UPDATE knowledge_spaces SET updated_at=? WHERE id=?",
                (time.time(), int(space_id)),
            )


def add_source(
    space_id: int,
    *,
    path: str,
    title: str = "",
    content_hash: str = "",
    mime: str = "text/plain",
    bytes_n: int = 0,
    meta: dict | None = None,
    status: str = "pending",
) -> dict:
    init()
    now = time.time()
    with _conn() as conn:
        # idempotent by content hash within space
        if content_hash:
            existing = conn.execute(
                "SELECT * FROM sources WHERE space_id=? AND content_hash=?",
                (int(space_id), content_hash),
            ).fetchone()
            if existing:
                return _row(existing)  # type: ignore[return-value]
        cur = conn.execute(
            "INSERT INTO sources(space_id,path,title,content_hash,mime,bytes,meta,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                int(space_id),
                (path or "")[:500],
                (title or Path(path).name or "source")[:200],
                (content_hash or "")[:64],
                (mime or "text/plain")[:80],
                int(bytes_n or 0),
                json.dumps(meta or {}),
                (status or "pending")[:40],
                now,
                now,
            ),
        )
        conn.execute(
            "UPDATE knowledge_spaces SET updated_at=? WHERE id=?",
            (now, int(space_id)),
        )
        return _row(conn.execute("SELECT * FROM sources WHERE id=?", (cur.lastrowid,)).fetchone())  # type: ignore[return-value]


def list_sources(space_id: int) -> list[dict]:
    init()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sources WHERE space_id=? ORDER BY id DESC",
            (int(space_id),),
        ).fetchall()
        return [_row(r) for r in rows]  # type: ignore[misc]


def update_source_status(source_id: int, status: str, *, meta: dict | None = None) -> None:
    init()
    with _conn() as conn:
        if meta is not None:
            conn.execute(
                "UPDATE sources SET status=?, meta=?, updated_at=? WHERE id=?",
                (status[:40], json.dumps(meta), time.time(), int(source_id)),
            )
        else:
            conn.execute(
                "UPDATE sources SET status=?, updated_at=? WHERE id=?",
                (status[:40], time.time(), int(source_id)),
            )


def create_job(space_id: int, stage: str = "queued") -> dict:
    init()
    now = time.time()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO ingest_jobs(space_id,stage,status,created_at,updated_at) VALUES(?,?,?,?,?)",
            (int(space_id), stage[:40], "running", now, now),
        )
        return _row(conn.execute("SELECT * FROM ingest_jobs WHERE id=?", (cur.lastrowid,)).fetchone())  # type: ignore[return-value]


def update_job(
    job_id: int,
    *,
    stage: str | None = None,
    status: str | None = None,
    detail: str = "",
    counts: dict | None = None,
    error: str = "",
) -> dict | None:
    init()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM ingest_jobs WHERE id=?", (int(job_id),)).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE ingest_jobs SET stage=?, status=?, detail=?, counts=?, error=?, updated_at=? WHERE id=?",
            (
                (stage or row["stage"])[:40],
                (status or row["status"])[:40],
                (detail or row["detail"] or "")[:2000],
                json.dumps(counts if counts is not None else json.loads(row["counts"] or "{}")),
                (error or "")[:2000],
                time.time(),
                int(job_id),
            ),
        )
        return _row(conn.execute("SELECT * FROM ingest_jobs WHERE id=?", (int(job_id),)).fetchone())


def get_job(job_id: int) -> dict | None:
    init()
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM ingest_jobs WHERE id=?", (int(job_id),)).fetchone())


def create_revision(space_id: int, *, profile: str = "local_hybrid_high") -> dict:
    init()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO revisions(space_id,status,profile,created_at) VALUES(?,?,?,?)",
            (int(space_id), "building", profile[:80], time.time()),
        )
        return _row(conn.execute("SELECT * FROM revisions WHERE id=?", (cur.lastrowid,)).fetchone())  # type: ignore[return-value]


def publish_revision(revision_id: int, *, chunk_count: int, source_count: int, metrics: dict | None = None) -> dict | None:
    init()
    now = time.time()
    with _conn() as conn:
        conn.execute(
            "UPDATE revisions SET status=?, chunk_count=?, source_count=?, metrics=?, published_at=? WHERE id=?",
            ("published", int(chunk_count), int(source_count), json.dumps(metrics or {}), now, int(revision_id)),
        )
        row = conn.execute("SELECT * FROM revisions WHERE id=?", (int(revision_id),)).fetchone()
        if row:
            conn.execute(
                "UPDATE knowledge_spaces SET status=?, updated_at=? WHERE id=?",
                ("ready", now, int(row["space_id"])),
            )
        return _row(row)


def clear_chunks(space_id: int) -> None:
    """Remove chunk rows + FTS for a space before rebuild (Phase 1 simple rebuild)."""
    init()
    with _conn() as conn:
        ids = [int(r["id"]) for r in conn.execute("SELECT id FROM chunks WHERE space_id=?", (int(space_id),))]
        if ids:
            q = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM chunks_fts WHERE chunk_id IN ({q})", ids)
        conn.execute("DELETE FROM chunks WHERE space_id=?", (int(space_id),))
        fids = [int(r["id"]) for r in conn.execute("SELECT id FROM file_index WHERE space_id=?", (int(space_id),))]
        if fids:
            q = ",".join("?" * len(fids))
            conn.execute(f"DELETE FROM file_index_fts WHERE file_id IN ({q})", fids)
        conn.execute("DELETE FROM file_index WHERE space_id=?", (int(space_id),))


def insert_chunk(
    *,
    space_id: int,
    source_id: int,
    revision_id: int,
    text: str,
    kind: str = "child",
    parent_id: int = 0,
    path: str = "",
    heading: str = "",
    page: int = 0,
    span_start: int = 0,
    span_end: int = 0,
    token_est: int = 0,
    meta: dict | None = None,
) -> int:
    init()
    now = time.time()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO chunks(space_id,source_id,revision_id,parent_id,kind,text,path,heading,page,"
            "span_start,span_end,token_est,meta,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(space_id),
                int(source_id),
                int(revision_id),
                int(parent_id),
                (kind or "child")[:20],
                text or "",
                (path or "")[:500],
                (heading or "")[:200],
                int(page),
                int(span_start),
                int(span_end),
                int(token_est),
                json.dumps(meta or {}),
                now,
            ),
        )
        cid = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO chunks_fts(text, path, heading, chunk_id) VALUES(?,?,?,?)",
            (text or "", path or "", heading or "", cid),
        )
        return cid


def insert_file_index(
    *,
    space_id: int,
    source_id: int,
    path: str,
    title: str,
    phrases: list[str] | None = None,
    headings: list[str] | None = None,
) -> int:
    init()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO file_index(space_id,source_id,path,title,phrases,headings,created_at) VALUES(?,?,?,?,?,?,?)",
            (
                int(space_id),
                int(source_id),
                (path or "")[:500],
                (title or "")[:200],
                json.dumps(phrases or []),
                json.dumps(headings or []),
                time.time(),
            ),
        )
        fid = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO file_index_fts(path, title, phrases, headings, file_id) VALUES(?,?,?,?,?)",
            (
                path or "",
                title or "",
                " ".join(phrases or []),
                " ".join(headings or []),
                fid,
            ),
        )
        return fid


def get_chunk(chunk_id: int) -> dict | None:
    init()
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM chunks WHERE id=?", (int(chunk_id),)).fetchone())


def neighbor_window(chunk_id: int, *, radius: int = 1, kind: str = "child") -> list[dict]:
    """Return chunks adjacent (by span) to `chunk_id` within the same source.

    Classic sentence-window / neighbour expansion: a semantic hit rarely contains
    the whole answer, so pulling the chunks just before/after it widens context
    for long passages — retrieval helped by neighbours, not chunks alone.
    """
    init()
    with _conn() as conn:
        cur = conn.execute("SELECT * FROM chunks WHERE id=?", (int(chunk_id),)).fetchone()
        if not cur:
            return []
        source_id = int(cur["source_id"])
        span = int(cur["span_start"] or 0)
        k = str(kind or cur["kind"] or "child")
        before = conn.execute(
            "SELECT * FROM chunks WHERE source_id=? AND kind=? AND span_start < ? "
            "ORDER BY span_start DESC LIMIT ?",
            (source_id, k, span, int(radius)),
        ).fetchall()
        after = conn.execute(
            "SELECT * FROM chunks WHERE source_id=? AND kind=? AND span_start > ? "
            "ORDER BY span_start ASC LIMIT ?",
            (source_id, k, span, int(radius)),
        ).fetchall()
    out = [_row(r) for r in reversed(before)] + [_row(r) for r in after]
    return [r for r in out if r]  # type: ignore[return-value]


def sample_parent_chunks(space_id: int, *, limit: int = 24) -> list[dict]:
    """Parent (or any) chunks for space summaries and the pipeline preview.

    Round-robins across sources. A plain "ORDER BY id LIMIT n" let one big file
    (e.g. a workbook with many sheets) fill the whole window, so other documents
    never appeared in the summary or the samples.
    """
    init()
    diverse = (
        "SELECT * FROM ("
        "  SELECT *, ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY id) AS _rn"
        "  FROM chunks WHERE space_id=? AND kind=?"
        ") ORDER BY _rn ASC, source_id ASC LIMIT ?"
    )
    with _conn() as conn:
        for kind in ("parent", None):
            try:
                if kind is None:
                    rows = conn.execute(
                        "SELECT * FROM ("
                        "  SELECT *, ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY id) AS _rn"
                        "  FROM chunks WHERE space_id=?"
                        ") ORDER BY _rn ASC, source_id ASC LIMIT ?",
                        (int(space_id), int(limit)),
                    ).fetchall()
                else:
                    rows = conn.execute(diverse, (int(space_id), kind, int(limit))).fetchall()
            except sqlite3.OperationalError:
                # No window-function support — fall back to insertion order.
                sql = "SELECT * FROM chunks WHERE space_id=?" + (
                    " AND kind='parent'" if kind else ""
                ) + " ORDER BY id ASC LIMIT ?"
                rows = conn.execute(sql, (int(space_id), int(limit))).fetchall()
            if rows:
                return [_row(r) for r in rows]  # type: ignore[misc]
        return []


def get_chunks_by_ids(ids: list[int]) -> list[dict]:
    if not ids:
        return []
    init()
    with _conn() as conn:
        qmarks = ",".join("?" * len(ids))
        rows = conn.execute(f"SELECT * FROM chunks WHERE id IN ({qmarks})", [int(i) for i in ids]).fetchall()
        return [_row(r) for r in rows]  # type: ignore[misc]


def create_chat(space_id: int, title: str = "New chat") -> dict:
    init()
    now = time.time()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO rag_chats(space_id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (int(space_id), (title or "New chat")[:120], now, now),
        )
        return _row(conn.execute("SELECT * FROM rag_chats WHERE id=?", (cur.lastrowid,)).fetchone())  # type: ignore[return-value]


def list_chats(space_id: int) -> list[dict]:
    init()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM rag_chats WHERE space_id=? ORDER BY updated_at DESC",
            (int(space_id),),
        ).fetchall()
        return [_row(r) for r in rows]  # type: ignore[misc]


def add_message(
    chat_id: int,
    role: str,
    content: str,
    *,
    citations: list | None = None,
    trace_id: str = "",
    depth: str = "high",
) -> dict:
    init()
    now = time.time()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO rag_messages(chat_id,role,content,citations,trace_id,depth,created_at) VALUES(?,?,?,?,?,?,?)",
            (
                int(chat_id),
                (role or "user")[:20],
                content or "",
                json.dumps(citations or []),
                (trace_id or "")[:80],
                (depth or "high")[:20],
                now,
            ),
        )
        conn.execute("UPDATE rag_chats SET updated_at=? WHERE id=?", (now, int(chat_id)))
        return _row(conn.execute("SELECT * FROM rag_messages WHERE id=?", (cur.lastrowid,)).fetchone())  # type: ignore[return-value]


def list_messages(chat_id: int) -> list[dict]:
    init()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM rag_messages WHERE chat_id=? ORDER BY id ASC",
            (int(chat_id),),
        ).fetchall()
        return [_row(r) for r in rows]  # type: ignore[misc]


def save_trace(
    trace_id: str,
    *,
    space_id: int,
    query: str,
    depth: str,
    template_id: str,
    payload: dict[str, Any],
    chat_id: int = 0,
) -> dict:
    init()
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO traces(id,space_id,chat_id,query,depth,template_id,payload,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                (trace_id or "")[:80],
                int(space_id),
                int(chat_id),
                (query or "")[:2000],
                (depth or "high")[:20],
                (template_id or "")[:80],
                json.dumps(payload or {}),
                time.time(),
            ),
        )
        return _row(conn.execute("SELECT * FROM traces WHERE id=?", (trace_id,)).fetchone())  # type: ignore[return-value]


def get_trace(trace_id: str) -> dict | None:
    init()
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM traces WHERE id=?", ((trace_id or "")[:80],)).fetchone())

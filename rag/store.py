"""SQLite system of record for RAG knowledge spaces (personal / local-first)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from config import DATA_DIR

RAG_DIR = DATA_DIR / "rag"
DB_PATH = RAG_DIR / "rag.db"
BLOB_DIR = RAG_DIR

# Bump to force a one-off reclassification of chunks.authority on existing databases.
AUTHORITY_SCHEMA_VERSION = 1


# One retrieval fans out ~50 short reads across sparse / dense / file / expand
# channels, and every one of them used to open its own connection and re-run the whole
# DDL script below. On a 37 MB index that was ~600 ms of pure setup for a corpus small
# enough to fit in L2. `session()` lets a burst share one connection; `init()` now runs
# the schema once per database file.
_local = threading.local()
_inited: set[str] = set()
_init_lock = threading.Lock()


def _open() -> sqlite3.Connection:
    # Create the parent of the database we are about to open, not the module
    # default. Tests and profile switches repoint DB_PATH, and creating RAG_DIR
    # instead left the real target's directory missing ("unable to open
    # database file").
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=60)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=60000")
    except Exception:
        pass
    return c


def _live_session() -> dict | None:
    """Active session for this thread, but only if it points at the current DB."""
    live = getattr(_local, "session", None)
    if live is not None and live.get("path") == str(DB_PATH):
        return live
    return None


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    """Share one connection across a burst of reads. Nests safely; read-mostly.

    Connections are closed when the outermost session exits, so no handle outlives the
    call — temp-directory teardown on Windows keeps working.
    """
    live = _live_session()
    if live is not None:
        live["depth"] += 1
        try:
            yield live["conn"]
        finally:
            live["depth"] -= 1
        return

    c = _open()
    prev = getattr(_local, "session", None)
    _local.session = {"conn": c, "depth": 1, "path": str(DB_PATH)}
    try:
        yield c
        c.commit()
    except Exception:
        try:
            c.rollback()
        except Exception:
            pass
        raise
    finally:
        _local.session = prev
        try:
            c.close()
        except Exception:
            pass


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    live = _live_session()
    if live is not None:
        live["depth"] += 1
        try:
            yield live["conn"]
        finally:
            live["depth"] -= 1
        return

    c = _open()
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _db_fingerprint() -> tuple[str, int] | None:
    """Identity of the database file, or None when the schema cannot be assumed.

    Someone deleting `data/rag/rag.db` from Explorer must not leave the app querying
    tables that no longer exist, so a missing or freshly-created (0-byte) file always
    forces the DDL to run again. One stat() beats a 160 ms schema script.
    """
    try:
        st = DB_PATH.stat()
    except OSError:
        return None
    if st.st_size == 0:
        return None
    return (str(DB_PATH), st.st_ctime_ns)


def init(*, force: bool = False) -> None:
    fp = _db_fingerprint()
    if not force and fp is not None and fp in _inited:
        return
    with _init_lock:
        fp = _db_fingerprint()
        if not force and fp is not None and fp in _inited:
            return
        _init_schema()
        fp = _db_fingerprint()
        if fp is not None:
            _inited.add(fp)


def reset_init_cache() -> None:
    """Forget which databases have been initialised (tests / profile switches)."""
    with _init_lock:
        _inited.clear()


def _init_schema() -> None:
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
              authority TEXT DEFAULT 'document',
              created_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_space ON chunks(space_id);
            -- idx_chunks_authority is created in _migrate_authority, not here: on a
            -- database that predates the column, CREATE TABLE IF NOT EXISTS is a no-op
            -- and indexing a column that does not exist yet aborts the whole script.
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
        _migrate_authority(conn)


def _migrate_authority(conn: sqlite3.Connection) -> None:
    """Add chunks.authority to existing databases and classify what is already there.

    Spaces indexed before source authority existed hold thousands of chat-transcript
    chunks marked as nothing in particular. Backfilling once at migration time means
    retrieval can filter in SQL instead of running a regex over every hit.
    """
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(chunks)")}
    except sqlite3.Error:
        return
    if "authority" not in cols:
        try:
            # No DEFAULT: existing rows must come out NULL so they are distinguishable
            # from rows genuinely classified as documents. Defaulting to 'document'
            # silently marked 1178 chat-transcript chunks as trustworthy.
            conn.execute("ALTER TABLE chunks ADD COLUMN authority TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_authority ON chunks(space_id, authority)"
            )
        except sqlite3.Error:
            return
    # Backfill through the same classifier retrieval uses, not a LIKE approximation —
    # SQL patterns loose enough to catch `sources/chat_126.md` also catch
    # `docs/chat_ui_notes.md`, which is a document about chat, not a transcript.
    from rag import authority as authority_mod

    # user_version gates the one-off full reclassification. An earlier build of this
    # migration added the column with DEFAULT 'document', so rows on those databases
    # carry a confident-but-wrong value that a "WHERE authority IS NULL" pass would
    # skip forever. Version 1 re-derives every row exactly once; after that only
    # unclassified rows are touched.
    try:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
    except sqlite3.Error:
        version = 0

    where = "" if version < AUTHORITY_SCHEMA_VERSION else "WHERE authority IS NULL OR authority = ''"
    try:
        rows = conn.execute(f"SELECT id, path, heading FROM chunks {where}").fetchall()
    except sqlite3.Error:
        return

    if rows:
        updates = [(authority_mod.classify(r[1] or "", r[2] or ""), r[0]) for r in rows]
        try:
            conn.executemany("UPDATE chunks SET authority=? WHERE id=?", updates)
        except sqlite3.Error:
            return
    if version < AUTHORITY_SCHEMA_VERSION:
        try:
            conn.execute(f"PRAGMA user_version = {AUTHORITY_SCHEMA_VERSION}")
        except sqlite3.Error:
            pass


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


def purge_chat_sources(space_id: int) -> dict:
    """Remove ingested chat_*.md transcript sources so they stop competing with real docs.

    RAG chat *sessions* (rag_chats) are untouched — only frozen transcript files that were
    attached as knowledge sources. Authority already refuses to cite them; this clears the
    pile when a space has swallowed hundreds of past chats (e.g. Space 5).
    """
    from rag import authority

    init()
    sid = int(space_id)
    removed = 0
    chunks = 0
    for src in list_sources(sid):
        # Origin-aware: pack-prefixed names defeat path regex; meta/chunks still know.
        kind = resolve_source_authority(src) or source_authority(int(src["id"]))
        if kind != authority.CONVERSATION:
            continue
        out = delete_source(int(src["id"]))
        if out.get("ok"):
            removed += 1
            chunks += int(out.get("chunks_removed") or 0)
    return {
        "ok": True,
        "space_id": sid,
        "sources_removed": removed,
        "chunks_removed": chunks,
    }


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


def source_authority(source_id: int) -> str:
    """The class the chunks of this source were written with.

    Export reads this so a pack carries how the material entered, not just what
    the file is called. Without it, re-importing a chat transcript under a
    pack-prefixed name would classify it as a document and make a past answer
    citable as evidence.
    """
    init()
    with _conn() as conn:
        row = conn.execute(
            "SELECT authority, COUNT(*) AS n FROM chunks WHERE source_id=? "
            "GROUP BY authority ORDER BY n DESC LIMIT 1",
            (int(source_id),),
        ).fetchone()
    return (row["authority"] if row and row["authority"] else "") or ""


def resolve_source_authority(src: dict) -> str:
    """Decide authority from how the source entered, not the live path alone.

    Path regex is a fallback — pack members are named ``0001__chat_126.md``, which
    defeats ``classify``. Prefer declared meta, then original basename, then path.
    """
    from rag import authority as authority_mod

    meta = src.get("meta") if isinstance(src.get("meta"), dict) else {}
    declared = str(meta.get("authority") or "").strip().lower()
    if declared in (
        authority_mod.DOCUMENT,
        authority_mod.WEB,
        authority_mod.CONVERSATION,
    ):
        return declared
    orig = str(meta.get("original_path") or "").strip()
    title = str(src.get("title") or "")
    if orig:
        return authority_mod.classify(orig, title or Path(orig).name)
    return authority_mod.classify(str(src.get("path") or ""), title)


def scrub_authority(space_id: int | None = None, *, dry_run: bool = False) -> dict:
    """Reclassify chunks from each source's origin (meta), closing the pre-tag gap.

    Spaces indexed before ingest-time authority — or imported under pack-prefixed
    names without a surviving class — still carry whatever path migration guessed.
    This pass keys on ``meta.authority`` / ``meta.original_path`` first.
    """
    init()
    spaces = [int(space_id)] if space_id is not None else [
        int(s["id"]) for s in list_spaces(include_archived=True)
    ]
    sources_checked = 0
    sources_changed = 0
    chunks_updated = 0
    details: list[dict] = []
    for sid in spaces:
        for src in list_sources(sid):
            sources_checked += 1
            want = resolve_source_authority(src) or "document"
            cur = source_authority(int(src["id"])) or ""
            meta = dict(src.get("meta") if isinstance(src.get("meta"), dict) else {})
            # Stamp meta even when chunk classes already match — origin must survive
            # a later path-only re-derivation. Only count as "changed" when something moved.
            chunk_mismatch = cur != want
            meta_needs = meta.get("authority") != want or (
                not meta.get("original_path")
            )
            if not chunk_mismatch and not meta_needs:
                continue
            n = 0
            if not dry_run:
                with _conn() as conn:
                    if chunk_mismatch:
                        cur_ex = conn.execute(
                            "UPDATE chunks SET authority=? WHERE source_id=? AND "
                            "(authority IS NULL OR authority='' OR authority!=?)",
                            (want[:20], int(src["id"]), want[:20]),
                        )
                        n = int(cur_ex.rowcount or 0)
                meta["authority"] = want
                if not meta.get("original_path"):
                    meta["original_path"] = Path(str(src.get("path") or src.get("title") or "")).name
                update_source_status(int(src["id"]), str(src.get("status") or "ready"), meta=meta)
            else:
                with _conn() as conn:
                    n = int(
                        conn.execute(
                            "SELECT COUNT(*) AS n FROM chunks WHERE source_id=? AND "
                            "(authority IS NULL OR authority='' OR authority!=?)",
                            (int(src["id"]), want[:20]),
                        ).fetchone()["n"]
                        or 0
                    )
            if chunk_mismatch or meta_needs:
                sources_changed += 1
                chunks_updated += n
                details.append(
                    {
                        "space_id": sid,
                        "source_id": int(src["id"]),
                        "from": cur or "(none)",
                        "to": want,
                        "chunks": n,
                    }
                )
    return {
        "ok": True,
        "dry_run": bool(dry_run),
        "spaces": len(spaces),
        "sources_checked": sources_checked,
        "sources_changed": sources_changed,
        "chunks_updated": chunks_updated,
        "changes": details[:50],
    }


def list_sources(space_id: int) -> list[dict]:
    init()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sources WHERE space_id=? ORDER BY id DESC",
            (int(space_id),),
        ).fetchall()
        return [_row(r) for r in rows]  # type: ignore[misc]


def get_source(source_id: int) -> dict | None:
    init()
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM sources WHERE id=?", (int(source_id),)
        ).fetchone()
        return _row(row) if row else None  # type: ignore[misc]


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
        _delete_fts_by_ids(conn, "chunks_fts", "chunk_id", ids)
        conn.execute("DELETE FROM chunks WHERE space_id=?", (int(space_id),))
        fids = [int(r["id"]) for r in conn.execute("SELECT id FROM file_index WHERE space_id=?", (int(space_id),))]
        _delete_fts_by_ids(conn, "file_index_fts", "file_id", fids)
        conn.execute("DELETE FROM file_index WHERE space_id=?", (int(space_id),))


# SQLite caps host parameters per statement (999 on older builds). A space with
# more chunks than that made rebuild die with "too many SQL variables" instead of
# rebuilding, so the delete is chunked rather than one giant IN (...).
_SQL_VARS_PER_BATCH = 800


def _delete_fts_by_ids(conn: sqlite3.Connection, table: str, column: str, ids: list[int]) -> None:
    for start in range(0, len(ids), _SQL_VARS_PER_BATCH):
        batch = ids[start : start + _SQL_VARS_PER_BATCH]
        marks = ",".join("?" * len(batch))
        conn.execute(f"DELETE FROM {table} WHERE {column} IN ({marks})", batch)


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
    authority: str = "",
) -> int:
    init()
    now = time.time()
    # Decided once, at write time. Re-deriving the class from a path regex on every
    # retrieved hit is both slower and fragile — a renamed or relocated file would
    # silently change how much the engine is willing to believe it.
    if not authority:
        from rag import authority as authority_mod

        authority = authority_mod.classify(path, heading)
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO chunks(space_id,source_id,revision_id,parent_id,kind,text,path,heading,page,"
            "span_start,span_end,token_est,meta,authority,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                (authority or "document")[:20],
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
    """Chats for a space, plus a rough preview for the Chats tab cards.

    ``preview`` = first user message; ``summary`` prefers last assistant reply
    (falls back to the user ask) so the card is readable without opening the thread.
    """
    init()
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT c.*,
              (SELECT m.content FROM rag_messages m
               WHERE m.chat_id=c.id AND m.role='user'
               ORDER BY m.id ASC LIMIT 1) AS preview,
              (SELECT m.content FROM rag_messages m
               WHERE m.chat_id=c.id AND m.role='assistant'
               ORDER BY m.id DESC LIMIT 1) AS last_answer
            FROM rag_chats c
            WHERE c.space_id=?
            ORDER BY c.updated_at DESC
            """,
            (int(space_id),),
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            d = _row(r)  # type: ignore[arg-type]
            prev = str(d.get("preview") or "").strip()
            ans = str(d.get("last_answer") or "").strip()
            rough = (ans or prev).replace("\n", " ").strip()
            d["summary"] = rough[:220] if rough else ""
            out.append(d)
        return out


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

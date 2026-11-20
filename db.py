"""SQLite storage for ClipDrop chat messages."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import re

from config import DATA_DIR, ROOT, ensure_dirs

ensure_dirs()
DB_PATH = DATA_DIR / "clipdrop.db"
FILES = DATA_DIR / "files"
THUMBS = DATA_DIR / "thumbs"

_lock = threading.Lock()

FIXED_CATEGORIES = [
    ("general", "General"),
    ("engineering", "Engineering"),
    ("finance", "Finance"),
    ("ml", "Machine Learning"),
]

MODE_TO_CATEGORY = {
    "general": "general",
    "engineering": "engineering",
    "finance": "finance",
    "ml": "ml",
}


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    FILES.mkdir(parents=True, exist_ok=True)
    THUMBS.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_ip TEXT,
                device_name TEXT NOT NULL,
                text TEXT DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'text',
                filename TEXT,
                filepath TEXT,
                thumb TEXT,
                mime TEXT,
                size INTEGER DEFAULT 0,
                source TEXT DEFAULT 'chat',
                content_hash TEXT,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS seen_hashes (
                hash TEXT PRIMARY KEY,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS devices (
                ip TEXT PRIMARY KEY,
                name TEXT,
                user_agent TEXT,
                last_seen REAL
            );
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT 'New chat',
                project_id INTEGER DEFAULT 0,
                capture_type TEXT DEFAULT 'manual',
                summary TEXT DEFAULT '',
                related_to TEXT DEFAULT '',
                vault_path TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                category TEXT DEFAULT 'general',
                description TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at DESC);
        """)
        # migrate older DBs
        cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
        if "source" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN source TEXT DEFAULT 'chat'")
        if "content_hash" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN content_hash TEXT")
        if "ai_analysis" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN ai_analysis TEXT DEFAULT ''")
        if "ai_status" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN ai_status TEXT DEFAULT 'none'")
        if "ai_model" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN ai_model TEXT DEFAULT ''")
        if "vision_cache" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN vision_cache TEXT DEFAULT ''")
        if "ai_category" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN ai_category TEXT DEFAULT ''")
        if "session_id" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN session_id INTEGER DEFAULT 0")
        # migrate chat_sessions
        scols = {r[1] for r in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()}
        for col, sql in (
            ("project_id", "ALTER TABLE chat_sessions ADD COLUMN project_id INTEGER DEFAULT 0"),
            ("capture_type", "ALTER TABLE chat_sessions ADD COLUMN capture_type TEXT DEFAULT 'manual'"),
            ("summary", "ALTER TABLE chat_sessions ADD COLUMN summary TEXT DEFAULT ''"),
            ("related_to", "ALTER TABLE chat_sessions ADD COLUMN related_to TEXT DEFAULT ''"),
            ("vault_path", "ALTER TABLE chat_sessions ADD COLUMN vault_path TEXT DEFAULT ''"),
        ):
            if col not in scols:
                conn.execute(sql)
        if "category" not in scols:
            conn.execute("ALTER TABLE chat_sessions ADD COLUMN category TEXT DEFAULT 'general'")
        if "pinned" not in scols:
            conn.execute("ALTER TABLE chat_sessions ADD COLUMN pinned INTEGER DEFAULT 0")
        if "archived" not in scols:
            conn.execute("ALTER TABLE chat_sessions ADD COLUMN archived INTEGER DEFAULT 0")
        pcols = {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
        if "category" not in pcols:
            conn.execute("ALTER TABLE projects ADD COLUMN category TEXT DEFAULT 'general'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_hash ON messages(content_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS hub_peers (
                ip TEXT PRIMARY KEY,
                device_id TEXT DEFAULT '',
                display_name TEXT DEFAULT '',
                access_level TEXT DEFAULT 'read_write',
                join_method TEXT DEFAULT 'lan',
                logged_in INTEGER DEFAULT 0,
                admin_name TEXT DEFAULT '',
                chat_sessions TEXT DEFAULT '',
                created_at REAL,
                updated_at REAL,
                last_seen REAL
            );
            CREATE TABLE IF NOT EXISTS hub_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT,
                device_id TEXT,
                event_type TEXT,
                detail TEXT,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_hub_events_created ON hub_events(created_at DESC);
        """)
        conn.commit()
    ensure_default_projects()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["date"] = datetime.fromtimestamp(d["created_at"]).strftime("%Y-%m-%d")
    d["time"] = datetime.fromtimestamp(d["created_at"]).strftime("%H:%M:%S")
    d["datetime"] = datetime.fromtimestamp(d["created_at"]).strftime("%Y-%m-%d %H:%M:%S")
    d.setdefault("ai_analysis", "")
    d.setdefault("ai_status", "none")
    d.setdefault("ai_model", "")
    d.setdefault("vision_cache", "")
    d.setdefault("ai_category", "")
    d.setdefault("session_id", 0)
    return d


def register_device(ip: str, name: str, ua: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO devices(ip,name,user_agent,last_seen) VALUES(?,?,?,?) "
            "ON CONFLICT(ip) DO UPDATE SET name=excluded.name,user_agent=excluded.user_agent,last_seen=excluded.last_seen",
            (ip, name, ua[:200], time.time()),
        )
        conn.commit()


def list_devices() -> list[dict]:
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT * FROM devices ORDER BY last_seen DESC LIMIT 20").fetchall()
    return [dict(r) for r in rows]


def upsert_hub_peer(
    ip: str,
    *,
    device_id: str = "",
    display_name: str = "",
    access_level: str = "",
    join_method: str = "",
    logged_in: bool | None = None,
    admin_name: str = "",
    chat_sessions: str = "",
) -> dict:
    ip = (ip or "").strip()
    # Never persist URL-encoded ghost keys (2a02%3A… from kick without unquote).
    if not ip or "%" in ip:
        return {}
    now = time.time()
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM hub_peers WHERE ip=?", (ip,)).fetchone()
        if row:
            cur = dict(row)
            if device_id:
                cur["device_id"] = device_id[:80]
            if display_name:
                cur["display_name"] = display_name[:120]
            if access_level:
                cur["access_level"] = access_level[:40]
            if join_method:
                cur["join_method"] = join_method[:40]
            if logged_in is not None:
                cur["logged_in"] = 1 if logged_in else 0
            if admin_name:
                cur["admin_name"] = admin_name[:120]
            if chat_sessions:
                cur["chat_sessions"] = chat_sessions[:200]
            cur["last_seen"] = now
            cur["updated_at"] = now
            conn.execute(
                "UPDATE hub_peers SET device_id=?, display_name=?, access_level=?, join_method=?, "
                "logged_in=?, admin_name=?, chat_sessions=?, updated_at=?, last_seen=? WHERE ip=?",
                (
                    cur["device_id"], cur["display_name"], cur["access_level"],
                    cur["join_method"], cur["logged_in"], cur["admin_name"],
                    cur["chat_sessions"], cur["updated_at"], cur["last_seen"], ip,
                ),
            )
        else:
            cur = {
                "ip": ip,
                "device_id": (device_id or ip)[:80],
                "display_name": (display_name or ip)[:120],
                "access_level": (access_level or "read_write")[:40],
                "join_method": (join_method or "lan")[:40],
                "logged_in": 1 if logged_in else 0,
                "admin_name": admin_name[:120],
                "chat_sessions": chat_sessions[:200],
                "created_at": now,
                "updated_at": now,
                "last_seen": now,
            }
            conn.execute(
                "INSERT INTO hub_peers(ip,device_id,display_name,access_level,join_method,"
                "logged_in,admin_name,chat_sessions,created_at,updated_at,last_seen) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ip, cur["device_id"], cur["display_name"], cur["access_level"],
                    cur["join_method"], cur["logged_in"], cur["admin_name"],
                    cur["chat_sessions"], cur["created_at"], cur["updated_at"], cur["last_seen"],
                ),
            )
        conn.commit()
    return cur


def get_hub_peer(ip: str) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM hub_peers WHERE ip=?", ((ip or "").strip(),)).fetchone()
    return dict(row) if row else None


def delete_hub_peer(ip: str) -> bool:
    """Remove a hub peer row. Returns True if a row was deleted."""
    ip = (ip or "").strip()
    if not ip:
        return False
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM hub_peers WHERE ip=?", (ip,))
        conn.commit()
        return cur.rowcount > 0


def delete_hub_peers_like(ips: list[str]) -> int:
    """Delete many peer rows (exact IP match). Returns count deleted."""
    cleaned = [((ip or "").strip()) for ip in ips if (ip or "").strip()]
    if not cleaned:
        return 0
    with _lock, _connect() as conn:
        n = 0
        for ip in cleaned:
            cur = conn.execute("DELETE FROM hub_peers WHERE ip=?", (ip,))
            n += cur.rowcount
        conn.commit()
        return n


def purge_junk_hub_peers() -> int:
    """Drop URL-encoded ghost IPs created by kick/acl without unquote (%3A / %253A)."""
    with _lock, _connect() as conn:
        # Any IP key that still contains % is not a real address.
        cur = conn.execute("DELETE FROM hub_peers WHERE ip LIKE '%\\%%' ESCAPE '\\'")
        # Also wipe the same junk from devices so they don't reappear via list_devices.
        cur2 = conn.execute("DELETE FROM devices WHERE ip LIKE '%\\%%' ESCAPE '\\'")
        conn.commit()
        return int(cur.rowcount or 0) + int(cur2.rowcount or 0)


def list_hub_peers(limit: int = 50) -> list[dict]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM hub_peers ORDER BY last_seen DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
    return [dict(r) for r in rows]


def find_hub_peer_by_device_id(device_id: str) -> dict | None:
    device_id = (device_id or "").strip()
    if not device_id:
        return None
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM hub_peers WHERE device_id=? ORDER BY last_seen DESC LIMIT 1",
            (device_id,),
        ).fetchone()
    return dict(row) if row else None


def log_hub_event(ip: str, event_type: str, detail: str = "", device_id: str = "") -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO hub_events(ip,device_id,event_type,detail,created_at) VALUES(?,?,?,?,?)",
            ((ip or "")[:64], (device_id or "")[:80], (event_type or "")[:40], (detail or "")[:500], time.time()),
        )
        conn.commit()


def list_hub_events(limit: int = 100, ip: str = "") -> list[dict]:
    with _lock, _connect() as conn:
        if ip:
            rows = conn.execute(
                "SELECT * FROM hub_events WHERE ip=? ORDER BY created_at DESC LIMIT ?",
                (ip, max(1, min(limit, 500))),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM hub_events ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
    return [dict(r) for r in rows]


def hash_seen(content_hash: str) -> bool:
    if not content_hash:
        return False
    with _lock, _connect() as conn:
        row = conn.execute("SELECT 1 FROM seen_hashes WHERE hash=?", (content_hash,)).fetchone()
        if row:
            return True
        row = conn.execute("SELECT 1 FROM messages WHERE content_hash=? LIMIT 1", (content_hash,)).fetchone()
    return bool(row)


def claim_hash(content_hash: str) -> bool:
    """Atomically claim a content hash for first publish. True = this caller won."""
    if not content_hash:
        return False
    with _lock, _connect() as conn:
        if conn.execute("SELECT 1 FROM seen_hashes WHERE hash=?", (content_hash,)).fetchone():
            return False
        if conn.execute(
            "SELECT 1 FROM messages WHERE content_hash=? LIMIT 1", (content_hash,)
        ).fetchone():
            conn.execute(
                "INSERT OR IGNORE INTO seen_hashes(hash,created_at) VALUES(?,?)",
                (content_hash, time.time()),
            )
            conn.commit()
            return False
        cur = conn.execute(
            "INSERT OR IGNORE INTO seen_hashes(hash,created_at) VALUES(?,?)",
            (content_hash, time.time()),
        )
        conn.commit()
        return cur.rowcount > 0


def mark_hash(content_hash: str) -> None:
    if not content_hash:
        return
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_hashes(hash,created_at) VALUES(?,?)",
            (content_hash, time.time()),
        )
        conn.commit()


def get_message(msg_id: int) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
    return _row_to_dict(row) if row else None


def update_ai(msg_id: int, *, status: str, analysis: str = "", model: str = "", vision_cache: str = "", ai_category: str = "") -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE messages SET ai_status=?, ai_analysis=?, ai_model=?, vision_cache=?, ai_category=? WHERE id=?",
            (status, analysis, model, vision_cache, ai_category, msg_id),
        )
        conn.commit()


def get_latest_image_context(session_id: int) -> dict | None:
    """Most recent analyzed image in session for AI follow-up."""
    if not session_id:
        return None
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE session_id=? AND kind='image' "
            "AND (vision_cache != '' OR ai_analysis != '') ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (name or "uncategorized").lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s[:56] or "uncategorized"


def ensure_default_projects() -> None:
    now = time.time()
    with _lock, _connect() as conn:
        for key, name in FIXED_CATEGORIES:
            slug = _slug(name)
            row = conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO projects(name,slug,category,created_at,updated_at) VALUES(?,?,?,?,?)",
                    (name, slug, key, now, now),
                )
        conn.commit()


def get_or_create_project(name: str, category: str = "general") -> dict:
    name = (name or "General").strip()[:80]
    cat = category if category in dict(FIXED_CATEGORIES) else "general"
    slug = _slug(name)
    now = time.time()
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE slug=?", (slug,)).fetchone()
        if row:
            conn.execute("UPDATE projects SET updated_at=?, category=? WHERE id=?", (now, cat, row["id"]))
            conn.commit()
            return dict(conn.execute("SELECT * FROM projects WHERE id=?", (row["id"],)).fetchone())
        cur = conn.execute(
            "INSERT INTO projects(name,slug,category,created_at,updated_at) VALUES(?,?,?,?,?)",
            (name, slug, cat, now, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM projects WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


def create_project_under_category(name: str, category: str) -> dict:
    cat = category if category in dict(FIXED_CATEGORIES) else "general"
    return get_or_create_project(name, category=cat)


def list_projects(limit: int = 200) -> list[dict]:
    """Every project row, newest touched first - what POST /api/projects wrote."""
    ensure_default_projects()
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM chat_sessions s WHERE s.project_id=p.id) as session_count "
            "FROM projects p ORDER BY p.updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_project(project_id: int) -> dict | None:
    """One project row, or None. Callers use this to refuse an unknown id."""
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (int(project_id),)).fetchone()
    return dict(row) if row else None


def get_default_project_for_category(category: str) -> dict:
    cat = category if category in dict(FIXED_CATEGORIES) else "general"
    label = dict(FIXED_CATEGORIES)[cat]
    return get_or_create_project(label, category=cat)


def update_session_meta(
    session_id: int,
    *,
    title: str | None = None,
    project_id: int | None = None,
    summary: str | None = None,
    related_to: str | None = None,
    vault_path: str | None = None,
    category: str | None = None,
    pinned: int | bool | None = None,
    archived: int | bool | None = None,
) -> None:
    fields, vals = [], []
    if title is not None:
        fields.append("title=?"); vals.append(title)
    if project_id is not None:
        fields.append("project_id=?"); vals.append(project_id)
    if summary is not None:
        fields.append("summary=?"); vals.append(summary[:500])
    if related_to is not None:
        fields.append("related_to=?"); vals.append(related_to[:200])
    if vault_path is not None:
        fields.append("vault_path=?"); vals.append(vault_path)
    if category is not None:
        fields.append("category=?"); vals.append(category[:20])
    if pinned is not None:
        fields.append("pinned=?"); vals.append(1 if pinned else 0)
    if archived is not None:
        fields.append("archived=?"); vals.append(1 if archived else 0)
    if not fields:
        return
    fields.append("updated_at=?"); vals.append(time.time())
    vals.append(session_id)
    with _lock, _connect() as conn:
        conn.execute(f"UPDATE chat_sessions SET {', '.join(fields)} WHERE id=?", vals)
        conn.commit()


def create_capture_session(source: str) -> dict:
    """Dedicated session for AI photo capture (non-screenshot)."""
    now = time.time()
    label = "Photo" if source == "chat" else ("Screenshot" if source == "screenshot" else "Capture")
    title = f"{label} {datetime.now().strftime('%b %d %H:%M')}"
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO chat_sessions(title,capture_type,created_at,updated_at,category) VALUES(?,?,?,?,?)",
            (title, source, now, now, "general"),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM chat_sessions WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


DAILY_CLIPBOARD_TYPES = ("daily_clipboard", "daily_clipboard_text", "daily_clipboard_image")
DAILY_AI_SCREENSHOT_TYPE = "daily_ai_screenshot"
DAILY_SESSION_TYPES = DAILY_CLIPBOARD_TYPES + (DAILY_AI_SCREENSHOT_TYPE,)


def _daily_session_meta(kind: str) -> tuple[str, str, str]:
    """Return (calendar_day, capture_type, title) for text|image|screenshot daily chats."""
    day = datetime.now().strftime("%Y-%m-%d")
    label = datetime.now().strftime("%b %d")
    if kind == "image":
        return day, "daily_clipboard_image", f"Images · {label}"
    if kind == "screenshot":
        return day, DAILY_AI_SCREENSHOT_TYPE, f"AI Screenshot Chat · {label}"
    return day, "daily_clipboard_text", f"Text · {label}"


def get_or_create_daily_session(kind: str = "text") -> dict:
    """One chat per calendar day per kind: text clipboard, image clipboard, or AI screenshots."""
    now = time.time()
    day, capture_type, title = _daily_session_meta(kind)
    with _lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM chat_sessions
            WHERE capture_type=?
              AND date(created_at, 'unixepoch', 'localtime') = ?
              AND COALESCE(archived,0)=0
            ORDER BY id DESC LIMIT 1
            """,
            (capture_type, day),
        ).fetchone()
        if row:
            # Keep user renames — only bump updated_at (do not reset daily title)
            conn.execute("UPDATE chat_sessions SET updated_at=? WHERE id=?", (now, row["id"]))
            conn.commit()
            return dict(conn.execute("SELECT * FROM chat_sessions WHERE id=?", (row["id"],)).fetchone())
        cur = conn.execute(
            "INSERT INTO chat_sessions(title,capture_type,created_at,updated_at,category) VALUES(?,?,?,?,?)",
            (title, capture_type, now, now, "general"),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM chat_sessions WHERE id=?", (cur.lastrowid,)).fetchone())


def get_or_create_daily_text_session() -> dict:
    return get_or_create_daily_session("text")


def get_or_create_daily_image_session() -> dict:
    return get_or_create_daily_session("image")


def get_or_create_daily_screenshot_session() -> dict:
    """One AI Screenshot Chat per calendar day for Win+Shift+S / Screenshots folder captures."""
    return get_or_create_daily_session("screenshot")


def hash_seen_in_session(content_hash: str, session_id: int) -> bool:
    """True if this hash already exists inside the given chat (session-scoped dedup)."""
    if not content_hash or not session_id:
        return False
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM messages WHERE content_hash=? AND session_id=? LIMIT 1",
            (content_hash, session_id),
        ).fetchone()
    return bool(row)


def message_by_hash_in_session(content_hash: str, session_id: int) -> dict | None:
    """The message in this chat that already holds this file, if any."""
    if not content_hash or not session_id:
        return None
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE content_hash=? AND session_id=? ORDER BY id DESC LIMIT 1",
            (content_hash, session_id),
        ).fetchone()
    return _row_to_dict(row) if row else None


def prune_empty_screenshot_sessions() -> int:
    """Back-compat alias — prunes empty screenshot + empty daily orphans."""
    return prune_empty_orphan_sessions()


def prune_empty_orphan_sessions() -> int:
    """Remove empty unpinned junk: Screenshot orphans, old empty daily_* rows, blank New chat.

    Today's empty daily_* chats are kept briefly so get_or_create → post_message
    cannot race with list_sessions and delete the row mid-ingest.
    """
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT s.id FROM chat_sessions s
            WHERE COALESCE(s.archived,0)=0
              AND COALESCE(s.pinned,0)=0
              AND (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id)=0
              AND (
                s.capture_type='screenshot'
                OR s.title LIKE 'Screenshot %'
                OR s.capture_type='scratch'
                OR LOWER(TRIM(COALESCE(s.title,''))) IN ('', 'new chat')
                OR (
                  s.capture_type IN (
                    'daily_clipboard','daily_clipboard_text','daily_clipboard_image','daily_ai_screenshot'
                  )
                  AND date(s.created_at, 'unixepoch', 'localtime') < date('now', 'localtime')
                )
              )
            """
        ).fetchall()
        ids = [int(r["id"]) for r in rows]
        for sid in ids:
            conn.execute("DELETE FROM chat_sessions WHERE id=?", (sid,))
            _drop_chat_prefs(conn, sid)
        conn.commit()
    return len(ids)


def get_or_create_daily_clipboard_session() -> dict:
    """Legacy combined daily chat — kept for old rows; new captures use text/image split."""
    now = time.time()
    day = datetime.now().strftime("%Y-%m-%d")
    title = f"Clipboard · {datetime.now().strftime('%b %d')}"
    with _lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM chat_sessions
            WHERE capture_type='daily_clipboard'
              AND date(created_at, 'unixepoch', 'localtime') = ?
              AND COALESCE(archived,0)=0
            ORDER BY id DESC LIMIT 1
            """,
            (day,),
        ).fetchone()
        if row:
            # Keep user renames — only bump updated_at
            conn.execute("UPDATE chat_sessions SET updated_at=? WHERE id=?", (now, row["id"]))
            conn.commit()
            return dict(conn.execute("SELECT * FROM chat_sessions WHERE id=?", (row["id"],)).fetchone())
        cur = conn.execute(
            "INSERT INTO chat_sessions(title,capture_type,created_at,updated_at,category) VALUES(?,?,?,?,?)",
            (title, "daily_clipboard", now, now, "general"),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM chat_sessions WHERE id=?", (cur.lastrowid,)).fetchone())


def _summarize_session_title(title: str) -> str:
    """Short Claude-like chat title from first user line or AI SESSION_TITLE."""
    t = re.sub(r"\s+", " ", (title or "").strip())
    t = re.sub(r"^(hey|hi|hello|please|can you|could you|would you)\b[:\s,]*", "", t, flags=re.I)
    t = t.split("\n", 1)[0].strip(" \t-–—:|")
    t = re.sub(r"[?!.]+$", "", t).strip()
    if len(t) > 56:
        cut = t[:54]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        t = cut + "…"
    return t[:80] if t else "New chat"


def maybe_set_ai_session_title(session_id: int, title: str, summary: str = "") -> None:
    """First AI response / user line becomes the chat title (when still a placeholder)."""
    if not session_id or not title:
        return
    title = _summarize_session_title(title)
    with _lock, _connect() as conn:
        row = conn.execute("SELECT title, capture_type FROM chat_sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            return
        # Daily chats keep their date title forever
        if row["capture_type"] in DAILY_SESSION_TYPES:
            if summary:
                conn.execute(
                    "UPDATE chat_sessions SET summary=?, updated_at=? WHERE id=?",
                    (summary[:280], time.time(), session_id),
                )
                conn.commit()
            return
        cur = (row["title"] or "").strip()
        placeholders = (
            cur.startswith("New chat")
            or cur.startswith("Screenshot ")
            or cur.startswith("Photo ")
            or cur.startswith("Capture ")
            or cur.startswith("Clipboard ")
            or cur.startswith("Text ·")
            or cur.startswith("Images ·")
            or cur.startswith("AI Screenshot Chat")
            or cur == "New chat"
            or not cur
        )
        if not placeholders:
            return  # already titled from first AI reply — keep it
        fields = ["title=?", "updated_at=?"]
        vals: list = [title, time.time()]
        if summary:
            fields.append("summary=?")
            vals.append(summary[:280])
        vals.append(session_id)
        conn.execute(f"UPDATE chat_sessions SET {', '.join(fields)} WHERE id=?", vals)
        conn.commit()


def create_session(
    title: str = "New chat",
    capture_type: str = "manual",
    *,
    related_to: str = "",
    category: str = "general",
) -> dict:
    now = time.time()
    cat = category if category in dict(FIXED_CATEGORIES) else "general"
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO chat_sessions(title,capture_type,created_at,updated_at,related_to,category) VALUES(?,?,?,?,?,?)",
            (title, capture_type, now, now, (related_to or "")[:200], cat),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM chat_sessions WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


def create_reply_session(
    parent_id: int,
    title: str,
    reply_snippet: str,
    category: str = "general",
) -> dict:
    """Branch chat replying to a parent session; seeds summary from quoted snippet."""
    related = f"session:{int(parent_id)}" if parent_id else ""
    snippet = (reply_snippet or "").strip()
    title = (title or "Reply")[:80]
    cat = category if category in dict(FIXED_CATEGORIES) else "general"
    now = time.time()
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO chat_sessions(title,capture_type,created_at,updated_at,category,related_to,summary) "
            "VALUES(?,?,?,?,?,?,?)",
            (title, "ai", now, now, cat, related[:200], snippet[:280]),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM chat_sessions WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


def get_session(session_id: int) -> dict | None:
    """One session row by id, or None. No pruning — callers may hold a stale id."""
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE id=?", (int(session_id),)
        ).fetchone()
    return dict(row) if row else None


def list_sessions(limit: int = 50, offset: int = 0) -> list[dict]:
    try:
        prune_empty_orphan_sessions()
    except Exception:
        pass
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) as msg_count, "
            "(SELECT substr(COALESCE(NULLIF(m2.text,''), m2.filename, ''),1,80) FROM messages m2 "
            " WHERE m2.session_id=s.id ORDER BY m2.id DESC LIMIT 1) as preview "
            "FROM chat_sessions s WHERE COALESCE(s.archived,0)=0 "
            "ORDER BY COALESCE(s.pinned,0) DESC, s.updated_at DESC, s.id DESC LIMIT ? OFFSET ?",
            (limit, max(0, int(offset))),
        ).fetchall()
    return [dict(r) for r in rows]


def first_session_of_type(capture_type: str) -> dict | None:
    """The newest chat of a kind (e.g. 'scratch'), however old. list_sessions only sees a page."""
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE capture_type=? AND COALESCE(archived,0)=0 "
            "ORDER BY updated_at DESC, id DESC LIMIT 1", (capture_type,),
        ).fetchone()
    return dict(row) if row else None


def count_sessions() -> int:
    """Chats that show in the list (the same filter list_sessions uses)."""
    with _lock, _connect() as conn:
        row = conn.execute("SELECT COUNT(*) FROM chat_sessions WHERE COALESCE(archived,0)=0").fetchone()
    return int(row[0] or 0)


def _resolve_date_filter(date_filter: str) -> str:
    """Normalize date filter to YYYY-MM-DD or empty."""
    raw = (date_filter or "").strip().lower()
    if not raw:
        return ""
    if raw == "today":
        return datetime.now().strftime("%Y-%m-%d")
    if raw == "yesterday":
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw
    return ""


def _search_like_variants(query: str) -> list[str]:
    """Build LIKE patterns with light typo tolerance (prefix / token splits)."""
    q = (query or "").strip()
    if not q:
        return []
    variants = [f"%{q}%"]
    for tok in re.split(r"\s+", q):
        if len(tok) >= 3:
            variants.append(f"%{tok}%")
            # drop one middle char for short-typo tolerance (e.g. helo → hello via hel/elo)
            if 4 <= len(tok) <= 12:
                mid = len(tok) // 2
                variants.append(f"%{tok[:mid]}%{tok[mid+1:]}%")
    # de-dupe preserve order
    out, seen = [], set()
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out[:8]


def search_messages_and_sessions(query: str = "", date_filter: str = "", limit: int = 80) -> dict:
    """Word search + optional calendar date (YYYY-MM-DD, today, yesterday). Typo-tolerant likes."""
    q = (query or "").strip()
    day = _resolve_date_filter(date_filter)
    likes = _search_like_variants(q)
    sessions: list[dict] = []
    messages: list[dict] = []
    with _lock, _connect() as conn:
        if q and likes:
            sess_clauses = " OR ".join(
                ["(s.title LIKE ? OR COALESCE(s.summary,'') LIKE ?)"] * len(likes)
            )
            sess_sql = (
                "SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) as msg_count "
                f"FROM chat_sessions s WHERE COALESCE(s.archived,0)=0 AND ({sess_clauses})"
            )
            sess_args: list = []
            for like in likes:
                sess_args.extend([like, like])
            if day:
                sess_sql += " AND date(COALESCE(s.updated_at,s.created_at), 'unixepoch', 'localtime') = ?"
                sess_args.append(day)
            sess_sql += " ORDER BY s.updated_at DESC LIMIT ?"
            sess_args.append(limit)
            sessions = [dict(r) for r in conn.execute(sess_sql, sess_args).fetchall()]

            msg_clauses = " OR ".join(
                ["(m.text LIKE ? OR COALESCE(m.filename,'') LIKE ? OR COALESCE(m.source,'') LIKE ?)"]
                * len(likes)
            )
            msg_sql = (
                "SELECT m.*, s.title as session_title FROM messages m "
                "LEFT JOIN chat_sessions s ON s.id = m.session_id "
                f"WHERE ({msg_clauses})"
            )
            msg_args: list = []
            for like in likes:
                msg_args.extend([like, like, like])
            if day:
                msg_sql += " AND date(m.created_at, 'unixepoch', 'localtime') = ?"
                msg_args.append(day)
            msg_sql += " ORDER BY m.id DESC LIMIT ?"
            msg_args.append(limit)
            messages = [_row_to_dict(r) for r in conn.execute(msg_sql, msg_args).fetchall()]
        elif day:
            sessions = [
                dict(r) for r in conn.execute(
                    """
                    SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) as msg_count
                    FROM chat_sessions s
                    WHERE COALESCE(s.archived,0)=0
                      AND date(COALESCE(s.updated_at,s.created_at), 'unixepoch', 'localtime') = ?
                    ORDER BY s.updated_at DESC LIMIT ?
                    """,
                    (day, limit),
                ).fetchall()
            ]
            messages = [
                _row_to_dict(r) for r in conn.execute(
                    "SELECT m.*, s.title as session_title FROM messages m "
                    "LEFT JOIN chat_sessions s ON s.id = m.session_id "
                    "WHERE date(m.created_at, 'unixepoch', 'localtime') = ? "
                    "ORDER BY m.id DESC LIMIT ?",
                    (day, limit),
                ).fetchall()
            ]
    return {"query": q, "date": day, "sessions": sessions, "messages": messages}


def list_vault_tree(limit_projects: int = 80) -> dict:
    """Fixed categories → sessions (all chats, including project_id=0)."""
    ensure_default_projects()
    tree = []
    with _lock, _connect() as conn:
        for key, label in FIXED_CATEGORIES:
            rows = conn.execute(
                """
                SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) as msg_count,
                       COALESCE(NULLIF(s.category,''), p.category, 'general') as eff_cat
                FROM chat_sessions s
                LEFT JOIN projects p ON p.id = s.project_id
                WHERE COALESCE(NULLIF(s.category,''), p.category, 'general') = ?
                ORDER BY s.updated_at DESC LIMIT 50
                """,
                (key,),
            ).fetchall()
            tree.append({
                "key": key,
                "name": label,
                "sessions": [dict(r) for r in rows],
                "projects": [],  # legacy shape
            })
    return {"categories": tree, "recent": list_sessions(200)}


def get_today_messages() -> list[dict]:
    today = datetime.now().strftime("%Y-%m-%d")
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM messages ORDER BY id ASC",
        ).fetchall()
    out = []
    for r in rows:
        m = _row_to_dict(r)
        if m["date"] == today:
            out.append(m)
    return out


def build_day_summary() -> dict:
    """Structured day digest: copies, AI asks, manual notes, AI learnings."""
    msgs = get_today_messages()
    today = datetime.now().strftime("%Y-%m-%d")
    copies: list[dict] = []
    asks: list[str] = []
    ai_replies: list[str] = []
    manual_notes: list[str] = []
    ai_learned: list[str] = []
    applied: list[str] = []

    for m in msgs:
        src = str(m.get("source") or "").lower()
        kind = str(m.get("kind") or "").lower()
        text = str(m.get("text") or "").strip()
        fname = str(m.get("filename") or "").strip()
        tlabel = m.get("time") or ""

        if src in ("clipboard", "screenshot") or (
            kind in ("image", "file", "text") and src in ("phone", "drop", "lan")
        ):
            label = fname or (text[:80] + ("…" if len(text) > 80 else "")) or kind or "item"
            copies.append({"time": tlabel, "kind": kind or src, "label": label, "source": src})

        if src == "ai-chat" and text:
            asks.append(text)
        elif src == "chat" and text and not m.get("ai_analysis"):
            manual_notes.append(text)

        if src == "ai" and text:
            ai_replies.append(text)

        if m.get("ai_status") == "done" and m.get("ai_analysis"):
            snippet = str(m.get("ai_analysis") or "").strip()
            if snippet:
                head = snippet.split("\n", 1)[0][:160]
                ai_learned.append(f"[{tlabel}] {head}" + ("…" if len(snippet) > 160 else ""))

        # Applied = short AI answers that look like actions / confirmations
        if src == "ai" and text and len(text) < 280:
            low = text.lower()
            if any(k in low for k in ("applied", "done", "saved", "updated", "created", "ok", "fallback")):
                applied.append(f"[{tlabel}] {text[:140]}")

    # Deduplicate asks / notes while preserving order
    def _uniq(seq: list[str], lim: int = 12) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for s in seq:
            key = s[:120].lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
            if len(out) >= lim:
                break
        return out

    asks_u = _uniq(asks, 10)
    manual_u = _uniq(manual_notes, 10)
    learned_u = _uniq(ai_learned, 10)
    applied_u = _uniq(applied, 8)
    replies_u = _uniq([r[:200] for r in ai_replies], 8)

    lines = [
        f"# AirGPT Day Summary — {today}\n",
        f"**Copied:** {len(copies)}  ·  **AI asks:** {len(asks_u)}  ·  "
        f"**Manual notes:** {len(manual_u)}  ·  **AI replies:** {len(ai_replies)}\n",
    ]
    lines.append("\n## Clipboard & captures\n")
    if copies:
        for c in copies[:20]:
            lines.append(f"- [{c['time']}] {c['kind']} · {c['label']}\n")
    else:
        lines.append("_Nothing copied today._\n")

    lines.append("\n## What you asked AI\n")
    if asks_u:
        for a in asks_u:
            lines.append(f"- {a[:220]}{'…' if len(a) > 220 else ''}\n")
    else:
        lines.append("_No AI chat questions today._\n")

    lines.append("\n## Manual mode — recorded\n")
    if manual_u:
        for n in manual_u:
            lines.append(f"- {n[:220]}{'…' if len(n) > 220 else ''}\n")
    else:
        lines.append("_No manual-mode notes today._\n")

    lines.append("\n## AI mode — learned\n")
    if learned_u:
        for n in learned_u:
            lines.append(f"- {n}\n")
    else:
        lines.append("_No screenshot/image analyses today._\n")

    lines.append("\n## AI mode — applied / short replies\n")
    if applied_u or replies_u:
        for n in (applied_u or replies_u):
            lines.append(f"- {n}\n")
    else:
        lines.append("_No short AI actions recorded._\n")

    lines.append("\n---\n*Local summary — stays on this PC.*\n")
    md = "".join(lines)
    return {
        "date": today,
        "markdown": md,
        "stats": {
            "copies": len(copies),
            "asks": len(asks_u),
            "manual": len(manual_u),
            "ai_replies": len(ai_replies),
            "learned": len(learned_u),
            "applied": len(applied_u),
            "total": len(msgs),
        },
        "copies": copies[:20],
        "asks": asks_u,
        "manual": manual_u,
        "learned": learned_u,
        "applied": applied_u or replies_u,
    }


def build_day_summary_markdown() -> str:
    return build_day_summary()["markdown"]


def touch_session(session_id: int) -> None:
    with _lock, _connect() as conn:
        conn.execute("UPDATE chat_sessions SET updated_at=? WHERE id=?", (time.time(), session_id))
        conn.commit()


def _drop_chat_prefs(conn, session_id: int) -> None:
    """A deleted chat takes its custom instructions with it (table is created lazily)."""
    try:
        conn.execute("DELETE FROM session_prefs WHERE session_id=?", (int(session_id),))
    except sqlite3.OperationalError:
        pass  # table never created: nothing to remove


def _forget_chat_memory(session_ids) -> None:
    """Memory rows, embeddings and vault notes a chat left behind go with it. A failure
    is raised, not swallowed: a chat that looks deleted but is still quoted is the bug."""
    import memory_index

    memory_index.forget_session(session_ids)


def delete_session(session_id: int) -> bool:
    _forget_chat_memory({int(session_id)})
    with _lock, _connect() as conn:
        ids = [int(r[0]) for r in conn.execute("SELECT id FROM messages WHERE session_id=?", (session_id,)).fetchall()]
    for mid in ids:
        delete_message(mid)
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,))
        _drop_chat_prefs(conn, session_id)
        conn.commit()
    return True


def clear_all_messages() -> int:
    _forget_chat_memory(None)
    with _lock, _connect() as conn:
        ids = [int(r[0]) for r in conn.execute("SELECT id FROM messages").fetchall()]
    for mid in ids:
        delete_message(mid)
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM seen_hashes")
        conn.commit()
    _purge_orphan_media()
    return len(ids)


def _purge_orphan_media() -> None:
    """Remove files in data/files and data/thumbs not referenced by any message."""
    with _lock, _connect() as conn:
        known: set[str] = set()
        for row in conn.execute("SELECT filepath, thumb FROM messages"):
            for f in (row["filepath"], row["thumb"]):
                if f:
                    known.add(str(f).replace("\\", "/"))
    for folder in (FILES, THUMBS):
        if not folder.is_dir():
            continue
        for p in folder.rglob("*"):
            if not p.is_file():
                continue
            try:
                rel = str(p.relative_to(DATA_DIR)).replace("\\", "/")
            except ValueError:
                continue
            if rel not in known:
                try:
                    p.unlink()
                except OSError:
                    pass


def add_message(
    *,
    device_ip: str,
    device_name: str,
    text: str = "",
    kind: str = "text",
    filename: str | None = None,
    filepath: str | None = None,
    thumb: str | None = None,
    mime: str | None = None,
    size: int = 0,
    source: str = "chat",
    content_hash: str | None = None,
    session_id: int = 0,
    allow_duplicate: bool = False,
    hash_preclaimed: bool = False,
) -> dict | None:
    if content_hash:
        if allow_duplicate and session_id:
            if hash_seen_in_session(content_hash, session_id):
                return None
        elif hash_preclaimed:
            pass  # caller already won claim_hash
        elif not claim_hash(content_hash):
            return None
    now = time.time()
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO messages(device_ip,device_name,text,kind,filename,filepath,thumb,mime,size,source,content_hash,created_at,session_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (device_ip, device_name, text or "", kind, filename, filepath, thumb, mime, size, source, content_hash, now, session_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM messages WHERE id=?", (cur.lastrowid,)).fetchone()
    if content_hash and (allow_duplicate or not hash_preclaimed):
        # Global claim already stored for preclaimed path; still mark for session-scoped dups
        mark_hash(content_hash)
    if session_id:
        touch_session(session_id)
    return _row_to_dict(row)


def count_session_messages(session_id: int, before_id: int = 0) -> int:
    """How many messages a chat holds (only those before `before_id` when given)."""
    with _lock, _connect() as conn:
        if before_id:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE session_id=? AND id<?", (session_id, before_id)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS n FROM messages WHERE session_id=?", (session_id,)).fetchone()
    return int(row["n"] or 0)


def get_messages_before(session_id: int, before_id: int, limit: int = 60) -> list[dict]:
    """The latest `limit` messages of a chat that come before `before_id`, oldest first."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id=? AND id<? ORDER BY id DESC LIMIT ?",
            (session_id, before_id, limit),
        ).fetchall()
    return [_row_to_dict(r) for r in reversed(rows)]


def set_message_ai_info(msg_id: int, *, model: str = "", status: str = "") -> None:
    """Record which model wrote a reply, and whether it was cut short ('stopped')."""
    with _lock, _connect() as conn:
        if model:
            conn.execute("UPDATE messages SET ai_model=? WHERE id=?", (model[:80], msg_id))
        if status:
            conn.execute("UPDATE messages SET ai_status=? WHERE id=?", (status[:20], msg_id))
        conn.commit()


def get_media_messages(limit: int = 200) -> list[dict]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE kind IN ('image','video','file') ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_dict(r) for r in reversed(list(rows))]


def get_messages(since_id: int = 0, limit: int = 500, session_id: int | None = None) -> list[dict]:
    with _lock, _connect() as conn:
        if since_id:
            if session_id is not None:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE id>? AND session_id=? ORDER BY id ASC LIMIT ?",
                    (since_id, session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE id>? ORDER BY id ASC LIMIT ?",
                    (since_id, limit),
                ).fetchall()
        elif session_id is not None:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            rows = list(reversed(rows))
        else:
            rows = conn.execute(
                "SELECT * FROM messages ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            rows = list(reversed(rows))
    return [_row_to_dict(r) for r in rows]


def latest_id() -> int:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT MAX(id) as m FROM messages").fetchone()
    return int(row["m"] or 0)


def delete_message(msg_id: int) -> bool:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT filepath,thumb FROM messages WHERE id=?", (msg_id,)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM messages WHERE id=?", (msg_id,))
        # Its prompt record (prompt_trace.py) holds the full text that was sent; deleting
        # the reply must delete that copy too. The table only exists once a trace was saved.
        try:
            conn.execute("DELETE FROM prompt_traces WHERE message_id=?", (msg_id,))
        except sqlite3.OperationalError:
            pass
        conn.commit()
        # A forked chat points at the same stored file, so only remove a file
        # once no other message still uses it.
        still_used = {
            rel for rel in (row["filepath"], row["thumb"]) if rel and conn.execute(
                "SELECT 1 FROM messages WHERE filepath=? OR thumb=? LIMIT 1", (rel, rel)
            ).fetchone()
        }
    for rel in (row["filepath"], row["thumb"]):
        if rel and rel not in still_used:
            p = DATA_DIR / rel.replace("/", "\\") if "\\" not in rel else DATA_DIR / rel
            if not p.is_file():
                p = ROOT / rel if (ROOT / rel).is_file() else FILES.parent / rel
            try:
                if p.is_file():
                    p.unlink()
            except OSError:
                pass
    return True


def fork_session(session_id: int, upto_message_id: int) -> dict:
    """Copy a chat up to and including one message into a new chat.

    Same order, same sender, same text, same project, titled "<title> (fork)".
    Attachment rows keep pointing at the same stored file (no bytes copied);
    delete_message leaves a file alone while another row still uses it.
    The source chat is only read. Raises LookupError (unknown chat or message)
    or ValueError (message belongs to another chat).
    """
    src = get_session(session_id)
    if not src:
        raise LookupError("Chat not found.")
    last = get_message(upto_message_id)
    if not last:
        raise LookupError("Message not found.")
    if int(last.get("session_id") or 0) != int(session_id):
        raise ValueError("That message is not in this chat.")
    with _lock, _connect() as conn:
        rows = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM messages WHERE session_id=? AND id<=? ORDER BY id ASC",
            (int(session_id), int(upto_message_id)),
        ).fetchall()]
    suffix = " (fork)"
    title = (str(src.get("title") or "New chat")[: 80 - len(suffix)]) + suffix
    new = create_session(title, src.get("capture_type") or "manual",
                         category=src.get("category") or "general")
    nid = int(new["id"])
    if src.get("project_id"):
        update_session_meta(nid, project_id=int(src["project_id"]))
    # A copy that answers differently is not a copy: standing instructions come along.
    import chat_prefs

    prefs_note: dict = {}
    try:
        text = chat_prefs.get(int(session_id))
        if text:
            chat_prefs.set(nid, text)
            prefs_note["instructions_copied"] = True
    except Exception as e:  # the fork exists; say the instructions did not come with it
        prefs_note = {"instructions_copied": False, "instructions_error": str(e)[:160]}
    for m in rows:
        c = add_message(
            device_ip=m.get("device_ip") or "", device_name=m.get("device_name") or "",
            text=m.get("text") or "", kind=m.get("kind") or "text",
            filename=m.get("filename"), filepath=m.get("filepath"), thumb=m.get("thumb"),
            mime=m.get("mime"), size=int(m.get("size") or 0), source=m.get("source") or "chat",
            session_id=nid,
        )
        if not c:
            continue
        with _lock, _connect() as conn:
            conn.execute(
                "UPDATE messages SET created_at=?, ai_status=?, ai_analysis=?, ai_model=?, ai_category=? WHERE id=?",
                (m["created_at"], m.get("ai_status") or "none", m.get("ai_analysis") or "",
                 m.get("ai_model") or "", m.get("ai_category") or "", c["id"]),
            )
            conn.commit()
    sess = get_session(nid) or new
    return {"session": sess, "copied": len(rows), **prefs_note}


def export_session(session_id: int, fmt: str = "md") -> tuple[str, str, str]:
    """Whole chat straight from the database. Returns (filename, content_type, text).
    Raises LookupError for an unknown chat."""
    sess = get_session(session_id)
    if not sess:
        raise LookupError("Chat not found.")
    with _lock, _connect() as conn:
        msgs = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY id ASC", (int(session_id),)
        ).fetchall()]
    title = str(sess.get("title") or "Chat")

    def who(m):
        if m.get("source") == "ai":
            return "AirGPT"
        return str(m.get("device_name") or "You")

    def body(m):
        t = m.get("text") or ""
        if m.get("kind") in ("image", "video", "file") and m.get("filename"):
            t = (t + "\n\n" if t else "") + "[Attachment: %s]" % m["filename"]
        return t

    # ASCII only: the name goes into an HTTP header, which cannot carry other characters.
    slug = "".join(ch if (ch.isascii() and ch.isalnum()) else "-" for ch in title.lower()).strip("-")[:40].strip("-") or "chat"
    if fmt == "json":
        out = {
            "chat": {"id": sess["id"], "title": title, "created_at": sess.get("created_at"),
                     "message_count": len(msgs)},
            "messages": [{"id": m["id"], "who": who(m), "role": "assistant" if m.get("source") == "ai" else "user",
                          "when": m["datetime"], "created_at": m["created_at"],
                          "kind": m.get("kind"), "filename": m.get("filename"), "text": m.get("text") or ""}
                         for m in msgs],
        }
        return f"airgpt-{slug}.json", "application/json; charset=utf-8", json.dumps(out, indent=2, ensure_ascii=False)
    heading = " ".join(title.split()) or "Chat"   # a line break in a title would split the heading
    lines = [f"# {heading}", "", f"{len(msgs)} messages", ""]
    for i, m in enumerate(msgs, 1):
        lines += [f"## {i}. {who(m)} - {m['datetime']}", "", body(m), ""]
    return f"airgpt-{slug}.md", "text/markdown; charset=utf-8", "\n".join(lines)


def session_latest_id(session_id: int) -> int:
    if not session_id:
        return latest_id()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT MAX(id) FROM messages WHERE session_id=?", (session_id,),
        ).fetchone()
    return int(row[0] or 0)


def messages_grouped(since_id: int = 0, limit: int = 500, session_id: int | None = None,
                     before_id: int = 0) -> dict:
    """Messages grouped by day. `before_id` (with a session) pages backwards: the latest
    `limit` messages older than it. `has_more` says whether older ones remain, so the
    page can offer "Load earlier messages" instead of silently cutting a long chat."""
    if before_id and session_id:
        msgs = get_messages_before(session_id, before_id, limit)
    else:
        msgs = get_messages(since_id=since_id, limit=limit, session_id=session_id)
    has_more = False
    if session_id and msgs and not since_id:
        with _lock, _connect() as conn:
            has_more = conn.execute(
                "SELECT 1 FROM messages WHERE session_id=? AND id<? LIMIT 1",
                (session_id, int(msgs[0]["id"])),
            ).fetchone() is not None
    groups: dict[str, list] = {}
    for m in msgs:
        groups.setdefault(m["date"], []).append(m)
    by_date = [{"date": d, "label": _date_label(d), "messages": groups[d]} for d in sorted(groups.keys())]
    lid = session_latest_id(session_id) if session_id else latest_id()
    return {"messages": msgs, "by_date": by_date, "latest_id": lid, "session_id": session_id or 0,
            "has_more": has_more}


def _date_label(d: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = datetime.fromtimestamp(time.time() - 86400).strftime("%Y-%m-%d")
    if d == today:
        return "Today"
    if d == yesterday:
        return "Yesterday"
    return datetime.strptime(d, "%Y-%m-%d").strftime("%A, %b %d, %Y")


def _ditch_content(msg: dict) -> str:
    return str(msg.get("content") or msg.get("text") or "")


def _ditch_chars(msg: dict) -> int:
    return len(_ditch_content(msg))


def _ditch_keywords(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[a-zA-Z0-9_]{3,}", text or "")[:24]}


def _ditch_is_compressed(msg: dict) -> bool:
    c = _ditch_content(msg).lower()
    markers = ("vision_cache", "[compressed", "compressed vision", "eq1:", "blocks:")
    return any(m in c for m in markers) or bool(msg.get("vision_cache"))


def _ditch_is_raw_dump(msg: dict) -> bool:
    c = _ditch_content(msg)
    return len(c) > 1800 and not _ditch_is_compressed(msg)


def ditch_context(
    messages: list[dict],
    budget_chars: int = 12000,
    pinned: list[dict] | None = None,
    *,
    query: str = "",
    sliding: int = 8,
) -> list[dict]:
    """DSA-style trim: keep sliding window + top-k overlap; ditch low-score when over budget.

    Inspired by DeepSeek sparse attention (indexer → select) at message level, not kernels.
    """
    if not messages:
        return []
    pinned = pinned or []
    pinned_ids = {id(p) for p in pinned}
    pinned_keys = {(p.get("role"), _ditch_content(p)[:80]) for p in pinned}

    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            last_user_idx = i
            break
    latest_user = query or (_ditch_content(messages[last_user_idx]) if last_user_idx >= 0 else "")
    kw = _ditch_keywords(latest_user)
    topic_shift = _topic_shift(messages, latest_user)

    protected: set[int] = set()
    n = len(messages)
    # Sliding local window (NSA-style) — always keep last N turns
    for i in range(max(0, n - sliding), n):
        protected.add(i)
    for i, m in enumerate(messages):
        if m.get("role") == "system":
            protected.add(i)
        if i == last_user_idx:
            protected.add(i)
        if id(m) in pinned_ids:
            protected.add(i)
        if (_ditch_content(m)[:80], m.get("role")) in {(c[:80], r) for r, c in pinned_keys}:
            protected.add(i)
        if m.get("vision_cache") or m.get("pinned"):
            protected.add(i)

    total = sum(_ditch_chars(m) for m in messages)
    if total <= budget_chars and not topic_shift:
        return list(messages)

    scored: list[tuple[float, int]] = []
    for i, m in enumerate(messages):
        if i in protected:
            continue
        c = _ditch_content(m)
        recency = (i + 1) / max(n, 1)
        overlap = sum(1 for t in kw if t in c.lower()) / max(len(kw), 1)
        compressed = 1.6 if _ditch_is_compressed(m) else 0.0
        raw_penalty = -0.8 if _ditch_is_raw_dump(m) else 0.0
        phatic = -1.2 if _ditch_is_phatic(c) else 0.0
        # On topic shift, older non-overlapping turns score worse
        shift_pen = -1.0 if topic_shift and overlap < 0.15 and i < n - sliding else 0.0
        hint = float((m.get("score_hints") or {}).get("priority", 0))
        role_bonus = 0.3 if m.get("role") == "user" else 0.0
        score = recency * 2.0 + overlap * 1.5 + compressed + raw_penalty + phatic + shift_pen + hint + role_bonus
        scored.append((score, i))

    scored.sort(key=lambda x: x[0])
    drop_order = [i for _, i in scored]
    kept = set(range(n))
    for i in drop_order:
        if sum(_ditch_chars(messages[j]) for j in kept) <= budget_chars:
            break
        kept.discard(i)

    must_keep_idx = {i for i in range(n) if messages[i].get("role") == "system"}
    if last_user_idx >= 0:
        must_keep_idx.add(last_user_idx)

    kept_list = sorted(kept)
    for i in drop_order:
        if sum(_ditch_chars(messages[j]) for j in kept_list) <= budget_chars:
            break
        if i in must_keep_idx:
            continue
        if i in kept_list:
            kept_list.remove(i)

    # Sliding window can still exceed budget — peel scored drops until under cap.
    while sum(_ditch_chars(messages[j]) for j in kept_list) > budget_chars:
        removable = [i for i in kept_list if i not in must_keep_idx]
        if not removable:
            break
        victim = removable[0]
        kept_list.remove(victim)

    return [messages[i] for i in kept_list]


def _topic_shift(messages: list[dict], latest_user: str) -> bool:
    """Cheap Jaccard on keywords vs prior user turns — True when topic diverges hard."""
    if not latest_user or len(messages) < 4:
        return False
    new_kw = set(_ditch_keywords(latest_user))
    if len(new_kw) < 3:
        return False
    prior = []
    for m in messages[:-2]:
        if m.get("role") == "user":
            prior.extend(_ditch_keywords(_ditch_content(m)))
    prior_set = set(prior)
    if not prior_set:
        return False
    inter = len(new_kw & prior_set)
    union = len(new_kw | prior_set) or 1
    return (inter / union) < 0.18


def _ditch_is_phatic(text: str) -> bool:
    t = (text or "").strip().lower()
    if len(t) > 40:
        return False
    return t in {"ok", "okay", "thanks", "thank you", "yes", "no", "yep", "cool", "got it", "sure", "k", "👍"}


def compress_message_text(text: str, limit: int = 400) -> str:
    """Extractive compress for ditched/oversized turns kept as stubs."""
    raw = (text or "").strip()
    if len(raw) <= limit:
        return raw
    cut = raw[: limit - 1].rsplit(" ", 1)[0]
    return f"[compressed] {cut}…"


def index_important_from_ditch(
    kept: list[dict],
    dropped: list[dict],
    *,
    project: str = "",
    session_id: int = 0,
) -> dict:
    """Persist keepers into MemPalace/memory_index; write carry note for ditched topic."""
    saved = 0
    try:
        import memory_index as mi
        import vault as vault_mod
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}

    for m in kept:
        c = _ditch_content(m)
        if len(c) < 80 or _ditch_is_phatic(c):
            continue
        if m.get("role") not in ("user", "assistant") and m.get("source") != "ai":
            continue
        # Only index high-signal: decisions/goals-ish or long substantive
        if len(c) < 160 and not any(k in c.lower() for k in ("decide", "goal", "must", "important", "todo", "fix")):
            continue
        try:
            mi.add_memory(
                kind="memory",
                title=(c[:48].replace("\n", " ")),
                body=compress_message_text(c, 500),
                project=project or "general",
                session_id=int(session_id or 0),
                folder="indexed",
                source="dsa_keep",
                pinned=False,
            )
            saved += 1
        except Exception:
            pass

    if dropped:
        gist_parts = []
        for m in dropped[-8:]:
            c = _ditch_content(m)
            if c and not _ditch_is_phatic(c):
                gist_parts.append(compress_message_text(c, 120))
        if gist_parts:
            body = "Prior topic (ditched from prompt):\n- " + "\n- ".join(gist_parts[:6])
            try:
                mi.add_memory(
                    kind="note",
                    title="Carry summary",
                    body=body[:900],
                    project=project or "general",
                    session_id=int(session_id or 0),
                    folder="carry",
                    source="dsa_ditch",
                )
                vault_mod.write_drawer(
                    project=project or "general",
                    title="carry-summary",
                    body=body[:1500],
                    room="carry",
                    source="dsa",
                    session_id=int(session_id or 0),
                )
                saved += 1
            except Exception:
                pass
    return {"ok": True, "saved": saved}


def device_activity_stats() -> list[dict]:
    """Per-device aggregates from messages (sessions, captures, AI usage)."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT device_ip, MAX(device_name) as device_name,
                   COUNT(DISTINCT CASE WHEN session_id > 0 THEN session_id END) as sessions,
                   SUM(CASE WHEN kind = 'image' THEN 1 ELSE 0 END) as screenshots,
                   SUM(CASE WHEN source = 'clipboard' OR source LIKE '%clipboard%' THEN 1 ELSE 0 END) as clipboard_events,
                   SUM(CASE WHEN source = 'ai' OR ai_status = 'done' THEN 1 ELSE 0 END) as ai_responses,
                   MAX(created_at) as last_seen
            FROM messages
            WHERE COALESCE(device_ip, '') != ''
            GROUP BY device_ip
            ORDER BY last_seen DESC
            LIMIT 80
            """
        ).fetchall()
    out = []
    for r in rows:
        ai_n = int(r["ai_responses"] or 0)
        out.append({
            "ip": r["device_ip"],
            "name": r["device_name"] or r["device_ip"],
            "sessions": int(r["sessions"] or 0),
            "screenshots": int(r["screenshots"] or 0),
            "clipboard_events": int(r["clipboard_events"] or 0),
            "ai_minutes": max(ai_n * 2, ai_n),
            "last_seen": float(r["last_seen"] or 0),
        })
    return out

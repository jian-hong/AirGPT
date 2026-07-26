"""SQLite store for Cortex agents, runs, links, and memory backend choice."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from config import DATA_DIR

DB_PATH = DATA_DIR / "agents.db"

# Product surfaces that can be pinned into the Agents left rail.
# Memory is NOT an agent — it is the chat memory panel / memFab.
DEFAULT_PIN_NAMES = ("OpenResearch", "OpenVertex", "RAG")
NON_AGENT_KINDS = ("memory_default",)
NON_AGENT_NAMES = ("memory", "vault summarizer")


def _conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(agents)").fetchall()}
    if "pinned" not in cols:
        conn.execute("ALTER TABLE agents ADD COLUMN pinned INTEGER DEFAULT 0")
        # First-time pin defaults for known workers
        for name in DEFAULT_PIN_NAMES:
            conn.execute("UPDATE agents SET pinned=1 WHERE name=?", (name,))
    # Memory is a product panel, never a pin-able agent catalog entry
    conn.execute(
        "DELETE FROM agents WHERE lower(kind) IN ('memory_default') OR lower(name)='memory'"
    )
    # Legacy seed — removed from product (was confusing / unused)
    conn.execute("DELETE FROM agents WHERE lower(name)='vault summarizer'")


def init() -> None:
    with _conn() as conn:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
        except Exception:
            pass
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS agents (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              kind TEXT DEFAULT 'special',
              skill_pack TEXT DEFAULT '',
              tools TEXT DEFAULT '[]',
              memory_scope TEXT DEFAULT 'project',
              project_id INTEGER DEFAULT 0,
              config TEXT DEFAULT '{}',
              pinned INTEGER DEFAULT 0,
              created_at REAL,
              updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS agent_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              agent_id INTEGER NOT NULL,
              status TEXT DEFAULT 'queued',
              prompt TEXT DEFAULT '',
              result TEXT DEFAULT '',
              error TEXT DEFAULT '',
              audit_ref TEXT DEFAULT '',
              created_at REAL,
              finished_at REAL
            );
            CREATE TABLE IF NOT EXISTS agent_links (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              a_id INTEGER NOT NULL,
              b_id INTEGER NOT NULL,
              relation TEXT DEFAULT 'a2a',
              created_at REAL
            );
            CREATE TABLE IF NOT EXISTS memory_meta (
              key TEXT PRIMARY KEY,
              value TEXT DEFAULT ''
            );
            """
        )
        _migrate(conn)
        row = conn.execute("SELECT value FROM memory_meta WHERE key='backend'").fetchone()
        if not row:
            conn.execute(
                "INSERT INTO memory_meta(key,value) VALUES('backend',?)",
                ("local_vault",),
            )


def create_agent(
    name: str,
    *,
    kind: str = "special",
    skill_pack: str = "",
    tools: list | None = None,
    memory_scope: str = "project",
    project_id: int = 0,
    config: dict | None = None,
    pinned: bool | None = None,
) -> dict:
    init()
    kind_l = (kind or "special").lower()
    name_s = (name or "Agent")[:80]
    if kind_l in NON_AGENT_KINDS or name_s.strip().lower() in NON_AGENT_NAMES:
        raise ValueError("Memory is a product panel, not a Cortex agent")
    now = time.time()
    if pinned is None:
        pinned = name_s in DEFAULT_PIN_NAMES
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO agents(name,kind,skill_pack,tools,memory_scope,project_id,config,pinned,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                name_s,
                (kind or "special")[:40],
                (skill_pack or "")[:120],
                json.dumps(tools or ["web_search", "vault_read", "vault_write", "audit_append", "session_summarize"]),
                (memory_scope or "project")[:40],
                int(project_id or 0),
                json.dumps(config or {}),
                1 if pinned else 0,
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM agents WHERE id=?", (cur.lastrowid,)).fetchone()
        return _agent_row(row)


def list_agents(limit: int = 100, *, pinned_only: bool = False) -> list[dict]:
    init()
    with _conn() as conn:
        if pinned_only:
            rows = conn.execute(
                "SELECT * FROM agents WHERE COALESCE(pinned,0)=1 "
                "AND lower(COALESCE(kind,'')) NOT IN ('memory_default') "
                "AND lower(name) != 'memory' "
                "ORDER BY pinned DESC, updated_at DESC LIMIT ?",
                (min(limit, 200),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agents "
                "WHERE lower(COALESCE(kind,'')) NOT IN ('memory_default') "
                "AND lower(name) != 'memory' "
                "ORDER BY COALESCE(pinned,0) DESC, updated_at DESC LIMIT ?",
                (min(limit, 200),),
            ).fetchall()
        return [_agent_row(r) for r in rows]


def get_agent(agent_id: int) -> dict | None:
    init()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM agents WHERE id=?", (int(agent_id),)).fetchone()
        return _agent_row(row) if row else None


def set_agent_pinned(agent_id: int, pinned: bool) -> dict | None:
    init()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM agents WHERE id=?", (int(agent_id),)).fetchone()
        if not row:
            return None
        d = _agent_row(row)
        if (d.get("kind") or "").lower() in NON_AGENT_KINDS or (d.get("name") or "").lower() in NON_AGENT_NAMES:
            return None
        conn.execute(
            "UPDATE agents SET pinned=?, updated_at=? WHERE id=?",
            (1 if pinned else 0, time.time(), int(agent_id)),
        )
        row = conn.execute("SELECT * FROM agents WHERE id=?", (int(agent_id),)).fetchone()
        return _agent_row(row) if row else None


def delete_agent(agent_id: int) -> dict:
    """Hard-delete an agent row (keeps run history orphaned — fine for local)."""
    init()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM agents WHERE id=?", (int(agent_id),)).fetchone()
        if not row:
            return {"ok": False, "error": "not found"}
        conn.execute("DELETE FROM agents WHERE id=?", (int(agent_id),))
        return {"ok": True, "id": int(agent_id)}


def create_run(agent_id: int, prompt: str) -> dict:
    init()
    now = time.time()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_runs(agent_id,status,prompt,created_at) VALUES(?,?,?,?)",
            (int(agent_id), "running", (prompt or "")[:4000], now),
        )
        row = conn.execute("SELECT * FROM agent_runs WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)


def claim_run(run_id: int) -> dict:
    """Mark a queued run as running so the worker does not re-pick it."""
    init()
    with _conn() as conn:
        conn.execute(
            "UPDATE agent_runs SET status=? WHERE id=? AND status IN ('queued','awaiting_human')",
            ("running", int(run_id)),
        )
        row = conn.execute("SELECT * FROM agent_runs WHERE id=?", (int(run_id),)).fetchone()
        return dict(row) if row else {}


def finish_run(run_id: int, *, status: str, result: str = "", error: str = "", audit_ref: str = "") -> dict:
    init()
    with _conn() as conn:
        conn.execute(
            "UPDATE agent_runs SET status=?, result=?, error=?, audit_ref=?, finished_at=? WHERE id=?",
            (
                status[:40],
                (result or "")[:20000],
                (error or "")[:2000],
                (audit_ref or "")[:200],
                time.time(),
                int(run_id),
            ),
        )
        row = conn.execute("SELECT * FROM agent_runs WHERE id=?", (int(run_id),)).fetchone()
        return dict(row) if row else {}


def list_runs(agent_id: int | None = None, limit: int = 50) -> list[dict]:
    init()
    with _conn() as conn:
        if agent_id:
            rows = conn.execute(
                "SELECT * FROM agent_runs WHERE agent_id=? ORDER BY id DESC LIMIT ?",
                (int(agent_id), min(limit, 200)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_runs ORDER BY id DESC LIMIT ?",
                (min(limit, 200),),
            ).fetchall()
        return [dict(r) for r in rows]


def link_agents(a_id: int, b_id: int, relation: str = "a2a") -> dict:
    init()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_links(a_id,b_id,relation,created_at) VALUES(?,?,?,?)",
            (int(a_id), int(b_id), (relation or "a2a")[:40], time.time()),
        )
        return {"ok": True, "id": cur.lastrowid, "a_id": a_id, "b_id": b_id, "relation": relation}


def list_links() -> list[dict]:
    init()
    with _conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM agent_links ORDER BY id DESC LIMIT 200").fetchall()]


def memory_overview() -> dict:
    init()
    with _conn() as conn:
        backend = conn.execute("SELECT value FROM memory_meta WHERE key='backend'").fetchone()
        backend_val = backend["value"] if backend else "local_vault"
    wings: list[dict] = []
    try:
        import vault as vault_mod

        wings = vault_mod.list_wings(80)
    except Exception:
        vault_dir = DATA_DIR / "vault"
        if vault_dir.is_dir():
            for p in sorted(vault_dir.rglob("*.md"))[:80]:
                try:
                    wings.append(
                        {
                            "path": str(p.relative_to(DATA_DIR)).replace("\\", "/"),
                            "bytes": p.stat().st_size,
                            "mtime": p.stat().st_mtime,
                            "wing": "/rooms/" in str(p).replace("\\", "/"),
                        }
                    )
                except Exception:
                    pass
    wing_count = sum(1 for w in wings if w.get("wing"))
    return {
        "backend": backend_val,
        "items": wings,
        "count": len(wings),
        "wing_drawers": wing_count,
        "layout": "data/vault/{project}/rooms/{topic}/",
    }


def set_memory_backend(backend: str) -> dict:
    init()
    backend = (backend or "local_vault").strip()[:60]
    if backend not in ("local_vault", "project_wing"):
        backend = "local_vault"
    with _conn() as conn:
        conn.execute(
            "INSERT INTO memory_meta(key,value) VALUES('backend',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (backend,),
        )
    return {"ok": True, "backend": backend}


def _agent_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    try:
        d["tools"] = json.loads(d.get("tools") or "[]")
    except Exception:
        d["tools"] = []
    try:
        d["config"] = json.loads(d.get("config") or "{}")
    except Exception:
        d["config"] = {}
    d["pinned"] = bool(int(d.get("pinned") or 0))
    return d


init()

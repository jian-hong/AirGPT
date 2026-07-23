"""Dense vector index for RAG chunks — sqlite-vec when available, else blob+cosine.

Soft-fail contract: never raises out of the package; retrieve falls back to lexical.
"""
from __future__ import annotations

import json
import math
import sqlite3
import struct
from typing import Iterable

from rag import embed, store

# Keyed by DB path — a bare bool breaks when store.DB_PATH changes (tests, profiles)
_VEC_READY: str | None = None
_USE_SQLITE_VEC: bool = False


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *[float(x) for x in vec])


def _unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    if n <= 0:
        return []
    return list(struct.unpack(f"{n}f", blob[: n * 4]))


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return float(dot / (na * nb))


def _ensure_tables(conn: sqlite3.Connection) -> None:
    global _VEC_READY, _USE_SQLITE_VEC
    cur_db = str(store.DB_PATH)
    if _VEC_READY == cur_db:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunk_vectors (
          chunk_id INTEGER PRIMARY KEY,
          space_id INTEGER NOT NULL,
          dim INTEGER NOT NULL,
          backend TEXT DEFAULT 'hash',
          vec BLOB NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunk_vectors_space ON chunk_vectors(space_id)")
    # Optional sqlite-vec virtual table (best effort)
    _USE_SQLITE_VEC = False
    try:
        import sqlite_vec  # type: ignore

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec_idx USING vec0("
            "chunk_id INTEGER PRIMARY KEY, embedding float[64])"
        )
        _USE_SQLITE_VEC = True
    except Exception:
        _USE_SQLITE_VEC = False
    _VEC_READY = cur_db


def available() -> dict:
    """Report dense backend status without requiring an open space."""
    store.init()
    with store._conn() as conn:
        _ensure_tables(conn)
    return {
        "ok": True,
        "sqlite_vec": _USE_SQLITE_VEC,
        "embedder": embed.backend_name(),
        "mode": "sqlite_vec" if _USE_SQLITE_VEC else "blob_cosine",
    }


def upsert_chunk_vector(chunk_id: int, space_id: int, text: str) -> bool:
    try:
        vec = embed.embed_text(text)
        blob = _pack(vec)
        store.init()
        with store._conn() as conn:
            _ensure_tables(conn)
            conn.execute(
                "INSERT OR REPLACE INTO chunk_vectors(chunk_id,space_id,dim,backend,vec) VALUES(?,?,?,?,?)",
                (int(chunk_id), int(space_id), len(vec), embed.backend_name(), blob),
            )
            if _USE_SQLITE_VEC and len(vec) == 64:
                try:
                    conn.execute("DELETE FROM chunk_vec_idx WHERE chunk_id=?", (int(chunk_id),))
                    conn.execute(
                        "INSERT INTO chunk_vec_idx(chunk_id, embedding) VALUES (?, ?)",
                        (int(chunk_id), blob),
                    )
                except Exception:
                    pass
        return True
    except Exception:
        return False


def clear_space(space_id: int) -> None:
    store.init()
    with store._conn() as conn:
        _ensure_tables(conn)
        ids = [
            int(r["chunk_id"])
            for r in conn.execute(
                "SELECT chunk_id FROM chunk_vectors WHERE space_id=?", (int(space_id),)
            )
        ]
        conn.execute("DELETE FROM chunk_vectors WHERE space_id=?", (int(space_id),))
        if _USE_SQLITE_VEC and ids:
            try:
                q = ",".join("?" * len(ids))
                conn.execute(f"DELETE FROM chunk_vec_idx WHERE chunk_id IN ({q})", ids)
            except Exception:
                pass


def search(space_id: int, query: str, *, k: int = 40) -> list[tuple[int, float]]:
    """Return [(chunk_id, score)] descending. Empty list on soft-fail."""
    try:
        qv = embed.embed_text(query)
        store.init()
        with store._conn() as conn:
            _ensure_tables(conn)
            if _USE_SQLITE_VEC and len(qv) == 64:
                try:
                    rows = conn.execute(
                        """
                        SELECT chunk_id, distance
                        FROM chunk_vec_idx
                        WHERE embedding MATCH ?
                          AND k = ?
                          AND chunk_id IN (SELECT chunk_id FROM chunk_vectors WHERE space_id=?)
                        """,
                        (_pack(qv), int(k), int(space_id)),
                    ).fetchall()
                    # sqlite-vec distance: lower is better → invert
                    return [(int(r[0]), 1.0 / (1.0 + float(r[1]))) for r in rows]
                except Exception:
                    pass
            rows = conn.execute(
                "SELECT chunk_id, vec FROM chunk_vectors WHERE space_id=? LIMIT 4000",
                (int(space_id),),
            ).fetchall()
        scored: list[tuple[int, float]] = []
        for r in rows:
            s = _cosine(qv, _unpack(bytes(r["vec"])))
            if s > 0:
                scored.append((int(r["chunk_id"]), s))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]
    except Exception:
        return []


def index_children(space_id: int, pairs: Iterable[tuple[int, str]]) -> int:
    n = 0
    for cid, text in pairs:
        if upsert_chunk_vector(int(cid), int(space_id), text or ""):
            n += 1
    return n

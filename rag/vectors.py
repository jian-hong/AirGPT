"""Dense vector index for RAG chunks — sqlite-vec when available, else blob+cosine.

Soft-fail contract: never raises out of the package; retrieve falls back to lexical.
Public search/upsert dispatch by knowledge_spaces.profile via vector_backends.
"""
from __future__ import annotations

import math
import sqlite3
import struct
from typing import Iterable

from rag import embed, store

# Keyed by DB path — a bare bool breaks when store.DB_PATH changes (tests, profiles)
_VEC_READY: str | None = None
_USE_SQLITE_VEC: bool = False
# The vec0 table has a fixed width, so it must be built at the width the *active*
# embedder emits. This was hard-coded to 64 while the model backend emits 384, which
# meant the ANN index never matched a single query and every dense search silently
# brute-forced the whole space. Keyed by dim so switching embedders builds a new table
# instead of corrupting the old one.
_VEC_DIM: int = 0
_VEC_TABLE: str = ""


def _vec_table(dim: int) -> str:
    return f"chunk_vec_idx_{int(dim)}"


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


def _load_vec_extension(conn: sqlite3.Connection) -> bool:
    """Load sqlite-vec into THIS connection.

    Extension loading is per-connection state, not per-database. Caching it alongside
    the DDL meant only the very first connection ever had `vec0`; every later one threw
    "no such module: vec0" into a bare `except: pass` and silently brute-forced. Cheap
    enough (microseconds) to just do every time.
    """
    try:
        import sqlite_vec  # type: ignore

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:
        return False


def _ensure_tables(conn: sqlite3.Connection) -> None:
    global _VEC_READY, _USE_SQLITE_VEC, _VEC_DIM, _VEC_TABLE
    cur_db = str(store.DB_PATH)
    dim = embed.active_dim()
    if _VEC_READY == cur_db and _VEC_DIM == dim:
        # Schema is known good, but this connection still needs the extension.
        _USE_SQLITE_VEC = _load_vec_extension(conn)
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
    # Optional sqlite-vec virtual table (best effort) — built at the embedder's width
    _VEC_TABLE = _vec_table(dim)
    _USE_SQLITE_VEC = _load_vec_extension(conn)
    if _USE_SQLITE_VEC:
        # vec0 defaults to L2. The rest of the pipeline ranks by cosine, and on
        # un-normalised vectors the two orderings barely overlap (measured recall@40 of
        # 0.05), so the metric has to be stated explicitly or the "fast" path returns
        # different — worse — results than the slow one.
        try:
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {_VEC_TABLE} USING vec0("
                f"chunk_id INTEGER PRIMARY KEY, "
                f"embedding float[{int(dim)}] distance_metric=cosine)"
            )
        except Exception:
            # Older sqlite-vec without distance_metric: fall back to brute force rather
            # than serve L2 rankings through a cosine-shaped API.
            _USE_SQLITE_VEC = False
    _VEC_DIM = dim
    _VEC_READY = cur_db


def _local_available() -> dict:
    """Local sqlite-vec / blob cosine status only."""
    store.init()
    with store._conn() as conn:
        _ensure_tables(conn)
    up = {}
    try:
        up = embed.upgrade_available()
    except Exception:
        up = {}
    return {
        "ok": True,
        "sqlite_vec": _USE_SQLITE_VEC,
        "embedder": embed.backend_name(),
        "mode": "sqlite_vec" if _USE_SQLITE_VEC else "blob_cosine",
        "upgrade_available": bool(up.get("available")),
        "upgrade_hint": up.get("hint") or "",
    }


def available() -> dict:
    """Report dense backends (local + profile stubs)."""
    from rag import vector_backends

    return vector_backends.available()


def _local_upsert_chunk_vector(chunk_id: int, space_id: int, text: str) -> bool:
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
            if _USE_SQLITE_VEC and _VEC_TABLE and len(vec) == _VEC_DIM:
                try:
                    conn.execute(f"DELETE FROM {_VEC_TABLE} WHERE chunk_id=?", (int(chunk_id),))
                    conn.execute(
                        f"INSERT INTO {_VEC_TABLE}(chunk_id, embedding) VALUES (?, ?)",
                        (int(chunk_id), blob),
                    )
                except Exception:
                    pass
        return True
    except Exception:
        return False


def upsert_chunk_vector(chunk_id: int, space_id: int, text: str) -> bool:
    from rag import vector_backends

    return vector_backends.upsert_chunk_vector(chunk_id, space_id, text)


def _local_clear_space(space_id: int) -> None:
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
        if _USE_SQLITE_VEC and _VEC_TABLE and ids:
            try:
                q = ",".join("?" * len(ids))
                conn.execute(f"DELETE FROM {_VEC_TABLE} WHERE chunk_id IN ({q})", ids)
            except Exception:
                pass


def clear_space(space_id: int) -> None:
    from rag import vector_backends

    vector_backends.clear_space(space_id)


def _local_search(space_id: int, query: str, *, k: int = 40) -> list[tuple[int, float]]:
    """Return [(chunk_id, score)] descending. Empty list on soft-fail."""
    try:
        qv = embed.embed_text(query)
        store.init()
        with store._conn() as conn:
            _ensure_tables(conn)
            if _USE_SQLITE_VEC and _VEC_TABLE and len(qv) == _VEC_DIM:
                try:
                    rows = conn.execute(
                        f"""
                        SELECT chunk_id, distance
                        FROM {_VEC_TABLE}
                        WHERE embedding MATCH ?
                          AND k = ?
                          AND chunk_id IN (SELECT chunk_id FROM chunk_vectors WHERE space_id=?)
                        """,
                        (_pack(qv), int(k), int(space_id)),
                    ).fetchall()
                    # An empty ANN table is the normal state for spaces indexed before
                    # this table existed. Returning [] there would silently delete dense
                    # retrieval for every existing user until they knew to rebuild — so
                    # no hits means fall through to the brute-force scan below, which is
                    # slower but always right.
                    if rows:
                        # Same SCALE as the brute-force branch, not just the same order.
                        # With distance_metric=cosine, distance == 1 - cosine_similarity,
                        # so this recovers the identical number. The old 1/(1+d) form
                        # preserved ranking but scored orthogonal vectors 0.5 instead of
                        # 0.0 — and coverage / fusion downstream read the score, not the
                        # rank, so which path ran could change the answer.
                        return [
                            (int(r[0]), max(0.0, min(1.0, 1.0 - float(r[1]))))
                            for r in rows
                        ]
                except Exception:
                    pass
            # Stream ALL vectors in batches (no arbitrary cap — a LIMIT here silently
            # hides later chunks from dense retrieval on large corpora). Each batch is
            # decoded as ONE buffer and scored with numpy; a running top-k bounds memory.
            try:
                import numpy as _np

                dim = len(qv)
                qa = _np.asarray(qv, dtype=_np.float32)
                qn = float(_np.linalg.norm(qa)) or 1.0
                keep_ids = _np.empty(0, dtype=_np.int64)
                keep_sims = _np.empty(0, dtype=_np.float32)
                cur = conn.execute(
                    "SELECT chunk_id, vec FROM chunk_vectors WHERE space_id=?", (int(space_id),)
                )
                while True:
                    rows = cur.fetchmany(4096)
                    if not rows:
                        break
                    ids: list[int] = []
                    blobs: list[bytes] = []
                    for r in rows:
                        b = bytes(r["vec"])
                        if len(b) // 4 != dim:
                            continue  # dim mismatch (embedder changed) — skip stale vectors
                        ids.append(int(r["chunk_id"]))
                        blobs.append(b)
                    if not ids:
                        continue
                    M = _np.frombuffer(b"".join(blobs), dtype=_np.float32).reshape(len(ids), dim)
                    norms = _np.linalg.norm(M, axis=1)
                    norms[norms == 0] = 1.0
                    sims = ((M @ qa) / (norms * qn)).astype(_np.float32)
                    keep_ids = _np.concatenate([keep_ids, _np.asarray(ids, dtype=_np.int64)])
                    keep_sims = _np.concatenate([keep_sims, sims])
                    if keep_sims.size > max(int(k) * 4, 256):  # trim so memory stays bounded
                        sel = _np.argpartition(-keep_sims, int(k) - 1)[: int(k)]
                        keep_ids, keep_sims = keep_ids[sel], keep_sims[sel]
                if keep_ids.size == 0:
                    return []
                kk = min(int(k), keep_sims.size)
                sel = (
                    _np.argpartition(-keep_sims, kk - 1)[:kk]
                    if kk < keep_sims.size
                    else _np.arange(keep_sims.size)
                )
                pairs = [(int(keep_ids[i]), float(keep_sims[i])) for i in sel if keep_sims[i] > 0]
                pairs.sort(key=lambda x: x[1], reverse=True)
                return pairs[:k]
            except Exception:
                pass
            rows = conn.execute(
                "SELECT chunk_id, vec FROM chunk_vectors WHERE space_id=? LIMIT 20000",
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


def search(space_id: int, query: str, *, k: int = 40) -> list[tuple[int, float]]:
    from rag import vector_backends

    return vector_backends.search(space_id, query, k=k)


def ann_index_status(space_id: int) -> dict:
    """Compare blob vectors vs sqlite-vec rows for one space (no re-embed)."""
    store.init()
    with store._conn() as conn:
        _ensure_tables(conn)
        blob_n = int(
            conn.execute(
                "SELECT COUNT(*) FROM chunk_vectors WHERE space_id=?", (int(space_id),)
            ).fetchone()[0]
        )
        ann_n = 0
        if _USE_SQLITE_VEC and _VEC_TABLE:
            try:
                ann_n = int(
                    conn.execute(
                        f"""
                        SELECT COUNT(*) FROM {_VEC_TABLE}
                        WHERE chunk_id IN (SELECT chunk_id FROM chunk_vectors WHERE space_id=?)
                        """,
                        (int(space_id),),
                    ).fetchone()[0]
                )
            except Exception:
                ann_n = 0
        return {
            "ok": True,
            "space_id": int(space_id),
            "blob_count": blob_n,
            "ann_count": ann_n,
            "sqlite_vec": bool(_USE_SQLITE_VEC and _VEC_TABLE),
            "needs_backfill": bool(_USE_SQLITE_VEC and _VEC_TABLE and blob_n > ann_n),
            "pending": max(0, blob_n - ann_n),
        }


def backfill_ann_index(space_id: int, *, limit: int = 50_000) -> dict:
    """Insert existing chunk_vectors blobs into sqlite-vec. Does not re-embed.

    Soft-fail: if sqlite-vec is unavailable, returns needs_backfill=False and inserted=0.
    """
    st = ann_index_status(space_id)
    if not st.get("sqlite_vec"):
        return {**st, "inserted": 0, "skipped": True, "reason": "sqlite_vec_unavailable"}
    if not st.get("needs_backfill"):
        return {**st, "inserted": 0, "skipped": True, "reason": "already_synced"}

    inserted = 0
    store.init()
    with store._conn() as conn:
        _ensure_tables(conn)
        if not (_USE_SQLITE_VEC and _VEC_TABLE):
            return {**st, "inserted": 0, "skipped": True, "reason": "sqlite_vec_unavailable"}
        rows = conn.execute(
            """
            SELECT chunk_id, vec, dim FROM chunk_vectors
            WHERE space_id=?
            ORDER BY chunk_id
            LIMIT ?
            """,
            (int(space_id), int(limit)),
        ).fetchall()
        for r in rows:
            cid = int(r["chunk_id"])
            blob = bytes(r["vec"])
            dim = int(r["dim"] or 0)
            if dim and _VEC_DIM and dim != _VEC_DIM:
                continue
            if len(blob) // 4 != (_VEC_DIM or dim):
                continue
            try:
                exists = conn.execute(
                    f"SELECT 1 FROM {_VEC_TABLE} WHERE chunk_id=? LIMIT 1", (cid,)
                ).fetchone()
                if exists:
                    continue
                conn.execute(
                    f"INSERT INTO {_VEC_TABLE}(chunk_id, embedding) VALUES (?, ?)",
                    (cid, blob),
                )
                inserted += 1
            except Exception:
                continue
    out = ann_index_status(space_id)
    out["inserted"] = inserted
    out["skipped"] = False
    return out


def index_children(space_id: int, pairs, progress=None) -> int:
    """Embed + store child vectors. progress(done, total) is called periodically."""
    from rag import vector_backends

    return vector_backends.index_children(space_id, pairs, progress=progress)

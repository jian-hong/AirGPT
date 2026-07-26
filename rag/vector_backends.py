"""Profile-selected dense vector backends for RAG (Plane 2).

Profiles: local | local_qdrant | business
Flag picks backend, never the feature. Soft-fail search falls back to local.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

from rag import store

PROFILES = frozenset({"local", "local_qdrant", "business"})

# Last search metadata for retrieve traces (backend_fallback etc.)
_LAST_SEARCH_META: dict[str, Any] = {}


class ProfileNotBuiltError(RuntimeError):
    """Raised on ingest/upsert when a non-local profile cannot run on this install."""


def last_search_meta() -> dict[str, Any]:
    return dict(_LAST_SEARCH_META)


def normalize_profile(raw: object) -> str:
    p = str(raw or "local").strip().lower()
    if p in ("local+", "local_plus", "local-qdrant"):
        return "local_qdrant"
    return p if p in PROFILES else "local"


def resolve_profile(space_id: int) -> str:
    space = store.get_space(int(space_id)) or {}
    return normalize_profile(space.get("profile"))


def _qdrant_url() -> str:
    return (os.environ.get("QDRANT_URL") or os.environ.get("AIRGPT_QDRANT_URL") or "").strip()


def _qdrant_ready() -> tuple[bool, str]:
    if not _qdrant_url():
        return False, "QDRANT_URL unset"
    try:
        import qdrant_client  # noqa: F401
    except Exception:
        return False, "qdrant-client not installed"
    return True, ""


def business_ready() -> tuple[bool, str]:
    # Postgres/pgvector not wired this pass
    return False, "business profile (Postgres/pgvector) not built on this install"


def available_for_profile(profile: str | None = None) -> dict:
    from rag import vectors as v
    from rag import semantic_cache

    p = normalize_profile(profile or "local")
    local = v._local_available()
    out: dict[str, Any] = {
        "ok": True,
        "profile": p,
        "local": local,
        "semantic_cache": semantic_cache.available(),
    }
    if p == "local":
        out["mode"] = local.get("mode")
        out["built"] = True
        return out
    if p == "local_qdrant":
        ready, reason = _qdrant_ready()
        out["built"] = ready
        out["mode"] = "qdrant" if ready else "not_built"
        out["reason"] = reason
        out["qdrant_url"] = _qdrant_url() or None
        return out
    ready, reason = business_ready()
    out["built"] = ready
    out["mode"] = "not_built"
    out["reason"] = reason
    return out


def available() -> dict:
    """Aggregate status (local always + optional remotes)."""
    from rag import vectors as v
    from rag import semantic_cache

    local = v._local_available()
    q_ok, q_reason = _qdrant_ready()
    b_ok, b_reason = business_ready()
    return {
        "ok": True,
        "sqlite_vec": local.get("sqlite_vec"),
        "embedder": local.get("embedder"),
        "mode": local.get("mode"),
        "upgrade_available": local.get("upgrade_available"),
        "upgrade_hint": local.get("upgrade_hint") or "",
        "profiles": {
            "local": {"built": True, "mode": local.get("mode")},
            "local_qdrant": {"built": q_ok, "reason": q_reason, "url": _qdrant_url() or None},
            "business": {"built": b_ok, "reason": b_reason},
        },
        "semantic_cache": semantic_cache.available(),
    }


def require_upsert_backend(space_id: int) -> str:
    """Return profile if upsert can proceed; raise ProfileNotBuiltError otherwise."""
    profile = resolve_profile(space_id)
    if profile == "local":
        return profile
    if profile == "local_qdrant":
        ready, reason = _qdrant_ready()
        if not ready:
            raise ProfileNotBuiltError(
                f"profile local_qdrant not built on this install ({reason or 'missing deps'})"
            )
        return profile
    ready, reason = business_ready()
    raise ProfileNotBuiltError(reason or "business profile not built on this install")


def upsert_chunk_vector(chunk_id: int, space_id: int, text: str) -> bool:
    from rag import vectors as v

    profile = resolve_profile(space_id)
    if profile == "local":
        return v._local_upsert_chunk_vector(chunk_id, space_id, text)
    if profile == "local_qdrant":
        require_upsert_backend(space_id)
        ok = _qdrant_upsert(chunk_id, space_id, text)
        # Mirror to local so soft-fail search always has a copy
        v._local_upsert_chunk_vector(chunk_id, space_id, text)
        return ok
    require_upsert_backend(space_id)
    return False


def clear_space(space_id: int) -> None:
    from rag import vectors as v

    profile = resolve_profile(space_id)
    v._local_clear_space(space_id)
    if profile == "local_qdrant":
        ready, _ = _qdrant_ready()
        if ready:
            try:
                _qdrant_clear(space_id)
            except Exception:
                pass


def search(space_id: int, query: str, *, k: int = 40) -> list[tuple[int, float]]:
    """Dense search with profile dispatch; soft-falls to local when remote fails."""
    global _LAST_SEARCH_META
    from rag import vectors as v

    profile = resolve_profile(space_id)
    _LAST_SEARCH_META = {"profile": profile, "backend_fallback": None}

    if profile == "local":
        return v._local_search(space_id, query, k=k)

    if profile == "local_qdrant":
        ready, reason = _qdrant_ready()
        if ready:
            try:
                hits = _qdrant_search(space_id, query, k=k)
                if hits:
                    _LAST_SEARCH_META["mode"] = "qdrant"
                    return hits
            except Exception as e:
                _LAST_SEARCH_META["remote_error"] = str(e)[:120]
        else:
            _LAST_SEARCH_META["remote_error"] = reason
        _LAST_SEARCH_META["backend_fallback"] = "local"
        return v._local_search(space_id, query, k=k)

    # business: always soft-fall this pass
    _LAST_SEARCH_META["backend_fallback"] = "local"
    _LAST_SEARCH_META["remote_error"] = business_ready()[1]
    return v._local_search(space_id, query, k=k)


def index_children(space_id: int, pairs: Iterable, progress=None) -> int:
    """Embed + store; raises ProfileNotBuiltError for unbuilt non-local profiles."""
    require_upsert_backend(space_id)
    items = list(pairs)
    total = len(items)
    n = 0
    for i, (cid, text) in enumerate(items, start=1):
        if upsert_chunk_vector(int(cid), int(space_id), text or ""):
            n += 1
        if progress and (i % 8 == 0 or i == total):
            try:
                progress(i, total)
            except Exception:
                pass
    return n


# --- Qdrant (optional) ---

def _collection_name(space_id: int) -> str:
    return f"airgpt_rag_{int(space_id)}"


def _qdrant_client() -> Any:
    from qdrant_client import QdrantClient

    return QdrantClient(url=_qdrant_url(), timeout=5)


def _ensure_collection(client: Any, space_id: int, dim: int) -> None:
    from qdrant_client.http import models as qm

    name = _collection_name(space_id)
    try:
        client.get_collection(name)
        return
    except Exception:
        pass
    client.create_collection(
        collection_name=name,
        vectors_config=qm.VectorParams(size=int(dim), distance=qm.Distance.COSINE),
    )


def _qdrant_upsert(chunk_id: int, space_id: int, text: str) -> bool:
    from rag import embed
    from qdrant_client.http import models as qm

    vec = embed.embed_text(text)
    client = _qdrant_client()
    _ensure_collection(client, space_id, len(vec))
    client.upsert(
        collection_name=_collection_name(space_id),
        points=[
            qm.PointStruct(
                id=int(chunk_id),
                vector=vec,
                payload={"space_id": int(space_id), "chunk_id": int(chunk_id)},
            )
        ],
    )
    return True


def _qdrant_clear(space_id: int) -> None:
    client = _qdrant_client()
    name = _collection_name(space_id)
    try:
        client.delete_collection(name)
    except Exception:
        pass


def _qdrant_search(space_id: int, query: str, *, k: int = 40) -> list[tuple[int, float]]:
    from rag import embed

    vec = embed.embed_text(query)
    client = _qdrant_client()
    name = _collection_name(space_id)
    try:
        client.get_collection(name)
    except Exception:
        return []
    res = client.search(collection_name=name, query_vector=vec, limit=int(k))
    out: list[tuple[int, float]] = []
    for hit in res or []:
        cid = hit.id
        if hit.payload and hit.payload.get("chunk_id") is not None:
            cid = hit.payload["chunk_id"]
        out.append((int(cid), float(hit.score or 0.0)))
    return out

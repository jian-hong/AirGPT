"""Optional Redis semantic cache for Local+ / Business RAG retrieve.

Key: query_hash + space_id + revision_id -> chunk_ids. Soft-fail if Redis is
down or REDIS_URL unset (miss = normal retrieve). Not a vector store.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any


DEFAULT_TTL_S = 3600
_CLIENT: Any = None
_CLIENT_FAILED = False


def _redis_url() -> str:
    return (os.environ.get("REDIS_URL") or "").strip()


def available() -> dict:
    url = _redis_url()
    if not url:
        return {"ok": False, "enabled": False, "reason": "REDIS_URL unset"}
    client = _client()
    if client is None:
        return {"ok": False, "enabled": True, "reason": "redis client unavailable"}
    try:
        client.ping()
        return {"ok": True, "enabled": True, "ttl_s": DEFAULT_TTL_S}
    except Exception as e:
        return {"ok": False, "enabled": True, "reason": str(e)[:120]}


def _client() -> Any:
    global _CLIENT, _CLIENT_FAILED
    if _CLIENT_FAILED:
        return None
    if _CLIENT is not None:
        return _CLIENT
    url = _redis_url()
    if not url:
        _CLIENT_FAILED = True
        return None
    try:
        import redis  # type: ignore

        _CLIENT = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.5)
        return _CLIENT
    except Exception:
        _CLIENT_FAILED = True
        return None


def _key(space_id: int, revision_id: int, query: str) -> str:
    qh = hashlib.sha256((query or "").encode("utf-8", errors="replace")).hexdigest()[:24]
    return f"airgpt:rag:sem:{int(space_id)}:{int(revision_id)}:{qh}"


def get_chunk_ids(space_id: int, revision_id: int, query: str) -> list[int] | None:
    """Return cached chunk ids or None on miss / soft-fail."""
    try:
        client = _client()
        if client is None:
            return None
        raw = client.get(_key(space_id, revision_id, query))
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, list):
            return None
        return [int(x) for x in data]
    except Exception:
        return None


def set_chunk_ids(
    space_id: int,
    revision_id: int,
    query: str,
    chunk_ids: list[int],
    *,
    ttl_s: int = DEFAULT_TTL_S,
) -> bool:
    try:
        client = _client()
        if client is None:
            return False
        client.setex(
            _key(space_id, revision_id, query),
            int(ttl_s),
            json.dumps([int(x) for x in chunk_ids]),
        )
        return True
    except Exception:
        return False

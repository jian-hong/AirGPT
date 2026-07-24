"""Resolve automatic RAG depth from benchmark recommendations."""
from __future__ import annotations

from rag import store

_DEPTHS = {"basic", "high", "max", "manual"}


def _valid_depth(value: object) -> str | None:
    depth = str(value or "").strip().lower()
    return depth if depth in _DEPTHS else None


def recommended_depth(space_id: int, task_type: str = "general") -> str | None:
    """Return the benchmark-recommended depth for a space and task type."""
    space = store.get_space(space_id)
    if not space:
        return None
    config = space.get("config")
    if not isinstance(config, dict):
        return None
    recommend = config.get("adaptive_recommend")
    if not isinstance(recommend, dict):
        return None
    task = str(task_type or "general").strip() or "general"
    return _valid_depth(recommend.get(task) or recommend.get("general"))


def resolve_depth(space_id: int, depth: str | None = None, task_type: str = "general") -> str:
    """Resolve an automatic depth request using benchmark then space defaults."""
    requested = str(depth or "").strip().lower()
    if requested and requested != "auto":
        return requested
    return recommended_depth(space_id, task_type) or _valid_depth(
        (store.get_space(space_id) or {}).get("depth_default")
    ) or "high"

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


# Chunk-count thresholds for corpus-size fallback. A handful of chunks does not
# need a multi-hop pass, and a large corpus is exactly where one pays off.
_SMALL_CORPUS = 200
_LARGE_CORPUS = 2000


def depth_from_corpus_size(space_id: int) -> str:
    """Pick a depth from how much is actually indexed.

    This is what the Adaptive control has always promised the founder - the button
    reads "Picks depth per question from corpus size" - but nothing implemented it.
    Without it, `auto` fell through to "high" and Adaptive was indistinguishable
    from High on every ask.
    """
    try:
        n = store.count_chunks(space_id)
    except Exception:
        return "high"
    if n <= 0:
        # Nothing indexed: a deep pass cannot find more than a shallow one.
        return "basic"
    if n < _SMALL_CORPUS:
        return "basic"
    if n < _LARGE_CORPUS:
        return "high"
    return "max"


def resolve_depth(space_id: int, depth: str | None = None, task_type: str = "general") -> str:
    """Resolve an automatic depth request using benchmark, then corpus size.

    `auto` used to end at "high": `recommended_depth` needs `config.adaptive_recommend`,
    written only by `rag/evaluate.py` behind a benchmark endpoint with no UI caller, and
    the space-default fallback rejected "auto" itself because it is not a real depth. So
    a space set to Adaptive silently answered every question at High. R-0011.
    """
    requested = str(depth or "").strip().lower()
    if requested == "adaptive":
        requested = "auto"
    if requested and requested != "auto":
        return requested
    benched = recommended_depth(space_id, task_type)
    if benched:
        return benched
    stored = _valid_depth((store.get_space(space_id) or {}).get("depth_default"))
    if stored:
        return stored
    return depth_from_corpus_size(space_id)

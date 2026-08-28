"""Identity of the index a score was measured against (EPIC-D05 precondition).

Authorized with an explicit precondition: chunking by data type re-chunks the
corpus, and a score row measured before the change is not comparable to one
measured after. Without a fingerprint the scoreboard silently compares two
different indexes and every conclusion drawn from it is unsound - including the
0.5375 baseline, once the chunker moves.

This is deliberately conservative about what counts as "the same index". Chunk
boundaries and embedder identity both change what retrieval can possibly find,
so both are in the id. Anything that only changes ranking *after* retrieval
(depth, reranking, the answer model) is not, because those can be compared
across runs on one index - that is the whole point of a variant sweep.

`comparable()` returns the reasons rather than a bare bool: a scoreboard that
refuses to merge two runs should be able to say which field diverged, or nobody
will believe it (R-0011 - the refusal has to be legible, not silent).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# Bump when a change alters chunk boundaries or vector meaning in a way the
# fields below do not already capture. Never reuse a value.
SCHEMA_VERSION = 1

# Defaults mirror rag.chunking.parent_child_chunk. Recorded rather than assumed,
# so a caller that overrides them produces a different id instead of a silent
# collision with the default index.
DEFAULT_CHILD_TOKENS = 200
DEFAULT_PARENT_MAX_TOKENS = 900
DEFAULT_CHILD_OVERLAP = 40


def _embed_identity() -> dict[str, Any]:
    """Backend, model and vector width actually in use right now."""
    out: dict[str, Any] = {"backend": "unknown", "model": "", "dim": 0}
    try:
        from rag import embed

        out["backend"] = str(embed.backend_name())
        out["dim"] = int(embed.active_dim())
        # The model id only matters when a model backend is live; the hash
        # backend has no model and should not pretend to.
        if out["backend"] not in ("hash", "off"):
            out["model"] = str(getattr(embed, "BGE_MODEL_ID", "") or "")
    except Exception as exc:  # pragma: no cover - identity must never crash a run
        out["error"] = f"{type(exc).__name__}: {exc}"[:120]
    return out


def _tokenizer_id() -> str:
    try:
        from rag.sira import TOKENIZER_ID

        return str(TOKENIZER_ID)
    except Exception:
        return "unknown"


def fingerprint(
    *,
    chunker: str = "parent_child",
    child_tokens: int = DEFAULT_CHILD_TOKENS,
    parent_max_tokens: int = DEFAULT_PARENT_MAX_TOKENS,
    child_overlap: int = DEFAULT_CHILD_OVERLAP,
    table: bool = False,
    extra: dict | None = None,
) -> dict[str, Any]:
    """Full, human-readable description of the index a score belongs to."""
    fp: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "chunker": {
            "name": str(chunker),
            "child_tokens": int(child_tokens),
            "parent_max_tokens": int(parent_max_tokens),
            "child_overlap": int(child_overlap),
            "table": bool(table),
        },
        "embed": _embed_identity(),
        "lexical": {"tokenizer": _tokenizer_id()},
    }
    if extra:
        # Namespaced so a caller cannot shadow a field comparability depends on.
        fp["extra"] = dict(extra)
    fp["id"] = _hash_fields(fp)
    return fp


def _hash_fields(fp: dict[str, Any]) -> str:
    """Stable short id over the comparability-relevant fields only.

    `extra` is excluded: it is for provenance a human wants to read (fixture pack,
    git sha), not for deciding whether two indexes are the same one.
    """
    core = {
        "schema_version": fp.get("schema_version"),
        "chunker": fp.get("chunker"),
        "embed": {k: v for k, v in (fp.get("embed") or {}).items() if k != "error"},
        "lexical": fp.get("lexical") or {},
    }
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(blob.encode("utf-8"), digest_size=8).hexdigest()


def comparable(a: dict | None, b: dict | None) -> tuple[bool, list[str]]:
    """Can these two score rows sit on one scoreboard? Returns (ok, reasons).

    A missing fingerprint is NOT treated as a match. Rows recorded before this
    existed are of unknown provenance, and quietly folding them in is exactly the
    failure this module was added to prevent.
    """
    if not a or not b:
        missing = [n for n, v in (("left", a), ("right", b)) if not v]
        return False, [f"no fingerprint recorded on {', '.join(missing)} run"]
    if a.get("id") == b.get("id"):
        return True, []

    reasons: list[str] = []
    if a.get("schema_version") != b.get("schema_version"):
        reasons.append(
            f"fingerprint schema {a.get('schema_version')} vs {b.get('schema_version')}"
        )
    ca, cb = a.get("chunker") or {}, b.get("chunker") or {}
    for key in ("name", "child_tokens", "parent_max_tokens", "child_overlap", "table"):
        if ca.get(key) != cb.get(key):
            reasons.append(f"chunker.{key} {ca.get(key)!r} vs {cb.get(key)!r}")
    ea, eb = a.get("embed") or {}, b.get("embed") or {}
    for key in ("backend", "model", "dim"):
        if ea.get(key) != eb.get(key):
            reasons.append(f"embed.{key} {ea.get(key)!r} vs {eb.get(key)!r}")
    la, lb = a.get("lexical") or {}, b.get("lexical") or {}
    if la.get("tokenizer") != lb.get("tokenizer"):
        reasons.append(f"lexical.tokenizer {la.get('tokenizer')!r} vs {lb.get('tokenizer')!r}")
    if not reasons:
        reasons.append(f"ids differ ({a.get('id')} vs {b.get('id')}) with no field diff")
    return False, reasons


def describe(fp: dict | None) -> str:
    """One line for a bench header, so a reader sees the index without opening JSON."""
    if not fp:
        return "index: UNKNOWN (no fingerprint)"
    c = fp.get("chunker") or {}
    e = fp.get("embed") or {}
    lex = fp.get("lexical") or {}
    return (
        f"index {fp.get('id', '?')}: {c.get('name')}"
        f"(child={c.get('child_tokens')},parent={c.get('parent_max_tokens')},"
        f"overlap={c.get('child_overlap')}) "
        f"embed={e.get('backend')}/{e.get('model') or 'none'}@{e.get('dim')}d "
        f"tok={lex.get('tokenizer') or '?'}"
    )

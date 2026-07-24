"""Typo tolerance — correct out-of-vocabulary query terms against the corpus.

FTS is exact-match, so a misspelled distinctive term ("secuirty hardning") misses.
For each query token not already in the corpus vocabulary, substitute the closest
real corpus term (stdlib difflib — no dependency, local-first). Only OOV tokens are
touched, so valid/rare terms are never corrupted. Soft-fail: returns the query
unchanged on any error.
"""
from __future__ import annotations

import difflib
import re

from rag import sira, store

_VOCAB_CACHE: dict = {}  # (db_path, space_id) -> (version, vocab_set, vocab_list)


def _vocab(space_id: int) -> tuple[set, list]:
    store.init()
    key = (str(store.DB_PATH), int(space_id))
    with store._conn() as conn:
        v = conn.execute(
            "SELECT COUNT(*) c, COALESCE(MAX(id),0) m FROM chunks WHERE space_id=?",
            (int(space_id),),
        ).fetchone()
        version = (int(v["c"] or 0), int(v["m"] or 0))
        cached = _VOCAB_CACHE.get(key)
        if cached and cached[0] == version:
            return cached[1], cached[2]
        rows = conn.execute(
            "SELECT text, heading FROM chunks WHERE space_id=? LIMIT 3000", (int(space_id),)
        ).fetchall()
    vocab: set[str] = set()
    for r in rows:
        for t in sira.tokenize(f"{r['heading'] or ''} {r['text'] or ''}"):
            if 4 <= len(t) <= 30 and t.isascii():
                vocab.add(t)
    vlist = list(vocab)
    _VOCAB_CACHE[key] = (version, vocab, vlist)
    return vocab, vlist


def correct_query(query: str, space_id: int, *, cutoff: float = 0.82, max_corrections: int = 4) -> str:
    """Return the query with OOV tokens replaced by their closest corpus term."""
    try:
        vocab, vlist = _vocab(space_id)
    except Exception:
        return query
    if not vlist:
        return query
    out: list[str] = []
    corrected = 0
    for raw in (query or "").split():
        clean = re.sub(r"[^\w]", "", raw.lower())
        if len(clean) < 4 or clean in vocab or corrected >= max_corrections:
            out.append(raw)
            continue
        m = difflib.get_close_matches(clean, vlist, n=1, cutoff=cutoff)
        cand = m[0] if m else ""
        # Skip inflections: if the candidate is a prefix/suffix of the token (plural,
        # tense, agent — "provide"→"provider", "plans"→"plan"), the original is a valid
        # word form, not a misspelling. Genuine typos ("secuirty"→"security") aren't
        # prefix-related, so this preserves real corrections while stopping corruption.
        if cand and cand != clean and not cand.startswith(clean) and not clean.startswith(cand):
            out.append(cand)
            corrected += 1
        else:
            out.append(raw)
    return " ".join(out)

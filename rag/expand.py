"""Multi-query expansion — a local bridge over a weak (hash) embedder.

The dense channel falls back to hash/blob-cosine when no real embedder is
installed, so paraphrased queries (synonyms, ~0 keyword overlap) miss. Rather
than require a heavy embedding model, we widen the *query*: retrieve over the
original plus a few synonym-rich rephrasings and merge the hits. When no
expander is available (offline, no LLM) this is the identity — retrieval is
unchanged, so there is no regression on the default path.
"""
from __future__ import annotations

from rag import retrieve, store


def default_llm_expander(query: str, n: int = 4) -> list[str]:
    """Ask the chat model for synonym-rich rephrasings. Soft-fail → []."""
    try:
        import ai_engine

        prompt = (
            f"Rewrite this search query {n} different ways using synonyms and related "
            f"terminology so a keyword search can find relevant documents. One per line, "
            f"no numbering, no commentary.\n\nQuery: {query}"
        )
        text = ""
        if hasattr(ai_engine, "chat_text"):
            text = str(ai_engine.chat_text(prompt) or "")
        elif hasattr(ai_engine, "_standard_llm"):
            text, _ = ai_engine._standard_llm(  # noqa: SLF001
                prompt, "You expand search queries.", max_tokens=160
            )
        alts = [ln.strip("-•* \t").strip() for ln in str(text).splitlines() if ln.strip()]
        return [a for a in alts if a][:n]
    except Exception:
        return []


def _rebuild_citations(hits: list[dict]) -> list[dict]:
    cites: list[dict] = []
    for h in hits:
        cid = int(h.get("chunk_id") or h.get("doc_id") or 0)
        meta = store.get_chunk(cid) or {}
        cites.append(
            {
                "chunk_id": cid,
                "path": h.get("path") or meta.get("path"),
                "heading": h.get("heading") or meta.get("heading"),
                "span_start": meta.get("span_start"),
                "span_end": meta.get("span_end"),
                "parent_id": meta.get("parent_id") or h.get("parent_id"),
                "score": h.get("score"),
                "excerpt": (h.get("text") or "")[:280],
            }
        )
    return cites


def multi_query_search(
    space_id: int,
    query: str,
    *,
    depth: str = "high",
    top_k: int = 8,
    expander=None,
    max_alts: int = 4,
) -> dict:
    """retrieve.search over the query + synonym rephrasings, merged (best score wins).

    Same return shape as retrieve.search, plus `expanded_queries`. `expander(query)`
    returns alt phrasings; pass `expander=None` to use the LLM (soft-fails to identity).
    """
    base = retrieve.search(space_id, query, depth=depth, top_k=top_k, debug=False)
    if not base.get("ok"):
        return base
    exp = default_llm_expander if expander is None else expander
    try:
        alts = [
            a for a in (exp(query) or [])
            if a and a.strip().lower() != (query or "").strip().lower()
        ][:max_alts]
    except Exception:
        alts = []
    if not alts:
        return base  # identity — default path unchanged

    merged: dict[int, dict] = {}

    def _add(hits):
        for h in hits or []:
            cid = int(h.get("chunk_id") or h.get("doc_id") or 0)
            if not cid:
                continue
            if cid not in merged or float(h.get("score") or 0) > float(merged[cid].get("score") or 0):
                merged[cid] = h

    _add(base.get("hits"))
    for a in alts:
        r = retrieve.search(space_id, a, depth=depth, top_k=top_k, debug=False)
        if r.get("ok"):
            _add(r.get("hits"))

    hits = sorted(merged.values(), key=lambda x: float(x.get("score") or 0), reverse=True)[:top_k]
    out = dict(base)
    out["hits"] = hits
    out["citations"] = _rebuild_citations(hits)
    out["expanded_queries"] = alts
    return out

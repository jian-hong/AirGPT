"""Grounded answer assembly for RAG chats.

Supports extractive offline answers and true token streaming via ai_engine
when use_llm=True. SSE transport maps events → meta / citations / delta / done.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from rag import retrieve, sira, store

# Sufficiency floor for the corrective loop: fraction of salient query tokens
# that must appear in the evidence set before generation proceeds.
_COVERAGE_FLOOR = 0.6

_FAITH_STOP = {
    "the", "and", "for", "that", "this", "with", "from", "into", "are", "was", "were",
    "you", "your", "our", "has", "have", "not", "but", "all", "can", "will", "use",
    "used", "using", "how", "what", "when", "which", "where", "they", "them", "its",
    "based", "indexed", "sources", "source", "answer", "provided", "documents", "according",
}


def verify_faithfulness(text: str, context: str, *, floor: float = 0.5) -> dict:
    """Flag answer sentences whose content words aren't supported by the evidence.

    A citation-forced LLM can still assert specifics not in the retrieved context.
    Cheap, dependency-free check: a sentence is grounded when most of its content
    tokens appear in the context. Returns {score, unsupported: [sentences]}.
    """
    ctx = set(sira.tokenize(context or ""))
    # split on sentence punctuation followed by whitespace (won't break decimals like 0.7)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if len(s.strip()) >= 20]
    if not sentences or not ctx:
        return {"score": 1.0, "unsupported": []}
    unsupported: list[str] = []
    supported = 0
    for s in sentences:
        toks = [t for t in sira.tokenize(s) if len(t) >= 3 and t not in _FAITH_STOP]
        if not toks:
            supported += 1
            continue
        overlap = sum(1 for t in toks if t in ctx) / len(toks)
        if overlap >= floor:
            supported += 1
        else:
            unsupported.append(s[:200])
    return {"score": round(supported / len(sentences), 3), "unsupported": unsupported[:5]}


def _display_path(path: str | None) -> str:
    p = (path or "").strip()
    if not p:
        return "source"
    name = Path(p.replace("\\", "/")).name
    return name or p[-48:]


def _widen_with_neighbors(h: dict, text: str, *, radius: int = 1, max_add: int = 900) -> str:
    """Stitch adjacent chunks around a hit so the passage isn't truncated mid-idea."""
    cid = int(h.get("chunk_id") or h.get("doc_id") or 0)
    if not cid or h.get("expanded"):  # parent already widened this one
        return text
    try:
        neighbors = store.neighbor_window(cid, radius=radius)
    except Exception:
        return text
    if not neighbors:
        return text
    body = text
    for nb in neighbors:
        seg = (nb.get("text") or "").strip()
        if not seg or seg in body:
            continue
        if len(body) + len(seg) > len(text) + max_add:
            break
        # order roughly by span: earlier neighbours prepend, later append
        if int(nb.get("span_start") or 0) < int(h.get("span_start") or 0):
            body = seg + "\n" + body
        else:
            body = body + "\n" + seg
    return body


def build_context_block(hits: list[dict], *, max_chars: int = 6000, neighbors: bool = True) -> str:
    parts: list[str] = []
    used = 0
    for i, h in enumerate(hits, start=1):
        path = _display_path(h.get("path"))
        heading = h.get("heading") or ""
        text = (h.get("text") or "").strip()
        if neighbors:
            text = _widen_with_neighbors(h, text)
        header = f"[{i}] {path}" + (f" · {heading}" if heading else "")
        chunk = f"{header}\n{text}\n"
        if used + len(chunk) > max_chars:
            break
        parts.append(chunk)
        used += len(chunk)
    return "\n".join(parts)


def extractive_answer(query: str, hits: list[dict]) -> str:
    if not hits:
        return (
            "I could not find supporting evidence in this RAG knowledge space. "
            "Try ingesting more sources or rephrasing the question."
        )
    # Short prose from top hits — not a raw path dump.
    bits: list[str] = []
    for h in hits[:4]:
        excerpt = (h.get("text") or "").strip().replace("\n", " ")
        if len(excerpt) > 180:
            excerpt = excerpt[:177] + "…"
        if excerpt:
            bits.append(excerpt)
    body = " ".join(bits) if bits else "Evidence was retrieved but could not be paraphrased offline."
    cites = ", ".join(f"[{i}] {_display_path(h.get('path'))}" for i, h in enumerate(hits[:5], start=1))
    return (
        f"{body}\n\n"
        f"(Offline extractive answer — turn LLM ON for a fuller grounded reply. Sources: {cites}.)"
    )


def grounded_prompt(query: str, context: str) -> tuple[str, str]:
    """Return (system, user) for grounded generation — no vault/memory mix-in."""
    system = (
        "You are AirGPT RAG — a precise grounded assistant. "
        "Write a clear, natural answer in full sentences for the user. "
        "Use ONLY the numbered evidence provided. Cite as [n] inline where claims come from. "
        "Do NOT paste raw file paths, do NOT list every excerpt as a numbered dump, "
        "and do NOT start with “Based on the indexed sources”. "
        "If evidence is thin, say what is known and what is missing."
    )
    user = (
        f"Question: {query}\n\n"
        f"Evidence (cite by number only):\n{context}\n\n"
        "Write the answer now:"
    )
    return system, user


def _chunk_text(text: str, size: int = 240) -> Iterator[str]:
    t = text or ""
    for i in range(0, len(t), size):
        yield t[i : i + size]


_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been", "being",
    "of", "to", "in", "on", "for", "with", "about", "into", "from", "by", "as", "at", "it", "its",
    "this", "that", "these", "those", "what", "which", "who", "whom", "how", "why", "when", "where",
    "do", "does", "did", "can", "could", "should", "would", "will", "please", "me", "my", "our",
    "your", "tell", "explain", "describe", "give", "summarise", "summarize", "summary", "talking",
    "document", "documents", "content", "contents", "first", "thing", "things", "stuff", "here",
}


def _salient_tokens(query: str) -> list[str]:
    # Question/meta words are not "coverage" terms — counting them made trivial
    # queries ("what is this about") look uncovered and fabricated gap notes.
    return [t for t in dict.fromkeys(sira.tokenize(query)) if len(t) >= 3 and t not in _STOPWORDS]


def _evidence_blob(hits: list[dict]) -> str:
    return " ".join(
        f"{h.get('heading') or ''} {h.get('path') or ''} {h.get('text') or ''}" for h in hits
    ).lower()


def _coverage(query: str, hits: list[dict]) -> float:
    """Fraction of salient query tokens present anywhere in the evidence set."""
    toks = _salient_tokens(query)
    if not toks:
        return 1.0
    blob = _evidence_blob(hits)
    return sum(1 for t in toks if t in blob) / len(toks)


def _lexical_rerank(query: str, hits: list[dict]) -> list[dict]:
    """Rank chunks that actually contain the query terms first (coverage), tie-broken
    by retrieval score. A weak (hash) embedder lets RRF fusion float distractors up;
    grounding the final order in real term overlap fixes ranking on ambiguous queries.
    """
    hits = list(hits)
    qt = {t for t in sira.tokenize(query or "") if len(t) >= 3}
    n = len(hits)
    if not qt or n <= 1:
        return sorted(hits, key=lambda x: float(x.get("score") or 0), reverse=True)
    # rank-normalise retrieval score to [0,1] so it blends with coverage on one scale
    order = sorted(hits, key=lambda h: float(h.get("score") or 0), reverse=True)
    srank = {id(h): 1.0 - pos / (n - 1) for pos, h in enumerate(order)}

    def blended(h):
        toks = set(sira.tokenize(f"{h.get('heading') or ''} {h.get('text') or ''}"))
        cov = len(qt & toks) / len(qt)
        # coverage-weighted, but retrieval score still matters (and dominates when
        # coverage is ~0, e.g. paraphrase queries → this stays neutral there)
        return 0.6 * cov + 0.4 * srank[id(h)]

    return sorted(hits, key=blended, reverse=True)


def _diversify(hits: list[dict], k: int, *, max_per_source: int = 3, sim_floor: float = 0.85) -> list[dict]:
    """Cap chunks per source and drop near-duplicate text so one file (or repeated
    boilerplate) can't crowd out complementary evidence in the top-k.

    hits must be relevance-ordered (best first). A source's best chunks are kept up
    to max_per_source; anything beyond, or a near-duplicate (token-Jaccard ≥ floor)
    of an already-picked chunk, is deferred and only used to backfill empty slots.
    """
    n = len(hits)
    if n <= 1 or k <= 1:
        return hits[:k]
    toks = [set(sira.tokenize(f"{h.get('heading') or ''} {h.get('text') or ''}")) for h in hits]
    picked: list[int] = []
    counts: dict = {}
    overflow: list[int] = []
    for i, h in enumerate(hits):
        src = h.get("source_id") or h.get("path") or i
        dup = any(len(toks[i] & toks[p]) / max(1, len(toks[i] | toks[p])) >= sim_floor for p in picked)
        if counts.get(src, 0) < max_per_source and not dup:
            picked.append(i)
            counts[src] = counts.get(src, 0) + 1
        else:
            overflow.append(i)
        if len(picked) >= k:
            break
    for i in overflow:  # backfill if too few distinct sources to fill k
        if len(picked) >= k:
            break
        picked.append(i)
    return [hits[i] for i in picked[:k]]


def _round_cap(depth: str, space: dict | None) -> int:
    """Bounded retrieval rounds (Auto-RAG caps): basic 1 · high ≤2 · max ≤3."""
    d = (depth or "high").lower()
    if d == "manual":
        arch = str(((space or {}).get("config") or {}).get("architecture") or "").lower()
        return 3 if arch in ("agentic", "graph", "hybrid_kg") else 2
    return {"basic": 1, "high": 2, "max": 3}.get(d, 2)


def heuristic_space_blurb(space: dict, chunks: list[dict], sources: list[dict]) -> str:
    """Offline summary from titles/headings/chunk openings — not pipeline boilerplate."""
    name = str(space.get("name") or "This RAG")
    titles = [str(s.get("title") or Path(str(s.get("path") or "")).name) for s in sources[:12]]
    titles = [t for t in titles if t]
    headings: list[str] = []
    openings: list[str] = []
    for c in chunks[:16]:
        h = (c.get("heading") or "").strip()
        if h and h not in headings and len(h) > 2:
            headings.append(h[:80])
        tx = (c.get("text") or "").strip().replace("\n", " ")
        if tx and len(tx) > 40:
            openings.append(tx[:160] + ("…" if len(tx) > 160 else ""))
    themes = headings[:5] or titles[:5]
    theme_bit = "; ".join(themes) if themes else "ingested documents"
    open_bit = openings[0] if openings else ""
    n = len(sources)
    out = f"{name} covers {theme_bit}."
    if open_bit:
        out += f" From the indexed text: “{open_bit}”"
    out += f" ({n} source{'s' if n != 1 else ''} indexed locally.)"
    return out


def summarize_space(space_id: int, *, use_llm: bool = True, force: bool = False) -> dict:
    """Generative (or heuristic) summary of what a RAG corpus is about. Cached on space.config."""
    space = store.get_space(int(space_id))
    if not space:
        return {"ok": False, "error": "space not found"}
    cfg = dict(space.get("config") or {}) if isinstance(space.get("config"), dict) else {}
    cached = str(cfg.get("corpus_summary") or "").strip()
    if cached and not force:
        return {"ok": True, "summary": cached, "mode": "cached", "space_id": space_id}

    sources = store.list_sources(int(space_id))
    chunks = store.sample_parent_chunks(int(space_id), limit=20)
    heuristic = heuristic_space_blurb(space, chunks, sources)
    summary = heuristic
    mode = "heuristic"

    if use_llm and chunks:
        try:
            import ai_engine

            blob_parts = []
            for c in chunks[:14]:
                path = _display_path(c.get("path"))
                heading = c.get("heading") or ""
                text = (c.get("text") or "")[:500]
                blob_parts.append(f"- {path}" + (f" / {heading}" if heading else "") + f": {text}")
            blob = "\n".join(blob_parts)[:5000]
            system = (
                "Summarize what this knowledge base is about in 2–4 natural sentences. "
                "Be specific to the content (topics, projects, docs). "
                "Do not mention chunking, embeddings, RAG pipelines, or “local knowledge space” boilerplate."
            )
            user = f"Space name: {space.get('name')}\n\nIndexed excerpts:\n{blob}\n\nSummary:"
            text, _prov = ai_engine._standard_llm(user, system, max_tokens=280, task="rag")  # noqa: SLF001
            text = (text or "").strip()
            if len(text) >= 40:
                summary = text
                mode = "llm"
        except Exception:
            mode = "heuristic"

    cfg["corpus_summary"] = summary
    try:
        store.update_space_settings(int(space_id), config=cfg)
    except Exception:
        pass
    return {"ok": True, "summary": summary, "mode": mode, "space_id": space_id}


def answer_events(
    space_id: int,
    query: str,
    *,
    depth: str = "high",
    use_llm: bool = True,
    model_tier: str | None = None,
) -> Iterator[dict]:
    """Yield RAG SSE events: thinking?, meta, citations, delta*, done|error.

    Does not persist chat messages — caller owns that (avoids double-write).
    """
    yield {"type": "thinking", "text": "Retrieving evidence…"}
    # Typo tolerance: correct out-of-vocabulary query terms against the corpus so
    # a misspelled distinctive term ("secuirty hardning") still retrieves.
    try:
        from rag import spell as _spell
        _fixed = _spell.correct_query(query, space_id)
        if _fixed and _fixed != query:
            yield {"type": "thinking", "text": "Corrected likely typos in the query…"}
            query = _fixed
    except Exception:
        pass
    top_k = {"basic": 6, "high": 8}.get((depth or "").lower(), 12)
    caps = _round_cap(depth, store.get_space(space_id))

    merged: dict[int, dict] = {}
    hits: list[dict] = []
    rounds: list[dict] = []
    result: dict = {}
    query_r = query
    for rnd in range(1, caps + 1):
        if rnd > 1:
            yield {"type": "thinking", "text": f"Evidence looks thin — corrective retrieval ({rnd}/{caps})…"}
        # Max + LLM: widen the first pass with synonym rephrasings (bridges a weak
        # embedder on paraphrased queries). Soft-fails to plain search when offline.
        if rnd == 1 and use_llm and (depth or "").lower() == "max":
            try:
                from rag import expand as _expand
                step = _expand.multi_query_search(space_id, query_r, depth=depth, top_k=top_k)
                if step.get("expanded_queries"):
                    yield {"type": "thinking", "text": f"Expanded query {len(step['expanded_queries'])} ways for wider recall…"}
            except Exception:
                step = retrieve.search(space_id, query_r, depth=depth, top_k=top_k, debug=False)
        else:
            step = retrieve.search(space_id, query_r, depth=depth, top_k=top_k, debug=False)
        if not step.get("ok"):
            if rnd == 1:
                yield {"type": "error", "error": str(step.get("error") or "retrieve failed")}
                return
            break
        result = step
        for h in step.get("hits") or []:
            cid = int(h.get("chunk_id") or 0)
            if cid and (cid not in merged or float(h.get("score") or 0) > float(merged[cid].get("score") or 0)):
                merged[cid] = h
        hits = _diversify(_lexical_rerank(query, list(merged.values())), top_k)
        cov = _coverage(query, hits)
        rounds.append({"round": rnd, "query": query_r[:200], "n_new": len(step.get("hits") or []), "coverage": round(cov, 3)})
        if hits and cov >= _COVERAGE_FLOOR:
            break
        missing = [t for t in _salient_tokens(query) if t not in _evidence_blob(hits)]
        if not missing:
            break
        next_q = " ".join(missing + [query])
        if any(r["query"] == next_q[:200] for r in rounds):
            break
        query_r = next_q

    coverage = rounds[-1]["coverage"] if rounds else 0.0
    gap_terms = [t for t in _salient_tokens(query) if t not in _evidence_blob(hits)]
    if not hits:
        stop_reason = "no_evidence"
    elif coverage >= _COVERAGE_FLOOR:
        stop_reason = "evidence_ok"
    else:
        stop_reason = "gaps_disclosed"

    citations = []
    for h in hits:
        cid = int(h.get("chunk_id") or 0)
        meta_row = store.get_chunk(cid) or {}
        raw_path = h.get("path") or meta_row.get("path") or ""
        citations.append(
            {
                "chunk_id": cid,
                "path": _display_path(raw_path),
                "path_full": raw_path,
                "title": Path(str(raw_path).replace("\\", "/")).name if raw_path else "",
                "heading": h.get("heading") or meta_row.get("heading"),
                "span_start": meta_row.get("span_start"),
                "span_end": meta_row.get("span_end"),
                "parent_id": meta_row.get("parent_id") or h.get("parent_id"),
                "score": h.get("score"),
                "excerpt": (h.get("text") or "")[:280],
            }
        )
    context = build_context_block(hits)
    confidence = (
        min(1.0, sum(float(h.get("score") or 0) for h in hits[:3]) / 3.0) if hits else 0.0
    )

    if result.get("trace_id") and len(rounds) > 1:
        try:
            tr = store.get_trace(result["trace_id"]) or {}
            payload = dict(tr.get("payload") or {})
            payload["rounds"] = rounds
            payload["corrective_rounds"] = len(rounds) - 1
            store.save_trace(
                result["trace_id"],
                space_id=space_id,
                query=query,
                depth=str(result.get("depth") or depth),
                template_id=str(result.get("template_id") or ""),
                payload=payload,
            )
        except Exception:
            pass
    tier = (model_tier or {"max": "max", "basic": "basic"}.get((depth or "").lower(), "high")).lower()
    if tier not in ("basic", "high", "max"):
        tier = "high"

    yield {
        "type": "meta",
        "depth": result.get("depth") or depth,
        "template_id": result.get("template_id"),
        "trace_id": result.get("trace_id"),
        "space_id": space_id,
        "confidence": confidence,
        "rounds": len(rounds),
        "coverage": coverage,
        "hits": hits,
        "context": context,
    }
    yield {"type": "citations", "citations": citations}

    if not use_llm or not context.strip() or not hits:
        text = extractive_answer(query, hits)
        if hits and gap_terms:
            text += "\n\nNote: the indexed evidence may not cover: " + ", ".join(gap_terms[:6]) + "."
        for piece in _chunk_text(text):
            yield {"type": "delta", "text": piece}
        yield {
            "type": "done",
            "answer": text,
            "trace_id": result.get("trace_id"),
            "confidence": confidence,
            "stop_reason": stop_reason,
            "rounds": len(rounds),
            "coverage": coverage,
            "faithfulness": 1.0,
            "unsupported_claims": [],
            "model": "extractive",
            "citations": citations,
            "hits": hits,
            "context": context,
            "template_id": result.get("template_id"),
            "depth": result.get("depth") or depth,
        }
        return

    system, user = grounded_prompt(query, context)
    text = ""
    model = "llm"
    try:
        import ai_engine

        yield {"type": "thinking", "text": "Writing grounded answer…"}
        stream, model_ref = ai_engine._standard_llm_stream(  # noqa: SLF001
            user,
            system,
            max_tokens=getattr(ai_engine, "CHAT_MAX_TOKENS", 2048),
        )
        parts: list[str] = []
        for delta in stream:
            if isinstance(delta, str) and delta.startswith("\x1eT:"):
                yield {"type": "thinking", "text": delta[3:]}
                continue
            piece = str(delta or "")
            if not piece:
                continue
            parts.append(piece)
            yield {"type": "delta", "text": piece}
        model = model_ref[0] if isinstance(model_ref, list) else (model_ref or "llm")
        text = "".join(parts)
        if not text.strip():
            full, model = ai_engine._standard_llm(  # noqa: SLF001
                user, system, max_tokens=getattr(ai_engine, "CHAT_MAX_TOKENS", 2048), task="rag"
            )
            text = str(full or "")
            for piece in _chunk_text(text):
                yield {"type": "delta", "text": piece}
    except Exception as e:
        yield {"type": "thinking", "text": f"LLM unavailable ({str(e)[:80]}); concise extractive reply."}
        text = extractive_answer(query, hits)
        model = "extractive-fallback"
        for piece in _chunk_text(text):
            yield {"type": "delta", "text": piece}

    # Only real LLM output can hallucinate; extractive text is grounded by construction.
    if str(model).startswith("extractive"):
        faith = {"score": 1.0, "unsupported": []}
    else:
        faith = verify_faithfulness(text, context)
    if faith["unsupported"]:
        yield {"type": "verify", "faithfulness": faith["score"], "unsupported": faith["unsupported"]}
    yield {
        "type": "done",
        "answer": text,
        "trace_id": result.get("trace_id"),
        "confidence": confidence,
        "stop_reason": stop_reason,
        "rounds": len(rounds),
        "coverage": coverage,
        "faithfulness": faith["score"],
        "unsupported_claims": faith["unsupported"],
        "model": model,
        "model_tier": tier,
        "citations": citations,
        "hits": hits,
        "context": context,
        "template_id": result.get("template_id"),
        "depth": result.get("depth") or depth,
    }


def answer(
    space_id: int,
    query: str,
    *,
    depth: str = "high",
    chat_id: int = 0,
    use_llm: bool = True,
) -> dict:
    """Blocking answer — collects answer_events."""
    text = ""
    citations: list = []
    hits: list = []
    context = ""
    done: dict = {}
    for ev in answer_events(space_id, query, depth=depth, use_llm=use_llm):
        t = ev.get("type")
        if t == "citations":
            citations = ev.get("citations") or citations
        elif t == "meta":
            hits = ev.get("hits") or hits
            context = ev.get("context") or context
        elif t == "delta":
            text += ev.get("text") or ""
        elif t == "done":
            done = ev
            text = str(ev.get("answer") or text)
            citations = ev.get("citations") or citations
            hits = ev.get("hits") or hits
            context = ev.get("context") or context
        elif t == "error":
            return {"ok": False, "error": ev.get("error") or "answer failed"}

    if chat_id:
        store.add_message(chat_id, "user", query, depth=depth, trace_id=done.get("trace_id") or "")
        store.add_message(
            chat_id,
            "assistant",
            text,
            citations=citations,
            depth=depth,
            trace_id=done.get("trace_id") or "",
        )

    return {
        "ok": True,
        "space_id": space_id,
        "query": query,
        "depth": done.get("depth") or depth,
        "answer": text,
        "citations": citations,
        "hits": hits,
        "context": context,
        "trace_id": done.get("trace_id"),
        "template_id": done.get("template_id"),
        "confidence": done.get("confidence"),
        "stop_reason": done.get("stop_reason"),
        "faithfulness": done.get("faithfulness"),
        "unsupported_claims": done.get("unsupported_claims") or [],
        "rounds": done.get("rounds"),
        "coverage": done.get("coverage"),
        "model": done.get("model"),
    }

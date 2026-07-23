"""Grounded answer assembly for RAG chats.

Supports extractive offline answers and true token streaming via ai_engine
when use_llm=True. SSE transport maps events → meta / citations / delta / done.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from rag import retrieve, sira, store

# Sufficiency floor for the corrective loop: fraction of salient query tokens
# that must appear in the evidence set before generation proceeds.
_COVERAGE_FLOOR = 0.6


def _display_path(path: str | None) -> str:
    p = (path or "").strip()
    if not p:
        return "source"
    name = Path(p.replace("\\", "/")).name
    return name or p[-48:]


def build_context_block(hits: list[dict], *, max_chars: int = 6000) -> str:
    parts: list[str] = []
    used = 0
    for i, h in enumerate(hits, start=1):
        path = _display_path(h.get("path"))
        heading = h.get("heading") or ""
        text = (h.get("text") or "").strip()
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
            text, _prov = ai_engine._standard_llm(user, system, max_tokens=280)  # noqa: SLF001
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
        hits = sorted(merged.values(), key=lambda x: float(x.get("score") or 0), reverse=True)[:top_k]
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
                user, system, max_tokens=getattr(ai_engine, "CHAT_MAX_TOKENS", 2048)
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

    yield {
        "type": "done",
        "answer": text,
        "trace_id": result.get("trace_id"),
        "confidence": confidence,
        "stop_reason": stop_reason,
        "rounds": len(rounds),
        "coverage": coverage,
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
        "rounds": done.get("rounds"),
        "coverage": done.get("coverage"),
        "model": done.get("model"),
    }

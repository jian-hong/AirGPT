"""Local hybrid retrieval: sparse FTS + lexical dense stub + file-level + RRF."""
from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from typing import Any

from rag import adaptive, authority, sira, store, vectors
from rag.fuse import RankedHit, fuse_channels
from rag.rerank import rerank_hits


def _tokens(text: str) -> list[str]:
    return sira.tokenize(text)


def _fts_query(query: str) -> str:
    toks = [t for t in _tokens(query) if len(t) >= 2][:12]
    if not toks:
        return (query or "").replace('"', " ").strip()[:80]
    return " OR ".join(f'"{t}"' for t in toks)


def _overlap_score(query: str, text: str) -> float:
    q = Counter(_tokens(query))
    if not q:
        return 0.0
    d = Counter(_tokens(text))
    dot = sum(q[t] * d.get(t, 0) for t in q)
    if not dot:
        return 0.0
    qn = math.sqrt(sum(v * v for v in q.values()))
    dn = math.sqrt(sum(v * v for v in d.values())) or 1.0
    return float(dot / (qn * dn))


def sparse_search(space_id: int, query: str, *, k: int = 40) -> list[RankedHit]:
    store.init()
    fts_q = _fts_query(query)
    with store._conn() as conn:
        try:
            rows = conn.execute(
                """
                SELECT c.id, c.text, c.path, c.heading, c.parent_id, c.kind, c.source_id, c.authority,
                       bm25(chunks_fts) AS score
                FROM chunks_fts
                JOIN chunks c ON c.id = chunks_fts.chunk_id
                WHERE chunks_fts MATCH ? AND c.space_id=? AND c.kind='child'
                ORDER BY score
                LIMIT ?
                """,
                (fts_q, int(space_id), int(k)),
            ).fetchall()
        except Exception:
            # MATCH syntax failure — fall back to LIKE
            like = f"%{(query or '')[:40]}%"
            rows = conn.execute(
                """
                SELECT id, text, path, heading, parent_id, kind, source_id, 0.0 AS score
                FROM chunks
                WHERE space_id=? AND kind='child' AND (text LIKE ? OR path LIKE ? OR heading LIKE ?)
                LIMIT ?
                """,
                (int(space_id), like, like, like, int(k)),
            ).fetchall()
    hits: list[RankedHit] = []
    for i, r in enumerate(rows):
        # sqlite bm25 is NEGATIVE, more negative = better. Clamping it at zero made
        # every sparse hit score exactly 1.0, so the trace showed a constant.
        raw = -float(r["score"] or 0.0)
        score = raw / (1.0 + raw) if raw > 0 else max(0.01, 1.0 / (i + 1))
        hits.append(
            RankedHit(
                doc_id=str(r["id"]),
                score=score,
                payload={
                    "chunk_id": int(r["id"]),
                    "text": r["text"],
                    "path": r["path"],
                    "heading": r["heading"],
                    "parent_id": int(r["parent_id"] or 0),
                    "source_id": int(r["source_id"] or 0),
                    "authority": r["authority"] or "",
                    "channel": "sparse",
                },
            )
        )
    return hits


# A code ("ZQ-4471", "frtr_0001", anything in quotes) or a name (capitalised somewhere
# other than the start of the question: "Halvorsen"). A bare number is neither: "2024"
# and "5" turn up by accident in chunks that have nothing to do with the question.
_WORD_RE = re.compile(r"[^\W_]+(?:[-_./][^\W_]+)*")
_QUOTED_RE = re.compile(r"[\"\u201c]([^\"\u201d]{2,60})[\"\u201d]")
EXACT_MAX_DF = 5
EXACT_WEIGHT = 3.0
_QUESTION_WORDS = frozenset(
    "what which when where does that this with from have about there their during will".split()
)


def _is_code(term: str) -> bool:
    return " " in term or (any(c.isdigit() for c in term) and any(c.isalpha() for c in term))


def identifier_terms(query: str) -> list[str]:
    """The words in a question that name one specific thing."""
    q = query or ""
    out = [m.group(1).strip() for m in _QUOTED_RE.finditer(q)]
    for i, m in enumerate(_WORD_RE.finditer(q)):
        w = m.group(0)
        if _is_code(w) or (i > 0 and w[0].isupper() and len(w) >= 3 and not w.isdigit()):
            out.append(w)
    return list(dict.fromkeys(out))[:6]


def exact_term_search(space_id: int, query: str, *, lowercase: bool = False) -> list[RankedHit]:
    """Chunks holding a name or code from the question that is RARE in this space.

    Someone who types "Halvorsen" or "ZQ-4471" wants the few places that say it.
    Rank fusion alone buries that chunk: it wins the keyword channel, but any chunk
    that is merely similar in two channels outvotes it. Common terms are left to the
    normal channels - a term in more than EXACT_MAX_DF chunks proves nothing.

    A code is never incidental, so it counts on its own. A capitalised word can be:
    "reimbursement for meals in Tromso" must not be pulled to a chunk that only
    says the office is in Tromso. A name therefore counts only where the chunk also
    covers at least half of what else the question asks about.
    """
    store.init()
    found: dict[int, dict] = {}
    terms = identifier_terms(query)
    content = {t for t in sira.tokenize(query) if len(t) >= 4 and t not in _QUESTION_WORDS}
    if lowercase:
        # A lowercase name is also where typos live ("halvorsn"). Correct words the
        # space has never seen against its own vocabulary before looking them up.
        try:
            from rag import spell

            query = spell.correct_query(query, space_id)
        except Exception:
            pass
        content = {t for t in sira.tokenize(query) if len(t) >= 4 and t not in _QUESTION_WORDS}
        # People type names in lowercase. Any longer word of the question may be one;
        # the rarity limit and the coverage rule decide, not the capital letter. Kept
        # as a separate, ordinary-weight channel: a rare lowercase word is weaker
        # evidence of a name than a capital or a code, and at full weight it took
        # rank 1 from the chunk that matched the capitalised name.
        seen = {t for term in terms for t in sira.tokenize(term)}
        terms = [t for t in sira.tokenize(query) if len(t) >= 5 and t in content and t not in seen]
    with store._conn() as conn:
        for term in terms:
            parts = re.findall(r"[^\W_]+", term.lower())
            if not parts:
                continue
            try:
                rows = conn.execute(
                    """
                    SELECT c.id, c.text, c.path, c.heading, c.parent_id, c.source_id, c.authority,
                           bm25(chunks_fts) AS score
                    FROM chunks_fts
                    JOIN chunks c ON c.id = chunks_fts.chunk_id
                    WHERE chunks_fts MATCH ? AND c.space_id=? AND c.kind='child'
                    ORDER BY score
                    LIMIT ?
                    """,
                    ('"' + " ".join(parts) + '"', int(space_id), EXACT_MAX_DF + 1),
                ).fetchall()
            except Exception:
                continue
            if not rows or len(rows) > EXACT_MAX_DF:
                continue
            rest = content - set(parts)
            for r in rows:
                if rest and not _is_code(term):
                    # snake_case keys ("discount_band") are one token to the tokenizer
                    have = set(sira.tokenize(str(r["text"]).replace("_", " ")))
                    if len(rest & have) < 0.5 * len(rest):
                        continue
                slot = found.setdefault(int(r["id"]), {"row": r, "terms": 0, "bm25": 0.0})
                slot["terms"] += 1
                slot["bm25"] += -float(r["score"] or 0.0)
    ranked = sorted(found.values(), key=lambda s: (-s["terms"], -s["bm25"]))
    return [
        RankedHit(
            doc_id=str(s["row"]["id"]),
            score=float(s["terms"]),
            payload={
                "chunk_id": int(s["row"]["id"]),
                "text": s["row"]["text"],
                "path": s["row"]["path"],
                "heading": s["row"]["heading"],
                "parent_id": int(s["row"]["parent_id"] or 0),
                "source_id": int(s["row"]["source_id"] or 0),
                "authority": s["row"]["authority"] or "",
                "channel": "exact",
            },
        )
        for s in ranked
    ]


def dense_vector_search(space_id: int, query: str, *, k: int = 40) -> list[RankedHit]:
    """Prefer sqlite-vec / blob cosine; fall back to bag-of-tokens overlap."""
    vec_hits = vectors.search(space_id, query, k=k)
    hits: list[RankedHit] = []
    if vec_hits:
        ids = [cid for cid, _ in vec_hits]
        rows = {int(r["id"]): r for r in store.get_chunks_by_ids(ids)}
        for cid, score in vec_hits:
            r = rows.get(int(cid))
            if not r or (r.get("kind") and r.get("kind") != "child"):
                continue
            hits.append(
                RankedHit(
                    doc_id=str(cid),
                    score=float(score),
                    payload={
                        "chunk_id": int(cid),
                        "text": r.get("text"),
                        "path": r.get("path"),
                        "heading": r.get("heading"),
                        "parent_id": int(r.get("parent_id") or 0),
                        "source_id": int(r.get("source_id") or 0),
                        "channel": "dense_vector",
                    },
                )
            )
        if hits:
            return hits

    # Lexical fallback
    store.init()
    with store._conn() as conn:
        rows = conn.execute(
            "SELECT id, text, path, heading, parent_id, source_id FROM chunks "
            "WHERE space_id=? AND kind='child' LIMIT 2000",
            (int(space_id),),
        ).fetchall()
    scored: list[tuple[float, Any]] = []
    for r in rows:
        s = _overlap_score(query, f"{r['heading']} {r['path']} {r['text']}")
        if s > 0:
            scored.append((s, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    for s, r in scored[:k]:
        hits.append(
            RankedHit(
                doc_id=str(r["id"]),
                score=float(s),
                payload={
                    "chunk_id": int(r["id"]),
                    "text": r["text"],
                    "path": r["path"],
                    "heading": r["heading"],
                    "parent_id": int(r["parent_id"] or 0),
                    "source_id": int(r["source_id"] or 0),
                    "channel": "dense_lexical",
                },
            )
        )
    return hits


def file_level_search(space_id: int, query: str, *, k: int = 20) -> list[RankedHit]:
    store.init()
    fts_q = _fts_query(query)
    with store._conn() as conn:
        try:
            rows = conn.execute(
                """
                SELECT f.id, f.path, f.title, f.source_id, f.phrases, bm25(file_index_fts) AS score
                FROM file_index_fts
                JOIN file_index f ON f.id = file_index_fts.file_id
                WHERE file_index_fts MATCH ? AND f.space_id=?
                ORDER BY score
                LIMIT ?
                """,
                (fts_q, int(space_id), int(k)),
            ).fetchall()
        except Exception:
            like = f"%{(query or '')[:40]}%"
            rows = conn.execute(
                "SELECT id, path, title, source_id, phrases, 0.0 AS score FROM file_index "
                "WHERE space_id=? AND (path LIKE ? OR title LIKE ? OR phrases LIKE ?) LIMIT ?",
                (int(space_id), like, like, like, int(k)),
            ).fetchall()
    hits: list[RankedHit] = []
    for i, r in enumerate(rows):
        raw = float(r["score"] or 0.0)
        score = 1.0 / (1.0 + max(raw, 0.0)) if raw else max(0.01, 1.0 / (i + 1))
        # Boost exact filename substring
        qlow = (query or "").lower()
        path = (r["path"] or "").lower()
        if qlow and (qlow in path or Path_name(r["path"]).lower() in qlow):
            score += 0.5
        hits.append(
            RankedHit(
                doc_id=f"file:{r['id']}",
                score=score,
                payload={
                    "file_index_id": int(r["id"]),
                    "path": r["path"],
                    "title": r["title"],
                    "source_id": int(r["source_id"] or 0),
                    "channel": "file",
                },
            )
        )
    return hits


def Path_name(path: str) -> str:
    from pathlib import Path

    return Path(path or "").name


def expand_parents(hits: list[dict], *, max_parents: int = 8) -> list[dict]:
    """Replace/augment child hits with parent context for generation."""
    out: list[dict] = []
    seen_parents: set[int] = set()
    for h in hits:
        pid = int(h.get("parent_id") or 0)
        if pid and pid not in seen_parents:
            parent = store.get_chunk(pid)
            if parent:
                seen_parents.add(pid)
                out.append(
                    {
                        **h,
                        "text": parent.get("text") or h.get("text"),
                        "parent_id": pid,
                        "expanded": True,
                        "heading": parent.get("heading") or h.get("heading"),
                    }
                )
                if len(out) >= max_parents:
                    break
                continue
        out.append(h)
        if len(out) >= max_parents:
            break
    return out


def search(
    space_id: int,
    query: str,
    *,
    depth: str | None = "high",
    top_k: int = 8,
    debug: bool = False,
    source_ids: list[int] | None = None,
) -> dict:
    """Hybrid search with optional SiRA-constrained expansion terms.

    source_ids narrows the answer to specific files — "ask this question of the lab
    report only" — instead of letting the whole space vote.
    """
    # All channels below share one connection instead of opening ~50 of their own.
    with store.session():
        return _search(
            space_id, query, depth=depth, top_k=top_k, debug=debug, source_ids=source_ids
        )


def _search(
    space_id: int,
    query: str,
    *,
    depth: str | None = "high",
    top_k: int = 8,
    debug: bool = False,
    source_ids: list[int] | None = None,
) -> dict:
    space = store.get_space(space_id)
    if not space:
        return {"ok": False, "error": "space not found"}

    if not depth or str(depth).strip().lower() == "auto":
        depth = adaptive.resolve_depth(space_id, depth)
    depth = str(depth).lower()
    arch = ""
    if depth == "manual":
        # Manual = user-picked architecture preset stored on the space; map to an
        # internal base pipeline. Never invented at runtime — preset ids only.
        arch = str(((space.get("config") or {}).get("architecture")) or "hybrid_rrf").lower()
        base = "max" if arch in ("agentic", "graph", "hybrid_kg") else "high"
    elif depth in ("basic", "high", "max"):
        base = depth
    else:
        depth = base = "high"

    # Collect phrases for constrained expansion (skipped on Basic: one-pass hybrid)
    expand_terms: list[str] = []
    expanded_q = query
    if base != "basic":
        store.init()
        with store._conn() as conn:
            phrase_rows = conn.execute(
                "SELECT phrases FROM file_index WHERE space_id=? LIMIT 200",
                (int(space_id),),
            ).fetchall()
        import json

        phrases_by_doc: list[list[str]] = []
        all_phrases: list[str] = []
        for r in phrase_rows:
            try:
                ph = json.loads(r["phrases"] or "[]")
            except Exception:
                ph = []
            phrases_by_doc.append(ph)
            all_phrases.extend(ph)
        df = sira.corpus_df(phrases_by_doc) if phrases_by_doc else {}
        expand_terms = sira.expand_query(
            query,
            index_phrases=all_phrases,
            df=df,
            n_docs=max(1, len(phrases_by_doc)),
        )
        expanded_q = " ".join([query] + [t for t in expand_terms if t.lower() not in (query or "").lower()])

    sparse_k = 60 if base == "max" else (20 if base == "basic" else 40)
    dense_k = sparse_k
    # Primary channels run the ORIGINAL query so exact matches keep their precise
    # rank; SiRA expansion is a SEPARATE recall channel that only adds candidates
    # the exact query missed — widening recall without diluting MRR.
    sparse = sparse_search(space_id, query, k=sparse_k)
    dense = dense_vector_search(space_id, query, k=dense_k)
    try:
        from rag.vector_backends import last_search_meta

        dense_meta = last_search_meta()
    except Exception:
        dense_meta = {}
    files = file_level_search(space_id, query, k=20)
    channels = {"sparse": sparse, "dense": dense, "file": files}
    if expanded_q and expanded_q.strip() != (query or "").strip():
        channels["expand"] = sparse_search(space_id, expanded_q, k=sparse_k)

    exact = exact_term_search(space_id, query)
    if exact:
        channels["exact"] = exact
    rare = exact_term_search(space_id, query, lowercase=True)
    if rare:
        channels["rare"] = rare

    fused = fuse_channels(
        channels,
        k=60,
        top_n=50 if base == "max" else (20 if base == "basic" else 30),
        weights={"exact": EXACT_WEIGHT},
    )

    # Keep chunk hits primarily; attach file hits as metadata boosts
    chunk_hits: list[dict] = []
    file_hits: list[dict] = []
    for fh in fused:
        if fh.doc_id.startswith("file:"):
            file_hits.append({"doc_id": fh.doc_id, "score": fh.fused_score, **fh.payload, "channel_scores": fh.channel_scores})
            continue
        payload = dict(fh.payload)
        payload.update(
            {
                "doc_id": fh.doc_id,
                "score": fh.fused_score,
                "channel_scores": fh.channel_scores,
            }
        )
        chunk_hits.append(payload)

    # File scoping happens after fusion so every channel still contributes its ranking
    # within the chosen files, rather than each channel silently returning fewer hits.
    if source_ids:
        wanted = {int(s) for s in source_ids if str(s).strip()}
        if wanted:
            chunk_hits = [h for h in chunk_hits if int(h.get("source_id") or 0) in wanted]
            file_hits = [f for f in file_hits if int(f.get("source_id") or 0) in wanted]

    # Prefer files that match: chunks of a file the file-level search ranked high get
    # one more rank vote, sized like any other channel's. This was a flat +0.05,
    # three times a first-place vote, so with more than five files in a space every
    # chunk of a favoured file outranked the chunk that actually held the answer.
    hot_rank = {int(f.get("source_id") or 0): i for i, f in enumerate(file_hits[:5], start=1)}
    for h in chunk_hits:
        rank = hot_rank.get(int(h.get("source_id") or 0))
        if rank:
            h["score"] = float(h.get("score") or 0) + 1.0 / (60 + rank)

    # Tag and weight by source class. A space that has swallowed 1000+ chat transcripts
    # would otherwise rank the assistant's own past answers above fetched documents —
    # which is how a fabricated netie.ai description came back as cited evidence.
    space = store.get_space(space_id) or {}
    cfg = space.get("config") if isinstance(space.get("config"), dict) else {}
    # Default True: still retrieve (downweighted) for "what did we decide…".
    # False: zero conversation scores so they cannot compete with docs/web.
    chats_as_evidence = True if "chats_as_evidence" not in cfg else bool(cfg.get("chats_as_evidence"))
    for h in chunk_hits:
        # Prefer the class stored at ingest; fall back to path inference for rows
        # written before the column existed.
        kind = h.get("authority") or authority.classify(
            h.get("path") or "", h.get("heading") or ""
        )
        h["authority"] = kind
        w = authority.weight(kind)
        if kind == authority.CONVERSATION and not chats_as_evidence:
            w = 0.0
        h["score"] = float(h.get("score") or 0) * w

    if not chats_as_evidence:
        chunk_hits = [h for h in chunk_hits if h.get("authority") != authority.CONVERSATION]

    # Spreadsheet KPI bias: aggregation questions drown in detail-row chunks
    # (e.g. 100+ Revenue windows bury a 1-screen Summary sheet). Soft-boost
    # summary/KPI headings when the query looks numerical/aggregative.
    _kpi_q = re.search(
        r"\b(total|sum|revenue|expense|margin|quarter|kpi|percent|%|average|agg|highest|lowest)\b",
        query or "",
        re.I,
    )
    if _kpi_q:
        _kpi_head = re.compile(r"\b(summary|kpi|dashboard|overview|totals?)\b", re.I)
        for h in chunk_hits:
            head = str(h.get("heading") or "")
            text = str(h.get("text") or "")
            boost = 0.0
            if _kpi_head.search(head):
                boost += 0.35
            elif len(text) < 900 and _kpi_head.search(text[:240]):
                boost += 0.2
            if boost:
                h["score"] = float(h.get("score") or 0) + boost
                h["sheet_kpi_boost"] = boost

    chunk_hits.sort(key=lambda x: float(x.get("score") or 0), reverse=True)

    # Cross-encoder rerank after RRF (feature-flagged; soft-falls to RRF order)
    chunk_hits = rerank_hits(query, chunk_hits, top_n=min(len(chunk_hits), 40 if base == "max" else 30))

    expanded = expand_parents(chunk_hits, max_parents=top_k)
    clean_cites = []
    for h in expanded:
        cid = int(h.get("chunk_id") or h.get("doc_id") or 0)
        meta = store.get_chunk(cid) or {}
        clean_cites.append(
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

    trace_id = uuid.uuid4().hex[:16]
    if depth == "manual":
        template_id = f"manual_{arch}"
    else:
        template_id = {
            "basic": "modular_hybrid_basic",
            "high": "modular_hybrid_high",
            "max": "modular_agentic_max",
        }[base]
    payload = {
        "expand_terms": expand_terms,
        "expanded_query": expanded_q,
        "n_sparse": len(sparse),
        "n_dense": len(dense),
        "n_file": len(files),
        "n_fused_chunks": len(chunk_hits),
        "backend_fallback": dense_meta.get("backend_fallback"),
        "vector_profile": dense_meta.get("profile") or space.get("profile") or "local",
    }
    if debug:
        payload["top_fused"] = [
            {"doc_id": f.doc_id, "score": f.fused_score, "channels": f.channel_scores} for f in fused[:12]
        ]
    store.save_trace(
        trace_id,
        space_id=space_id,
        query=query,
        depth=depth,
        template_id=template_id,
        payload=payload,
    )
    return {
        "ok": True,
        "space_id": space_id,
        "query": query,
        "depth": depth,
        "template_id": template_id,
        "hits": expanded,
        "files": file_hits[:10],
        "citations": clean_cites,
        "trace_id": trace_id,
        "debug": payload if debug else {"expand_terms": expand_terms},
    }

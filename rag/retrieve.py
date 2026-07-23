"""Local hybrid retrieval: sparse FTS + lexical dense stub + file-level + RRF."""
from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from typing import Any

from rag import sira, store, vectors
from rag.fuse import RankedHit, fuse_channels

_TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_\-./]{1,}")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


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
                SELECT c.id, c.text, c.path, c.heading, c.parent_id, c.kind, c.source_id,
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
        # bm25 in sqlite is lower-is-better; invert for ranking channel
        raw = float(r["score"] or 0.0)
        score = 1.0 / (1.0 + max(raw, 0.0)) if raw else max(0.01, 1.0 / (i + 1))
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
                    "channel": "sparse",
                },
            )
        )
    return hits


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
    depth: str = "high",
    top_k: int = 8,
    debug: bool = False,
) -> dict:
    """Hybrid search with optional SiRA-constrained expansion terms."""
    space = store.get_space(space_id)
    if not space:
        return {"ok": False, "error": "space not found"}

    depth = (depth or space.get("depth_default") or "high").lower()
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
    sparse = sparse_search(space_id, expanded_q, k=sparse_k)
    dense = dense_vector_search(space_id, expanded_q, k=dense_k)
    files = file_level_search(space_id, query, k=20)

    fused = fuse_channels(
        {"sparse": sparse, "dense": dense, "file": files},
        k=60,
        top_n=50 if base == "max" else (20 if base == "basic" else 30),
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

    # Prefer files that match: boost sibling chunks with same source_id
    hot_sources = {int(f.get("source_id") or 0) for f in file_hits[:5]}
    for h in chunk_hits:
        if int(h.get("source_id") or 0) in hot_sources:
            h["score"] = float(h.get("score") or 0) + 0.05
    chunk_hits.sort(key=lambda x: float(x.get("score") or 0), reverse=True)

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

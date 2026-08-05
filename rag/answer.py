"""Grounded answer assembly for RAG chats.

Supports extractive offline answers and true token streaming via ai_engine
when use_llm=True. SSE transport maps events → meta / citations / delta / done.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from rag import authority, goal, retrieve, sira, store

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
    # url_en-wikipedia-org-wiki-Yann_LeCun.md → Yann_LeCun (readable cite chip)
    if name.lower().startswith("url_"):
        stem = name[4:]
        if stem.lower().endswith(".md"):
            stem = stem[:-3]
        stem = stem.replace("-", "_").replace(".", "_")
        skip = {
            "+", "-", "www", "com", "org", "html", "https", "http", "edu", "net",
            "en", "wikipedia", "wiki", "linkedin", "in", "company", "news",
            "books", "pages", "psychology", "2e",
        }
        parts = [x for x in stem.split("_") if x and x.casefold() not in skip and len(x) > 1]
        if parts:
            name = " ".join(parts[-4:])[:72]
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
        "You are AirGPT RAG — a precise grounded assistant for a local knowledge space. "
        "Write a clear, natural answer in full sentences for the user. "
        "Use ONLY the numbered evidence provided. Cite as [n] inline where claims come from. "
        "Do NOT paste raw file paths, do NOT list every excerpt as a numbered dump, "
        "and do NOT start with “Based on the indexed sources”. "
        "If evidence is thin or off-topic for the question, say what is known and what is missing — "
        "never invent JEPA / Cortex / edge-AI facts from unrelated resistor or demo docs. "
        "If the user asked about JEPA and evidence has no JEPA, say so clearly, then describe "
        "what architecture *is* evidenced (e.g. Netie search/agents) instead of forcing a match. "
        "Never claim you cannot use tools, cannot modify “your system”, or are blocked by "
        "safety protocols for ordinary knowledge questions. "
        "Source deletes and mass wipes are Build-tab UI actions only — if asked, say so briefly "
        "and answer the knowledge part of the question from evidence. "
        "Web pages and [Wn] snippets were fetched for this turn — treat them like other sources. "
        "Prefer web evidence over prior chat transcripts when both appear."
    )
    user = (
        f"Question: {query}\n\n"
        f"Evidence (cite by number only):\n{context}\n\n"
        "Write the answer now:"
    )
    return system, user


_WEB_CUES = (
    "web search", "search the web", "search online", "look up", "google ",
    "from the internet", "from the web", "online about", "find online",
    "add another source", "add a source", "search about", "browse for",
)


def wants_web(query: str) -> bool:
    """True when the user asked to search/fetch the public web (not Build-only)."""
    q = (query or "").strip().lower()
    if not q:
        return False
    # Slash commands: /search and /web always mean live web (UI may strip the prefix)
    if q.startswith("/search") or q.startswith("/web"):
        return True
    if any(c in q for c in _WEB_CUES):
        return True
    # Typo-tolerant "search" / "find who" / paper lookups
    if re.search(r"\b(sear+ch|serach|searhc|lookup|look\s*up|google)\b", q):
        return True
    if re.search(r"\b(help\s+me\s+find|find\s+who|check\s+who|who\s+is)\b", q):
        return True
    if re.search(r"\b(what\s+paper|papers?\s+(did|has|have)|google\s+scholar|publish(ed)?)\b", q):
        return True
    if re.match(r"^(please\s+)?(search|find|lookup|research)\b", q):
        return True
    # Do not require a leading word-boundary before "/search" — \b fails at "^/…"
    if re.search(r"(?:^|\s)/(?:search|web)\b", q) or re.search(r"\bweb\s*search\b", q):
        return True
    # /edit … add source / change … without the words "web search" still means fetch
    if q.startswith("/edit") and re.search(r"\b(source|sources|add|fetch|url|online|internet)\b", q):
        return True
    return False


def destructive_injection_reply(query: str) -> str | None:
    """Refuse chat-driven mass deletes — those are Build UI only."""
    q = (query or "").lower()
    if re.search(r"\b(delete|remove)\s+(all\s+)?(files|sources|the\s+index|everything)\b", q):
        return (
            "I will not delete sources from chat. Open the **Build** tab and press ✕ on a "
            "source tile to remove one. Ask your knowledge question again (or say “search the web "
            "for …”) and I will answer from the corpus — and fetch web pages when needed."
        )
    if re.search(r"\b(drop|wipe|erase|rm\s+-rf)\s+(the\s+)?(database|rag|index|space|files)\b", q):
        return (
            "Mass wipe via chat is blocked. Use Build → source ✕ for a single source, or manage "
            "the space from Settings. I can still search the web and reason over your remaining corpus."
        )
    return None


def web_query_from_ask(query: str) -> str:
    """Strip command chrome so the search engine gets a clean topic."""
    q = (query or "").strip()
    q = re.sub(r"^/edit\s*", "", q, flags=re.I)
    q = re.sub(r"^/search\s*", "", q, flags=re.I)
    q = re.sub(
        r"^(please\s+)?(delete all files and\s+)?(/edit\s+)?(add\s+)?(hmm\s+)?(another\s+)?(source\s+for\s+me\s+)?",
        "",
        q,
        flags=re.I,
    )
    q = re.sub(
        r"\b(web\s*search|search\s+the\s+web|search\s+online|look\s+up|google|searhc|serach)\s+(about\s+|for\s+)?",
        "",
        q,
        flags=re.I,
    )
    q = re.sub(r"\b(then\s+)?(yup\s+)?reasoning\s+on\s+top\s+of\s+that\b", "", q, flags=re.I)
    q = re.sub(r"\bif you don'?t know u? websearch\b", "", q, flags=re.I)
    q = re.sub(r"\s+", " ", q).strip(" ,.-")
    return q or (query or "").strip()


_GOAL_FILLER = re.compile(
    r"\b(help\s+me|find|who\s+is|the\s+best\s+ppl|people|about|also|hmm+|maybe|next|"
    r"explain|thne|then|bro|check|what\s+is|that\s+file\s+mentioning|searhc|serach|"
    r"search\s+for\s+it|athen|do\s+you\s+think|i\s+can\s+get\s+rich|what\s+product|"
    r"can\s+i\s+ma?ke|from\s+this\s+rag|ensure|auot|auto|distirbution|distribution|"
    r"and\s+rich|ad|ppl)\b",
    re.I,
)


def _clean_goal(text: str) -> str:
    g = re.sub(r"\s+", " ", (text or "").strip(" ,.-;:"))
    g = _GOAL_FILLER.sub(" ", g)
    g = re.sub(r"\s+", " ", g).strip(" ,.-;:")
    return g


def _goal_ok(goal: str) -> bool:
    g = (goal or "").strip()
    if len(g) < 8:
        return False
    # Reject junk single-token / symbol goals that DDG interprets as "+" or "hong"
    toks = re.findall(r"[a-z0-9]{2,}", g.casefold())
    if len(toks) < 2 and g not in ("JEPA", "Netie", "Cortex"):
        return False
    if g in {"+", "-", "&", "hong", "ad", "hmm", "bro", "next", "then"}:
        return False
    return True


def split_web_goals(query: str, *, max_goals: int = 6) -> list[str]:
    """Break a compound ask into short, entity-clean search goals.

    Long mega-queries retrieve junk; single-token goals like \"hong\" or \"+\"
    ingest unrelated pages that then pollute citations.
    """
    q = web_query_from_ask(query)
    # Split on sentence / next / then / also / and what boundaries
    parts = re.split(
        r"[.?!\n]+|\b(?:next|then|thne|also)\b|\band (?:also\s+)?(?:what|how|who|why)\b",
        q,
        flags=re.I,
    )
    goals: list[str] = []

    def _add(raw: str) -> None:
        p = _clean_goal(raw)
        if not _goal_ok(p):
            # Keep a lightly cleaned version if cleaning wiped too much
            p2 = re.sub(r"\s+", " ", (raw or "").strip(" ,.-"))
            if len(p2) > 90:
                p2 = p2[:90].rsplit(" ", 1)[0]
            p = p2 if _goal_ok(p2) else p
        if not _goal_ok(p):
            return
        if len(p) > 90:
            p = p[:90].rsplit(" ", 1)[0]
        if p and p.casefold() not in {g.casefold() for g in goals}:
            goals.append(p)

    for part in parts:
        _add(part)
        if len(goals) >= max_goals:
            break

    # Named entities first — replace noisy mega-goals when entities are present
    q_cf = (query or "").casefold()
    entity_goals = [
        ("jian hong", "Jian Hong Netie AI founder"),
        ("yanlecun", "Yann LeCun papers publications"),
        ("yann lecun", "Yann LeCun papers publications"),
        ("lecun", "Yann LeCun Google Scholar papers"),
        ("jepa", "JEPA vs transfer learning Yann LeCun"),
        ("cognition", "what is cognition psychology OpenStax"),
        ("netie", "Netie AI startup"),
    ]
    entity_out: list[str] = []
    for needle, goal in entity_goals:
        if needle in q_cf and goal.casefold() not in {g.casefold() for g in entity_out}:
            if needle == "lecun" and any("lecun" in g.casefold() for g in entity_out):
                continue
            entity_out.append(goal)
    if entity_out:
        extra: list[str] = []
        for g in goals:
            gl = g.casefold()
            if any(n in gl for n, _ in entity_goals):
                continue
            if any(x in gl for x in ("rich", "product", "distir", "distribut", "money", "rag to")):
                continue
            if _goal_ok(g):
                extra.append(g)
        goals = entity_out + extra
    elif not goals and q:
        fallback = _clean_goal(q[:90]) or q[:90]
        if _goal_ok(fallback):
            goals = [fallback]
        elif len(q) >= 8:
            goals = [q[:90]]

    return goals[:max_goals]


def _tokens_for_match(text: str) -> set[str]:
    return {
        t
        for t in re.findall(r"[a-z0-9]{3,}", (text or "").casefold())
        if t not in _STOPWORDS
    }


def _result_matches_goal(result: dict, goal: str) -> bool:
    """Drop DDG hits that share no content tokens with the goal (stops +/hong junk)."""
    gtoks = _tokens_for_match(goal)
    if not gtoks:
        return True
    blob = f"{result.get('title') or ''} {result.get('url') or ''} {result.get('snippet') or ''}"
    rtoks = _tokens_for_match(blob)
    return bool(gtoks & rtoks)


def _filter_hits_to_goals(hits: list[dict], goals: list[str], query: str) -> list[dict]:
    """Keep only chunks that overlap at least one goal (or the query).

    Stops resistor/config docs from riding along on a Jian Hong / LeCun ask just
    because they live in the same Demo space.
    """
    pools = [_tokens_for_match(g) for g in (goals or []) if g]
    pools.append(_tokens_for_match(query))
    pools = [p for p in pools if p]
    if not pools:
        return hits
    kept: list[dict] = []
    for h in hits or []:
        blob = _tokens_for_match(
            f"{h.get('heading') or ''} {h.get('path') or ''} {h.get('text') or ''} {h.get('title') or ''}"
        )
        if any(blob & p for p in pools):
            kept.append(h)
    return kept if kept else hits  # never empty the set if nothing matched — caller decides


def _goal_covered(goal: str, blob: str) -> bool:
    toks = [t for t in re.findall(r"[a-z0-9]{3,}", goal.casefold()) if t not in _STOPWORDS]
    if not toks:
        return True
    hit = sum(1 for t in toks if t in blob)
    return hit >= max(1, (len(toks) + 1) // 2)


def goal_distance(goals: list[str], hits: list[dict], extra_text: str = "") -> dict:
    """0 = all goals evidenced, 1 = none. Drive another web round when far."""
    blob = (_evidence_blob(hits) + " " + (extra_text or "")).strip()
    if not goals:
        return {"distance": 0.0, "covered": [], "missing": []}
    covered = [g for g in goals if _goal_covered(g, blob)]
    missing = [g for g in goals if g not in covered]
    return {
        "distance": round(len(missing) / len(goals), 3),
        "covered": covered,
        "missing": missing,
    }


def _is_chat_path(path: str) -> bool:
    p = (path or "").replace("\\", "/").lower()
    name = p.rsplit("/", 1)[-1]
    return name.startswith("chat_") or "/chats/" in p or p.startswith("session_")


def _prefer_web_over_chats(hits: list[dict]) -> list[dict]:
    """When the user asked for web search, demote frozen chat transcripts vs URLs/files."""
    def key(h: dict) -> float:
        score = float(h.get("score") or 0)
        path = str(h.get("path") or "")
        pl = path.lower()
        if _is_chat_path(path):
            score *= 0.25
        elif pl.startswith("http://") or pl.startswith("https://") or "/web/" in pl.replace("\\", "/"):
            score *= 1.55
        return score

    return sorted(hits, key=key, reverse=True)


def _web_augment_space(space_id: int, query: str, *, max_pages: int = 6) -> dict:
    """Multi-goal web search + ingest. Falls back to snippets when pages are JS shells."""
    try:
        from rag import ingest, websearch
    except Exception as e:
        return {"ok": False, "error": str(e)[:120], "chunks": 0, "urls": [], "snippets": []}

    goals = split_web_goals(query)
    all_results: list[dict] = []
    seen_url: set[str] = set()
    for goal in goals:
        found = websearch.search_web(goal, max_results=4)
        if not found.get("ok"):
            continue
        for r in found.get("results") or []:
            u = str(r.get("url") or "")
            if not u.startswith("http") or u in seen_url:
                continue
            if not _result_matches_goal(r, goal):
                continue
            seen_url.add(u)
            all_results.append({**r, "goal": goal})

    urls = [r["url"] for r in all_results][:max_pages]
    snippets = [
        {
            "title": r.get("title") or r.get("url"),
            "url": r.get("url"),
            "snippet": r.get("snippet") or "",
            "goal": r.get("goal") or "",
        }
        for r in all_results[:12]
        if (r.get("snippet") or r.get("title"))
    ]

    chunks = 0
    failed: list = []
    if urls:
        try:
            ing = ingest.ingest_urls(space_id, urls, force=False)
            chunks = int(ing.get("chunks") or 0)
            failed = list(ing.get("failed_urls") or [])
            ok = bool(ing.get("ok")) or chunks > 0 or bool(snippets)
        except Exception as e:
            return {
                "ok": bool(snippets),
                "error": str(e)[:120],
                "chunks": 0,
                "urls": urls,
                "snippets": snippets,
                "goals": goals,
            }
    else:
        ok = bool(snippets)

    return {
        "ok": ok,
        "chunks": chunks,
        "urls": urls,
        "snippets": snippets,
        "goals": goals,
        "failed_urls": failed,
        "query": " | ".join(goals)[:200],
        "error": None if ok else "no pages or snippets",
    }


def _snippets_context(snippets: list[dict], *, max_chars: int = 3500) -> str:
    """Evidence block from search snippets when page fetch fails (JS shells)."""
    parts: list[str] = []
    used = 0
    for i, s in enumerate(snippets, start=1):
        title = (s.get("title") or "web")[:120]
        url = s.get("url") or ""
        snip = (s.get("snippet") or "")[:400]
        chunk = f"[W{i}] {title}\nURL: {url}\n{snip}\n"
        if used + len(chunk) > max_chars:
            break
        parts.append(chunk)
        used += len(chunk)
    return "\n".join(parts)


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
    "ensure", "mention", "mentioned", "mentions", "file", "files", "doc", "docs", "detail", "details",
    "every", "each", "entire", "whole", "full", "complete", "all", "any", "some", "info", "information",
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


def wants_corpus_summary(query: str) -> bool:
    """True when the user wants an inventory of what this space holds — not a topical retrieve."""
    q = (query or "").strip().lower()
    if not q:
        return False
    # Explicit inventory / "what's in this RAG" asks
    if re.search(
        r"\b(summaris[e]|summarize|summary|overview|inventory|catalogue|catalog)\b.{0,60}\b"
        r"(rag|space|corpus|knowledge(\s+base)?|sources?|indexed|contains?|about|files?|docs?|documents?)\b",
        q,
    ):
        return True
    if re.search(
        r"\bwhat('?s| is| does| do)?\s+(this|the|my|each|every|all)?\s*"
        r"(rag|space|corpus|knowledge(\s+base)?|index|file|files|doc|docs|document|documents)\b.{0,40}\b"
        r"(contain|about|cover|hold|include|have|say|mean)\b",
        q,
    ):
        return True
    if re.search(
        r"\b(what('?s| is) in (this|the) (rag|space|corpus)|list (the )?(sources|files|docs|documents))\b",
        q,
    ):
        return True
    if re.search(r"\b(this|the)\s+(rag|space|corpus)\s+(contains?|is about|covers)\b", q):
        return True
    # "ensure all files are mentioned" / "mention every source"
    if re.search(
        r"\b(all|every|each|entire|whole)\s+(the\s+)?(files?|sources?|docs?|documents?|links?)\b.{0,30}\b"
        r"(mention|mentioned|list|listed|include|included|cover|covered)\b",
        q,
    ):
        return True
    if re.search(
        r"\b(mention|list|include|cover)\b.{0,30}\b(all|every|each)\s+(the\s+)?"
        r"(files?|sources?|docs?|documents?|links?)\b",
        q,
    ):
        return True
    # Typo-tolerant: starts with summarise/summarize + asks about file(s)
    if re.match(r"^(please\s+)?(summaris[e]|summarize)\b", q) and re.search(
        r"\b(files?|sources?|docs?|documents?|corpus|space|rag)\b", q
    ):
        return True
    return False


def _inventory_answer_events(space_id: int, *, use_llm: bool, depth: str, refuse: str | None):
    """Shared SSE path for corpus inventory (no topical retrieve)."""
    yield {"type": "thinking", "text": "Inventorying sources in this space…"}
    # Always force a fresh inventory so every file is listed (cached summaries drop links).
    inv = summarize_space(space_id, use_llm=use_llm, force=True)
    sources = list(inv.get("sources") or [])
    # Guarantee a full numbered file list even if the LLM blurb omits some.
    listing = "\n".join(
        f"{i}. {s.get('title') or s.get('path') or f'source:{i}'}"
        for i, s in enumerate(sources, 1)
    )
    blurb = str(inv.get("summary") or "").strip()
    if listing:
        if blurb and listing.split("\n")[0][:20] in blurb:
            text = blurb
        else:
            head = f"This space holds {len(sources)} source{'s' if len(sources) != 1 else ''}:"
            text = (blurb + "\n\n" if blurb else "") + head + "\n" + listing
    else:
        text = blurb or "No sources indexed yet."
    if refuse:
        text = refuse + "\n\n" + text
    cites = []
    for i, s in enumerate(sources, 1):
        cites.append(
            {
                "i": i,
                "path": s.get("path") or s.get("title") or f"source:{i}",
                "title": s.get("title") or s.get("path") or f"Source {i}",
                "excerpt": "",
                "heading": "source",
                "score": 1.0,
                "web": False,
            }
        )
    yield {
        "type": "meta",
        "depth": depth,
        "space_id": space_id,
        "confidence": 1.0 if cites else 0.0,
        "rounds": 0,
        "coverage": 1.0 if cites else 0.0,
        "hits": len(cites),
        "context": "",
        "goal": {
            "verdict": "answerable" if cites else "unsupported",
            "coverage": 1.0 if cites else 0.0,
            "distance": 0.0 if cites else 1.0,
            "missing": [],
            "diagnosis": [] if cites else ["Add sources on the Build tab."],
        },
    }
    yield {"type": "citations", "citations": cites}
    for piece in _chunk_text(text):
        yield {"type": "delta", "text": piece}
    yield {
        "type": "done",
        "answer": text,
        "confidence": 1.0 if cites else 0.0,
        "model": inv.get("mode") or "inventory",
        "citations": cites,
        "hits": [],
        "context": "",
        "depth": depth,
        "source_count": inv.get("source_count") or len(cites),
    }


_WEAK_THEME = re.compile(
    r"^(slide\s*\d+|sheet\s*:?.*|page\s*\d+|untitled|contents?|weekly sync|"
    r"agenda|notes?|appendix|references?|toc|table of contents)$",
    re.I,
)


def _good_theme(heading: str) -> bool:
    h = (heading or "").strip()
    if len(h) < 8 or len(h) > 72:
        return False
    if _WEAK_THEME.match(h):
        return False
    # Prefer topical phrases over deck chrome / sheet labels
    if re.match(r"^(sheet|slide|tab|figure|table)\b", h, re.I):
        return False
    return True


def heuristic_space_blurb(space: dict, chunks: list[dict], sources: list[dict]) -> str:
    """Offline summary from titles/headings — prose first, then a clean source list."""
    name = str(space.get("name") or "This RAG")
    titles = [str(s.get("title") or Path(str(s.get("path") or "")).name) for s in sources]
    titles = [t for t in titles if t]
    headings: list[str] = []
    openings: list[str] = []
    for c in chunks[:16]:
        h = (c.get("heading") or "").strip()
        if h and h not in headings and _good_theme(h):
            headings.append(h[:80])
        tx = (c.get("text") or "").strip().replace("\n", " ")
        if tx and len(tx) > 40:
            openings.append(tx[:160] + ("…" if len(tx) > 160 else ""))
    n = len(sources)
    if not n:
        return f"{name} has no sources indexed yet."
    # Prose block (justify-friendly) + inventory block (rendered as a list in UI)
    prose = (
        f"{name} currently holds {n} indexed source{'s' if n != 1 else ''}. "
        "Ask from Overview or Chats for grounded answers over this corpus."
    )
    themes = headings[:4]
    if themes:
        prose += " Topics that show up in the indexed text include " + ", ".join(themes) + "."
    elif openings:
        prose += f" Opening excerpt: “{openings[0]}”"
    lines = [prose, "", "Sources:"]
    for i, t in enumerate(titles[:24], 1):
        lines.append(f"{i}. {t}")
    if len(titles) > 24:
        lines.append(f"… and {len(titles) - 24} more.")
    return "\n".join(lines)


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
    chunks = store.sample_parent_chunks(int(space_id), limit=24)
    heuristic = heuristic_space_blurb(space, chunks, sources)
    summary = heuristic
    mode = "heuristic"
    source_rows = [
        {
            "title": str(s.get("title") or Path(str(s.get("path") or "")).name)[:160],
            "path": str(s.get("path") or "")[:240],
            "id": s.get("id"),
        }
        for s in sources
    ]

    if use_llm and (chunks or sources):
        try:
            import ai_engine

            inv = "\n".join(
                f"{i}. {r['title']}" + (f" ({r['path']})" if r.get("path") else "")
                for i, r in enumerate(source_rows[:30], 1)
            )
            blob_parts = []
            for c in chunks[:12]:
                path = _display_path(c.get("path"))
                heading = c.get("heading") or ""
                text = (c.get("text") or "")[:400]
                blob_parts.append(f"- {path}" + (f" / {heading}" if heading else "") + f": {text}")
            blob = "\n".join(blob_parts)[:4000]
            system = (
                "You inventory a local knowledge base. Write 2–3 calm prose sentences "
                "(no bullet dump in the prose) naming what topics the SOURCES cover. "
                "Do not list every filename in the prose — a Sources: numbered list will "
                "be appended separately. Skip slide numbers, sheet names, and meeting chrome. "
                "If sources are mostly one theme, say so clearly. "
                "Do not describe RAG pipelines, chunking, or embeddings. "
                "Do not invent sources that are not listed."
            )
            user = (
                f"Space name: {space.get('name')}\n\n"
                f"Source inventory:\n{inv or '(none)'}\n\n"
                f"Indexed excerpts:\n{blob or '(none)'}\n\n"
                "Write only the short prose overview (no numbered list):"
            )
            text, _prov = ai_engine._standard_llm(user, system, max_tokens=420, task="rag")  # noqa: SLF001
            text = (text or "").strip()
            if len(text) >= 40:
                # Strip any accidental inventory the model still emitted, then append ours
                prose = re.split(r"\n\s*(?:Sources?|Files?)\s*:\s*\n", text, maxsplit=1, flags=re.I)[0]
                prose = re.sub(r"\n\s*\d+\.\s+.+$", "", prose, flags=re.M).strip()
                if len(prose) < 40:
                    prose = text.strip()
                if source_rows:
                    prose = prose.rstrip() + "\n\nSources:\n" + "\n".join(
                        f"{i}. {r['title']}" for i, r in enumerate(source_rows, 1)
                    )
                summary = prose
                mode = "llm"
        except Exception:
            mode = "heuristic"

    cfg["corpus_summary"] = summary
    try:
        store.update_space_settings(int(space_id), config=cfg)
    except Exception:
        pass
    return {
        "ok": True,
        "summary": summary,
        "mode": mode,
        "space_id": space_id,
        "sources": source_rows,
        "source_count": len(source_rows),
    }


def _try_hybrid_sql_lane(space_id: int, query: str) -> dict | None:
    """Pandas-over-xlsx answers for Top-N / KPI asks. Never emits confirm UI."""
    import sys

    bench = Path(__file__).resolve().parents[1] / "tests" / "RAG"
    if bench.is_dir() and str(bench) not in sys.path:
        sys.path.insert(0, str(bench))
    try:
        from frtr_sql_baseline import answer_sqlish, load_sheets
    except Exception:
        return None

    cites: list[dict] = []
    # Prefer Docs/ originals (audit), then live path.
    frames: dict = {}
    for src in store.list_sources(int(space_id)):
        meta = src.get("meta") if isinstance(src.get("meta"), dict) else {}
        docs = str(meta.get("docs_path") or "").strip()
        path = docs or str(src.get("path") or "")
        if not path.lower().endswith((".xlsx", ".xlsm", ".xls")):
            continue
        p = Path(path)
        if not p.is_file():
            # Docs missing — fall back to ingest path
            path = str(src.get("path") or "")
            p = Path(path)
            if not p.is_file():
                continue
        try:
            sheets = load_sheets(p)
        except Exception:
            continue
        pred = answer_sqlish(sheets, query)
        if pred and not str(pred).startswith("ABSTAIN:"):
            return {
                "answer": str(pred),
                "citations": [
                    {
                        "path": path,
                        "path_full": path,
                        "title": src.get("title") or p.name,
                        "docs_path": docs or None,
                    }
                ],
            }
        if pred and str(pred).startswith("ABSTAIN:"):
            return {
                "answer": str(pred),
                "citations": [{"path": path, "title": src.get("title") or p.name}],
            }
        for k, df in sheets.items():
            frames[f"{p.name}:{k}"] = df
        cites.append({"path": path, "title": src.get("title") or p.name})
    if not frames:
        return None
    # Flatten to bare sheet names for answer_sqlish (last workbook wins on clash)
    flat = {}
    for key, df in frames.items():
        flat[key.split(":", 1)[-1]] = df
    pred = answer_sqlish(flat, query)
    if not pred:
        return None
    return {"answer": str(pred), "citations": cites[:5]}


def answer_events(
    space_id: int,
    query: str,
    *,
    depth: str = "high",
    use_llm: bool = True,
    model_tier: str | None = None,
    use_web: bool | None = None,
    source_ids: list[int] | None = None,
) -> Iterator[dict]:
    """Yield RAG SSE events: thinking?, meta, citations, delta*, done|error.

    Does not persist chat messages — caller owns that (avoids double-write).
    When use_web is True (or auto when the ask clearly wants the web / coverage is
    thin), DuckDuckGo results are ingested into the space before answering so chat
    is not stuck on the Build-tab search box.
    """
    refuse = destructive_injection_reply(query)
    raw_q = (query or "").strip()

    # Hybrid SQL lane (demo variant hybrid_max): act once, never confirm-loop.
    try:
        from rag import demo_variants as _dv
        from rag import ontology as _onto

        _preset = _dv.resolve_for_space(space_id)
        _ont = _onto.ontology_for_space(space_id, force=False)
        _logic = _onto.logic_for_query(_ont if _ont.get("ok") else {}, raw_q)
        _reason = _onto.reasoning_prose(_logic, query=raw_q)
        if _logic:
            yield {
                "type": "ontology",
                "summary": (_ont.get("summary") if isinstance(_ont, dict) else None),
                "logic": _logic,
                "reasoning": _reason,
            }
            yield {
                "type": "thinking",
                "text": "Ontology → " + " → ".join(s.get("op") or "" for s in _logic),
            }
            if _reason:
                yield {"type": "reasoning", "text": _reason, "logic": _logic}
        if _preset.get("hybrid_sql_lane") and raw_q:
            sql_hit = _try_hybrid_sql_lane(space_id, raw_q)
            if sql_hit:
                yield {"type": "thinking", "text": "Hybrid SQL lane (no confirm loop)…"}
                yield {
                    "type": "meta",
                    "depth": depth,
                    "variant": _preset.get("name"),
                    "honesty": _preset.get("honesty"),
                    "lane": "sql",
                    "logic": _logic,
                    "reasoning": _reason,
                    "ontology_summary": _ont.get("summary") if isinstance(_ont, dict) else None,
                    "hits": [],
                    "context": "",
                }
                yield {"type": "citations", "citations": sql_hit.get("citations") or []}
                yield {"type": "delta", "text": sql_hit["answer"]}
                yield {
                    "type": "done",
                    "answer": sql_hit["answer"],
                    "citations": sql_hit.get("citations") or [],
                    "hits": [],
                    "model": "pandas-sql",
                    "lane": "sql",
                    "honesty": _preset.get("honesty"),
                    "variant": _preset.get("name"),
                    "logic": _logic,
                    "reasoning": _reason,
                    "ontology_summary": _ont.get("summary") if isinstance(_ont, dict) else None,
                }
                return
    except Exception:
        pass

    # Strip /edit · "web search about" chrome so retrieval + web ingest get a real topic
    if refuse or wants_web(raw_q) or raw_q.lower().startswith("/edit"):
        knowledge_q = web_query_from_ask(raw_q)
    else:
        knowledge_q = raw_q

    # "What does this RAG contain?" → inventory, not topical retrieve (avoids JEPA wall)
    if wants_corpus_summary(raw_q) and not wants_web(raw_q):
        yield from _inventory_answer_events(space_id, use_llm=use_llm, depth=depth, refuse=refuse)
        return

    yield {"type": "thinking", "text": "Retrieving evidence…"}
    # Typo tolerance: correct out-of-vocabulary query terms against the corpus so
    # a misspelled distinctive term ("secuirty hardning") still retrieves.
    try:
        from rag import spell as _spell
        _fixed = _spell.correct_query(knowledge_q or query, space_id)
        if _fixed and _fixed != (knowledge_q or query):
            yield {"type": "thinking", "text": "Corrected likely typos in the query…"}
            knowledge_q = _fixed
    except Exception:
        pass
    query = knowledge_q or query
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
                step = retrieve.search(space_id, query_r, depth=depth, top_k=top_k, debug=False, source_ids=source_ids)
        else:
            step = retrieve.search(space_id, query_r, depth=depth, top_k=top_k, debug=False, source_ids=source_ids)
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

    # Web augment only when asked (client use_web=true, or natural-language web cues).
    web_snippets_ctx = ""
    web_snippet_rows: list[dict] = []
    web_error = ""
    auto_web = bool(use_web) if use_web is not None else wants_web(raw_q)
    goals = split_web_goals(raw_q or knowledge_q or query)
    if auto_web:
        yield {"type": "thinking", "text": "Searching the public web (split goals)…"}
        aug = _web_augment_space(space_id, raw_q or query, max_pages=6)
        goals = list(aug.get("goals") or goals)
        if aug.get("ok"):
            n_url = len(aug.get("urls") or [])
            n_snip = len(aug.get("snippets") or [])
            yield {
                "type": "thinking",
                "text": f"Web: {len(goals)} goal(s) · {n_url} page(s) · {aug.get('chunks') or 0} chunks · {n_snip} snippets",
            }
            if aug.get("chunks"):
                # Re-retrieve per goal so resistor docs don't dominate a LeCun ask
                for g in goals[:4]:
                    step = retrieve.search(
                        space_id, g, depth=depth, top_k=max(4, top_k // 2), debug=False, source_ids=source_ids
                    )
                    if step.get("ok"):
                        for h in step.get("hits") or []:
                            cid = int(h.get("chunk_id") or 0)
                            if cid and (
                                cid not in merged
                                or float(h.get("score") or 0) > float(merged[cid].get("score") or 0)
                            ):
                                merged[cid] = h
                hits = _diversify(
                    _prefer_web_over_chats(_lexical_rerank(" ".join(goals), list(merged.values()))),
                    top_k,
                )
                hits = _filter_hits_to_goals(hits, goals, knowledge_q or query)
                coverage = _coverage(" ".join(goals), hits)
                gap_terms = [t for t in _salient_tokens(" ".join(goals)) if t not in _evidence_blob(hits)]
                rounds.append(
                    {
                        "round": "web",
                        "query": aug.get("query") or query,
                        "n_new": len(hits),
                        "coverage": round(coverage, 3),
                    }
                )
            if aug.get("snippets"):
                web_snippet_rows.extend(aug["snippets"])
                web_snippets_ctx = _snippets_context(web_snippet_rows)
            dist = goal_distance(goals, hits, web_snippets_ctx)
            yield {
                "type": "thinking",
                "text": f"Goal distance {dist['distance']:.0%} — missing: {', '.join(dist['missing'][:3]) or 'none'}",
            }
            if dist["distance"] >= 0.4 and dist["missing"]:
                yield {"type": "thinking", "text": "Distance to goal still high — searching missing topics…"}
                for miss in dist["missing"][:3]:
                    if not _goal_ok(miss):
                        continue
                    aug2 = _web_augment_space(space_id, miss, max_pages=3)
                    if aug2.get("chunks"):
                        step = retrieve.search(
                            space_id, miss, depth=depth, top_k=max(4, top_k // 2), debug=False, source_ids=source_ids
                        )
                        if step.get("ok"):
                            for h in step.get("hits") or []:
                                cid = int(h.get("chunk_id") or 0)
                                if cid and (
                                    cid not in merged
                                    or float(h.get("score") or 0) > float(merged[cid].get("score") or 0)
                                ):
                                    merged[cid] = h
                            hits = _diversify(
                                _prefer_web_over_chats(
                                    _lexical_rerank(" ".join(goals), list(merged.values()))
                                ),
                                top_k,
                            )
                    if aug2.get("snippets"):
                        web_snippet_rows.extend(aug2["snippets"])
                        web_snippets_ctx = _snippets_context(web_snippet_rows)
                hits = _filter_hits_to_goals(hits, goals, knowledge_q or query)
                dist = goal_distance(goals, hits, web_snippets_ctx)
                rounds.append(
                    {
                        "round": "web2",
                        "query": " | ".join(dist["missing"][:3]),
                        "coverage": round(1.0 - dist["distance"], 3),
                    }
                )
                yield {"type": "thinking", "text": f"After second pass, goal distance {dist['distance']:.0%}"}
            if merged:
                hits = _diversify(
                    _prefer_web_over_chats(
                        _lexical_rerank(" ".join(goals) if goals else query, list(merged.values()))
                    ),
                    top_k,
                )
                hits = _filter_hits_to_goals(hits, goals, knowledge_q or query)
        else:
            why = (aug.get("error") or "no pages").strip()
            web_error = why
            yield {
                "type": "thinking",
                "text": f"Web search skipped ({why[:80]}) — answering from local sources only.",
            }
            if aug.get("snippets"):
                web_snippet_rows.extend(aug["snippets"])
                web_snippets_ctx = _snippets_context(web_snippet_rows)

    # Drop off-topic local docs (resistors on a LeCun ask) even without web
    if goals and hits:
        hits = _filter_hits_to_goals(hits, goals, knowledge_q or query)
        coverage = _coverage(
            " ".join(goals) if len(goals) > 1 else (knowledge_q or query),
            hits,
        )

    if not hits:
        stop_reason = "no_evidence"
    elif coverage >= _COVERAGE_FLOOR:
        stop_reason = "evidence_ok"
    else:
        stop_reason = "gaps_disclosed"

    if refuse and not (knowledge_q and len(knowledge_q) > 12 and not re.search(r"\b(delete|wipe|erase)\b", knowledge_q, re.I)):
        # Pure wipe / delete-all with nothing left to answer
        for piece in _chunk_text(refuse):
            yield {"type": "delta", "text": piece}
        yield {
            "type": "done",
            "answer": refuse,
            "trace_id": result.get("trace_id") if result else None,
            "confidence": 1.0,
            "stop_reason": "policy_refuse",
            "rounds": len(rounds),
            "coverage": coverage,
            "faithfulness": 1.0,
            "unsupported_claims": [],
            "model": "policy",
            "citations": [],
            "hits": [],
            "context": "",
            "template_id": (result or {}).get("template_id"),
            "depth": depth,
        }
        return

    citations = []
    # Web snippets first so the UI "sources visited" is not only chat_*
    for i, sn in enumerate(web_snippet_rows[:8], start=1):
        url = str(sn.get("url") or "")
        citations.append(
            {
                "chunk_id": 0,
                "path": url or f"web:{i}",
                "path_full": url,
                "title": (sn.get("title") or url or f"Web {i}")[:160],
                "heading": "web",
                "span_start": None,
                "span_end": None,
                "parent_id": None,
                "score": 0.55,
                "excerpt": (sn.get("snippet") or "")[:280],
                "web": True,
            }
        )
    # Only document/web chunks may be cited. Past chat transcripts contain the
    # assistant's own earlier answers, so citing them lets a fabrication come back
    # wearing a citation — which is exactly how an invented netie.ai description
    # survived being corrected. They stay retrievable as context, never as proof.
    evidence_hits, convo_hits = authority.split_evidence(list(hits))
    for h in evidence_hits:
        cid = int(h.get("chunk_id") or 0)
        meta_row = store.get_chunk(cid) or {}
        raw_path = h.get("path") or meta_row.get("path") or ""
        docs_path = ""
        try:
            src_id = int(meta_row.get("source_id") or h.get("source_id") or 0)
            if src_id:
                src = store.get_source(src_id) or {}
                sm = src.get("meta") if isinstance(src.get("meta"), dict) else {}
                docs_path = str(sm.get("docs_path") or "").strip()
                # Prefer durable Docs / live source path over vanished temp uploads
                live = str(src.get("path") or "").strip()
                if docs_path:
                    raw_path = docs_path
                elif live and Path(live).is_file():
                    raw_path = live
                elif not raw_path:
                    raw_path = str(sm.get("original_path") or live or "")
        except Exception:
            docs_path = ""
        citations.append(
            {
                "chunk_id": cid,
                "path": _display_path(raw_path),
                "path_full": raw_path,
                "docs_path": docs_path or None,
                "title": Path(str(raw_path).replace("\\", "/")).name if raw_path else "",
                "heading": h.get("heading") or meta_row.get("heading"),
                "span_start": meta_row.get("span_start"),
                "span_end": meta_row.get("span_end"),
                "parent_id": meta_row.get("parent_id") or h.get("parent_id"),
                "score": h.get("score"),
                "excerpt": (h.get("text") or "")[:280],
                "authority": h.get("authority") or "document",
            }
        )
    context = build_context_block(evidence_hits)
    if convo_hits and not evidence_hits:
        # Nothing citable. Hand the transcripts over clearly marked so the model can
        # talk about the conversation without presenting it as established fact.
        context = (
            "No documents or web pages matched. The only matches are transcripts of "
            "earlier chats, which are NOT evidence — they may contain the assistant's "
            "own past guesses. Do not state anything from them as fact:\n"
            + build_context_block(convo_hits)
        )
    if web_snippets_ctx:
        # Prefer web evidence ahead of chat_* when the user asked to search
        context = (
            "Web search evidence (cite as [Wn] when used):\n"
            + web_snippets_ctx
            + ("\n\nLocal corpus evidence:\n" + context if context.strip() else "")
        )
    # Confidence tracks citable evidence only — a pile of chat matches is not support.
    confidence = (
        min(1.0, sum(float(h.get("score") or 0) for h in evidence_hits[:3]) / 3.0)
        if evidence_hits
        else 0.0
    )
    if web_snippets_ctx and confidence < 0.35:
        confidence = 0.45

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

    # Measure the gap before writing a word, so "I could not support this" is a
    # measured outcome rather than something the model decides to feel bad about.
    assessment = goal.assess(
        query,
        evidence_hits,
        convo_hits,
        web_ran=bool(auto_web),
        web_error=str(web_error or ""),
    )
    if web_snippet_rows and assessment.verdict == "unsupported":
        # Snippets are real fetched evidence even when nothing was indexed deeply.
        assessment.verdict = "partial"

    # Safety net: inventory asks that slipped past the opener (typos, "all files", …)
    # used to fall through to "missing: summarise, tlel, file" — never do that again.
    if (
        not wants_web(raw_q)
        and assessment.verdict == "unsupported"
        and (
            wants_corpus_summary(raw_q)
            or (
                re.search(r"\b(summaris|summariz|overview|inventory|list)\b", raw_q, re.I)
                and re.search(r"\b(file|files|source|sources|doc|docs|about|mention)\b", raw_q, re.I)
            )
        )
    ):
        yield from _inventory_answer_events(space_id, use_llm=use_llm, depth=depth, refuse=refuse)
        return

    # One refined retrieval aimed only at missing terms (JEPA-style close-the-gap).
    # It spends from the SAME budget as the corrective loop above — `_round_cap` is the
    # documented promise that High costs at most two retrievals, and a gap-closing pass
    # is still a retrieval. Without this guard High quietly did three.
    if len(rounds) >= caps:
        pass
    elif assessment.verdict != "answerable" and assessment.missing:
        refined = goal.refine_query(query, assessment)
        if refined and refined.casefold() != (query or "").casefold():
            yield {"type": "thinking", "text": f"Refining on missing terms: {refined[:80]}…"}
            step = retrieve.search(space_id, refined, depth=depth, top_k=top_k, debug=False, source_ids=source_ids)
            if step.get("ok"):
                for h in step.get("hits") or []:
                    cid = int(h.get("chunk_id") or 0)
                    if cid and (cid not in merged or float(h.get("score") or 0) > float(merged[cid].get("score") or 0)):
                        merged[cid] = h
                hits = _diversify(
                    _prefer_web_over_chats(_lexical_rerank(query, list(merged.values()))),
                    top_k,
                )
                evidence_hits, convo_hits = authority.split_evidence(list(hits))
                citations = [c for c in citations if c.get("web")]
                for h in evidence_hits:
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
                            "authority": h.get("authority") or "document",
                        }
                    )
                context = build_context_block(evidence_hits)
                if web_snippets_ctx:
                    context = (
                        "Web search evidence (cite as [Wn] when used):\n"
                        + web_snippets_ctx
                        + ("\n\nLocal corpus evidence:\n" + context if context.strip() else "")
                    )
                assessment = goal.assess(
                    query,
                    evidence_hits,
                    convo_hits,
                    web_ran=bool(auto_web),
                    web_error=str(web_error or ""),
                )
                if web_snippet_rows and assessment.verdict == "unsupported":
                    assessment.verdict = "partial"
                rounds.append({"round": "refine", "query": refined[:200], "coverage": round(assessment.coverage, 3)})
                yield {
                    "type": "thinking",
                    "text": f"After refine: goal distance {assessment.distance:.0%} · {assessment.verdict}",
                }

    # An unsupported verdict must not arrive wearing eight citations.
    #
    # Asking "what is netie ai" of a space holding only JEPA pages scored every chunk
    # at ~0.045 — noise — yet still attached them as sources and pasted their text as
    # the answer. The user reads "8 sources visited" and a wall of JEPA prose under a
    # sentence saying nothing could be supported. Citing unrelated documents is its own
    # kind of fabrication, so when the evidence does not reach the question we show the
    # gap and nothing else. Pages fetched live this turn stay listed: those really were
    # visited, and saying so is honest.
    if assessment.verdict == "unsupported":
        citations = [c for c in citations if c.get("web")]
        context = ""
        evidence_hits = []
        confidence = 0.0  # no bar for an answer we just declined to give

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
        "goal": assessment.as_dict(),
    }
    yield {"type": "citations", "citations": citations}

    if not use_llm or (not context.strip() and not hits):
        text = extractive_answer(query, evidence_hits) if evidence_hits else ""
        if web_snippets_ctx and not text:
            text = "From web search:\n" + web_snippets_ctx[:2000]
        # Lead with the measured gap, then the diagnosis — an honest "here is what is
        # missing and what to do" beats a fluent paragraph built on nothing.
        lead = goal.summary_line(assessment)
        if lead:
            text = (lead + "\n\n" + text).strip()
        if assessment.diagnosis:
            text += "\n\nTo get a better answer:\n" + "\n".join(
                f"- {d}" for d in assessment.diagnosis
            )
        if refuse:
            text = refuse + "\n\n" + text
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
            "goal": assessment.as_dict(),
            "model": "extractive",
            "citations": citations,
            "hits": hits,
            "context": context,
            "template_id": result.get("template_id"),
            "depth": result.get("depth") or depth,
        }
        return

    system, user = grounded_prompt(query, context)
    if assessment.verdict != "answerable":
        system += (
            " Evidence is incomplete for this question. Lead with what is known, name what is "
            "missing, and do not invent facts to fill gaps. If diagnosis steps are implied by "
            "missing terms, state them plainly."
        )
        if assessment.diagnosis:
            user += "\n\nMeasured gaps / next actions:\n" + "\n".join(
                f"- {d}" for d in assessment.diagnosis
            )
    text = ""
    model = "llm"
    if refuse:
        for piece in _chunk_text(refuse + "\n\n"):
            yield {"type": "delta", "text": piece}
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

    if refuse:
        text = refuse + "\n\n" + (text or "")

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
        "goal": assessment.as_dict(),
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
    use_web: bool | None = None,
    source_ids: list[int] | None = None,
) -> dict:
    """Blocking answer — collects answer_events."""
    text = ""
    citations: list = []
    hits: list = []
    context = ""
    done: dict = {}
    for ev in answer_events(
        space_id, query, depth=depth, use_llm=use_llm, use_web=use_web, source_ids=source_ids
    ):
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
        "goal": done.get("goal") or {},
        "rounds": done.get("rounds"),
        "coverage": done.get("coverage"),
        "model": done.get("model"),
        "lane": done.get("lane"),
        "variant": done.get("variant"),
        "honesty": done.get("honesty"),
        "logic": done.get("logic"),
        "ontology_summary": done.get("ontology_summary"),
    }

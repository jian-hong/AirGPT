"""SiRA-inspired lexical enrichment — DF-guarded, no free-form rewrite.

Reference: https://github.com/facebookresearch/sira (offline phrases + query expansion).
Default: heuristic phrases. Opt-in LLM enrich via AIRGPT_RAG_ENRICH=llm (soft-fail).
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_\-./]{1,}")

_LLM_SYSTEM = (
    "You extract short index phrases for lexical search. "
    "Return ONLY a JSON array of strings (no markdown). "
    "Phrases must appear in or clearly name concepts from the text: "
    "headings, API/identifiers, filenames, proper nouns. "
    "No full sentences, no rewriting the document."
)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def heuristic_index_phrases(text: str, *, max_phrases: int = 24) -> list[str]:
    """Extract filename-like tokens, CamelCase, headings-ish lines, and rare terms."""
    phrases: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("#"):
            h = s.lstrip("#").strip()
            if 2 <= len(h) <= 80:
                phrases.append(h)
        # identifier-looking tokens
        for tok in _TOKEN_RE.findall(s):
            if any(c.isupper() for c in tok) and any(c.islower() for c in tok):
                phrases.append(tok)
            elif "_" in tok or "/" in tok or "." in tok:
                if len(tok) >= 4:
                    phrases.append(tok)
    # rare unigrams by local frequency (proxy for DF until corpus DF table exists)
    counts = Counter(tokenize(text))
    rare = [w for w, c in counts.most_common() if c == 1 and 4 <= len(w) <= 40]
    phrases.extend(rare[: max_phrases // 2])
    # dedupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for p in phrases:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
        if len(out) >= max_phrases:
            break
    return out


def merge_phrases(*lists: list[str], max_phrases: int = 24) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for lst in lists:
        for p in lst:
            s = (p or "").strip()
            if not s or len(s) > 80:
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
            if len(out) >= max_phrases:
                return out
    return out


def llm_enrich_enabled(use_llm: bool | None = None) -> bool:
    if use_llm is not None:
        return bool(use_llm)
    return (os.environ.get("AIRGPT_RAG_ENRICH") or "").strip().lower() == "llm"


def _parse_phrase_json(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    # Strip optional markdown fences
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except Exception:
        # Try to find a JSON array substring
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except Exception:
            return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:80])
        elif isinstance(item, (int, float)):
            continue
    return out


def llm_index_phrases(text: str, *, max_phrases: int = 24) -> list[str]:
    """Ask the standard LLM for index phrases. Raises on provider failure."""
    import ai_engine

    snippet = (text or "")[:6000]
    prompt = (
        f"Extract up to {max_phrases} short index phrases from this document.\n"
        "Return a JSON array of strings only.\n\n"
        f"---\n{snippet}\n---"
    )
    result, _provider = ai_engine._standard_llm(prompt, _LLM_SYSTEM, max_tokens=400, task="rag")
    return _parse_phrase_json(result)[:max_phrases]


def index_phrases(
    text: str,
    *,
    max_phrases: int = 24,
    use_llm: bool | None = None,
) -> list[str]:
    """Heuristic by default; merge LLM phrases when AIRGPT_RAG_ENRICH=llm (soft-fail)."""
    base = heuristic_index_phrases(text, max_phrases=max_phrases)
    if not llm_enrich_enabled(use_llm):
        return base
    try:
        extra = llm_index_phrases(text, max_phrases=max_phrases)
        return merge_phrases(base, extra, max_phrases=max_phrases)
    except Exception:
        return base


def corpus_df(phrases_by_doc: list[list[str]]) -> dict[str, int]:
    df: Counter[str] = Counter()
    for phrases in phrases_by_doc:
        for p in {x.lower() for x in phrases}:
            df[p] += 1
    return dict(df)


def filter_phrases_by_df(
    candidates: list[str],
    df: dict[str, int],
    *,
    n_docs: int,
    min_df: int = 1,
    max_df_ratio: float = 0.5,
) -> list[str]:
    """Reject absent or overly generic expansions (SiRA DF guard)."""
    out: list[str] = []
    ceiling = max(1, int(n_docs * max_df_ratio))
    for c in candidates:
        key = c.lower()
        d = int(df.get(key, 0))
        if d < min_df:
            continue
        if d > ceiling and n_docs >= 4:
            continue
        out.append(c)
    return out


def expand_query(
    query: str,
    *,
    index_phrases: list[str],
    df: dict[str, int] | None = None,
    n_docs: int = 1,
    max_terms: int = 8,
) -> list[str]:
    """Constrained expansion: only keep query tokens + DF-valid index phrases that overlap."""
    q_toks = set(tokenize(query))
    cands: list[str] = []
    for p in index_phrases:
        pl = p.lower()
        pt = set(tokenize(p))
        if pt & q_toks or any(t in pl for t in q_toks if len(t) >= 4):
            cands.append(p)
    if df:
        cands = filter_phrases_by_df(cands, df, n_docs=n_docs)
    # Always keep original query tokens as terms
    terms = list(dict.fromkeys(list(q_toks) + cands))
    return terms[:max_terms]

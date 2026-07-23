"""Free web search for RAG sources — DuckDuckGo HTML endpoint, stdlib only.

No API key, no external packages. Soft-fail contract: always returns a dict,
never raises. Results feed the existing ingest_urls pipeline (search → pick →
ingest → retrieve → cite), so search stays a *source acquisition* step and the
corpus remains the single ground truth.
"""
from __future__ import annotations

import html as html_mod
import re
import urllib.parse
import urllib.request

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AirGPT-RAG/1.0"


def _strip_tags(s: str) -> str:
    return html_mod.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _decode_ddg(href: str) -> str:
    """DDG result hrefs are usually redirect links carrying uddg=<real url>."""
    h = href or ""
    if h.startswith("//"):
        h = "https:" + h
    if "uddg=" in h:
        try:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(h).query)
            real = (qs.get("uddg") or [""])[0]
            if real:
                return real
        except Exception:
            pass
    return h


def search_web(query: str, *, max_results: int = 8, timeout: int = 12) -> dict:
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query required"}
    # DDG's HTML endpoint blocks GET (bot challenge) but serves POST form queries.
    body = urllib.parse.urlencode({"q": q, "kl": "us-en"}).encode()
    req = urllib.request.Request(
        "https://html.duckduckgo.com/html/",
        data=body,
        headers={"User-Agent": _UA, "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            page = r.read(1_500_000).decode("utf-8", "replace")
    except Exception as e:
        return {"ok": False, "error": f"search fetch failed: {str(e)[:120]}"}

    results: list[dict] = []
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        u = _decode_ddg(m.group(1))
        title = _strip_tags(m.group(2))
        if not u.startswith("http") or "duckduckgo.com" in urllib.parse.urlparse(u).netloc:
            continue
        results.append({"title": title[:200] or u, "url": u, "snippet": ""})
        if len(results) >= max_results:
            break
    snippets = [_strip_tags(s) for s in re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', page, re.S)]
    for i, s in enumerate(snippets[: len(results)]):
        results[i]["snippet"] = s[:280]

    if not results:
        return {"ok": False, "error": "no results (engine may be rate-limiting — try again)", "query": q}
    return {"ok": True, "query": q, "results": results}

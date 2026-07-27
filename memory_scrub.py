"""Remove the assistant's stored accounts of links from local memory.

Memory is injected into later prompts as context, so an answer saved once keeps
coming back. That is fine for what the user said and what was decided. It is not
fine for the model's own description of a web page or a person behind a URL: if
the page could not be read, the answer was a guess, and storing it turns one
guess into a durable fact the model rediscovers on every related question. This
actually happened - two contradictory biographies of the same real person were
produced and both were saved.

The page is re-fetchable at any time, so nothing is lost by refusing to cache a
summary of it. The question is kept, so "we looked at netie.ai" stays recallable.

Prevention lives in ai_engine.persist_turn_memory. This module cleans up what was
stored before that guard existed.
"""
from __future__ import annotations

import re
from typing import Any

URL_RE = re.compile(r"https?://", re.I)
_ANSWER_RE = re.compile(r"^(?P<q>Q:.*?)(?:\n)A:\s*(?P<a>.*)$", re.S)

REPLACEMENT = (
    "A: [removed] this was the assistant's own account of a link, which may have "
    "been a guess. Re-read the page instead of trusting a remembered summary."
)


def _is_link_answer(mem: dict[str, Any]) -> bool:
    """True when this memory stores an assistant answer about a URL-bearing question."""
    body = str(mem.get("body") or "")
    if not URL_RE.search(body) and not URL_RE.search(str(mem.get("title") or "")):
        return False
    m = _ANSWER_RE.match(body.strip())
    if not m:
        return False
    answer = (m.group("a") or "").strip()
    if not answer or answer.startswith(("[not stored]", "[removed]")):
        return False  # already safe
    return True


def scrub(*, dry_run: bool = True, limit: int = 2000) -> dict[str, Any]:
    """Rewrite link-answer memories so the question survives and the claim does not.

    Rewriting rather than deleting: the fact that a topic was discussed is real
    signal, and an irreversible delete is a poor default for someone else's data.
    """
    import memory_index as mi

    mi.init()
    rows = mi.list_memories(limit=limit) or []
    changed: list[dict[str, Any]] = []
    for mem in rows:
        if not _is_link_answer(mem):
            continue
        body = str(mem.get("body") or "").strip()
        m = _ANSWER_RE.match(body)
        if not m:
            continue
        new_body = f"{m.group('q').strip()}\n{REPLACEMENT}"
        entry = {
            "id": mem.get("id"),
            "title": (mem.get("title") or "")[:80],
            "before": (m.group("a") or "").strip()[:160],
        }
        if not dry_run:
            try:
                mi.update_memory(int(mem["id"]), body=new_body)
            except Exception as exc:  # keep going; one bad row must not stop the sweep
                entry["error"] = str(exc)[:120]
        changed.append(entry)
    return {
        "ok": True,
        "dry_run": dry_run,
        "scanned": len(rows),
        "affected": len(changed),
        "items": changed,
    }


if __name__ == "__main__":  # pragma: no cover - operator entry point
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    args = ap.parse_args()
    print(json.dumps(scrub(dry_run=not args.apply), indent=2)[:4000])

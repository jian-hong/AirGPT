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


# ---------------------------------------------------------------------------
# The .md mirror.
#
# scrub() above rewrites the SQLite row, but update_memory writes no drawer - only
# add_memory mirrors - so the row read "[removed]" while the drawer beside it still
# held the full claim. And retrieve_vault_snippets greps the drawers, not the rows.
# Cleaning one side was worse than useless: it made the problem look solved while the
# fabrication kept being injected. On the machine this was found on, 12 of 46 drawers
# carried the same invented biography.

_FRONTMATTER_RE = re.compile(r"^---\n(?P<meta>.*?)\n---\n(?P<rest>.*)$", re.S)
_DRAWER_QA_RE = re.compile(r"(?P<head>.*?\nQ:.*?\n)A:\s*(?P<a>.*)$", re.S)


def _drawer_meta(text: str) -> dict[str, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group("meta").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _classify_drawer(text: str) -> str | None:
    """Why this drawer is a stored account of a link, or None to leave it alone.

    Conservative on purpose. A drawer that merely mentions a URL in passing is not
    evidence the model invented anything, and destroying real notes would be a far
    worse failure than leaving one guess in place.
    """
    if not URL_RE.search(text):
        return None
    if "[removed]" in text or "[not stored]" in text:
        return None  # already scrubbed
    m = _FRONTMATTER_RE.match(text)
    body = m.group("rest") if m else text

    qa = _DRAWER_QA_RE.match(body)
    if qa:
        # The question carried the URL, so the answer is the model's guess about it.
        return "qa_link_answer" if URL_RE.search(qa.group("head")) else None
    # The dual_brain feedback drawer is written straight from a chat answer with no
    # question stored beside it, so a URL in the body is the only signal available.
    meta = _drawer_meta(text)
    if meta.get("source") == "dual_brain" and meta.get("room") == "feedback":
        return "dual_brain_link_answer"
    return None


def scrub_drawers(*, dry_run: bool = True, root: str = "") -> dict[str, Any]:
    """Rewrite link-answer drawers under data/vault, keeping the question.

    Rewrite, never delete - same reasoning as scrub(). dry_run is the default so the
    operator sees the whole list before anything on disk changes.
    """
    from pathlib import Path

    if root:
        base = Path(root)
    else:
        from config import DATA_DIR

        base = Path(DATA_DIR) / "vault"
    if not base.is_dir():
        return {"ok": False, "error": f"no vault at {base}", "scanned": 0, "affected": 0, "items": []}

    changed: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    scanned = 0
    for path in sorted(base.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        scanned += 1
        why = _classify_drawer(text)
        if not why:
            # Carries a URL but the conservative rules above cannot prove it is an
            # assistant guess - typically because the URL sits in the answer rather
            # than the question, or the writer used a `source` this module does not
            # know. Reporting it beats both silently rewriting real notes and
            # silently leaving a fabrication in place: on the machine this was built
            # for, 6 of the 12 drawers holding an invented biography landed here.
            if URL_RE.search(text) and "[removed]" not in text and "[not stored]" not in text:
                meta = _drawer_meta(text)
                review.append(
                    {
                        "path": str(path),
                        "source": meta.get("source", ""),
                        "room": meta.get("room", ""),
                        "excerpt": text[-400:].strip()[:160],
                    }
                )
            continue

        m = _FRONTMATTER_RE.match(text)
        head = m.group("meta") if m else ""
        body = m.group("rest") if m else text

        if why == "qa_link_answer":
            qa = _DRAWER_QA_RE.match(body)
            new_body = qa.group("head") + REPLACEMENT
            before = (qa.group("a") or "").strip()[:160]
        else:
            title = next((ln for ln in body.splitlines() if ln.startswith("# ")), "")
            new_body = (title + "\n\n" if title else "") + REPLACEMENT
            before = body.strip()[:160]

        new_text = f"---\n{head}\n---\n{new_body}" if m else new_body
        entry = {"path": str(path), "why": why, "before": before}
        if not dry_run:
            try:
                path.write_text(new_text, encoding="utf-8")
            except Exception as exc:  # one bad file must not stop the sweep
                entry["error"] = str(exc)[:120]
        changed.append(entry)

    return {
        "ok": True,
        "dry_run": dry_run,
        "scanned": scanned,
        "affected": len(changed),
        "items": changed,
        # Never empty silently. A sweep that reports only what it fixed reads as
        # "all clear" when it is not.
        "needs_review": len(review),
        "review": review,
    }


if __name__ == "__main__":  # pragma: no cover - operator entry point
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    ap.add_argument("--drawers", action="store_true", help="also sweep the .md mirror under data/vault")
    args = ap.parse_args()
    print("== memory rows ==")
    print(json.dumps(scrub(dry_run=not args.apply), indent=2)[:4000])
    if args.drawers:
        print("== vault drawers ==")
        print(json.dumps(scrub_drawers(dry_run=not args.apply), indent=2)[:6000])

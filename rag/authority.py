"""How much a source is allowed to be believed.

A knowledge space happily ingests three very different things and, until now, ranked
them as equals:

  * documents the user supplied,
  * web pages the engine fetched,
  * transcripts of past chats — which contain the assistant's own previous answers.

That third class is the dangerous one. On 2026-07-26 the engine answered a question
about netie.ai by citing `chat_126.md`, which contained an earlier *fabricated*
description of netie.ai that the model itself had written. The correction was also in
the index (`chat_134.md`) and lost the ranking. A model citing its own hallucination
back to the user is indistinguishable from grounding, and it compounds every time the
conversation is re-ingested.

So conversation text is retrievable — "what did we decide last week" is a fair question
— but it is never evidence for a claim about the world, and it never becomes a
citation. If that leaves a space with nothing to stand on, the honest answer is to say
so, not to quote yesterday's guess.
"""
from __future__ import annotations

import os
import re

DOCUMENT = "document"
WEB = "web"
CONVERSATION = "conversation"

# Multiplies the retrieval score. Conversation is not zeroed out — it still wins when a
# question is genuinely about the conversation — but it cannot bury fetched evidence.
WEIGHT = {DOCUMENT: 1.0, WEB: 1.0, CONVERSATION: 0.25}

# Only these can be cited.
EVIDENCE_KINDS = (DOCUMENT, WEB)

_CHAT_RE = re.compile(r"(^|[\\/])chat_\d+\.md$", re.IGNORECASE)
_URL_RE = re.compile(r"(^|[\\/])url_", re.IGNORECASE)


def classify(path: str = "", title: str = "", mime: str = "") -> str:
    """Best-effort source class from the little that retrieval carries around."""
    p = (path or "").strip()
    t = (title or "").strip()
    if _CHAT_RE.search(p) or _CHAT_RE.search(t) or t.lower().startswith("chat_"):
        return CONVERSATION
    if _URL_RE.search(p) or t.lower().startswith("url_"):
        return WEB
    return DOCUMENT


def weight(kind: str) -> float:
    return WEIGHT.get(kind or DOCUMENT, 1.0)


def is_evidence(kind: str) -> bool:
    """May a chunk of this class be cited as support for a claim?"""
    return (kind or DOCUMENT) in EVIDENCE_KINDS


def label(kind: str) -> str:
    if kind == CONVERSATION:
        return "prior conversation (not a source of truth)"
    if kind == WEB:
        return "web page"
    return "document"


def display_name(path: str = "", title: str = "") -> str:
    """Human-facing source name — a bare hash filename tells the user nothing."""
    base = os.path.basename((title or path or "").strip()) or "source"
    return base


def split_evidence(hits: list[dict]) -> tuple[list[dict], list[dict]]:
    """Partition retrieved hits into citable evidence and conversation-only context."""
    evidence: list[dict] = []
    context: list[dict] = []
    for h in hits or []:
        kind = h.get("authority") or classify(h.get("path") or "", h.get("heading") or "")
        h["authority"] = kind
        (evidence if is_evidence(kind) else context).append(h)
    return evidence, context

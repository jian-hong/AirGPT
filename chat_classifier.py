"""Smarter chat grouping — route messages to the right session space.

Rules (owner spec, 2026-07-22):
  * screenshot/image ANALYSIS → each gets an ISOLATED session (no shared context;
    keeps vision prompts small and avoids cross-contaminated history).
  * random small-talk / one-off chatter → ONE shared "Scratch" space with **no
    linkage** (history is not fed back as context) to cut memory + compute.
  * substantive topics → stick with the current session; a topic shift beyond
    the overlap threshold suggests a new session.

Pure stdlib, deterministic, no LLM call — cheap enough to run on every message.
Wire-in point: clipdrop.post_message / queue_analysis pick session_id; callers
can consult classify() first. Not wired yet (additive module + tests only).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SCRATCH_SESSION_NAME = "Scratch"

_ST_WORD = (
    r"(?:hi|hello|hey|yo|thanks?|thank\s+you|ok(?:ay)?|nice|cool|lol|ha(?:ha)+|"
    r"good\s+(?:morning|night|evening)|test(?:ing)?|wow|bye|see\s+ya|gg|yes|no|"
    r"yep|nope|sure|great|bro|lah|\?+|\.+)"
)
# sequences of small-talk tokens ("haha nice", "ok thanks bye") still count
_SMALLTALK = re.compile(rf"(?i)^(?:{_ST_WORD}[\s!.?,~]*)+$")
_WORD = re.compile(r"[a-zA-Z一-鿿]{3,}")

# context budget guidance for the driver (chars of history to attach)
CONTEXT_BUDGET = {"isolated": 0, "scratch": 0, "topic": 6000}


@dataclass(frozen=True, slots=True)
class Routing:
    space: str          # "isolated" | "scratch" | "topic"
    new_session: bool   # start a fresh session_id?
    attach_history: bool
    context_chars: int
    reason: str


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or "")}


def topic_overlap(text: str, recent_texts: list[str]) -> float:
    """Jaccard overlap between message and recent session text (0..1)."""
    t = _tokens(text)
    if not t:
        return 0.0
    r: set[str] = set()
    for rt in recent_texts:
        r |= _tokens(rt)
    if not r:
        return 0.0
    return len(t & r) / max(1, len(t | r))


def classify(
    text: str = "",
    *,
    kind: str = "text",              # "text" | "image" | "file"
    is_analysis: bool = False,        # screenshot/file analysis run?
    recent_texts: list[str] | None = None,
    overlap_threshold: float = 0.08,
) -> Routing:
    """Decide which chat space a message belongs to."""
    if kind in ("image", "file") and is_analysis:
        return Routing(
            space="isolated", new_session=True, attach_history=False,
            context_chars=CONTEXT_BUDGET["isolated"],
            reason="analysis runs are isolated — no cross-context",
        )
    txt = (text or "").strip()
    if len(txt) <= 24 and _SMALLTALK.match(txt):
        return Routing(
            space="scratch", new_session=False, attach_history=False,
            context_chars=CONTEXT_BUDGET["scratch"],
            reason="small-talk → shared Scratch space, no linkage",
        )
    recent = recent_texts or []
    if recent and topic_overlap(txt, recent) < overlap_threshold and len(_tokens(txt)) >= 4:
        return Routing(
            space="topic", new_session=True, attach_history=False,
            context_chars=CONTEXT_BUDGET["topic"],
            reason="topic shift — suggest a fresh session",
        )
    return Routing(
        space="topic", new_session=False, attach_history=True,
        context_chars=CONTEXT_BUDGET["topic"],
        reason="continuing current topic — attach bounded history",
    )

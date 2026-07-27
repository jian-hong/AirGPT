"""How far is the evidence from actually answering the question?

Retrieval quietly succeeds at the wrong thing all the time: it returns forty chunks,
none of which mention the two words the question was actually about. The engine then
writes a fluent paragraph anyway. The user's complaint — "wrong, no verify" — is that
nothing ever measured the gap between what was asked and what was found.

So measure it explicitly, before generating:

    assess(query, evidence, conversation) -> Assessment
        .distance     0.0 = fully covered, 1.0 = nothing relevant found
        .missing      the salient terms with no support anywhere in the evidence
        .verdict      "answerable" | "partial" | "unsupported"
        .diagnosis    concrete, ordered fixes when it is not answerable

`distance` is what a retry loop should drive down, and what the UI can show as a
confidence bar. `diagnosis` is what to print instead of a confident guess — it names
the actual reason (no sources, only chat transcripts, terms absent from the corpus)
rather than apologising in general terms.

Deliberately deterministic and free: this runs on every answer, so it cannot cost a
model call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rag import authority

# Below this, generating prose is more likely to invent than to report.
ANSWERABLE_MAX_DISTANCE = 0.45
PARTIAL_MAX_DISTANCE = 0.75

_STOP = {
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "that", "this", "these",
    "those", "is", "are", "was", "were", "be", "been", "being", "to", "of", "in", "on",
    "for", "with", "by", "as", "at", "from", "about", "into", "it", "its", "how", "what",
    "why", "when", "where", "which", "who", "whom", "can", "could", "should", "would",
    "will", "do", "does", "did", "you", "your", "me", "my", "we", "our", "us", "i",
    "please", "tell", "explain", "give", "show", "search", "web", "look", "up", "find",
    "hmm", "yup", "ok", "okay", "also", "so", "there", "here", "not", "no", "yes",
    # Common verbs/auxiliaries. Without these a refined retry query becomes
    # "cortex use" instead of "cortex", and the filler term drags retrieval off target.
    "use", "used", "uses", "using", "have", "has", "had", "get", "got", "make", "made",
    "need", "want", "know", "think", "say", "said", "work", "works", "help", "let",
    "any", "all", "some", "more", "most", "much", "many", "other", "same", "such",
    "like", "just", "only", "still", "even", "back", "out", "over", "down", "off",
}
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-+./]{1,}")


@dataclass
class Assessment:
    distance: float
    coverage: float
    verdict: str
    missing: list[str] = field(default_factory=list)
    covered: list[str] = field(default_factory=list)
    evidence_count: int = 0
    conversation_only: bool = False
    diagnosis: list[str] = field(default_factory=list)

    @property
    def answerable(self) -> bool:
        return self.verdict == "answerable"

    def as_dict(self) -> dict:
        return {
            "distance": round(self.distance, 3),
            "coverage": round(self.coverage, 3),
            "verdict": self.verdict,
            "missing": self.missing,
            "covered": self.covered,
            "evidence_count": self.evidence_count,
            "conversation_only": self.conversation_only,
            "diagnosis": self.diagnosis,
        }


def salient_terms(query: str, limit: int = 12) -> list[str]:
    """Content words the answer is actually expected to be about."""
    out: list[str] = []
    for w in _WORD.findall(query or ""):
        t = w.lower().strip(".")
        if len(t) < 3 or t in _STOP or t in out:
            continue
        out.append(t)
        if len(out) >= limit:
            break
    return out


def _blob(hits: list[dict]) -> str:
    return " ".join(
        f"{h.get('heading') or ''} {h.get('path') or ''} {h.get('text') or ''}"
        for h in hits or []
    ).lower()


def assess(
    query: str,
    evidence: list[dict] | None = None,
    conversation: list[dict] | None = None,
    *,
    web_ran: bool = False,
    web_error: str = "",
) -> Assessment:
    evidence = list(evidence or [])
    conversation = list(conversation or [])
    terms = salient_terms(query)
    blob = _blob(evidence)

    covered = [t for t in terms if t in blob]
    missing = [t for t in terms if t not in blob]
    coverage = (len(covered) / len(terms)) if terms else (1.0 if evidence else 0.0)
    if not evidence:
        coverage = 0.0
    distance = 1.0 - coverage

    if distance <= ANSWERABLE_MAX_DISTANCE and evidence:
        verdict = "answerable"
    elif distance <= PARTIAL_MAX_DISTANCE and evidence:
        verdict = "partial"
    else:
        verdict = "unsupported"

    a = Assessment(
        distance=distance,
        coverage=coverage,
        verdict=verdict,
        missing=missing,
        covered=covered,
        evidence_count=len(evidence),
        conversation_only=bool(conversation and not evidence),
    )
    if verdict != "answerable":
        a.diagnosis = diagnose(a, web_ran=web_ran, web_error=web_error)
    return a


def diagnose(a: Assessment, *, web_ran: bool = False, web_error: str = "") -> list[str]:
    """Ordered, concrete next actions. Never generic apology."""
    out: list[str] = []
    if a.conversation_only:
        out.append(
            "This space only matched past chat transcripts, which are not evidence — "
            "they can contain the assistant's own earlier guesses. Add real sources "
            f"({authority.label(authority.DOCUMENT)}s or URLs) on the Build tab."
        )
    elif a.evidence_count == 0:
        out.append("No document or web evidence matched. Add sources on the Build tab.")

    if a.missing:
        shown = ", ".join(a.missing[:6])
        out.append(f"No source mentions: {shown}. The corpus likely does not cover this topic.")

    if not web_ran:
        out.append("Run a web search for this question — say \"web search about …\" or arm Web search in the composer.")
    elif web_error:
        out.append(f"Web search ran but failed ({web_error[:100]}). Retry, or paste a URL on the Build tab.")
    elif a.missing:
        out.append("Web search ran but the fetched pages did not cover the missing terms — try a narrower query, or paste a specific URL.")

    if a.evidence_count and a.coverage < 0.5:
        out.append("Rebuild the space with smaller chunks so specific terms are not diluted across long passages.")

    return out[:5]


def refine_query(query: str, a: Assessment) -> str:
    """Second-round query aimed at what is actually missing, not the whole question."""
    if not a.missing:
        return query
    return " ".join(a.missing[:6])


def summary_line(a: Assessment) -> str:
    """One honest sentence for the answer body when evidence is short."""
    if a.verdict == "answerable":
        return ""
    pct = int(round(a.coverage * 100))
    if a.verdict == "unsupported":
        return f"I could not support an answer from this space ({pct}% of the asked terms appear in any source)."
    return f"Partial answer only — {pct}% of the asked terms appear in the sources; missing: {', '.join(a.missing[:5])}."

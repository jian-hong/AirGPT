"""Lightweight intent detection: chat → Cortex / RAG / Memory (soft chips, no hijack)."""
from __future__ import annotations

import re

_RAG_PATTERNS = [
    r"\brag\b",
    r"knowledge\s*base",
    r"index\s+(this|my|the)\s+(folder|project|repo|files?)",
    r"ingest\b",
    r"build\s+a\s+(rag|corpus|knowledge)",
    r"vector\s*search",
    r"chunk(ing)?\b",
    r"upload\s+(folder|files?).*(search|ask|chat)",
]
_AGENTIC_PATTERNS = [
    r"\bagents?\b",
    r"\bcortex\b",
    r"run\s+the\s+agent",
    r"tool\s*loop",
    r"automat(e|ion)",
    r"multi[- ]?step",
    r"use\s+tools?\s+to",
]
_MEMORY_PATTERNS = [
    r"\bremember\b",
    r"what\s+did\s+we\s+(decide|agree|say)",
    r"from\s+memory",
    r"@memory",
    r"last\s+time\s+we",
]


def classify_intent(text: str) -> dict:
    t = (text or "").strip().lower()
    if not t:
        return {"intent": "none", "confidence": 0.0, "suggest": None}

    scores = {"rag": 0.0, "cortex": 0.0, "memory": 0.0}
    for pat in _RAG_PATTERNS:
        if re.search(pat, t, re.I):
            scores["rag"] += 1.0
    for pat in _AGENTIC_PATTERNS:
        if re.search(pat, t, re.I):
            scores["cortex"] += 1.0
    for pat in _MEMORY_PATTERNS:
        if re.search(pat, t, re.I):
            scores["memory"] += 1.0

    intent, score = max(scores.items(), key=lambda x: x[1])
    if score <= 0:
        return {"intent": "chat", "confidence": 0.2, "suggest": None, "scores": scores}

    suggest = {
        "rag": {"action": "open_rag", "label": "Continue in RAG Agent?"},
        "cortex": {"action": "open_cortex", "label": "Open in Cortex?"},
        "memory": {"action": "open_memory", "label": "Ask Memory Agent?"},
    }[intent]
    return {
        "intent": intent,
        "confidence": min(1.0, score / 3.0),
        "suggest": suggest,
        "scores": scores,
    }

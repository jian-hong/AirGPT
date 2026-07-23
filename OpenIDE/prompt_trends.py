"""Prompt-trend memory — turn repeated OpenIDE asks into one-step-ahead advice.

Stores lightweight n-gram / keyword counts under data/prompt_trends.json.
Never stores secrets. Advice is injected into scaffold seed prompts.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from config import DATA_DIR

TRENDS_FILE = DATA_DIR / "prompt_trends.json"
_STOP = frozenset(
    "a an the and or for to of in on with from my a app build make create please help me".split()
)
_WORD = re.compile(r"[a-z0-9]{3,}")


def _load() -> dict[str, Any]:
    if TRENDS_FILE.is_file():
        try:
            return json.loads(TRENDS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"prompts": [], "tokens": {}, "updated_at": 0}


def _save(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = time.time()
    TRENDS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _tokens(prompt: str) -> list[str]:
    return [w for w in _WORD.findall((prompt or "").lower()) if w not in _STOP]


def record_and_advise(prompt: str) -> dict[str, Any]:
    """Record a prompt and return automation advice if trends emerge."""
    data = _load()
    toks = _tokens(prompt)
    if not toks:
        return {"ok": True, "advice": "", "hits": {}}

    hist: list[dict] = list(data.get("prompts") or [])
    hist.append({"t": time.time(), "tokens": toks[:24], "preview": (prompt or "")[:160]})
    data["prompts"] = hist[-80:]

    counts: dict[str, int] = dict(data.get("tokens") or {})
    for w in toks:
        counts[w] = int(counts.get(w) or 0) + 1
    data["tokens"] = counts
    _save(data)

    # Advice when a token appears often across history
    hot = sorted(
        ((w, n) for w, n in counts.items() if n >= 3 and w in toks),
        key=lambda x: -x[1],
    )[:5]
    advice_bits: list[str] = []
    for w, n in hot:
        if w in ("test", "tests", "pytest", "playwright", "stress"):
            advice_bits.append(
                f"You often ask about '{w}' ({n}x) — after implementing, add a smoke test and run it."
            )
        elif w in ("deploy", "ship", "openship", "hosting"):
            advice_bits.append(
                f"You often ask about '{w}' ({n}x) — leave deploy notes + OpenShip/env hooks in README."
            )
        elif w in ("ui", "button", "polish", "css", "design"):
            advice_bits.append(
                f"You often ask about '{w}' ({n}x) — prioritize contrast, primary CTA, and keyboard Run."
            )
        elif w in ("key", "keys", "vault", "openfree", "omniroute"):
            advice_bits.append(
                f"You often ask about '{w}' ({n}x) — wire Key Vault / OpenFree; never hardcode secrets."
            )
        else:
            advice_bits.append(
                f"Recurring theme '{w}' ({n}x) — treat it as a standing requirement unless the user overrides."
            )

    # Same-ish prompt seen before → stress until works
    recent = hist[:-1][-12:]
    overlap = 0
    for prev in recent:
        prev_set = set(prev.get("tokens") or [])
        if len(prev_set & set(toks)) >= 3:
            overlap += 1
    if overlap >= 2:
        advice_bits.append(
            "Similar prompts repeated — implement end-to-end, then stress-test until the happy path works."
        )

    return {"ok": True, "advice": "\n".join(advice_bits), "hits": dict(hot)}

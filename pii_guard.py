"""PII guard — layer 1 of the AirGPT safety stack.

Deterministic regex NER that redacts personal data from text BEFORE it is sent
to any CLOUD provider. Local engines (Ollama / vLLM / SGLang / Colibri) are
exempt by design: data that never leaves the laptop needs no masking, and this
preserves full fidelity for the local-first path.

Design rules:
  * Pure stdlib, zero deps, compiled once at import — adds <1ms per call.
  * Placeholders are stable within one text ([EMAIL_1], [EMAIL_2], …) so the
    model can still reason about "the same email mentioned twice".
  * Credit cards are Luhn-validated to avoid false positives on invoice ids.
  * Layer 2 (model-based NER for names/addresses) is a research-gated upgrade —
    see docs/research brief F-section; this module is the choke point it will
    plug into.

Toggle: env PII_GUARD=0 disables (default on). Audit logging is done by the
caller (ai_engine) so this module stays side-effect free.
"""
from __future__ import annotations

import os
import re

# --- Patterns (order matters: most specific first) -------------------------
_PATTERNS: list[tuple[str, re.Pattern]] = [
    # Secrets / API keys — never send even to "trusted" clouds
    ("KEY", re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}"
        r"|ghp_[A-Za-z0-9]{36}|gho_[A-Za-z0-9]{36}|xox[bpars]-[A-Za-z0-9-]{10,}"
        r"|AIza[0-9A-Za-z_-]{35}|ya29\.[0-9A-Za-z_-]{20,})\b")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # Singapore NRIC/FIN + Malaysian IC (YYMMDD-PB-###G)
    ("NRIC", re.compile(r"\b[STFGM]\d{7}[A-Z]\b")),
    ("MYIC", re.compile(r"\b\d{6}-\d{2}-\d{4}\b")),
    # Phones: intl +xx… and common MY/SG local forms (guarded to avoid years/ids)
    ("PHONE", re.compile(
        r"(?<![\w.])(?:\+\d{1,3}[ -]?)?(?:\d{2,4}[ -]){1,3}\d{3,4}(?![\w.])"
        r"|(?<![\w.])\+\d{8,15}(?![\w.])")),
    ("IPV4", re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
                        r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b")),
    # Card numbers: 13-19 digits with optional spaces/dashes → Luhn check
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
]

_MIN_PHONE_DIGITS = 8  # fewer digits → likely a quantity/id, not a phone


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def enabled() -> bool:
    return (os.environ.get("PII_GUARD") or "1").strip() not in ("0", "false", "off")


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Return (redacted_text, {kind: count}). Original text is never logged."""
    if not text or not enabled():
        return text, {}
    findings: dict[str, int] = {}
    seen: dict[str, str] = {}  # original span -> placeholder (stable references)

    def _sub(kind: str, m: re.Match) -> str:
        raw = m.group(0)
        if kind == "CARD":
            digits = re.sub(r"[^\d]", "", raw)
            if not (13 <= len(digits) <= 19 and _luhn_ok(digits)):
                return raw
        if kind == "PHONE":
            digits = re.sub(r"[^\d]", "", raw)
            if len(digits) < _MIN_PHONE_DIGITS or len(digits) > 15:
                return raw
        if raw in seen:
            return seen[raw]
        findings[kind] = findings.get(kind, 0) + 1
        ph = f"[{kind}_{findings[kind]}]"
        seen[raw] = ph
        return ph

    out = text
    for kind, pat in _PATTERNS:
        out = pat.sub(lambda m, k=kind: _sub(k, m), out)
    return out, findings


def self_check() -> dict:
    sample = (
        "Mail oojianhongg@gmail.com or +60 12-345 6789, IC 990101-14-5678, "
        "NRIC S1234567D, card 4539 1488 0343 6467, key sk-abcdefghij1234567890, "
        "invoice 12345 stays, year 2026 stays."
    )
    red, f = redact(sample)
    assert "[EMAIL_1]" in red and "[MYIC_1]" in red and "[NRIC_1]" in red
    assert "[CARD_1]" in red and "[KEY_1]" in red and "[PHONE_1]" in red
    assert "2026" in red and "12345" in red  # no false positives
    assert "gmail" not in red and "4539" not in red
    return {"ok": True, "findings": f, "sample": red[:120]}


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(self_check(), indent=2))

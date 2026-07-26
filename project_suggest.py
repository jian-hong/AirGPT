"""Suggest a better project for a chat whose subject has drifted. Never move it.

Deliberately deterministic — pure stdlib, no LLM call. This runs after every assistant
turn, so it must not add latency to the reply path, must not cost a token, and must not
give a different answer when the same conversation is replayed.

The bar for showing anything is high on purpose. A single off-topic question inside an
Engineering chat is normal conversation, and prompting on it is noise the user learns to
dismiss without reading. So a suggestion needs **three consecutive** user turns that all
point at the same other category, each with a clear lexical signal, before it surfaces.
Dismissing silences it for the rest of the session.

Public surface:
    classify(text)                         -> (category, confidence)
    observe(session_id, text, current)     -> dict for the UI
    dismiss(session_id)                    -> stop suggesting in this session
    reset(session_id=None)                 -> tests / new chat
"""
from __future__ import annotations

import re
import threading

# "general" is the fallback bucket, never a suggestion — moving a chat *into* General
# tells the user nothing and costs them a click.
SUGGESTABLE = ("engineering", "ml", "finance")

STREAK_REQUIRED = 3
MIN_MARKERS = 2          # distinct domain terms in a single turn
MIN_LEAD = 1             # winner must beat runner-up by this many markers
MIN_CONFIDENCE = 0.5
MIN_CONTENT_WORDS = 4

# Terms are drawn from the domain focus lines in ai_engine.MODES. Kept narrow: a term
# earns its place only if it is far more likely in its domain than in general chat.
# "model", "signal", "risk" and friends are deliberately absent — they are everywhere.
CATEGORY_TERMS: dict[str, frozenset[str]] = {
    "engineering": frozenset(
        """serdes pll cdr transceiver eye-diagram jitter ber equalizer ffe dfe ctle
        adc dac opamp op-amp transistor mosfet cmos bjt vlsi rtl verilog vhdl netlist
        testbench silicon wafer fab tapeout foundry substrate pcb layout parasitic
        impedance capacitance inductance transconductance slew phase-noise crosstalk
        s-parameters insertion-loss return-loss nyquist decoupling ldo buck boost
        bandgap thermal-noise flicker-noise snr sndr enob thd spur harmonic
        oscilloscope spectrum-analyzer probe bandwidth rise-time setup-time hold-time
        high-speed-io backplane""".split()
    ),
    "ml": frozenset(
        """transformer attention self-attention embedding embeddings tokenizer tokens
        logits softmax gradient backprop backpropagation optimizer adam sgd learning-rate
        epoch epochs batch-size overfitting regularization dropout finetune fine-tune
        finetuning pretrain pretraining checkpoint inference quantization quantized lora
        rag retrieval-augmented vector-database cosine-similarity perplexity bleu rouge
        hallucination prompt-engineering few-shot zero-shot cnn rnn lstm gan diffusion
        convolution pooling activation relu gelu loss-function cross-entropy
        hyperparameter dataset-split validation-set""".split()
    ),
    "finance": frozenset(
        """valuation dcf ebitda ebit p/e pe-ratio eps revenue margin gross-margin
        free-cash-flow fcf balance-sheet income-statement cash-flow amortization
        depreciation portfolio hedge hedging derivative derivatives futures options
        call-option put-option strike expiry greeks delta gamma vega theta implied-vol
        volatility sharpe drawdown alpha beta yield coupon bond treasury duration
        interest-rate inflation macro cpi fed dividend buyback market-cap ticker
        earnings-call guidance short-interest arbitrage""".split()
    ),
}

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-/.]*")

_lock = threading.Lock()
# session_id -> {"cat": str, "streak": int, "dismissed": bool}
_state: dict[int, dict] = {}


def _terms(text: str) -> set[str]:
    """Lowercased word set plus hyphen-joined bigrams, so `phase noise` matches too."""
    words = [w.lower().strip(".") for w in _WORD.findall(text or "")]
    words = [w for w in words if w]
    out = set(words)
    out.update(f"{a}-{b}" for a, b in zip(words, words[1:]))
    return out


def classify(text: str) -> tuple[str, float]:
    """Best domain guess for one message. ("general", 0.0) when nothing stands out."""
    found = _terms(text)
    if len(found) < MIN_CONTENT_WORDS:
        return ("general", 0.0)

    hits = {cat: len(found & terms) for cat, terms in CATEGORY_TERMS.items()}
    ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    top_cat, top_n = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0

    if top_n < MIN_MARKERS or (top_n - runner_up) < MIN_LEAD:
        return ("general", 0.0)
    return (top_cat, min(1.0, top_n / 4.0))


def _quiet(**extra) -> dict:
    return {"suggest": False, "category": "", "project": "", "confidence": 0.0, **extra}


def observe(session_id: int, text: str, current_category: str = "general") -> dict:
    """Record one user turn and report whether to surface a suggestion."""
    sid = int(session_id or 0)
    if not sid:
        return _quiet(reason="no session")

    with _lock:
        st = _state.setdefault(sid, {"cat": "", "streak": 0, "dismissed": False})
        if st["dismissed"]:
            return _quiet(reason="dismissed this session")

        cat, conf = classify(text)
        current = (current_category or "general").strip().lower()

        # Nothing to say: no signal, already there, or not a suggestable bucket.
        if cat == "general" or cat == current or cat not in SUGGESTABLE:
            st["cat"], st["streak"] = "", 0
            return _quiet(reason="no drift", streak=0)

        if st["cat"] == cat:
            st["streak"] += 1
        else:
            st["cat"], st["streak"] = cat, 1

        streak = st["streak"]
        if streak < STREAK_REQUIRED or conf < MIN_CONFIDENCE:
            return _quiet(reason="building confidence", streak=streak, candidate=cat)

        return {
            "suggest": True,
            "category": cat,
            "project": cat.capitalize(),
            "confidence": round(conf, 2),
            "streak": streak,
        }


def dismiss(session_id: int) -> None:
    sid = int(session_id or 0)
    if not sid:
        return
    with _lock:
        st = _state.setdefault(sid, {"cat": "", "streak": 0, "dismissed": False})
        st["dismissed"] = True
        st["cat"], st["streak"] = "", 0


def accepted(session_id: int) -> None:
    """The chat moved — clear the streak so it does not immediately re-suggest."""
    sid = int(session_id or 0)
    with _lock:
        _state[sid] = {"cat": "", "streak": 0, "dismissed": False}


def reset(session_id: int | None = None) -> None:
    with _lock:
        if session_id is None:
            _state.clear()
        else:
            _state.pop(int(session_id), None)

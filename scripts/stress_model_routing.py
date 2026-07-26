#!/usr/bin/env python3
"""Stress-test use-case model routing (no GPU/build box required).

Dry-run by default: prints the cascade each task would use given keys present
in env.local. Pass --live to hit each available provider with a 1-token ping
(costs a few cents / free-tier units).

  python scripts/stress_model_routing.py
  python scripts/stress_model_routing.py --live
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="Actually call providers")
    args = ap.parse_args()

    import ai_engine

    env = ai_engine.load_env()
    known = ("anthropic", "openai", "groq", "openrouter", "sea-lion", "google", "deepseek")
    key_map = {
        "anthropic": bool(env.get("ANTHROPIC_API_KEY")),
        "openai": bool(env.get("OPENAI_API_KEY")),
        "groq": bool(env.get("GROQ_API_KEY") or env.get("GROQ_API_KEY_SISWA")),
        "openrouter": bool(env.get("OPENROUTER_API_KEY")),
        "sea-lion": bool(env.get("SEA_LION_API_KEY") or env.get("SEA_LION_API_KEY_SISWA")),
        "google": bool(env.get("GOOGLE_API_KEY")),
        "deepseek": bool(env.get("DEEPSEEK_API_KEY")),
    }
    print("Keys present:", {k: v for k, v in key_map.items() if v} or "(none)")
    print("Default order:", list(ai_engine._DEFAULT_CLOUD_ORDER))
    print()

    samples = {
        "chat": "Explain RRF fusion in one paragraph.",
        "rag": "Cite the SNR stitching method from the corpus.",
        "agent": "List the next three tool calls for a file edit.",
        "multilingual": "Tolong terangkan apa itu RAG dalam bahasa Melayu.",
        "multilingual_zh": "请用中文解释什么是检索增强生成。",
        "router": '{"complexity":"low"}',
    }

    for task, prompt in samples.items():
        order = ai_engine._cloud_provider_order(known, task=task.split("_")[0], prompt=prompt)
        with_keys = [p for p in order if key_map.get(p)]
        print(f"[{task}] cascade: {' -> '.join(order)}")
        print(f"         available: {' -> '.join(with_keys) or '(none)'}")
        print(f"         multilingual={ai_engine._looks_multilingual(prompt)}")

    # Assert Gemini is ahead of SEA-LION for English chat/rag when both present
    chat = ai_engine._cloud_provider_order(known, task="chat", prompt="hello")
    rag = ai_engine._cloud_provider_order(known, task="rag", prompt="hello")
    if "google" in chat and "sea-lion" in chat:
        assert chat.index("google") < chat.index("sea-lion"), chat
    if "google" in rag and "sea-lion" in rag:
        assert rag.index("google") < rag.index("sea-lion"), rag
    ml = ai_engine._cloud_provider_order(known, task="chat", prompt="请解释")
    if "sea-lion" in ml and "google" in ml:
        assert ml.index("sea-lion") < ml.index("google"), ml
    print("\nOrder assertions: OK")

    if not args.live:
        print("\nDry-run only. Re-run with --live to ping providers.")
        return 0

    # Windows consoles are often cp1252 — keep live output ASCII-safe
    def _safe(s: str) -> str:
        return (s or "").encode("ascii", "replace").decode("ascii")

    results = []
    for task, prompt in (("chat", "Reply with exactly: OK"), ("rag", "Reply with exactly: OK")):
        t0 = time.monotonic()
        try:
            text, model = ai_engine._standard_llm(prompt, "You reply with one short word.", max_tokens=8, task=task)
            ms = int((time.monotonic() - t0) * 1000)
            results.append({"task": task, "model": model, "ms": ms, "text": (text or "")[:40], "ok": True})
            print(_safe(f"LIVE {task}: {model} in {ms}ms -> {(text or '')[:40]!r}"))
        except Exception as e:
            results.append({"task": task, "error": str(e)[:200], "ok": False})
            print(_safe(f"LIVE {task}: FAIL {e}"))

    out = ROOT + os.sep + "data" + os.sep + "routing_stress.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"at": time.time(), "results": results, "keys": key_map}, f, indent=2)
    print(f"Wrote {out}")
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

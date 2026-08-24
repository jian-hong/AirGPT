"""Compare the Groq models AirGPT routes through, and verify the pinned IDs still exist.

Two jobs:

  --list    Ask Groq which models the key can actually serve, and flag any ID pinned
            in ai_engine._GROQ_MODELS that is missing. A retired ID answers 404, which
            is indistinguishable from an outage - that is exactly how a dead
            `google/gemini-2.0-flash-001` made OpenRouter look broken for weeks.

  (default) Run every pinned model over the same probes and print latency plus the
            answers, so "which one is better" is decided by reading output rather
            than by vibes.

    python scripts/bench_groq_models.py --list
    python scripts/bench_groq_models.py
    python scripts/bench_groq_models.py --repeat 3

Needs GROQ_API_KEY in env.local (or the environment). Nothing here writes secrets;
the key is read, used, and never printed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

import ai_engine  # noqa: E402

BASE = "https://api.groq.com/openai/v1"

# Probes chosen to separate these models on the work AirGPT actually does, not on
# trivia. Each has a checkable expectation so a wrong answer is visible at a glance.
PROBES = (
    (
        "reasoning",
        "A bat and a ball cost $1.10 total. The bat costs $1.00 more than the ball. "
        "How much is the ball? Reply with just the amount.",
        "expect $0.05 - the intuitive $0.10 is wrong",
    ),
    (
        "instruction",
        "Reply with exactly three words, lowercase, no punctuation.",
        "expect exactly 3 lowercase words",
    ),
    (
        "multilingual",
        "用一句话解释什么是向量数据库。",
        "expect one fluent Chinese sentence - this is the SEA-LION-vs-Groq case",
    ),
    (
        "grounding",
        "What is the population of the fictional city of Zzyzxville? "
        "If you do not know, say you do not know.",
        "expect a refusal, NOT an invented number",
    ),
)


def _key() -> str:
    env = ai_engine.load_env()
    k = (env.get("GROQ_API_KEY") or "").strip()
    if not k:
        sys.exit(
            "GROQ_API_KEY not found in env.local or the environment.\n"
            "Add it yourself (never paste a key into a chat), then re-run."
        )
    return k


def _get(path: str, key: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}", headers={"Authorization": f"Bearer {key}"}, method="GET"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def cmd_list(key: str) -> int:
    try:
        data = _get("/models", key)
    except urllib.error.HTTPError as e:
        print(f"FAIL  /models -> HTTP {e.code} {e.reason}")
        if e.code in (401, 403):
            print("      The key is rejected. Reissue it at https://console.groq.com/keys")
        return 1
    live = sorted(m.get("id", "") for m in data.get("data", []))
    print(f"Groq serves {len(live)} model ids for this key.\n")

    pinned = [m for m, _ in ai_engine._GROQ_MODELS]
    print("Pinned in ai_engine._GROQ_MODELS:")
    missing = 0
    for m in pinned:
        ok = m in live
        if not ok:
            missing += 1
        print(f"  {'OK     ' if ok else 'MISSING'}  {m}")

    extra = [m for m in live if m not in pinned and "whisper" not in m and "guard" not in m]
    if extra:
        print("\nAvailable but not pinned (candidates):")
        for m in extra:
            print(f"           {m}")

    if missing:
        print(f"\n{missing} pinned id(s) no longer exist - they will answer 404 and look")
        print("like an outage. Update _GROQ_MODELS before trusting the cascade.")
        return 1
    print("\nAll pinned ids are live.")
    return 0


def ask(model: str, prompt: str, key: str, timeout: int = 60) -> tuple[bool, float, str]:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.6,
        "max_completion_tokens": 512,
    }
    t0 = time.monotonic()
    try:
        out = ai_engine._http_post(
            f"{BASE}/chat/completions", {"Authorization": f"Bearer {key}"}, body, timeout=timeout
        )
    except Exception as e:
        wait = ai_engine._retry_after_seconds(e)
        note = f"{type(e).__name__}: {e}"
        if wait:
            note += f"  [server says retry in {wait:.2f}s]"
        return False, time.monotonic() - t0, note[:200]
    text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return True, time.monotonic() - t0, text.strip()


def cmd_bench(key: str, repeat: int) -> int:
    models = [m for m, _ in ai_engine._GROQ_MODELS]
    print(f"Comparing {len(models)} models over {len(PROBES)} probes x {repeat} run(s).\n")

    latency: dict[str, list[float]] = {m: [] for m in models}
    failures: dict[str, int] = {m: 0 for m in models}

    for name, prompt, expectation in PROBES:
        print("=" * 78)
        print(f"PROBE: {name}   ({expectation})")
        print(f"  prompt: {prompt}")
        print("=" * 78)
        for model in models:
            for i in range(repeat):
                ok, secs, text = ask(model, prompt, key)
                if ok:
                    latency[model].append(secs)
                else:
                    failures[model] += 1
                tag = f"  {model:28s} {secs:6.2f}s "
                if not ok:
                    print(tag + "FAIL  " + text)
                else:
                    first = text.replace("\n", " ")
                    print(tag + ("| " + first[:150] + ("..." if len(first) > 150 else "")))
                # Stay inside 30 RPM even with several models in flight.
                time.sleep(0.4)
        print()

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  {'model':28s} {'runs':>5s} {'fails':>6s} {'median':>8s} {'slowest':>8s}")
    for m in models:
        xs = sorted(latency[m])
        if xs:
            med = xs[len(xs) // 2]
            print(f"  {m:28s} {len(xs):5d} {failures[m]:6d} {med:7.2f}s {xs[-1]:7.2f}s")
        else:
            print(f"  {m:28s} {0:5d} {failures[m]:6d} {'-':>8s} {'-':>8s}")

    n = len(PROBES) * repeat
    print(f"\n  n = {n} calls per model. That is enough to compare latency and to spot an")
    print("  obviously wrong answer, and nowhere near enough to claim an accuracy rate:")
    print(f"  zero errors in {n} trials only bounds the true error rate at about {3 / max(n, 1):.0%}.")
    print("  Read the answers above and judge quality yourself.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="verify pinned model ids still exist")
    ap.add_argument("--repeat", type=int, default=1, help="runs per probe per model")
    args = ap.parse_args()
    key = _key()
    return cmd_list(key) if args.list else cmd_bench(key, max(1, args.repeat))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())

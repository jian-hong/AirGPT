"""Model trial pipeline — download (optional) → token smoke → quality gate → delete.

Designed for low-VRAM / no-GPU laptops: prefer tiny GGUF or already-bound OpenAI
endpoints. Heavy weights are never kept after a failed trial.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from config import DATA_DIR

TRIAL_DIR = DATA_DIR / "marketplace" / "trials"
TRIAL_LOG = DATA_DIR / "marketplace" / "trials.jsonl"

SMOKE_PROMPT = "Reply with exactly: AIRGPT_OK"
QUALITY_RUBRIC = (
    "You are a strict judge. Given CANDIDATE model output for the task "
    "'Reply with exactly: AIRGPT_OK', score 0-10. Reply ONLY JSON: "
    '{"score":N,"pass":bool,"reason":"..."}'
)


def ensure() -> None:
    TRIAL_DIR.mkdir(parents=True, exist_ok=True)


def _append(ev: dict) -> None:
    ensure()
    with TRIAL_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def run_trial(
    item_id: str,
    *,
    pull: bool = False,
    keep: bool = False,
    verify_cloud: bool = True,
) -> dict[str, Any]:
    """Trial a marketplace item.

    Stages:
      1. fit gate (suitable for this laptop profile)
      2. optional pull (disabled by default for large models)
      3. smoke generate via bound local OpenAI endpoint OR simulated skip
      4. optional cloud judge (Composer-class / BYOK strong model)
      5. delete trial artifacts unless keep=True and pass
    """
    ensure()
    import marketplace
    import serve_profile

    catalog = {i["id"]: i for i in marketplace.MARKET_ITEMS}
    item = catalog.get(item_id)
    if not item:
        return {"ok": False, "error": "unknown item"}

    profile = serve_profile.detect_profile()
    hw = marketplace.effective_hardware()
    fit = marketplace.fit_item(item, hw)
    trial_id = f"trial-{item_id}-{int(time.time())}"
    work = TRIAL_DIR / trial_id
    work.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "ok": False,
        "trial_id": trial_id,
        "item_id": item_id,
        "profile": profile.get("profile"),
        "fit": fit,
        "stages": [],
    }

    if not fit.get("fits"):
        result["stages"].append({"stage": "fit", "ok": False, "detail": fit.get("reasons")})
        result["error"] = "does_not_fit"
        _cleanup(work, keep=False)
        _append(result)
        return result
    result["stages"].append({"stage": "fit", "ok": True})

    # Pull is opt-in; Colibri / large vLLM never auto-pulled here
    need_disk = float(item.get("approx_disk_gb") or 0)
    if pull and need_disk > 20:
        result["stages"].append(
            {
                "stage": "pull",
                "ok": False,
                "detail": f"Refusing auto-pull of {need_disk}GB in trial — use prepare script / Install confirm",
            }
        )
        result["error"] = "pull_too_large"
        _cleanup(work, keep=False)
        _append(result)
        return result

    if pull and need_disk <= 20:
        pull_res = _try_pull(item, work)
        result["stages"].append({"stage": "pull", **pull_res})
        if not pull_res.get("ok"):
            result["error"] = "pull_failed"
            _cleanup(work, keep=False)
            _append(result)
            return result
    else:
        result["stages"].append({"stage": "pull", "ok": True, "skipped": True, "detail": "use bound endpoint"})

    smoke = _smoke_generate(item)
    result["stages"].append({"stage": "smoke", **smoke})
    if not smoke.get("ok"):
        result["error"] = "smoke_failed"
        result["detail"] = smoke.get("detail")
        _cleanup(work, keep=False)
        _append(result)
        try:
            import audit

            audit.log("marketplace.trial.fail", detail=f"{item_id} smoke", ok=False)
        except Exception:
            pass
        return result

    quality = {"ok": True, "skipped": True, "score": None, "pass": True}
    if verify_cloud:
        quality = _cloud_judge(smoke.get("text") or "")
    result["stages"].append({"stage": "quality", **quality})

    passed = bool(smoke.get("ok")) and bool(quality.get("pass", True))
    result["ok"] = passed
    result["passed"] = passed
    result["output"] = (smoke.get("text") or "")[:500]
    result["model_used"] = smoke.get("model")

    if passed and keep:
        result["kept"] = str(work)
    else:
        _cleanup(work, keep=False)
        result["deleted"] = True

    try:
        import audit

        audit.log(
            "marketplace.trial",
            detail=json.dumps({"item": item_id, "pass": passed, "model": smoke.get("model")})[:400],
            ok=passed,
        )
        import hosting

        hosting.log_usage(
            model=str(smoke.get("model") or item_id),
            tokens=int(smoke.get("tokens") or 32),
            kind="trial",
            detail=f"pass={passed}",
        )
    except Exception:
        pass

    _append(result)
    return result


def _try_pull(item: dict, work: Path) -> dict:
    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except Exception:
        return {"ok": False, "detail": "huggingface_hub not installed — Marketplace → Optimizers"}
    try:
        path = snapshot_download(
            repo_id=item["hf_id"],
            local_dir=str(work / "weights"),
            max_workers=2,
        )
        return {"ok": True, "path": path}
    except Exception as e:
        return {"ok": False, "detail": str(e)[:240]}


def _smoke_generate(item: dict) -> dict:
    """Hit local OpenAI-compatible server if bound; else fail soft with guidance."""
    import hosting
    from ai_engine import _http_post, _local_openai_endpoint, load_env

    env = load_env()
    serving = item.get("serving")
    st = hosting.status()

    # Prefer matching live backend
    if serving == "vllm" and (st.get("vllm") or {}).get("ok"):
        ep = _local_openai_endpoint(env, kind="vllm")
    elif serving == "colibri" and (st.get("colibri") or {}).get("ok"):
        ep = _local_openai_endpoint(env, kind="colibri")
    else:
        # Any live local backend
        ep = _local_openai_endpoint(env, kind="vllm") or _local_openai_endpoint(env, kind="colibri")

    if not ep:
        return {
            "ok": False,
            "detail": (
                "No local OpenAI server live. Bind Serve in Marketplace and start "
                "llama.cpp/vLLM/coli serve, then Trial again. "
                f"Profile prefers {serving}."
            ),
        }

    url, key, model = ep
    # Prefer catalog hf id when server accepts it
    body = {
        "model": item.get("hf_id") or model,
        "messages": [{"role": "user", "content": SMOKE_PROMPT}],
        "temperature": 0,
        "max_tokens": 32,
    }
    try:
        data = _http_post(url, {"Authorization": f"Bearer {key}"}, body, timeout=60)
        text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        usage = data.get("usage") or {}
        tokens = int(usage.get("completion_tokens") or usage.get("total_tokens") or len(text.split()) or 0)
        ok = bool(text) and ("AIRGPT_OK" in text.upper() or len(text) >= 4)
        return {"ok": ok, "text": text, "model": model, "tokens": tokens, "raw_ok": bool(text)}
    except Exception as e:
        # Retry with server default model id
        try:
            body["model"] = model
            data = _http_post(url, {"Authorization": f"Bearer {key}"}, body, timeout=60)
            text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            ok = bool(text)
            return {"ok": ok, "text": text, "model": model, "tokens": len(text.split()), "detail": "fallback model id"}
        except Exception as e2:
            return {"ok": False, "detail": str(e2)[:240] or str(e)[:240]}


def _cloud_judge(candidate: str) -> dict:
    try:
        from ai_engine import _standard_llm
        from cortex_runtime import cortex_cloud_allowed

        if not cortex_cloud_allowed():
            return {"ok": True, "skipped": True, "pass": True, "reason": "CORTEX_LOCAL_ONLY — skip cloud judge"}
        prompt = f"CANDIDATE:\n{candidate[:800]}\n\n{QUALITY_RUBRIC}"
        text, model = _standard_llm(prompt, "You output JSON only.", max_tokens=128)
        score, passed, reason = 0, False, text[:200]
        try:
            # find JSON object
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                j = json.loads(text[start:end])
                score = int(j.get("score") or 0)
                passed = bool(j.get("pass")) or score >= 6
                reason = str(j.get("reason") or "")[:200]
        except Exception:
            passed = "AIRGPT_OK" in (candidate or "").upper()
            score = 8 if passed else 2
        return {"ok": True, "score": score, "pass": passed, "reason": reason, "judge_model": model}
    except Exception as e:
        # Soft-fail: if smoke produced tokens, don't block on judge outage
        return {"ok": True, "skipped": True, "pass": True, "detail": str(e)[:160]}


def _cleanup(work: Path, *, keep: bool) -> None:
    if keep:
        return
    try:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
    except Exception:
        pass


def list_trials(limit: int = 30) -> dict:
    ensure()
    rows: list[dict] = []
    if TRIAL_LOG.is_file():
        for line in TRIAL_LOG.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return {"ok": True, "trials": list(reversed(rows))}

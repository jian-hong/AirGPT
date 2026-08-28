"""Local hosting status, token usage ledger, and Colibri/vLLM health checks."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from config import DATA_DIR, ENV_FILE, ROOT

USAGE_DIR = DATA_DIR / "usage"
USAGE_FILE = USAGE_DIR / "events.jsonl"
HOST_STATE = DATA_DIR / "marketplace" / "hosting.json"


def ensure() -> None:
    USAGE_DIR.mkdir(parents=True, exist_ok=True)
    HOST_STATE.parent.mkdir(parents=True, exist_ok=True)


def _env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV_FILE.is_file():
        return out
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _ping_openai(base: str, key: str = "EMPTY", timeout: float = 2.5) -> dict:
    base = (base or "").rstrip("/")
    if not base:
        return {"ok": False, "status": "unset"}
    url = base if base.endswith("/models") else f"{base}/v1/models"
    if "/v1/v1/" in url:
        url = url.replace("/v1/v1/", "/v1/")
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="ignore")
        data = json.loads(raw) if raw else {}
        models = [m.get("id") for m in (data.get("data") or []) if isinstance(m, dict)]
        return {"ok": True, "status": "live", "models": models[:12], "url": url}
    except Exception as e:
        return {"ok": False, "status": "offline", "error": str(e)[:160], "url": url}


# Backend health pings are polled, not asked for. The Hosting page re-fetches
# /api/hosting every 8s while it is open, and every call used to fan out to four
# live _ping_openai() requests at 2.5s apiece — up to ~10s of serial blocking
# network I/O on the request thread, so an 8s poll could arrive while the handler
# was still servicing the previous one. Throttle the fan-out behind a TTL, same
# shape as _net_profile_cache / _lan_diag_cache in clipdrop.py. HOST-DEMO-01.
PING_TTL = 20.0
_ping_cache: dict = {"ts": 0.0, "key": "", "value": None}


def _backend_pings(env: dict[str, str]) -> dict[str, dict]:
    """The four backend probes, cached for PING_TTL seconds."""
    backends = {
        "ollama": (env.get("OLLAMA_BASE_URL") or "", env.get("OLLAMA_API_KEY") or "ollama"),
        "vllm": (env.get("VLLM_BASE_URL") or "", env.get("VLLM_API_KEY") or "EMPTY"),
        "sglang": (env.get("SGLANG_BASE_URL") or "", env.get("SGLANG_API_KEY") or "EMPTY"),
        "colibri": (env.get("COLIBRI_BASE_URL") or "", env.get("COLIBRI_API_KEY") or "EMPTY"),
    }
    # Re-point a base URL in .env and the cached verdict for the old one is a lie,
    # so the URLs are part of the key rather than just the clock.
    key = "|".join(f"{n}={b}" for n, (b, _k) in sorted(backends.items()))
    now = time.time()
    cached = _ping_cache.get("value")
    if cached and _ping_cache.get("key") == key and now - float(_ping_cache["ts"]) < PING_TTL:
        return {n: dict(v) for n, v in cached.items()}
    out = {
        n: (_ping_openai(base, k) if base else {"ok": False, "status": "unset"})
        for n, (base, k) in backends.items()
    }
    _ping_cache["ts"] = now
    _ping_cache["key"] = key
    _ping_cache["value"] = {n: dict(v) for n, v in out.items()}
    return out


def status() -> dict:
    ensure()
    env = _env()
    ollama_base = env.get("OLLAMA_BASE_URL") or ""
    vllm_base = env.get("VLLM_BASE_URL") or ""
    sglang_base = env.get("SGLANG_BASE_URL") or ""
    coli_base = env.get("COLIBRI_BASE_URL") or ""
    pings = _backend_pings(env)
    ollama = pings["ollama"]
    vllm = pings["vllm"]
    sglang = pings["sglang"]
    coli = pings["colibri"]
    coli_engine = ROOT / "third_party" / "colibri"
    state = {}
    if HOST_STATE.is_file():
        try:
            state = json.loads(HOST_STATE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    return {
        "ok": True,
        "ollama": {**ollama, "base_url": ollama_base or None, "model": env.get("OLLAMA_MODEL")},
        "vllm": {**vllm, "base_url": vllm_base or None, "model": env.get("VLLM_MODEL")},
        "sglang": {**sglang, "base_url": sglang_base or None, "model": env.get("SGLANG_MODEL")},
        "colibri": {
            **coli,
            "base_url": coli_base or None,
            "model": env.get("COLIBRI_MODEL"),
            "engine_cloned": coli_engine.is_dir(),
            "engine_path": str(coli_engine) if coli_engine.is_dir() else None,
        },
        "host_role": state.get("host_role") or "personal",
        "collaboration": {
            "note": "Strong host (GPU/RAM) serves; phones/weak PCs join via LAN/tunnel chat.",
            "share": "Use Connect QR / tunnel — inference stays on the host base URL.",
        },
        "kv_policy": {
            "preferred": "vLLM FP8/INT8 PagedAttention",
            "research": ["RotorQuant", "SpectralQuant", "KVTC", "AWQ weights"],
            "airgpt": "Do not reimplement TurboQuant in-process; use engine-side quant.",
        },
    }


def set_host_role(role: str) -> dict:
    ensure()
    role = (role or "personal").strip()[:40]
    data = {"host_role": role, "updated_at": time.time()}
    HOST_STATE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"ok": True, **data}


def log_usage(
    *,
    model: str,
    tokens: int = 0,
    cost: float = 0.0,
    kind: str = "included",
    detail: str = "",
    user: str = "",
    ip: str = "",
    session_id: int = 0,
    tier: str = "",
) -> dict:
    ensure()
    ev = {
        "ts": time.time(),
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": (model or "unknown")[:80],
        "tokens": int(tokens or 0),
        "cost": float(cost or 0),
        "type": kind,
        "detail": (detail or "")[:200],
        "user": (user or ip or "local")[:60],
        "ip": (ip or "")[:45],
        "session_id": int(session_id or 0),
        "tier": (tier or "")[:20],
    }
    with USAGE_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    try:
        import audit as app_audit

        app_audit.log(
            "ai.usage",
            ip=ip,
            user=user or ip,
            detail=f"{model}:{tokens}:{tier}"[:200],
            ok=True,
            category="tokens",
            session_id=session_id,
            model=model,
            tokens=tokens,
        )
    except Exception:
        pass
    return {"ok": True, "event": ev}


def usage_summary(limit: int = 80) -> dict:
    ensure()
    events: list[dict] = []
    if USAGE_FILE.is_file():
        lines = USAGE_FILE.read_text(encoding="utf-8").splitlines()
        for line in lines[-max(1, limit) :]:
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    by_model: dict[str, dict] = {}
    total_tokens = 0
    total_cost = 0.0
    for e in events:
        m = e.get("model") or "other"
        slot = by_model.setdefault(m, {"model": m, "tokens": 0, "cost": 0.0, "calls": 0})
        slot["tokens"] += int(e.get("tokens") or 0)
        slot["cost"] += float(e.get("cost") or 0)
        slot["calls"] += 1
        total_tokens += int(e.get("tokens") or 0)
        total_cost += float(e.get("cost") or 0)
    return {
        "ok": True,
        "total_tokens": total_tokens,
        "total_spend": round(total_cost, 4),
        "included": round(total_cost, 4),
        "on_demand": 0.0,
        "by_model": sorted(by_model.values(), key=lambda x: -x["tokens"]),
        "events": list(reversed(events)),
        "plan": {"name": "Personal", "on_demand": "Disabled"},
    }


def usage_csv(limit: int = 500) -> str:
    summary = usage_summary(limit)
    lines = ["date,type,model,tokens,cost"]
    for e in summary.get("events") or []:
        lines.append(
            ",".join(
                [
                    str(e.get("ts") or e.get("date") or ""),
                    str(e.get("type") or ""),
                    str(e.get("model") or "").replace(",", " "),
                    str(int(e.get("tokens") or 0)),
                    str(float(e.get("cost") or 0)),
                ]
            )
        )
    return "\n".join(lines) + "\n"

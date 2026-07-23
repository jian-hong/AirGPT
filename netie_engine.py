"""Netie Engine — one unified local runtime that absorbs the strengths of
vLLM (PagedAttention KV), SGLang (RadixAttention prefix cache), Colibri
(disk-streaming MoE + int4 quant) and Ollama (dead-simple GGUF), so large
models run without OOM.

The Hosting UI shows a single **Netie Engine** box. Users press **+** to add a
sub-engine from the liquid-glass marketplace; each added engine becomes its own
box with a **Model** button. This module is the backend for that: the engine
catalog, per-engine hardware fit + live detection, the added-engine registry,
and the merged optimisation spec shown in the (i) popover.

No heavy imports at module load — everything is lazy so a missing optional
dependency never breaks `/api/hosting`.
"""
from __future__ import annotations

import json
import shutil
import socket
import time
from pathlib import Path

from config import DATA_DIR

STATE_FILE = DATA_DIR / "marketplace" / "netie_engines.json"


# --- Engine catalog -------------------------------------------------------
# Each engine contributes a strength to the merged Netie Engine runtime.
ENGINE_CATALOG: list[dict] = [
    {
        "id": "ollama",
        "name": "Ollama",
        "icon": "🦙",
        "tagline": "Dead-simple GGUF runtime — one command, always fits.",
        "strengths": ["GGUF Q4/Q5/Q8", "auto model pull", "CPU or GPU", "no config"],
        "kv_strategy": "llama.cpp paged KV + mmap weights",
        "quant": "GGUF Q4_K_M / Q5_K_M / Q8_0",
        "oom_strategy": "mmap + partial GPU offload; spills to RAM/disk, never OOMs",
        "serving": "ollama",
        "needs_gpu": False,
        "port": 11434,
        "base_url_env": "OLLAMA_BASE_URL",
        "install_how": "installer",  # winget / official installer
        "detect_bin": "ollama",
        "docs": "https://ollama.com",
        "recommended": True,
    },
    {
        "id": "vllm",
        "name": "vLLM",
        "icon": "⚡",
        "tagline": "Throughput king — PagedAttention KV, continuous batching.",
        "strengths": ["PagedAttention KV", "continuous batching", "FP8/AWQ/GPTQ", "OpenAI API"],
        "kv_strategy": "PagedAttention (block KV cache, near-zero fragmentation)",
        "quant": "FP8 / AWQ / GPTQ",
        "oom_strategy": "paged KV blocks + CPU KV offload + gpu_memory_utilization cap",
        "serving": "vllm",
        "needs_gpu": True,
        "port": 8001,
        "base_url_env": "VLLM_BASE_URL",
        "install_how": "docker",  # native Windows unsupported → Docker + WSL2 GPU
        "detect_bin": None,
        "docker_image": "vllm/vllm-openai:latest",
        "docs": "https://docs.vllm.ai",
        "windows_note": "No native Windows build — runs in Docker with WSL2 GPU passthrough.",
    },
    {
        "id": "sglang",
        "name": "SGLang",
        "icon": "🧬",
        "tagline": "RadixAttention prefix cache — fastest for shared prompts / agents.",
        "strengths": ["RadixAttention prefix cache", "structured output", "FP8/AWQ", "OpenAI API"],
        "kv_strategy": "RadixAttention (automatic prefix/KV reuse across requests)",
        "quant": "FP8 / AWQ / GPTQ",
        "oom_strategy": "radix KV sharing + chunked prefill + mem-fraction cap",
        "serving": "sglang",
        "needs_gpu": True,
        "port": 30000,
        "base_url_env": "SGLANG_BASE_URL",
        "install_how": "docker",
        "detect_bin": None,
        "docker_image": "lmsysorg/sglang:latest",
        "docs": "https://docs.sglang.ai",
        "windows_note": "Runs in Docker with WSL2 GPU passthrough.",
    },
    {
        "id": "colibri",
        "name": "Colibri",
        "icon": "🐦",
        "tagline": "Run frontier MoE far bigger than VRAM — streams experts from disk.",
        "strengths": ["disk-streamed MoE", "int4 experts + int8 MTP", "runs > VRAM models", "host role"],
        "kv_strategy": "expert-streaming + int8 MTP KV",
        "quant": "int4 experts / int8 MTP",
        "oom_strategy": "streams inactive experts from NVMe on demand — model size ≫ VRAM/RAM",
        "serving": "colibri",
        "needs_gpu": False,
        "port": 8002,
        "base_url_env": "COLIBRI_BASE_URL",
        "install_how": "vendored",  # third_party/colibri submodule
        "detect_bin": None,
        "docs": "https://github.com/JustVugg/colibri",
    },
]

ENGINE_BY_ID = {e["id"]: e for e in ENGINE_CATALOG}


# --- Registry (which engines the user has added) --------------------------
def _load_state() -> dict:
    try:
        if STATE_FILE.is_file():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"added": [], "updated_at": 0}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = time.time()
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def add_engine(engine_id: str) -> dict:
    engine_id = (engine_id or "").strip().lower()
    if engine_id not in ENGINE_BY_ID:
        return {"ok": False, "error": f"unknown engine '{engine_id}'"}
    state = _load_state()
    if engine_id not in state["added"]:
        state["added"].append(engine_id)
        _save_state(state)
        try:
            import audit
            audit.log("hosting.engine.add", detail=engine_id, ok=True, category="hosting")
        except Exception:
            pass
    return {"ok": True, "added": state["added"], "engine": _engine_view(ENGINE_BY_ID[engine_id])}


def set_config(cfg: dict) -> dict:
    """Persist runtime preferences — prefers live Cortex /api/engine/config.

    llm_runtime: netie (default, unified) | ollama | vllm | sglang | llamacpp | colibri
    agents_runtime: cortex (default) | langgraph | langchain
    model: preferred local model id from the marketplace

    Requires Cortex engine running (D:\\Cortex start_cortex_engine.ps1) for
    authoritative config; local JSON is a cache/fallback only.
    """
    # Map AirGPT keys → Cortex engine_routes contract
    cortex_body: dict = {}
    if cfg.get("llm_runtime") is not None:
        cortex_body["backend"] = str(cfg["llm_runtime"])[:80]
    if cfg.get("backend") is not None:
        cortex_body["backend"] = str(cfg["backend"])[:80]
    if cfg.get("agents_runtime") is not None:
        cortex_body["agents_runtime"] = str(cfg["agents_runtime"])[:80]
    if cfg.get("optimizers") is not None:
        cortex_body["optimizers"] = cfg["optimizers"]
    if cfg.get("research") is not None:
        cortex_body["research"] = bool(cfg["research"])
    if cfg.get("primary_provider") is not None:
        cortex_body["primary_provider"] = str(cfg["primary_provider"])[:40]
    if cfg.get("provider_order") is not None:
        cortex_body["provider_order"] = [str(p)[:40] for p in (cfg["provider_order"] or [])][:12]
    if cfg.get("hardware") is not None:
        cortex_body["hardware"] = cfg["hardware"]

    try:
        import cortex_client
        if cortex_body:
            remote = cortex_client.engine_config(cortex_body)
            if remote.get("require_engine"):
                return remote
            if remote.get("ok"):
                # Mirror into local cache for offline UI
                state = _load_state()
                conf = dict(state.get("config") or {})
                for key in ("llm_runtime", "agents_runtime", "model", "primary_provider"):
                    if cfg.get(key) is not None:
                        conf[key] = str(cfg[key])[:80]
                if cfg.get("provider_order") is not None:
                    conf["provider_order"] = [str(p)[:40] for p in (cfg["provider_order"] or [])][:12]
                if cortex_body.get("backend"):
                    conf["llm_runtime"] = cortex_body["backend"]
                if cortex_body.get("agents_runtime"):
                    conf["agents_runtime"] = cortex_body["agents_runtime"]
                state["config"] = conf
                _save_state(state)
                return remote
    except Exception:
        pass

    state = _load_state()
    conf = dict(state.get("config") or {})
    for key in ("llm_runtime", "agents_runtime", "model", "primary_provider"):
        if cfg.get(key) is not None:
            conf[key] = str(cfg[key])[:80]
    if cfg.get("provider_order") is not None:
        conf["provider_order"] = [str(p)[:40] for p in (cfg["provider_order"] or [])][:12]
    state["config"] = conf
    _save_state(state)
    try:
        import audit
        audit.log("hosting.engine.config", detail=json.dumps(conf)[:200], ok=True, category="hosting")
    except Exception:
        pass
    return {
        "ok": True,
        "config": conf,
        "cortex": "standby",
        "hint": "Cached locally — start D:\\Cortex engine to sync authoritative config.",
    }


def get_config() -> dict:
    conf = dict(_load_state().get("config") or {})
    conf.setdefault("llm_runtime", "netie")
    conf.setdefault("agents_runtime", "cortex")
    return conf


def remove_engine(engine_id: str) -> dict:
    engine_id = (engine_id or "").strip().lower()
    state = _load_state()
    if engine_id in state["added"]:
        state["added"].remove(engine_id)
        _save_state(state)
        try:
            import audit
            audit.log("hosting.engine.remove", detail=engine_id, ok=True, category="hosting")
        except Exception:
            pass
    return {"ok": True, "added": state["added"]}


# --- Live detection -------------------------------------------------------
def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _hardware() -> dict:
    try:
        import marketplace
        return marketplace.effective_hardware()
    except Exception:
        return {}


def _engine_fit(engine: dict, hw: dict) -> dict:
    """Cheap hardware fit for an *engine* (not a model)."""
    vram = float(hw.get("vram_gb") or 0)
    nvidia = hw.get("nvidia") or {}
    has_gpu = bool(nvidia.get("present")) or vram >= 6
    reasons: list[str] = []
    ok = True
    if engine.get("needs_gpu") and not has_gpu:
        ok = False
        reasons.append("Needs an NVIDIA GPU (none detected)")
    if engine.get("install_how") == "docker":
        if shutil.which("docker"):
            reasons.append("Runs via Docker (detected)")
        else:
            reasons.append("Runs via Docker (Docker Desktop not detected)")
    if engine["id"] == "colibri" and not hw.get("colibri_cloned"):
        reasons.append("Engine vendored under third_party/colibri")
    if ok and not reasons:
        reasons.append("Fits this machine")
    return {"fits": ok, "reasons": reasons, "has_gpu": has_gpu}


def _detect(engine: dict) -> dict:
    """Is this engine installed / running on the box right now?"""
    running = _port_open(int(engine.get("port") or 0)) if engine.get("port") else False
    installed = False
    how = ""
    dbin = engine.get("detect_bin")
    if dbin and shutil.which(dbin):
        installed = True
        how = "path"
    if engine["id"] == "colibri":
        hw = _hardware()
        if hw.get("colibri_cloned"):
            installed = True
            how = how or "vendored"
    if engine.get("install_how") == "docker" and shutil.which("docker"):
        # Docker present means the engine is one `docker run` away.
        how = how or "docker-ready"
    if running:
        installed = True
    status = "running" if running else ("installed" if installed else "available")
    return {"installed": installed, "running": running, "status": status, "how": how}


def _engine_view(engine: dict, *, added: bool = False, hw: dict | None = None) -> dict:
    hw = hw if hw is not None else _hardware()
    fit = _engine_fit(engine, hw)
    det = _detect(engine)
    return {
        **{k: engine[k] for k in (
            "id", "name", "icon", "tagline", "strengths", "kv_strategy",
            "quant", "oom_strategy", "serving", "needs_gpu", "port",
            "install_how", "docs",
        )},
        "windows_note": engine.get("windows_note"),
        "recommended": engine.get("recommended", False),
        "added": added,
        "fit": fit,
        "detect": det,
        "status": det["status"],
    }


def list_engines() -> dict:
    """Everything the Hosting page needs: added engine boxes + the addable ones.

    When Cortex is live, backend catalog/config come from /api/engine/*;
    local detect (ports/binaries) still runs on this machine.
    """
    hw = _hardware()
    state = _load_state()
    added_ids = state.get("added", [])
    cortex_live = False
    cortex_url = None
    cortex_cfg: dict = {}
    try:
        import cortex_client
        snap = cortex_client.snapshot()
        cortex_live = bool(snap.get("ok"))
        cortex_url = snap.get("url")
        if cortex_live:
            remote = cortex_client.engine_backends()
            if remote.get("ok") and remote.get("backends"):
                # Prefer Cortex-active set as "added" when user hasn't picked yet
                active = remote.get("active") or []
                if active and not added_ids:
                    added_ids = list(active)
            cortex_cfg = (snap.get("engine") or {}).get("config") or {}
    except Exception:
        pass

    added, available = [], []
    for eng in ENGINE_CATALOG:
        view = _engine_view(eng, added=eng["id"] in added_ids, hw=hw)
        (added if view["added"] else available).append(view)
    # Recommended engines float to the top of the "add" list.
    available.sort(key=lambda e: (not e.get("recommended"), not e["fit"]["fits"]))
    conf = get_config()
    if cortex_cfg.get("backend"):
        conf["llm_runtime"] = cortex_cfg["backend"]
    if cortex_cfg.get("agents_runtime"):
        conf["agents_runtime"] = cortex_cfg["agents_runtime"]
    return {
        "ok": True,
        "engine": "Netie Engine",
        "added": added,
        "available": available,
        "hardware": hw,
        "config": conf,
        "cortex": {"live": cortex_live, "url": cortex_url},
        "require_engine": not cortex_live,
        "hint": None if cortex_live else "Start D:\\Cortex engine first, then manage engines here via API.",
    }


# --- Merged spec for the (i) popover --------------------------------------
def specs() -> dict:
    """The unified Netie Engine spec: prefer Cortex /api/engine/specs when live."""
    hw = _hardware()
    try:
        import cortex_client
        remote = cortex_client.engine_specs()
        if remote and remote.get("engine") and not remote.get("error"):
            nvidia = hw.get("nvidia") or {}
            gpus = nvidia.get("gpus") or []
            gpu_name = gpus[0].get("name") if gpus else None
            # Adapt Cortex optimization categories → UI rows; keep local hardware probe
            opts = []
            for row in remote.get("optimizations") or []:
                items = row.get("items") or []
                opts.append({
                    "key": row.get("category") or "opt",
                    "label": (row.get("category") or "opt").replace("_", " ").title(),
                    "detail": "; ".join(items) if items else "",
                    "on": True,
                })
            profile = remote.get("profile") or {}
            return {
                "ok": True,
                "source": "cortex",
                "engine": remote.get("engine") or "Netie Engine",
                "summary": remote.get("summary") or "Cortex-owned capability registry.",
                "hardware": {
                    "cpu_threads": None,
                    "ram_gb": hw.get("ram_gb"),
                    "vram_gb": hw.get("vram_gb") or profile.get("vram_gb"),
                    "gpu": gpu_name,
                    "disk_free_gb": hw.get("disk_free_gb"),
                    "tier": hw.get("tier"),
                    "platform": hw.get("platform"),
                },
                "optimizations": opts or [{
                    "key": "registry",
                    "label": "Cortex registry",
                    "detail": "Live from /api/engine/specs",
                    "on": True,
                }],
                "engines_merged": [
                    {"name": b, "icon": "▢", "contributes": "registry"}
                    for b in (remote.get("backends") or [])
                ],
                "config": remote.get("config") or {},
                "profile": profile,
            }
    except Exception:
        pass

    state = _load_state()
    added_ids = state.get("added", []) or [e["id"] for e in ENGINE_CATALOG]
    active = [ENGINE_BY_ID[i] for i in added_ids if i in ENGINE_BY_ID]
    if not active:
        active = ENGINE_CATALOG

    nvidia = hw.get("nvidia") or {}
    gpus = nvidia.get("gpus") or []
    gpu_name = gpus[0].get("name") if gpus else None

    kv = sorted({e["kv_strategy"] for e in active})
    quant = sorted({q.strip() for e in active for q in str(e["quant"]).replace("/", ",").split(",")})
    oom = [{"engine": e["name"], "how": e["oom_strategy"]} for e in active]

    return {
        "ok": True,
        "source": "local",
        "engine": "Netie Engine",
        "summary": "Local catalog (Cortex offline). Start D:\\Cortex for authoritative specs.",
        "hardware": {
            "cpu_threads": None,  # filled client-side if available
            "ram_gb": hw.get("ram_gb"),
            "vram_gb": hw.get("vram_gb"),
            "gpu": gpu_name,
            "disk_free_gb": hw.get("disk_free_gb"),
            "tier": hw.get("tier"),
            "platform": hw.get("platform"),
        },
        "optimizations": [
            {
                "key": "kv_cache",
                "label": "KV-Cache Optimization",
                "detail": "; ".join(kv) or "PagedAttention + RadixAttention prefix reuse",
                "on": True,
            },
            {
                "key": "quant",
                "label": "Quant Optimization",
                "detail": ", ".join([q for q in quant if q]) or "FP8 / AWQ / INT4 / GGUF",
                "on": True,
            },
            {
                "key": "prealloc",
                "label": "Next Pre-allocation (AI prediction)",
                "detail": "Predicts next-token KV block demand and pre-allocates ahead of decode to cut stalls.",
                "on": True,
            },
            {
                "key": "oom",
                "label": "OOM-free routing",
                "detail": "Routes oversized models to disk-streaming (Colibri) or offloaded KV so weights ≫ VRAM still run.",
                "on": True,
                "per_engine": oom,
            },
        ],
        "engines_merged": [
            {"name": e["name"], "icon": e["icon"], "contributes": e["strengths"][0]} for e in active
        ],
        "require_engine": True,
    }


def status() -> dict:
    """Compact Netie Engine status for the hero box."""
    engines = list_engines()
    running = [e for e in engines["added"] if e["status"] == "running"]
    return {
        "ok": True,
        "engine": "Netie Engine",
        "added_count": len(engines["added"]),
        "running_count": len(running),
        "running": [e["id"] for e in running],
        "state": "live" if running else ("standby" if engines["added"] else "empty"),
    }

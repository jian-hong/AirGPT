"""Laptop serving profile — auto-detect + recommended optimizers.

Profiles (general engine, low-VRAM first):
  cloud_only   — no local GPU/RAM headroom; BYOK cloud + governance
  cpu_gguf     — no NVIDIA; llama.cpp / GGUF CPU (or iGPU) path
  vllm_small   — ~8–16GB VRAM; AWQ/FP8 7–8B
  vllm_mid     — ~20GB+ VRAM
  colibri_disk — ≥25GB RAM + large NVMe for disk-streamed MoE

Learnings from Colibri we apply as *policy* (not a second engine):
  - stream/cache what does not fit in fast memory
  - never silently change precision/router semantics
  - soft-fail to a working tier instead of OOM
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from config import DATA_DIR, ROOT

OPT_STATE = DATA_DIR / "marketplace" / "optimizers.json"


def _probe_hw() -> dict:
    import model_probe

    try:
        import marketplace

        return marketplace.effective_hardware(model_probe.probe())
    except Exception:
        return model_probe.probe().get("hardware") or {}


def detect_profile(hw: dict | None = None) -> dict[str, Any]:
    hw = hw or _probe_hw()
    ram = float(hw.get("ram_gb") or 0)
    disk = float(hw.get("disk_free_gb") or 0)
    vram = float(hw.get("vram_gb") or 0)
    nvidia = hw.get("nvidia") or {}
    has_gpu = bool(nvidia.get("present")) or vram >= 6

    if has_gpu and vram >= 20:
        profile = "vllm_mid"
    elif has_gpu and vram >= 7:
        profile = "vllm_small"
    elif ram >= 24 and disk >= 400:
        profile = "colibri_disk"  # can *host* Colibri even without GPU
    elif ram >= 8:
        profile = "cpu_gguf"
    else:
        profile = "cloud_only"

    # No GPU → never default to vLLM GPU tiers
    if not has_gpu and profile.startswith("vllm"):
        profile = "cpu_gguf" if ram >= 8 else "cloud_only"

    return {
        "ok": True,
        "profile": profile,
        "hardware": hw,
        "has_gpu": has_gpu,
        "rationale": _rationale(profile, ram, vram, disk, has_gpu),
        "default_serving": {
            "cloud_only": "cloud",
            "cpu_gguf": "gguf",
            "vllm_small": "vllm",
            "vllm_mid": "vllm",
            "colibri_disk": "colibri",
        }.get(profile, "cloud"),
        "optimizers": recommend_optimizers(profile, has_gpu),
        "marketplace_filter": {
            "suitable_only": True,
            "preferred_serving": _preferred_serving(profile, has_gpu),
            "hide_heavy": not has_gpu,
        },
    }


def _preferred_serving(profile: str, has_gpu: bool) -> list[str]:
    if profile == "cloud_only":
        return ["cloud"]
    if profile == "cpu_gguf" or not has_gpu:
        return ["gguf", "cloud"]
    if profile == "colibri_disk":
        return ["colibri", "gguf", "vllm", "cloud"]
    if profile == "vllm_mid":
        return ["vllm", "gguf", "cloud"]
    return ["vllm", "gguf", "cloud"]


def _rationale(profile: str, ram: float, vram: float, disk: float, has_gpu: bool) -> str:
    if profile == "cpu_gguf":
        return f"No usable NVIDIA GPU detected — use CPU GGUF (RAM {ram:.1f}GB). vLLM deferred until host GPU."
    if profile == "cloud_only":
        return "Insufficient local headroom — BYOK cloud + Cortex governance."
    if profile == "vllm_small":
        return f"GPU ~{vram:.1f}GB VRAM — vLLM 7–8B with AWQ/FP8."
    if profile == "vllm_mid":
        return f"GPU ~{vram:.1f}GB — vLLM mid-size / quantized 32B class."
    if profile == "colibri_disk":
        return f"RAM {ram:.1f}GB + disk {disk:.0f}GB free — Colibri disk-MoE host path available."
    return profile


def recommend_optimizers(profile: str, has_gpu: bool) -> list[dict]:
    """Curated optimizer install stubs — detect presence, never silent heavy installs."""
    opts: list[dict] = []
    # Always useful
    opts.append(
        {
            "id": "huggingface_hub",
            "name": "Hugging Face Hub",
            "why": "Marketplace download / trial pulls",
            "pip": "huggingface_hub",
            "present": _mod("huggingface_hub"),
            "priority": 1,
        }
    )
    if profile in ("cpu_gguf", "cloud_only") or not has_gpu:
        opts.append(
            {
                "id": "llama_cpp",
                "name": "llama-cpp-python",
                "why": "GGUF CPU/iGPU runtime — best low-RAM local path without CUDA",
                "pip": "llama-cpp-python",
                "present": _mod("llama_cpp"),
                "priority": 2,
            }
        )
    if has_gpu:
        opts.append(
            {
                "id": "vllm",
                "name": "vLLM",
                "why": "PagedAttention OpenAI server — high throughput on NVIDIA",
                "pip": "vllm",
                "present": _mod("vllm"),
                "priority": 2,
            }
        )
        opts.append(
            {
                "id": "autoawq",
                "name": "AutoAWQ",
                "why": "Activation-aware 4-bit weights for low VRAM",
                "pip": "autoawq",
                "present": _mod("awq") or _mod("autoawq"),
                "priority": 3,
            }
        )
        opts.append(
            {
                "id": "turboquant_kv",
                "name": "TurboQuant KV cache",
                "why": "3–4 bit KV compression on llama.cpp — long context on 8–24GB VRAM (pairs with GGUF, not a weight quant)",
                "pip": "",
                "flags": "--cache-type-k turbo3 --cache-type-v turbo3 -fa on",
                "present": False,
                "deferred": True,
                "priority": 3,
            }
        )
    opts.append(
        {
            "id": "safetensors",
            "name": "safetensors",
            "why": "Safe weight I/O for convert/trial pipelines",
            "pip": "safetensors",
            "present": _mod("safetensors"),
            "priority": 4,
        }
    )
    return sorted(opts, key=lambda x: x["priority"])


def _mod(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def install_optimizer(opt_id: str, *, dry_run: bool = True) -> dict:
    """Install a single optimizer via pip. Default dry_run=True for safety."""
    profile = detect_profile()
    match = next((o for o in profile["optimizers"] if o["id"] == opt_id), None)
    if not match:
        return {"ok": False, "error": "unknown optimizer"}
    if match.get("deferred") or not match.get("pip"):
        return {
            "ok": True,
            "dry_run": True,
            "deferred": True,
            "optimizer": match,
            "note": "No pip package — enable via llama.cpp flags when GPU host is ready",
            "flags": match.get("flags") or "",
        }
    pkg = match["pip"]
    cmd = [sys.executable, "-m", "pip", "install", "-U", pkg]
    if dry_run:
        return {"ok": True, "dry_run": True, "command": " ".join(cmd), "optimizer": match}
    import subprocess

    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, timeout=600)
        _record_install(opt_id, True, out[-500:])
        try:
            import audit

            audit.log("optimizer.install", detail=f"{opt_id} ok", ok=True)
        except Exception:
            pass
        return {"ok": True, "dry_run": False, "optimizer": match, "log": out[-800:]}
    except Exception as e:
        _record_install(opt_id, False, str(e)[:300])
        return {"ok": False, "error": str(e)[:300], "command": " ".join(cmd)}


def _record_install(opt_id: str, ok: bool, log: str) -> None:
    OPT_STATE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if OPT_STATE.is_file():
        try:
            data = json.loads(OPT_STATE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[opt_id] = {"ok": ok, "log": log[:400]}
    OPT_STATE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def disk_budget_ok(need_gb: float) -> bool:
    try:
        free = shutil.disk_usage(str(DATA_DIR if DATA_DIR.exists() else ROOT)).free / (1024**3)
        return free >= need_gb + 2
    except Exception:
        return False

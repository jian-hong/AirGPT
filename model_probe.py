"""Hardware probe + curated Hugging Face model suggestions for local serving.

Does not download models. Used by GET /api/models/probe so Cortex can pick a tier.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from config import DATA_DIR, ROOT

# Curated catalog — sizes are rough VRAM / disk hints for planning only.
HF_CATALOG: dict[str, list[dict]] = {
    "cloud_only": [
        {
            "id": "deepseek-ai/DeepSeek-V3",
            "why": "Strong chat/reasoner via BYOK; too large for typical laptop VRAM",
            "approx_vram_gb": 0,
            "approx_disk_gb": 0,
            "serving": "cloud",
        }
    ],
    "vllm_small": [
        {
            "id": "Qwen/Qwen2.5-7B-Instruct",
            "why": "Fits ~8GB VRAM with AWQ/GPTQ or FP8 on small GPUs",
            "approx_vram_gb": 8,
            "approx_disk_gb": 15,
            "serving": "vllm",
        },
        {
            "id": "meta-llama/Llama-3.1-8B-Instruct",
            "why": "Common vLLM baseline for 8–12GB cards",
            "approx_vram_gb": 10,
            "approx_disk_gb": 16,
            "serving": "vllm",
        },
    ],
    "vllm_mid": [
        {
            "id": "Qwen/Qwen2.5-32B-Instruct",
            "why": "Strong mid-size; needs ~24GB+ with quantization",
            "approx_vram_gb": 24,
            "approx_disk_gb": 70,
            "serving": "vllm",
        },
        {
            "id": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
            "why": "Reasoning distill suitable for mid GPUs via vLLM",
            "approx_vram_gb": 24,
            "approx_disk_gb": 70,
            "serving": "vllm",
        },
    ],
    "colibri_disk": [
        {
            "id": "mateogrgic/GLM-5.2-colibri-int4-with-int8-mtp",
            "why": "Colibri disk-streamed MoE (~25GB RAM resident, ~370GB NVMe)",
            "approx_vram_gb": 0,
            "approx_disk_gb": 370,
            "approx_ram_gb": 25,
            "serving": "colibri",
        }
    ],
}


def _ram_gb() -> float | None:
    try:
        import psutil  # type: ignore

        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return round(stat.ullTotalPhys / (1024**3), 1)
        except Exception:
            pass
        try:
            out = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory",
                ],
                text=True,
                timeout=8,
                stderr=subprocess.DEVNULL,
            )
            val = int((out or "").strip().splitlines()[-1])
            return round(val / (1024**3), 1)
        except Exception:
            pass
    if Path("/proc/meminfo").is_file():
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / (1024**2), 1)
        except Exception:
            pass
    return None


def _disk_free_gb(path: Path | None = None) -> float | None:
    try:
        usage = shutil.disk_usage(str(path or ROOT))
        return round(usage.free / (1024**3), 1)
    except Exception:
        return None


def _nvidia() -> dict:
    info: dict = {"present": False, "gpus": [], "driver": None, "cuda": None}
    smi = shutil.which("nvidia-smi")
    for c in (
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
        r"C:\Windows\System32\nvidia-smi.exe",
    ):
        if Path(c).is_file():
            smi = c
            break
    if not smi:
        return info
    try:
        out = subprocess.check_output(
            [
                smi,
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=8,
            stderr=subprocess.DEVNULL,
        )
        gpus = []
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                try:
                    mem = float(parts[1])
                except ValueError:
                    mem = 0.0
                gpus.append({"name": parts[0], "vram_mb": mem, "vram_gb": round(mem / 1024, 1)})
                if len(parts) >= 3:
                    info["driver"] = parts[2]
        if gpus:
            info["present"] = True
            info["gpus"] = gpus
    except Exception:
        pass
    return info


def _env_backends() -> dict:
    env: dict[str, str] = {}
    env_file = ROOT / "env.local"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    # OS env overrides file
    for k in ("VLLM_BASE_URL", "VLLM_MODEL", "COLIBRI_BASE_URL", "COLIBRI_MODEL"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return {
        "vllm_configured": bool((env.get("VLLM_BASE_URL") or "").strip()),
        "vllm_base_url": (env.get("VLLM_BASE_URL") or "").strip() or None,
        "vllm_model": (env.get("VLLM_MODEL") or "").strip() or None,
        "colibri_configured": bool((env.get("COLIBRI_BASE_URL") or "").strip()),
        "colibri_base_url": (env.get("COLIBRI_BASE_URL") or "").strip() or None,
        "colibri_model": (env.get("COLIBRI_MODEL") or "").strip() or None,
    }


def suggest_tier(ram_gb: float | None, disk_gb: float | None, nvidia: dict) -> str:
    max_vram = 0.0
    for g in nvidia.get("gpus") or []:
        max_vram = max(max_vram, float(g.get("vram_gb") or 0))
    if max_vram >= 20:
        return "vllm_mid"
    if max_vram >= 7:
        return "vllm_small"
    if (ram_gb or 0) >= 24 and (disk_gb or 0) >= 400:
        return "colibri_disk"
    return "cloud_only"


def probe() -> dict:
    ram = _ram_gb()
    disk = _disk_free_gb(DATA_DIR if DATA_DIR.exists() else ROOT)
    nvidia = _nvidia()
    tier = suggest_tier(ram, disk, nvidia)
    backends = _env_backends()
    return {
        "ok": True,
        "hardware": {
            "ram_gb": ram,
            "disk_free_gb": disk,
            "platform": sys.platform,
            "nvidia": nvidia,
        },
        "tier": tier,
        "suggestions": HF_CATALOG.get(tier, HF_CATALOG["cloud_only"]),
        "catalog": {k: v for k, v in HF_CATALOG.items()},
        "backends": backends,
        "notes": [
            "Suggestions are a curated catalog — nothing is downloaded by this probe.",
            "vLLM: set VLLM_BASE_URL to an OpenAI-compatible /v1 endpoint.",
            "Colibri: optional disk-MoE sidecar; set COLIBRI_BASE_URL when ./coli serve is running.",
            "Cortex orchestrates providers; cloud BYOK remains the soft-fail path.",
        ],
    }


def probe_json() -> str:
    return json.dumps(probe(), indent=2)

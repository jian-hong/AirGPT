"""AirGPT Model Marketplace — curated HF catalog with hardware fit gates.

Suitable-only by default (profile-filtered). Not a dump of all Hugging Face models.
CPU/GGUF first on no-GPU laptops; vLLM/Colibri appear when the host can run them.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from config import DATA_DIR, ENV_FILE, ROOT

MARKET_DIR = DATA_DIR / "marketplace"
JOBS_FILE = MARKET_DIR / "jobs.json"
OVERRIDE_FILE = MARKET_DIR / "hardware_override.json"
STATS_FILE = MARKET_DIR / "stats.json"
COLIBRI_DIR = ROOT / "third_party" / "colibri"
MODELS_DIR = DATA_DIR / "models"

# Default popularity seeds (local counters; sync from hub later)
_DEFAULT_STATS: dict[str, dict[str, int]] = {
    "qwen2.5-1.5b-gguf": {"downloads": 4200, "likes": 890},
    "phi-3-mini-gguf": {"downloads": 3100, "likes": 720},
    "mod-openforge": {"downloads": 1800, "likes": 410},
    "mod-openresearch": {"downloads": 950, "likes": 280},
    "mod-pptx": {"downloads": 1200, "likes": 190},
}

# Curated ONLY — CPU / low-VRAM first. Heavy tiers gated by profiles.
MARKET_ITEMS: list[dict[str, Any]] = [
    {
        "id": "qwen2.5-1.5b-gguf",
        "hf_id": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "name": "Qwen2.5 1.5B GGUF",
        "icon": "Q1",
        "blurb": "Best first local model on no-GPU laptops. Tiny, fast CPU GGUF.",
        "serving": "gguf",
        "effort": "low",
        "approx_vram_gb": 0,
        "approx_ram_gb": 6,
        "approx_disk_gb": 2,
        "quant_hint": "Q4_K_M",
        "tags": ["gguf", "cpu", "starter"],
        "profiles": ["cpu_gguf", "cloud_only", "vllm_small", "vllm_mid", "colibri_disk"],
        "category": "llm",
    },
    {
        "id": "phi-3-mini-gguf",
        "hf_id": "microsoft/Phi-3-mini-4k-instruct-gguf",
        "name": "Phi-3 Mini GGUF",
        "icon": "Φ",
        "blurb": "Strong small instruct model for CPU. Good tool-calling baseline.",
        "serving": "gguf",
        "effort": "low",
        "approx_vram_gb": 0,
        "approx_ram_gb": 8,
        "approx_disk_gb": 3,
        "quant_hint": "Q4",
        "tags": ["gguf", "cpu", "tools"],
        "profiles": ["cpu_gguf", "vllm_small", "vllm_mid", "colibri_disk"],
    },
    {
        "id": "qwen2.5-3b-gguf",
        "hf_id": "Qwen/Qwen2.5-3B-Instruct-GGUF",
        "name": "Qwen2.5 3B GGUF",
        "icon": "Q3",
        "blurb": "Balanced CPU model when you have ≥12GB RAM.",
        "serving": "gguf",
        "effort": "mid",
        "approx_vram_gb": 0,
        "approx_ram_gb": 10,
        "approx_disk_gb": 3,
        "quant_hint": "Q4_K_M",
        "tags": ["gguf", "cpu"],
        "profiles": ["cpu_gguf", "vllm_small", "vllm_mid", "colibri_disk"],
    },
    {
        "id": "qwen2.5-7b-gguf",
        "hf_id": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "name": "Qwen2.5 7B GGUF",
        "icon": "GG",
        "blurb": "CPU/GPU hybrid GGUF when RAM ≥14GB and vLLM CUDA is unavailable.",
        "serving": "gguf",
        "effort": "mid",
        "approx_vram_gb": 0,
        "approx_ram_gb": 14,
        "approx_disk_gb": 8,
        "quant_hint": "Q4_K_M / Q5_K_M",
        "tags": ["gguf", "portable"],
        "profiles": ["cpu_gguf", "vllm_small", "vllm_mid", "colibri_disk"],
    },
    {
        "id": "qwen2.5-7b-instruct",
        "hf_id": "Qwen/Qwen2.5-7B-Instruct",
        "name": "Qwen2.5 7B Instruct",
        "icon": "Q7",
        "blurb": "Fast GPU chat via vLLM + AWQ/FP8 (RTX 4070-class).",
        "serving": "vllm",
        "effort": "low",
        "approx_vram_gb": 8,
        "approx_ram_gb": 16,
        "approx_disk_gb": 15,
        "quant_hint": "AWQ / FP8 / GPTQ",
        "tags": ["vllm", "chat", "4070"],
        "profiles": ["vllm_small", "vllm_mid"],
    },
    {
        "id": "llama-3.1-8b-instruct",
        "hf_id": "meta-llama/Llama-3.1-8B-Instruct",
        "name": "Llama 3.1 8B Instruct",
        "icon": "L8",
        "blurb": "Solid GPU baseline for host + phone-client join.",
        "serving": "vllm",
        "effort": "low",
        "approx_vram_gb": 10,
        "approx_ram_gb": 16,
        "approx_disk_gb": 16,
        "quant_hint": "AWQ preferred on 12GB",
        "tags": ["vllm", "chat", "4070"],
        "profiles": ["vllm_small", "vllm_mid"],
    },
    {
        "id": "deepseek-r1-distill-qwen-14b",
        "hf_id": "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B",
        "name": "DeepSeek R1 Distill 14B",
        "icon": "D14",
        "blurb": "Reasoning distill. Tight on 12GB — AWQ + lower context.",
        "serving": "vllm",
        "effort": "mid",
        "approx_vram_gb": 12,
        "approx_ram_gb": 24,
        "approx_disk_gb": 28,
        "quant_hint": "AWQ 4-bit",
        "tags": ["vllm", "reasoner"],
        "profiles": ["vllm_small", "vllm_mid"],
    },
    {
        "id": "qwen2.5-32b-instruct",
        "hf_id": "Qwen/Qwen2.5-32B-Instruct",
        "name": "Qwen2.5 32B Instruct",
        "icon": "Q32",
        "blurb": "Needs ~24GB+ VRAM. Hidden on no-GPU / 12GB hosts.",
        "serving": "vllm",
        "effort": "high",
        "approx_vram_gb": 24,
        "approx_ram_gb": 48,
        "approx_disk_gb": 70,
        "quant_hint": "FP8 / AWQ on 24GB+",
        "tags": ["vllm", "heavy"],
        "profiles": ["vllm_mid"],
    },
    {
        "id": "glm-5.2-colibri",
        "hf_id": "mateogrgic/GLM-5.2-colibri-int4-with-int8-mtp",
        "name": "GLM-5.2 Colibri MoE",
        "icon": "🐦",
        "blurb": "744B MoE streamed from disk. ~25GB RAM + ~370GB NVMe. Host for weak clients.",
        "serving": "colibri",
        "effort": "high",
        "approx_vram_gb": 0,
        "approx_ram_gb": 25,
        "approx_disk_gb": 370,
        "quant_hint": "int4 experts + int8 MTP",
        "tags": ["colibri", "moe", "frontier", "host"],
        "profiles": ["colibri_disk"],
    },
]

# Installable software modules (App Store style) — not HF weights.
SOFTWARE_MODULES: list[dict[str, Any]] = [
    {
        "id": "mod-pptx",
        "hf_id": "",
        "name": "PowerPoint (PPTX)",
        "icon": "P",
        "blurb": "Read/write .pptx in chat attachments and agent tools.",
        "serving": "module",
        "effort": "low",
        "approx_vram_gb": 0,
        "approx_ram_gb": 1,
        "approx_disk_gb": 0.05,
        "quant_hint": "pip python-pptx",
        "tags": ["module", "office"],
        "profiles": ["cpu_gguf", "cloud_only", "vllm_small", "vllm_mid", "colibri_disk"],
        "pip": ["python-pptx"],
    },
    {
        "id": "mod-docx",
        "hf_id": "",
        "name": "Word (DOCX)",
        "icon": "W",
        "blurb": "Office Word documents for attach + vault notes.",
        "serving": "module",
        "effort": "low",
        "approx_vram_gb": 0,
        "approx_ram_gb": 1,
        "approx_disk_gb": 0.05,
        "quant_hint": "pip python-docx",
        "tags": ["module", "office"],
        "profiles": ["cpu_gguf", "cloud_only", "vllm_small", "vllm_mid", "colibri_disk"],
        "pip": ["python-docx"],
    },
    {
        "id": "mod-openvault",
        "hf_id": "",
        "name": "Netie OpenVault",
        "icon": "OV",
        "blurb": "Local vault + wing drawers (MemPalace-style). Predictive flash↔hot memory policy (MEXT-inspired).",
        "serving": "module",
        "effort": "low",
        "approx_vram_gb": 0,
        "approx_ram_gb": 1,
        "approx_disk_gb": 0.01,
        "quant_hint": "built-in",
        "tags": ["module", "memory", "netie"],
        "profiles": ["cpu_gguf", "cloud_only", "vllm_small", "vllm_mid", "colibri_disk"],
        "builtin": "openvault",
    },
    {
        "id": "mod-openforge",
        "hf_id": "",
        "name": "Netie OpenForge",
        "icon": "OF",
        "blurb": "Forge local tool chains + agent recipes under Cortex (audited).",
        "serving": "module",
        "effort": "low",
        "approx_vram_gb": 0,
        "approx_ram_gb": 1,
        "approx_disk_gb": 0.01,
        "quant_hint": "built-in",
        "tags": ["module", "agents", "netie"],
        "profiles": ["cpu_gguf", "cloud_only", "vllm_small", "vllm_mid", "colibri_disk"],
        "builtin": "openforge",
    },
    {
        "id": "mod-vertex",
        "hf_id": "",
        "name": "Netie Vertex",
        "icon": "NV",
        "blurb": "Dual-brain routing vertex. Local GGUF + cloud BYOK under one Cortex gate.",
        "serving": "module",
        "effort": "mid",
        "approx_vram_gb": 0,
        "approx_ram_gb": 2,
        "approx_disk_gb": 0.01,
        "quant_hint": "built-in",
        "tags": ["module", "routing", "netie"],
        "profiles": ["cpu_gguf", "cloud_only", "vllm_small", "vllm_mid", "colibri_disk"],
        "builtin": "vertex",
    },
    {
        "id": "mod-openresearch",
        "hf_id": "",
        "name": "OpenResearch",
        "icon": "OR",
        "blurb": "arXiv-style research drafts, source certify, papers sorted under data/research.",
        "serving": "module",
        "effort": "low",
        "approx_vram_gb": 0,
        "approx_ram_gb": 1,
        "approx_disk_gb": 0.02,
        "quant_hint": "built-in",
        "tags": ["module", "research", "netie"],
        "profiles": ["cpu_gguf", "cloud_only", "vllm_small", "vllm_mid", "colibri_disk"],
        "builtin": "openresearch",
    },
    {
        "id": "mod-repomix",
        "hf_id": "",
        "name": "Repomix",
        "icon": "RM",
        "blurb": "Pack a repo into one AI-friendly file (XML/MD). Bundled tool for chat/context.",
        "serving": "module",
        "effort": "low",
        "approx_vram_gb": 0,
        "approx_ram_gb": 1,
        "approx_disk_gb": 0.05,
        "quant_hint": "npm",
        "tags": ["module", "tool", "apps", "code"],
        "profiles": ["cpu_gguf", "cloud_only", "vllm_small", "vllm_mid", "colibri_disk"],
        "npm": ["repomix"],
        "detect": "repomix",
        "builtin": "repomix",
    },
    {
        "id": "mod-constructor",
        "hf_id": "",
        "name": "Constructor",
        "icon": "CT",
        "blurb": "Chat-to-workflow canvas hosted inside Cortex at /cortex/constructor/.",
        "serving": "module",
        "effort": "low",
        "approx_vram_gb": 0,
        "approx_ram_gb": 1,
        "approx_disk_gb": 0.01,
        "quant_hint": "built-in",
        "tags": ["module", "apps", "constructor", "netie"],
        "profiles": ["cpu_gguf", "cloud_only", "vllm_small", "vllm_mid", "colibri_disk"],
        "builtin": "constructor",
    },
]

MARKET_ITEMS = MARKET_ITEMS + SOFTWARE_MODULES


def _item_category(item: dict) -> str:
    cat = item.get("category")
    if cat:
        return cat
    if item.get("serving") == "colibri":
        return "runtime"
    if item.get("serving") in ("gguf", "vllm"):
        return "llm"
    tags = set(item.get("tags") or [])
    builtin = item.get("builtin") or ""
    if "agents" in tags or builtin in ("openforge", "vertex", "openresearch"):
        return "agents"
    if item.get("id", "").startswith("skill-"):
        return "skills"
    if builtin == "openvault" or "office" in tags or "tool" in tags or "apps" in tags:
        return "tools"
    if item.get("serving") == "module" and "research" in tags:
        return "agents"
    return "tools"


def _skill_modules() -> list[dict[str, Any]]:
    skills_dir = DATA_DIR / "skills"
    out: list[dict[str, Any]] = []
    if not skills_dir.is_dir():
        return out
    for p in sorted(skills_dir.glob("*.md")):
        slug = p.stem
        title = slug.replace("-", " ").replace("_", " ").title()
        out.append({
            "id": f"skill-{slug}",
            "hf_id": "",
            "name": f"{title} Skill",
            "icon": "Sk",
            "blurb": f"Vault skill pack for {title.lower()} prompts and tools.",
            "serving": "module",
            "effort": "low",
            "approx_vram_gb": 0,
            "approx_ram_gb": 0,
            "approx_disk_gb": 0.01,
            "quant_hint": "built-in",
            "tags": ["skill", "vault"],
            "profiles": ["cpu_gguf", "cloud_only", "vllm_small", "vllm_mid", "colibri_disk"],
            "builtin": "skill",
            "category": "skills",
            "skill_path": str(p),
        })
    return out


def _item_stats(item_id: str) -> dict[str, int]:
    stats = _load_json(STATS_FILE, {})
    base = _DEFAULT_STATS.get(item_id, {"downloads": 0, "likes": 0})
    cur = stats.get(item_id) if isinstance(stats.get(item_id), dict) else {}
    return {
        "downloads": int((cur or {}).get("downloads", base.get("downloads", 0))),
        "likes": int((cur or {}).get("likes", base.get("likes", 0))),
    }


def bump_stat(item_id: str, field: str = "downloads", delta: int = 1) -> None:
    stats = _load_json(STATS_FILE, {})
    row = stats.setdefault(item_id, {"downloads": 0, "likes": 0})
    row[field] = int(row.get(field, 0)) + delta
    _save_json(STATS_FILE, stats)


def ensure_dirs() -> None:
    MARKET_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data: Any) -> None:
    ensure_dirs()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def set_hardware_override(payload: dict) -> dict:
    clean = {
        "ram_gb": float(payload.get("ram_gb") or 0) or None,
        "vram_gb": float(payload.get("vram_gb") or 0) or None,
        "gpu_name": str(payload.get("gpu_name") or "")[:80] or None,
        "note": str(payload.get("note") or "")[:200],
        "updated_at": time.time(),
    }
    _save_json(OVERRIDE_FILE, clean)
    return {"ok": True, "override": clean}


def get_hardware_override() -> dict:
    return _load_json(OVERRIDE_FILE, {})


def clear_hardware_override() -> dict:
    if OVERRIDE_FILE.is_file():
        OVERRIDE_FILE.unlink(missing_ok=True)
    return {"ok": True, "cleared": True}


def effective_hardware(probe: dict | None = None) -> dict:
    import model_probe

    p = probe or model_probe.probe()
    hw = dict(p.get("hardware") or {})
    ov = get_hardware_override()
    nvidia = dict(hw.get("nvidia") or {})
    max_vram = 0.0
    for g in nvidia.get("gpus") or []:
        max_vram = max(max_vram, float(g.get("vram_gb") or 0))
    if ov.get("vram_gb"):
        max_vram = float(ov["vram_gb"])
        nvidia = {
            "present": True,
            "gpus": [{"name": ov.get("gpu_name") or "declared", "vram_gb": max_vram}],
            "source": "override",
        }
    ram = hw.get("ram_gb")
    if ov.get("ram_gb"):
        ram = float(ov["ram_gb"])
    return {
        "ram_gb": ram,
        "disk_free_gb": hw.get("disk_free_gb"),
        "vram_gb": max_vram or None,
        "nvidia": nvidia,
        "platform": hw.get("platform"),
        "override": bool(ov),
        "tier": p.get("tier"),
        "colibri_cloned": COLIBRI_DIR.is_dir() and (COLIBRI_DIR / "README.md").is_file(),
        "colibri_path": str(COLIBRI_DIR) if COLIBRI_DIR.is_dir() else None,
    }


def fit_item(item: dict, hw: dict) -> dict:
    ram = float(hw.get("ram_gb") or 0)
    disk = float(hw.get("disk_free_gb") or 0)
    vram = float(hw.get("vram_gb") or 0)
    plat = (hw.get("platform") or "").lower()
    need_vram = float(item.get("approx_vram_gb") or 0)
    need_ram = float(item.get("approx_ram_gb") or 0)
    need_disk = float(item.get("approx_disk_gb") or 0)
    platforms = item.get("platforms")
    reasons: list[str] = []
    ok = True
    nvidia = hw.get("nvidia") or {}
    has_gpu = bool(nvidia.get("present")) or vram >= 6

    if platforms and plat and plat not in platforms:
        ok = False
        reasons.append(f"Platform {plat or '?'} not in {platforms}")

    serving = item.get("serving")
    if serving == "module":
        reasons.append("Lightweight module — installs like App Store")
        return {"fits": True, "reasons": reasons, "score": 120}
    if serving == "colibri":
        if need_ram and ram and ram < need_ram:
            ok = False
            reasons.append(f"Needs ~{need_ram:.0f}GB RAM (have {ram:.1f}GB)")
        if need_disk and disk and disk < need_disk:
            ok = False
            reasons.append(f"Needs ~{need_disk:.0f}GB disk (have {disk:.1f}GB free)")
        if not hw.get("colibri_cloned"):
            reasons.append("Colibri engine not cloned (will auto-use third_party/colibri)")
    elif serving == "vllm":
        if not has_gpu:
            ok = False
            reasons.append("No GPU — use GGUF CPU path on this laptop")
        elif need_vram and (not vram or vram + 0.5 < need_vram):
            ok = False
            reasons.append(f"Needs ~{need_vram:.0f}GB VRAM (have {vram or 0:.1f}GB)")
        if need_disk and disk and disk < need_disk:
            ok = False
            reasons.append(f"Needs ~{need_disk:.0f}GB disk")
    elif serving == "gguf":
        if need_ram and ram and ram < need_ram * 0.7:
            ok = False
            reasons.append(f"Low RAM for GGUF (~{need_ram:.0f}GB recommended)")
    elif serving == "mlx":
        if plat and plat != "darwin":
            ok = False
            reasons.append("MLX is Apple Silicon only")

    if ok and not reasons:
        reasons.append("Fits this machine")

    score = (100 if ok else 0)
    if ok and serving == "gguf" and not has_gpu:
        score += 20  # prefer GGUF on CPU laptops
    if ok and serving == "vllm" and has_gpu and vram >= need_vram >= 1:
        score += 10
    if item.get("effort") == "low":
        score += 5

    return {"fits": ok, "reasons": reasons, "score": score}


def _detect_module(item: dict) -> dict:
    """Auto-detect whether a bundled tool/app/model module is already available."""
    import shutil
    import subprocess

    out = {"detected": False, "installed": False, "how": ""}
    bid = item.get("builtin") or ""
    flag = MARKET_DIR / f"module_{bid}.enabled" if bid else None
    if flag and flag.is_file():
        out["installed"] = True
        out["detected"] = True
        out["how"] = "enabled"
    detect = item.get("detect") or ""
    if detect and shutil.which(detect):
        out["detected"] = True
        out["how"] = out["how"] or "path"
        return out
    for pkg in item.get("npm") or []:
        # npx can resolve without global install
        try:
            r = subprocess.run(
                ["npx", "--no-install", pkg, "--version"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if r.returncode == 0:
                out["detected"] = True
                out["how"] = "npx"
                return out
        except Exception:
            pass
        if shutil.which(pkg):
            out["detected"] = True
            out["how"] = "path"
            return out
    for pkg in item.get("pip") or []:
        try:
            import importlib

            name = pkg.replace("-", "_").split("[")[0]
            importlib.import_module(name)
            out["detected"] = True
            out["how"] = "pip"
            return out
        except Exception:
            # common aliases
            aliases = {"python_docx": "docx", "Pillow": "PIL"}
            try:
                importlib.import_module(aliases.get(name, name))
                out["detected"] = True
                out["how"] = "pip"
                return out
            except Exception:
                pass
    return out


def _params_b(text: str) -> float | None:
    """Extract parameter count in billions from a model id/name (e.g. 'Qwen3-8B' → 8)."""
    import re

    best = None
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*[bB]\b", text or ""):
        v = float(m.group(1))
        if 0.1 <= v <= 2000 and (best is None or v > best):
            best = v
    return best


def _est_tps(params_b: float, hw: dict) -> tuple[float, str]:
    """Rough decode-speed estimate for THIS machine (RTX 4070-class heuristics).

    GPU Q4 ≈ 250/params_B tok/s, CPU Q4 ≈ 45/params_B — order-of-magnitude only,
    shown as a range so it reads as an estimate, not a promise.
    """
    vram = float(hw.get("vram_gb") or 0)
    p = max(0.5, float(params_b or 8))
    need = p * 0.62 + 1.2  # ~Q4 VRAM footprint
    if vram >= need:
        t = 250.0 / p
    elif vram >= need * 0.5:
        t = 90.0 / p  # partial offload
    else:
        t = 45.0 / p  # CPU
    lo, hi = max(0.5, t * 0.7), t * 1.25
    if hi < 4:
        label = f"~{lo:.0f}–{hi:.0f} tok/s" if hi >= 2 else f"~{lo:.1f}–{hi:.1f} tok/s"
    else:
        label = f"~{lo:.0f}–{hi:.0f} tok/s"
    return round(t, 1), label


_CREATORS = [
    ("llama", {"name": "Meta", "logo": "M"}),
    ("qwen", {"name": "Qwen · Alibaba", "logo": "Q"}),
    ("deepseek", {"name": "DeepSeek", "logo": "D"}),
    ("glm", {"name": "Zhipu AI", "logo": "Z"}),
    ("gemma", {"name": "Google", "logo": "G"}),
    ("phi", {"name": "Microsoft", "logo": "P"}),
    ("mistral", {"name": "Mistral", "logo": "M"}),
    ("colibri", {"name": "Colibri", "logo": "C"}),
]


def _creator_for(item: dict) -> dict:
    hf = str(item.get("hf_id") or "")
    if "/" in hf:
        org = hf.split("/")[0]
        base = {"name": org, "logo": (org[:1] or "?").upper()}
    else:
        base = {"name": "Community", "logo": "•"}
    key = f"{item.get('id','')} {hf} {item.get('name','')}".lower()
    for frag, c in _CREATORS:
        if frag in key:
            return c
    return base


def _good_for(params_b: float | None, item: dict) -> str:
    tags = " ".join(item.get("tags") or []).lower()
    if "moe" in tags or "frontier" in tags:
        return "Frontier-class answers on a host box; slow but deep"
    p = params_b or 8
    if p <= 2:
        return "Quick chat, drafting, autocomplete on battery"
    if p <= 9:
        return "Daily driver: chat, code, summaries, tool use"
    if p <= 16:
        return "Complex reasoning, code review, long documents"
    return "Heavy reasoning and analysis; needs strong hardware"


def hf_trending(limit: int = 24, only_fit: bool = True) -> dict:
    """Hugging Face trending text-generation models, device-fit annotated.

    Fetched server-side with a 1h cache (data/marketplace/hf_trending.json);
    fully offline-safe — falls back to cache, then to empty.
    """
    import urllib.request

    ensure_dirs()
    cache_file = MARKET_DIR / "hf_trending.json"
    raw_list: list[dict] = []
    cached = _load_json(cache_file, {})
    fresh = bool(cached.get("at")) and (time.time() - float(cached["at"])) < 3600
    if fresh:
        raw_list = cached.get("models") or []
    else:
        url = (
            "https://huggingface.co/api/models?pipeline_tag=text-generation"
            "&sort=trendingScore&direction=-1&limit=48"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AirGPT/0.9"})
            with urllib.request.urlopen(req, timeout=6) as r:
                raw_list = json.loads(r.read().decode("utf-8", errors="ignore"))
            _save_json(cache_file, {"at": time.time(), "models": raw_list})
        except Exception:
            raw_list = cached.get("models") or []

    hw = effective_hardware()
    vram = float(hw.get("vram_gb") or 0)
    ram = float(hw.get("ram_gb") or 0)
    items: list[dict] = []
    for m in raw_list:
        mid = str(m.get("modelId") or m.get("id") or "")
        if not mid:
            continue
        pb = _params_b(mid)
        need_vram = (pb * 0.62 + 1.2) if pb else None
        gpu_fit = bool(pb and vram and need_vram and vram >= need_vram)
        cpu_fit = bool(pb and ram and ram >= pb * 0.75 + 2)
        fits = gpu_fit or cpu_fit
        unknown = pb is None
        tps, tps_label = _est_tps(pb or 8, hw)
        org = mid.split("/")[0] if "/" in mid else "community"
        items.append({
            "id": mid,
            "hf_id": mid,
            "name": mid.split("/")[-1],
            "creator": {"name": org, "logo": (org[:1] or "?").upper()},
            "params_b": pb,
            "fit": {
                "fits": fits,
                "unknown": unknown,
                "reasons": (
                    ["Size unknown — check card"] if unknown
                    else ([f"Fits ({'GPU' if gpu_fit else 'CPU'}, ~{pb:g}B)"] if fits
                          else [f"Needs ~{need_vram:.0f}GB VRAM (have {vram:g}GB)"])
                ),
            },
            "est_tps": tps if not unknown else None,
            "est_tps_label": tps_label if not unknown else "? tok/s",
            "good_for": _good_for(pb, {"tags": m.get("tags") or []}),
            "stats": {"downloads": int(m.get("downloads") or 0), "likes": int(m.get("likes") or 0)},
            "url": f"https://huggingface.co/{mid}",
            "serving": "hf",
        })
    if only_fit:
        items = [i for i in items if i["fit"]["fits"]]
    return {
        "ok": True,
        "items": items[: max(1, limit)],
        "hardware": {"vram_gb": vram, "ram_gb": ram},
        "cached": fresh,
        "count": len(items),
    }


def list_catalog(
    *,
    effort: str = "",
    serving: str = "",
    category: str = "",
    sort: str = "relevance",
    only_fit: bool = False,
    suitable_only: bool = True,
) -> dict:
    import model_probe
    import serve_profile

    probe = model_probe.probe()
    hw = effective_hardware(probe)
    profile = serve_profile.detect_profile(hw)
    pname = profile.get("profile") or "cloud_only"
    catalog_src = MARKET_ITEMS + _skill_modules()
    items = []
    for raw in catalog_src:
        if raw.get("serving") == "colibri":
            continue
        cat = _item_category(raw)
        profiles = raw.get("profiles")
        if suitable_only and profiles and pname not in profiles:
            continue
        if effort and raw.get("effort") != effort:
            continue
        if serving and raw.get("serving") != serving:
            continue
        if category and cat != category:
            continue
        fit = fit_item(raw, hw)
        if only_fit and not fit["fits"]:
            continue
        det = _detect_module(raw) if raw.get("serving") == "module" else {"detected": False, "installed": False}
        stats = _item_stats(raw["id"])
        pb = _params_b(f"{raw.get('id','')} {raw.get('hf_id','')} {raw.get('name','')}")
        tps, tps_label = (_est_tps(pb or float(raw.get("approx_vram_gb") or 8), hw)
                          if cat == "llm" else (None, ""))
        items.append({
            **raw,
            "category": cat,
            "fit": fit,
            "stats": stats,
            "detected": det.get("detected"),
            "installed": det.get("installed") or det.get("detected"),
            "detect_how": det.get("how"),
            "creator": _creator_for(raw) if cat == "llm" else None,
            "good_for": raw.get("good_for") or (_good_for(pb, raw) if cat == "llm" else ""),
            "est_tps": tps,
            "est_tps_label": tps_label,
        })
    sort = (sort or "relevance").strip().lower()

    def _sort_key(x: dict) -> tuple:
        fit = float((x.get("fit") or {}).get("score") or 0)
        st = x.get("stats") or {}
        if sort == "downloads":
            return (-int(st.get("downloads", 0)), -fit, x.get("name") or "")
        if sort == "likes":
            return (-int(st.get("likes", 0)), -fit, x.get("name") or "")
        if sort == "tps":
            return (-float(x.get("est_tps") or 0), -fit, x.get("name") or "")
        return (-fit, -int(st.get("downloads", 0)), x.get("name") or "")

    items.sort(key=_sort_key)
    return {
        "ok": True,
        "hardware": hw,
        "profile": profile,
        "items": items,
        "count": len(items),
        "suitable_only": suitable_only,
        "sort": sort,
        "categories": ["llm", "agents", "skills", "tools"],
        "colibri": {
            "cloned": hw.get("colibri_cloned"),
            "path": hw.get("colibri_path"),
            "serve_hint": "python coli serve --model <MODEL_DIR> --host 127.0.0.1 --port 8002",
            "model_hf": "mateogrgic/GLM-5.2-colibri-int4-with-int8-mtp",
            "note": "Colibri is a runtime host capability — use Hosting panel, not Marketplace LLM cards.",
        },
    }


def _jobs() -> list[dict]:
    return list(_load_json(JOBS_FILE, []))


def _save_jobs(jobs: list[dict]) -> None:
    _save_json(JOBS_FILE, jobs[-100:])


def queue_install(item_id: str, *, force: bool = False, confirm: bool = False) -> dict:
    """App Store style: enqueue + auto-run install in background (no manual CLI popup)."""
    ensure_dirs()
    catalog = {i["id"]: i for i in MARKET_ITEMS}
    item = catalog.get(item_id)
    if not item:
        return {"ok": False, "error": "unknown item"}
    hw = effective_hardware()
    fit = fit_item(item, hw)
    if not fit["fits"] and not force:
        return {
            "ok": False,
            "error": "does_not_fit",
            "fit": fit,
            "item": item,
            "hint": "Pass force=true only if a stronger host will hold the weights.",
        }
    if item["serving"] == "colibri" and not (force or confirm):
        return {
            "ok": False,
            "error": "confirm_required",
            "item": item,
            "fit": fit,
            "message": (
                "Colibri GLM-5.2 needs ~370GB download + ~25GB RAM. "
                "Re-POST with confirm=true to enqueue preparation."
            ),
            "script": "scripts/colibri_prepare.ps1",
        }

    job = {
        "id": f"job-{int(time.time()*1000)}",
        "item_id": item_id,
        "hf_id": item.get("hf_id") or "",
        "serving": item["serving"],
        "status": "installing",
        "progress": 0,
        "created_at": time.time(),
        "updated_at": time.time(),
        "target_dir": str(MODELS_DIR / item_id),
        "log": ["Starting install…"],
        "auto": True,
    }
    jobs = _jobs()
    jobs.append(job)
    _save_jobs(jobs)
    try:
        import audit

        audit.log("marketplace.install", detail=json.dumps({"item": item_id, "status": job["status"]})[:400])
    except Exception:
        pass
    _spawn_install(job["id"], item)
    return {"ok": True, "job": job, "fit": fit, "auto": True}


def _update_job(job_id: str, **fields: Any) -> None:
    jobs = _jobs()
    for j in jobs:
        if j.get("id") == job_id:
            j.update(fields)
            j["updated_at"] = time.time()
            break
    _save_jobs(jobs)


def _job_log(job_id: str, line: str, *, progress: int | None = None) -> None:
    jobs = _jobs()
    for j in jobs:
        if j.get("id") == job_id:
            log = list(j.get("log") or [])
            log.append(str(line)[:300])
            j["log"] = log[-40:]
            if progress is not None:
                j["progress"] = int(progress)
            j["updated_at"] = time.time()
            break
    _save_jobs(jobs)


def _spawn_install(job_id: str, item: dict) -> None:
    import threading

    def run() -> None:
        try:
            _run_install(job_id, item)
        except Exception as e:
            _update_job(job_id, status="failed", error=str(e)[:300])
            _job_log(job_id, f"FAILED: {e}")

    threading.Thread(target=run, daemon=True, name=f"mp-install-{job_id}").start()


def _run_install(job_id: str, item: dict) -> None:
    import subprocess
    import sys

    serving = item.get("serving")
    target = Path(MODELS_DIR / item["id"])
    target.mkdir(parents=True, exist_ok=True)

    # Built-in / pip / npm modules
    if serving == "module":
        _job_log(job_id, "Installing module…", progress=10)
        if item.get("builtin") and not item.get("npm") and not item.get("pip"):
            flag = MARKET_DIR / f"module_{item['builtin']}.enabled"
            flag.write_text(json.dumps({"enabled": True, "at": time.time()}), encoding="utf-8")
            if item["builtin"] == "openvault":
                try:
                    import agent_store

                    agent_store.set_memory_backend("project_wing")
                except Exception:
                    pass
            if item["builtin"] == "openresearch":
                try:
                    import research as research_lib

                    research_lib.ensure()
                    research_lib.seed_agents()
                except Exception:
                    pass
            if item["builtin"] == "openforge":
                try:
                    import openforge_chip

                    openforge_chip.FORGE_DIR.mkdir(parents=True, exist_ok=True)
                    (MARKET_DIR / "module_openforge.enabled").write_text(
                        json.dumps({"enabled": True, "pipeline": "chat-to-chip", "at": time.time()}),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
            _job_log(job_id, f"Enabled {item['name']}", progress=100)
            _update_job(job_id, status="installed", progress=100)
            return
        pips = item.get("pip") or []
        for i, pkg in enumerate(pips):
            _job_log(job_id, f"pip install {pkg}", progress=20 + i * 20)
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-U", pkg],
                timeout=600,
            )
        npms = item.get("npm") or []
        for i, pkg in enumerate(npms):
            _job_log(job_id, f"npm install -g {pkg}", progress=40 + i * 25)
            try:
                subprocess.check_call(["npm", "install", "-g", pkg], timeout=600)
            except Exception as e:
                _job_log(job_id, f"npm global failed ({e}); trying npx cache…", progress=55)
                subprocess.check_call(["npm", "install", "-g", pkg], shell=True, timeout=600)
        if item.get("builtin"):
            flag = MARKET_DIR / f"module_{item['builtin']}.enabled"
            flag.write_text(json.dumps({"enabled": True, "at": time.time()}), encoding="utf-8")
        _job_log(job_id, "Module ready", progress=100)
        _update_job(job_id, status="installed", progress=100)
        return

    if serving == "colibri":
        _job_log(job_id, "Colibri prepare — run scripts/colibri_prepare.ps1 for full weights", progress=20)
        _update_job(job_id, status="prepare", progress=20)
        return

    hf_id = item.get("hf_id") or ""
    if not hf_id:
        _update_job(job_id, status="failed", error="no hf_id")
        return

    _job_log(job_id, f"Downloading {hf_id}…", progress=5)
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=hf_id,
            local_dir=str(target),
            local_dir_use_symlinks=False,
        )
        _job_log(job_id, f"Downloaded → {target}", progress=85)
    except Exception as e:
        # Fallback CLI
        _job_log(job_id, f"hub API failed ({e}); trying huggingface-cli…", progress=15)
        try:
            subprocess.check_call(
                [
                    sys.executable,
                    "-m",
                    "huggingface_hub.commands.huggingface_cli",
                    "download",
                    hf_id,
                    "--local-dir",
                    str(target),
                ],
                timeout=3600,
            )
            _job_log(job_id, f"CLI download ok → {target}", progress=85)
        except Exception as e2:
            # Last resort: mark ready_to_pull with command (still auto-queued)
            _job_log(job_id, f"Auto-download blocked: {e2}", progress=30)
            _update_job(
                job_id,
                status="ready_to_pull",
                progress=30,
                error=str(e2)[:200],
                command=f"huggingface-cli download {hf_id} --local-dir {target}",
            )
            return

    # Light integration probe (does not load full model into RAM)
    _job_log(job_id, "Integration check…", progress=90)
    files = list(target.rglob("*"))
    n = len([f for f in files if f.is_file()])
    gguf = [f for f in files if f.suffix.lower() == ".gguf"]
    _job_log(job_id, f"Files: {n}" + (f" · GGUF: {gguf[0].name}" if gguf else ""), progress=95)
    if serving == "gguf" and not gguf:
        _update_job(job_id, status="needs_gguf_pick", progress=95)
        _job_log(job_id, "Repo has no .gguf yet — check HF file variants")
        return
    # Auto-bind serve URL stub for later
    try:
        bind_serve(item["id"])
        _job_log(job_id, "Serve binding written to env.local", progress=98)
    except Exception as e:
        _job_log(job_id, f"Serve bind skipped: {e}")
    _update_job(job_id, status="installed", progress=100)
    _job_log(job_id, "Installed — ready", progress=100)


def confirm_colibri_install(*, force: bool = True) -> dict:
    return queue_install("glm-5.2-colibri", force=force, confirm=True)


def list_jobs() -> dict:
    return {"ok": True, "jobs": _jobs()}


def get_job(job_id: str) -> dict:
    for j in _jobs():
        if j.get("id") == job_id:
            return {"ok": True, "job": j}
    return {"ok": False, "error": "not found"}


def upsert_env_local(updates: dict[str, str]) -> None:
    lines: list[str] = []
    if ENV_FILE.is_file():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    keep_keys = set(updates.keys())
    out = [
        ln
        for ln in lines
        if not (ln.strip() and not ln.strip().startswith("#") and ln.split("=", 1)[0].strip() in keep_keys)
    ]
    out.append("")
    out.append("# AirGPT marketplace serve bindings")
    for k, v in updates.items():
        out.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def bind_serve(item_id: str, *, port: int | None = None) -> dict:
    catalog = {i["id"]: i for i in MARKET_ITEMS}
    item = catalog.get(item_id)
    if not item:
        return {"ok": False, "error": "unknown item"}
    serving = item["serving"]
    if serving == "vllm":
        p = int(port or 8001)
        base = f"http://127.0.0.1:{p}"
        upsert_env_local({"VLLM_BASE_URL": base, "VLLM_API_KEY": "EMPTY", "VLLM_MODEL": item["hf_id"]})
        cmd = (
            f'python -m vllm.entrypoints.openai.api_server --model "{item["hf_id"]}" '
            f"--host 127.0.0.1 --port {p} --max-model-len 8192"
        )
        try:
            import audit

            audit.log("marketplace.serve", detail=f"vllm {item_id} -> {base}")
        except Exception:
            pass
        return {
            "ok": True,
            "serving": "vllm",
            "base_url": base,
            "model": item["hf_id"],
            "command": cmd,
            "note": "Start on a GPU host; AirGPT soft-fails to BYOK until live.",
        }
    if serving == "gguf":
        p = int(port or 8003)
        base = f"http://127.0.0.1:{p}"
        # Reuse vLLM slot — ai_engine already prefers OpenAI-compatible local URL
        upsert_env_local(
            {
                "VLLM_BASE_URL": base,
                "VLLM_API_KEY": "EMPTY",
                "VLLM_MODEL": item["hf_id"],
                "GGUF_BASE_URL": base,
            }
        )
        cmd = (
            f'python -m llama_cpp.server --model "<path-to-q4.gguf>" '
            f"--host 127.0.0.1 --port {p} --n_ctx 4096"
        )
        try:
            import audit

            audit.log("marketplace.serve", detail=f"gguf {item_id} -> {base}")
        except Exception:
            pass
        return {
            "ok": True,
            "serving": "gguf",
            "base_url": base,
            "model": item["hf_id"],
            "command": cmd,
            "note": "Best path on no-GPU laptops. Install llama-cpp-python via Optimizers.",
        }
    if serving == "colibri":
        p = int(port or 8002)
        base = f"http://127.0.0.1:{p}"
        upsert_env_local(
            {
                "COLIBRI_BASE_URL": base,
                "COLIBRI_API_KEY": "local-secret",
                "COLIBRI_MODEL": "glm-5.2-colibri",
            }
        )
        model_dir = MODELS_DIR / "glm-5.2-colibri"
        cmd = (
            f'cd "{COLIBRI_DIR}"; python coli serve --model "{model_dir}" '
            f"--host 127.0.0.1 --port {p} --model-id glm-5.2-colibri"
        )
        try:
            import audit

            audit.log("marketplace.serve", detail=f"colibri {item_id} -> {base}")
        except Exception:
            pass
        return {
            "ok": True,
            "serving": "colibri",
            "base_url": base,
            "model": "glm-5.2-colibri",
            "command": cmd,
            "engine_path": str(COLIBRI_DIR),
            "model_dir": str(model_dir),
            "note": "Needs ~25GB RAM. Host serves; phones join chat.",
        }
    if serving == "module":
        return {
            "ok": True,
            "serving": "module",
            "base_url": "",
            "model": item.get("name") or item_id,
            "command": "",
            "note": "Module enabled locally — no model server needed.",
        }
    return {"ok": False, "error": f"serve path for {serving} not automated", "item": item}

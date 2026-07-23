"""BYO-key vault registry — provider links, guidance, and configured status.

Data source for the Key Vault popup (index.html) via GET /api/keyvault.
Keys are STORED by the existing settings.py path (POST /api/settings → env.local,
host-only); this module never writes secrets and never returns raw values.

Boundary (owner decision, 2026-07-20): we link + guide + paste-back keys the user
legitimately holds. No automated account creation, no credential entry on
provider sites — that stays a human step.
"""
from __future__ import annotations

from typing import Any

# ---- provider registry -----------------------------------------------------
# group: "official" | "cloud" | "local" | "gateway"
PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "id": "netie_official", "label": "Netie Official (Engine keys)", "group": "official",
        "env_key": "NETIE_ENGINE_KEY", "alt_env_keys": [],
        "console": "https://netie.ai",
        "signup": "https://netie.ai",
        "prefix": "netie_",
        "free_note": "Buy or claim Netie Engine keys from us (contact / account). If you skip this, use free-tier providers below — AirGPT falls back automatically.",
        "steps": [
            "Open netie.ai → Contact / account",
            "Request or purchase a Netie Engine API key",
            "Paste the key below when issued (optional — free tiers work without it)",
        ],
    },
    {
        "id": "cursor", "label": "Cursor SDK", "group": "cloud",
        "env_key": "CURSOR_API_KEY", "alt_env_keys": [],
        "console": "https://cursor.com/dashboard",
        "signup": "https://cursor.com",
        "prefix": "",
        "ui_hidden": True,  # OpenIDE uses Cortex paths; hide from Key Vault UI
        "free_note": "Required for OpenIDE Cursor / Cloud backends (cursor-sdk).",
        "steps": [
            "Sign in at cursor.com",
            "Open Dashboard → API / Agents keys",
            "Paste CURSOR_API_KEY below",
        ],
    },
    {
        "id": "omniroute", "label": "OpenFree", "group": "gateway",
        "env_key": "OMNIROUTE_API_KEY", "alt_env_keys": [],
        "console": "https://github.com/diegosouzapw/OmniRoute",
        "signup": "https://github.com/diegosouzapw/OmniRoute",
        "prefix": "",
        "brand": "OpenFree",
        "free_note": "OpenFree is ours (OmniRoute-inspired free gateway). One tap enables automatic fallback — no paste required. Capacity via OpenVault routing; Cortex Engine covers local models.",
        "steps": [
            "Tap Enable OpenFree · auto fallback",
            "AirGPT turns on the free gateway path (no key paste)",
            "Bundled OpenFree install + liquid-glass UI ships as an app feature",
            "Fallback runs before paid cloud when enabled; custody SoT is OpenVault",
        ],
        "base_url_env": "OMNIROUTE_BASE_URL",
        "default_base": "http://127.0.0.1:20128/v1",
    },
    {
        "id": "groq", "label": "Groq", "group": "cloud",
        "env_key": "GROQ_API_KEY", "alt_env_keys": ["GROQ_API_KEY_SISWA"],
        "console": "https://console.groq.com/keys",
        "signup": "https://console.groq.com",
        "prefix": "gsk_",
        "free_note": "Free tier with generous rate limits — best default for fast chat + vision OCR.",
        "steps": [
            "Sign in at console.groq.com (Google/GitHub works)",
            "Open Keys → Create API Key",
            "Copy the gsk_… value and paste it below",
        ],
    },
    {
        "id": "openrouter", "label": "OpenRouter", "group": "cloud",
        "env_key": "OPENROUTER_API_KEY", "alt_env_keys": [],
        "console": "https://openrouter.ai/settings/keys",
        "signup": "https://openrouter.ai",
        "prefix": "sk-or-",
        "free_note": "One key, many models; ':free' models cost nothing. Good universal fallback.",
        "steps": [
            "Sign in at openrouter.ai",
            "Settings → Keys → Create Key",
            "Copy the sk-or-… value and paste it below",
        ],
    },
    {
        "id": "gemini", "label": "Google Gemini", "group": "cloud",
        "env_key": "GOOGLE_API_KEY", "alt_env_keys": [],
        "console": "https://aistudio.google.com/apikey",
        "signup": "https://aistudio.google.com",
        "prefix": "AIza",
        "free_note": "Free tier via AI Studio (rate-limited). Strong vision + long context.",
        "steps": [
            "Sign in at aistudio.google.com with a Google account",
            "Get API key → Create API key",
            "Copy the AIza… value and paste it below",
        ],
    },
    {
        "id": "deepseek", "label": "DeepSeek", "group": "cloud",
        "env_key": "DEEPSEEK_API_KEY", "alt_env_keys": [],
        "console": "https://platform.deepseek.com/api_keys",
        "signup": "https://platform.deepseek.com",
        "prefix": "sk-",
        "free_note": "Very low cost; reasoner model unlocks deep-analysis mode.",
        "steps": [
            "Register at platform.deepseek.com",
            "API Keys → Create new key",
            "Copy the sk-… value and paste it below",
        ],
    },
    {
        "id": "sealion", "label": "SEA-LION (AI Singapore)", "group": "cloud",
        "env_key": "SEA_LION_API_KEY", "alt_env_keys": ["SEA_LION_API_KEY_SISWA"],
        "console": "https://playground.sea-lion.ai",
        "signup": "https://playground.sea-lion.ai",
        "prefix": "",
        "free_note": "Free trial key; best for SEA languages (BM/中文/regional).",
        "steps": [
            "Sign in at playground.sea-lion.ai",
            "Profile → API Key → generate",
            "Paste the key below",
        ],
    },
    {
        "id": "anthropic", "label": "Anthropic Claude", "group": "cloud",
        "env_key": "ANTHROPIC_API_KEY", "alt_env_keys": [],
        "console": "https://console.anthropic.com/settings/keys",
        "signup": "https://console.anthropic.com",
        "prefix": "sk-ant-",
        "free_note": "Paid — highest quality tier for hard reasoning (used by Business mode T3).",
        "steps": [
            "Sign in at console.anthropic.com",
            "Settings → API Keys → Create Key",
            "Copy the sk-ant-… value and paste it below",
        ],
    },
    {
        "id": "openai", "label": "OpenAI", "group": "cloud",
        "env_key": "OPENAI_API_KEY", "alt_env_keys": [],
        "console": "https://platform.openai.com/api-keys",
        "signup": "https://platform.openai.com",
        "prefix": "sk-",
        "free_note": "Paid; broad ecosystem compatibility.",
        "steps": [
            "Sign in at platform.openai.com",
            "API keys → Create new secret key",
            "Copy the sk-… value and paste it below",
        ],
    },
    # ---- local engines: no signup, endpoint on this machine ----
    {
        "id": "ollama", "label": "Ollama (local)", "group": "local",
        "env_key": "OLLAMA_API_KEY", "alt_env_keys": [],
        "console": "https://ollama.com/download",
        "signup": "https://ollama.com/download",
        "prefix": "",
        "ui_hidden": True,  # Cortex Engine replaces user-facing local engine chooser
        "free_note": "Runs models on this PC — no account, no key needed (key optional).",
        "steps": ["Install Ollama for Windows", "ollama pull llama3.2", "AirGPT auto-detects localhost:11434"],
    },
    {
        "id": "vllm", "label": "vLLM (local)", "group": "local",
        "env_key": "VLLM_API_KEY", "alt_env_keys": [],
        "console": "", "signup": "", "prefix": "",
        "ui_hidden": True,  # Hosted via Cortex Engine / Hosting — not Key Vault
        "free_note": "Self-hosted GPU server (port 8001) — managed by Netie Engine hosting page.",
        "steps": ["Use Hosting page to start a vLLM engine", "Key optional (EMPTY default)"],
    },
    # ---- CLI connections (orchestrate your own CLIs) ----
    {
        "id": "github_cli", "label": "GitHub CLI token", "group": "cli",
        "env_key": "GH_TOKEN", "alt_env_keys": ["GITHUB_TOKEN"],
        "console": "https://github.com/settings/tokens",
        "signup": "https://cli.github.com/",
        "prefix": "ghp_",
        "free_note": "Connect your own gh CLI — clone, PR, and push without typing passwords. AirGPT never creates accounts.",
        "steps": [
            "Install GitHub CLI (gh) if needed",
            "Create a fine-grained or classic token with repo scope",
            "Paste GH_TOKEN below — or run `gh auth login` in Terminal",
        ],
    },
    {
        "id": "cursor_cli", "label": "Cursor / agent CLI key", "group": "cli",
        "env_key": "CURSOR_API_KEY", "alt_env_keys": [],
        "console": "https://cursor.com/dashboard",
        "signup": "https://cursor.com",
        "prefix": "",
        "free_note": "Optional — wire Cursor SDK / cloud agents when you want that backend instead of local Cortex.",
        "steps": [
            "Open Cursor Dashboard → API / Agents keys",
            "Paste CURSOR_API_KEY",
            "In OpenIDE, set backend to cursor_local / cursor_cloud when ready",
        ],
    },
    # ---- Deploy (OpenShip-inspired local ship hooks) ----
    {
        "id": "openship", "label": "OpenShip (OpenVault)", "group": "deploy",
        "env_key": "OPENSHIP_API_TOKEN", "alt_env_keys": [],
        "console": "http://127.0.0.1:5000",
        "signup": "file:///D:/OpenVault/OpenMW/openmw/openvault/ship/openship.py",
        "prefix": "",
        "brand": "OpenShip",
        "base_url_env": "OPENSHIP_URL",
        "default_base": "http://127.0.0.1:5000",
        "free_note": "OpenShip lives inside OpenVault (ship gate + deploy plan/execute). Optional external OPENSHIP_URL/token for a separate instance — prefer OpenVault :5000.",
        "steps": [
            "Run OpenVault console on http://127.0.0.1:5000 (OpenShip is built-in)",
            "Connect AirGPT → OpenVault mesh from Key Vault",
            "Optional: paste OPENSHIP_URL + OPENSHIP_API_TOKEN only if using an external adapter",
        ],
    },
    {
        "id": "openvault_mesh", "label": "OpenVault (D:\\OpenVault)", "group": "gateway",
        "env_key": "OPENVAULT_URL", "alt_env_keys": [],
        "console": "http://127.0.0.1:5000/#mesh",
        "signup": "file:///D:/OpenVault/README.md",
        "prefix": "",
        "brand": "OpenVault",
        "base_url_env": "OPENVAULT_URL",
        "default_base": "http://127.0.0.1:5000",
        "free_note": "Local OpenVault mesh (keys + OpenFree routing + OpenIDE handshake). Repo: D:\\OpenVault. One tap Connect from OpenIDE Keys.",
        "steps": [
            "Keep OpenVault console on http://127.0.0.1:5000",
            "In OpenIDE tap Keys → Connect OpenVault (or POST /api/openvault/connect)",
            "Optional: set OPENVAULT_URL if not on :5000",
        ],
    },
)


def _configured_map() -> dict[str, str]:
    """env_key -> masked value, from the existing settings module. Never raw."""
    try:
        import settings as app_settings
        return dict(app_settings.get_public_settings().get("keys_configured") or {})
    except Exception:
        return {}


def _env_raw(key: str) -> str:
    import os
    v = (os.environ.get(key) or "").strip()
    if v:
        return v
    try:
        from config import ENV_FILE
        if ENV_FILE.is_file():
            for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().startswith(f"{key}="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def snapshot(include_status: bool = True) -> dict[str, Any]:
    """Registry + configured status for the Key Vault popup. No secrets.

    Prefer OpenVault SoT when online (PRODUCT_ROLES); fall back to local catalog.
    """
    try:
        import openvault_bridge

        ov = openvault_bridge.keyvault_snapshot()
        if ov.get("ok") and ov.get("providers"):
            # Keep AirGPT-only cards that OV may omit by merging local ids not present
            ov_ids = {p.get("id") for p in ov["providers"]}
            configured = _configured_map() if include_status else {}
            for p in PROVIDERS:
                if p["id"] in ov_ids or p.get("ui_hidden"):
                    continue
                masked = configured.get(p["env_key"], "")
                ov["providers"].append({**p, "configured": bool(masked), "masked": masked})
            ov.setdefault("save_endpoint", "/api/settings")
            ov["save_endpoint"] = "/api/settings"  # AirGPT proxies → OpenVault
            ov["product_name"] = "OpenVault Key Vault"
            ov["policy"] = (
                "OpenVault Key Vault — keys live in OpenVault; AirGPT links and caches. "
                "Open Free gateway + OpenShip deploy tokens also store there. "
                "Account signup stays a human step."
            )
            return ov
    except Exception:
        pass

    configured = _configured_map() if include_status else {}
    providers = []
    for p in PROVIDERS:
        masked = configured.get(p["env_key"], "")
        if not masked:
            for alt in p.get("alt_env_keys") or []:
                masked = configured.get(alt, "")
                if masked:
                    break
        if p["id"] == "omniroute":
            base = _env_raw(p.get("base_url_env") or "OMNIROUTE_BASE_URL")
            enabled = _env_raw("OMNIROUTE_ENABLED").lower() in ("1", "true", "yes", "on")
            ready = bool(base) or enabled or bool(masked)
        elif p["id"] == "ollama":
            ready = bool(masked) or bool(_env_raw("OLLAMA_BASE_URL"))
        elif p["id"] == "openship":
            base = _env_raw(p.get("base_url_env") or "OPENSHIP_URL")
            ready = bool(masked) or bool(base)
        elif p["id"] == "openvault_mesh":
            base = _env_raw(p.get("base_url_env") or "OPENVAULT_URL") or "http://127.0.0.1:5000"
            try:
                import openvault_bridge

                ready = bool(openvault_bridge.ping().get("ok"))
            except Exception:
                ready = bool(base)
        else:
            ready = bool(masked)
        entry = {**p, "configured": ready, "masked": masked}
        providers.append(entry)
    return {
        "providers": providers,
        "policy": "OpenVault Key Vault — one place for keys (OpenVault SoT). "
                  "Offline fallback reads local env.local cache only. "
                  "Missing paid keys fall back to OpenFree → free-tier cloud.",
        "product_name": "OpenVault Key Vault",
        "save_endpoint": "/api/settings",
        "source": "local_cache",
        "free_fallback_order": ["omniroute", "groq", "openrouter", "gemini"],
    }


def ready_for_backend(backend: str = "local") -> dict[str, Any]:
    """Whether OpenIDE Run can proceed for the selected backend."""
    snap = snapshot(include_status=True)
    providers = {p["id"]: p for p in snap["providers"]}
    backend = (backend or "local").lower()
    if backend in ("cursor_local", "cursor_cloud"):
        ok = bool(providers.get("cursor", {}).get("configured"))
        return {
            "ok": ok,
            "backend": backend,
            "need": "CURSOR_API_KEY",
            "hint": "Paste a Cursor API key, or switch backend to Local and use a free-tier provider.",
            "providers": snap["providers"],
            "free_fallback_order": snap["free_fallback_order"],
        }
    # local Cortex agent — any cloud/gateway/local capacity
    usable = [
        p for p in snap["providers"]
        if p.get("configured") and p["id"] not in ("netie_official",)
        and p["group"] in ("cloud", "gateway", "local")
    ]
    # Prefer free-ish if nothing configured: still allow Run (ai_engine soft-fails)
    # but OpenIDE preflight prompts when zero keys for cloud backends.
    has_cloud = any(p["group"] == "cloud" and p.get("configured") for p in usable)
    has_local = any(p["group"] in ("local", "gateway") and p.get("configured") for p in usable)
    # Also treat Groq/OpenRouter etc configured map
    ok = has_cloud or has_local
    return {
        "ok": ok,
        "backend": backend,
        "need": "any free-tier or local key",
        "hint": "Open Key Vault — enable OpenFree, or paste Groq/OpenRouter/Gemini.",
        "providers": snap["providers"],
        "free_fallback_order": snap["free_fallback_order"],
        "usable_count": len(usable),
    }

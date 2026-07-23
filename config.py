"""AirGPT — portable paths and product constants (EXE-friendly)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "AirGPT"
APP_TAGLINE = "Local-first AI clipboard & chat"
APP_VERSION = "1.0.0"

# Licensing (Stripe hooks later)
TRIAL_DAYS = 30
SUBSCRIPTION_PRICE_USD = 5
LICENSE_PRICE_USD = 5
API_STARTER_CREDIT_USD = 9

# Allowed user-configurable secret keys (stored locally in env.local)
USER_SECRET_KEYS = (
    "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY",
    "GROQ_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY_SISWA",
    "SEA_LION_API_KEY",
    "SEA_LION_API_KEY_SISWA",
    # ai_engine reads these too — persist them via the same settings path
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OLLAMA_API_KEY",
    "VLLM_API_KEY",
    "CURSOR_API_KEY",
    "OMNIROUTE_API_KEY",
    "OMNIROUTE_BASE_URL",
    "OMNIROUTE_ENABLED",
    "NETIE_ENGINE_KEY",
    # CLI + deploy (OpenVault Key Vault)
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "OPENSHIP_API_TOKEN",
    "OPENSHIP_URL",
    "OPENVAULT_URL",
    "OPENVAULT_ROOT",
    "OPENIDE_URL",
)

# Demo / marketing profile (separate disposable data dir — never touches real `data/`)
DEMO_MOCK = (os.environ.get("AIRGPT_DEMO_MOCK") or "").strip().lower() in ("1", "true", "yes", "on")
DEMO_MOCK_LAN_IP = (os.environ.get("AIRGPT_DEMO_LAN_IP") or "10.10.20.42").strip() or "10.10.20.42"
DEMO_MOCK_HOSTNAME = (os.environ.get("AIRGPT_DEMO_HOSTNAME") or "DEMO-LAPTOP").strip() or "DEMO-LAPTOP"


def app_root() -> Path:
    """When frozen (PyInstaller), data lives beside the EXE."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = app_root()


def _resolve_data_dir() -> Path:
    """Prefer AIRGPT_DATA_DIR; else demo mock dir when flagged; else ./data."""
    override = (os.environ.get("AIRGPT_DATA_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if DEMO_MOCK:
        return (ROOT / "data-demo-mock").resolve()
    return (ROOT / "data").resolve()


DATA_DIR = _resolve_data_dir()
BIN_DIR = ROOT / "bin"
ENV_FILE = ROOT / "env.local"
LICENSE_FILE = DATA_DIR / "license.json"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "files").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "thumbs").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "vault").mkdir(parents=True, exist_ok=True)

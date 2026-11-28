"""First-run steps shared by the guide, the wizard, and the page."""
from __future__ import annotations

STEPS: tuple[dict[str, str], ...] = (
    {
        "id": "install",
        "title": "Install on this computer",
        "body": (
            "Install Python 3.11 or newer. In the AirGPT folder run: "
            "pip install -r requirements.lock. "
            "On Windows that also installs pywin32. On Linux and macOS that line is skipped."
        ),
    },
    {
        "id": "token",
        "title": "Create the local service token",
        "body": (
            "Run: python -m bundle.launch --check. "
            "The wizard creates one token for AirGPT, DMS, and OpenVault. "
            "It is stored in the OS keychain when that works, and in a file "
            "with mode 0600 so the other programs can read it. The token is never shown."
        ),
    },
    {
        "id": "start",
        "title": "Start AirGPT, DMS, and OpenVault",
        "body": (
            "Run: python -m bundle.launch --up. "
            "AirGPT listens on 127.0.0.1:8765. "
            "DMS (Cortex, pack dms) listens on 127.0.0.1:8011 when DMS_CMD or DMS_ROOT is set. "
            "OpenVault listens on 127.0.0.1:5000 when OPENVAULT_CMD or OPENVAULT_ROOT is set. "
            "Docker: docker compose -f bundle/docker-compose.yml up --build. "
            "Add --profile siblings when those images are available."
        ),
    },
    {
        "id": "passcode",
        "title": "Set a passcode on this computer",
        "body": (
            "Open http://127.0.0.1:8765. In Settings, then Profile, set a host "
            "passcode before any phone joins."
        ),
    },
    {
        "id": "tunnel",
        "title": "Leave the public tunnel off",
        "body": (
            "The tunnel stays off. In Connected Devices, press the tunnel button "
            "only after you read the warning, or set AIRGPT_TUNNEL=1 before start. "
            "That publishes this computer on the internet."
        ),
    },
    {
        "id": "lan",
        "title": "Open the LAN only if you mean to",
        "body": (
            "The default bind is 127.0.0.1. Set AIRGPT_BIND=0.0.0.0 only when "
            "other machines on your network should connect. Startup prints a warning."
        ),
    },
)


def public_steps() -> list[dict[str, str]]:
    return [{"id": s["id"], "title": s["title"], "body": s["body"]} for s in STEPS]

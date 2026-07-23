"""Resend email — waitlist & security alerts only. Keys from env.local."""
from __future__ import annotations

import json
import urllib.request

from config import ENV_FILE

CONTACT_TO = "hello@netie.ai"


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_FILE.is_file():
        return env
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def send_waitlist(email: str, feature_request: str) -> dict:
    env = _load_env()
    api_key = env.get("RESEND_API_KEY", "")
    from_email = env.get("RESEND_FROM_EMAIL") or env.get("RESEND_FROM_AUTH") or "hello@netie.ai"
    to_email = env.get("CONTACT_TO") or CONTACT_TO
    if not api_key:
        return {"ok": False, "error": "RESEND_API_KEY not configured in env.local"}

    subject = f"AirGPT Pro waitlist — {email}"
    body = (
        f"New AirGPT Pro waitlist signup\n\n"
        f"Email: {email}\n\n"
        f"What feature they wish to add:\n{feature_request or '(not provided)'}\n\n"
        f"— Sent from local AirGPT instance"
    )
    payload = {
        "from": from_email,
        "to": [to_email],
        "reply_to": env.get("RESEND_REPLY_TO") or email,
        "subject": subject,
        "text": body,
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode())
        return {"ok": True, "id": data.get("id", ""), "message": "Waitlist sent — we'll email you at launch"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def send_security_alert(subject: str, body: str) -> None:
    env = _load_env()
    api_key = env.get("RESEND_API_KEY", "")
    if not api_key:
        return
    from_email = env.get("RESEND_FROM_AUTH") or env.get("RESEND_FROM_EMAIL", "hello@netie.ai")
    to_email = env.get("CONTACT_TO") or CONTACT_TO
    payload = {
        "from": from_email,
        "to": [to_email],
        "subject": f"[AirGPT Security] {subject}"[:120],
        "text": body[:4000],
    }
    try:
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass

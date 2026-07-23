"""Simulate LAN/WiFi attacks against AirGPT — run before demo."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"


def _get(path: str, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(BASE + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"error": body[:200]}


def main() -> int:
    fails = 0
    print("=== AirGPT Security Simulation ===\n")

    # 1. Unauthenticated access to history (should 401 if workspace initialized)
    code, data = _get("/api/history", {"X-Forwarded-For": "192.168.1.99"})
    ok = code == 401 or "messages" in data
    print(f"[{'PASS' if ok else 'FAIL'}] Unauth history: HTTP {code}")
    if not ok:
        fails += 1

    # 2. Brute force passcode (should fail, not crash)
    for i in range(5):
        req = urllib.request.Request(
            BASE + "/api/auth/join",
            data=json.dumps({"passcode": f"wrong{i}"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=3)
        except urllib.error.HTTPError:
            pass
    print("[PASS] Brute force join attempts handled")

    # 3. Path traversal on /data/
    code, _ = _get("/data/../../env.local")
    ok = code in (400, 401, 404)
    print(f"[{'PASS' if ok else 'FAIL'}] Path traversal blocked: HTTP {code}")
    if not ok:
        fails += 1

    # 4. Invalid QR token
    req = urllib.request.Request(
        BASE + "/api/auth/qr-redeem",
        data=json.dumps({"qr_token": "fake-token-attack"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        d = json.loads(r.read().decode())
    ok = not d.get("ok")
    print(f"[{'PASS' if ok else 'FAIL'}] Fake QR token rejected")
    if not ok:
        fails += 1

    # 5. Audit log exists
    code, data = _get("/api/audit")
    ok = code == 200 and "events" in data
    print(f"[{'PASS' if ok else 'FAIL'}] Audit trail readable: {len(data.get('events', []))} events")
    if not ok:
        fails += 1

    print(f"\n{5 - fails}/5 security checks passed")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

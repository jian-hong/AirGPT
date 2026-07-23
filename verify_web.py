"""AirGPT web health check — run after every server start or deploy."""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8765"
CHECKS = [
    ("/api/probe", lambda d: d.get("ok") is True),
    ("/api/info", lambda d: "tunnel_url" in d and "online" in d),
    ("/api/history", lambda d: "messages" in d),
    ("/api/ai/config", lambda d: "auto" in d),
    ("/api/auth/status", lambda d: "needs_auth" in d),
    ("/api/vault", lambda d: "categories" in d or "recent" in d),
    ("/api/audit", lambda d: "events" in d),
]


def main() -> int:
    passed = 0
    for path, validate in CHECKS:
        try:
            with urllib.request.urlopen(BASE + path, timeout=8) as r:
                data = json.loads(r.read().decode())
            ok = validate(data)
            status = "OK" if ok else "FAIL"
            if ok:
                passed += 1
            print(f"  [{status}] GET {path}")
        except Exception as e:
            print(f"  [ERR] GET {path}: {e}")
    # QR endpoint
    try:
        with urllib.request.urlopen(
            BASE + "/api/qr.png?u=https://test.trycloudflare.com", timeout=8,
        ) as r:
            qr_ok = r.status == 200 and r.headers.get("Content-Type", "").startswith("image/")
        if qr_ok:
            passed += 1
        print(f"  [{'OK' if qr_ok else 'FAIL'}] GET /api/qr.png")
    except Exception as e:
        print(f"  [ERR] GET /api/qr.png: {e}")

    total = len(CHECKS) + 1
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())

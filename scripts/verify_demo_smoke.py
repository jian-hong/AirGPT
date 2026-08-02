"""Demo smoke — health endpoints only (no Playwright / long E2E).

Usage:
  python scripts/verify_demo_smoke.py
  python scripts/verify_demo_smoke.py --base http://127.0.0.1:8765
  python scripts/verify_demo_smoke.py --require-demo-mock   # after start_demo_mock.bat

Exit 0 when all checks pass; 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_CHECKS: tuple[tuple[str, callable], ...] = (
    ("/api/probe", lambda d: d.get("ok") is True),
    (
        "/api/info",
        lambda d: bool(d.get("local_url")) and d.get("port") == 8765,
    ),
    ("/api/sessions", lambda d: isinstance(d.get("sessions"), list) and len(d.get("sessions") or []) > 0),
    ("/api/hub", lambda d: d.get("ok") and isinstance(d.get("peers"), list)),
    ("/api/history", lambda d: "messages" in d),
    ("/api/vault", lambda d: "categories" in d or "recent" in d),
    ("/api/keyvault", lambda d: isinstance(d.get("providers"), list)),
)


def _get(base: str, path: str, timeout: float = 8.0) -> tuple[bool, dict | str]:
    url = base.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return True, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            return False, json.loads(e.read().decode())
        except Exception:
            return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)


def main() -> int:
    ap = argparse.ArgumentParser(description="AirGPT demo smoke (health endpoints)")
    ap.add_argument("--base", default="http://127.0.0.1:8765", help="AirGPT base URL")
    ap.add_argument(
        "--require-demo-mock",
        action="store_true",
        help="Require /api/info.demo_mock === true (BUSINESS MOCK profile)",
    )
    args = ap.parse_args()
    base = args.base.rstrip("/")

    fails = 0
    print(f"=== AirGPT demo smoke ===\n  base: {base}\n")

    ok_info, info = _get(base, "/api/info")
    if not ok_info:
        print(f"  [FAIL] GET /api/info — cannot reach server: {info}")
        print("\n  Start demo: .\\start_demo_mock.bat")
        return 1

    if args.require_demo_mock and not info.get("demo_mock"):
        print("  [FAIL] demo_mock is false — run start_demo_mock.bat (not restart.bat)")
        fails += 1
    elif info.get("demo_mock"):
        print(f"  [OK] demo_mock profile (data_dir={info.get('data_dir', '')})")
    else:
        print(f"  [WARN] real data profile (data_dir={info.get('data_dir', '')})")

    for path, pred in DEFAULT_CHECKS:
        ok, data = _get(base, path)
        if not ok:
            print(f"  [FAIL] GET {path} — {data}")
            fails += 1
            continue
        if not isinstance(data, dict):
            print(f"  [FAIL] GET {path} — not JSON object")
            fails += 1
            continue
        if pred(data):
            print(f"  [OK] GET {path}")
        else:
            print(f"  [FAIL] GET {path} — predicate failed")
            fails += 1

    try:
        with urllib.request.urlopen(base + "/", timeout=8) as resp:
            page = resp.read().decode("utf-8", errors="replace")
        opens = page.count("<script")
        closes = page.count("</script>")
        if opens == closes and "</html>" in page[-4000:] and len(page) >= 200_000:
            print(f"  [OK] index.html served ({len(page):,}B, scripts balanced)")
        else:
            print(f"  [FAIL] index.html integrity (size={len(page)}, scripts {opens}/{closes})")
            fails += 1
    except Exception as e:
        print(f"  [FAIL] GET / — {e}")
        fails += 1

    print()
    if fails:
        print(f"  Result: {fails} issue(s)")
        return 1
    print("  Result: all demo smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

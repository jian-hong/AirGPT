"""Gentle resilience probe for AirGPT (defensive review, localhost only).

Fires a moderate number of concurrent GET requests at read-only endpoints and
records latency / error distribution. NOT a load/DDoS test — capped low.
"""
from __future__ import annotations

import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "http://127.0.0.1:8765"
READ_ENDPOINTS = ["/api/probe", "/api/info", "/api/wait?since=0", "/api/sessions?limit=20"]
CONCURRENCY = 12          # gentle
REQUESTS_PER_EP = 40      # 4 endpoints * 40 = 160 total


def hit(path: str) -> tuple[int, float, str]:
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(BASE + path, headers={"User-Agent": "resilience-probe"})
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
            return r.status, (time.perf_counter() - t0) * 1000, ""
    except urllib.error.HTTPError as e:
        return e.code, (time.perf_counter() - t0) * 1000, ""
    except Exception as e:  # noqa: BLE001
        return 0, (time.perf_counter() - t0) * 1000, type(e).__name__


def main() -> int:
    jobs = [ep for ep in READ_ENDPOINTS for _ in range(REQUESTS_PER_EP)]
    lat: list[float] = []
    codes: dict[int, int] = {}
    errs: dict[str, int] = {}
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = [ex.submit(hit, p) for p in jobs]
        for f in as_completed(futs):
            code, ms, err = f.result()
            lat.append(ms)
            codes[code] = codes.get(code, 0) + 1
            if err:
                errs[err] = errs.get(err, 0) + 1
    wall = time.perf_counter() - started
    lat.sort()
    n = len(lat)
    def pct(p: float) -> float:
        return lat[min(n - 1, int(p * n))]
    print(f"total_requests={n} concurrency={CONCURRENCY} wall_s={wall:.2f} rps={n / wall:.1f}")
    print(f"status_codes={codes}")
    print(f"errors={errs or 'none'}")
    print(f"latency_ms min={lat[0]:.1f} p50={pct(0.5):.1f} p90={pct(0.9):.1f} "
          f"p99={pct(0.99):.1f} max={lat[-1]:.1f} mean={statistics.mean(lat):.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Stress-check hot paths that cause AirGPT lag (wait poll, fingerprint, vault)."""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ms(fn, n: int = 20) -> list[float]:
    times: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return times


def main() -> None:
    import workspace_api
    from clipdrop import _lan_diag_cache, lan_diagnostics

    lan_diagnostics()
    assert _lan_diag_cache.get("value")

    def cheap_wait_sim():
        cached = _lan_diag_cache.get("value") or {}
        _ = cached.get("lan_url")

    def old_wait_sim():
        lan_diagnostics()

    cheap = _ms(cheap_wait_sim, 50)
    old = _ms(old_wait_sim, 20)
    print(f"wait_cheap_ms p50={statistics.median(cheap):.2f} max={max(cheap):.2f}")
    print(f"wait_old_lan_ms p50={statistics.median(old):.2f} max={max(old):.2f}")

    def fp_light():
        workspace_api.fingerprint(light=True, use_cache=True)

    fp = _ms(fp_light, 8)
    print(f"fingerprint_light_ms p50={statistics.median(fp):.2f} max={max(fp):.2f}")

    from OpenIDE.workspace_api import SKIP_DIRS

    assert "research" in SKIP_DIRS and "CortexOS" in SKIP_DIRS
    print("skip_dirs_ok")
    print("stress_ok")


if __name__ == "__main__":
    main()

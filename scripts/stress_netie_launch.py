"""Stress / smoke for Netie account API and scroll download dock config."""
from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def stress_netie_id(n: int = 200) -> None:
    import netie_id

    tmp = tempfile.TemporaryDirectory()
    netie_id.ACCOUNT_FILE = Path(tmp.name) / "account.json"
    t0 = time.perf_counter()
    for i in range(n):
        netie_id.link_local(email=f"u{i % 17}@netie.ai", product="airgpt", sku="personal")
        netie_id.status()
    elapsed = time.perf_counter() - t0
    assert netie_id.status()["signed_in"]
    print(f"OK netie_id stress {n} ops in {elapsed:.3f}s ({n/elapsed:.0f}/s)")
    tmp.cleanup()


def check_scroll_dock() -> None:
    html = (ROOT / "netie-scroll-world" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "netie-scroll-world" / "scroll-world.js").read_text(encoding="utf-8")
    assert "downloadDock" in html
    assert "Download AirGPT" in html
    assert "Netie Space" in html
    assert "airgpt/download" in html
    assert "buildDownloadDock" in js
    assert "sw-dock" in js
    print("OK scroll-world download dock config")


def check_installer() -> None:
    iss = (ROOT / "installer" / "AirGPT.iss").read_text(encoding="utf-8")
    assert "installspace" in iss
    assert "NetieSpace" in iss
    assert "Copilot" in iss or "copilot" in iss
    assert (ROOT / "installer" / "legal" / "terms.txt").is_file()
    assert (ROOT / "legal" / "privacy.md").is_file()
    print("OK installer + legal stubs")


def main() -> int:
    check_scroll_dock()
    check_installer()
    stress_netie_id(300)
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

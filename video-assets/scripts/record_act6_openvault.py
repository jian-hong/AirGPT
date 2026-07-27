"""Act 6 — OpenVault sync → detect → ship (Simulated target on screen)."""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from yc_rec_common import (
    BASE,
    VIEWPORT,
    finalize_video,
    inject_demo_badge,
    pause,
    require_demo_mock,
    safe_click,
)

OUT = Path(__file__).resolve().parents[1] / "03-demo-clips" / "multiplayer" / "act6"


def run() -> Path:
    require_demo_mock()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    work = OUT / f"_pw_{stamp}"
    work.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(work),
            record_video_size=VIEWPORT,
        )
        page = ctx.new_page()
        page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        inject_demo_badge(page)
        pause(page, 1000)
        safe_click(page, ["text=Projects", "button:has-text('Projects')"])
        pause(page, 800)
        if not safe_click(page, ["button.proj-share:has-text('Ship')", "button:has-text('Ship')"]):
            page.evaluate("() => window.MP && MP.shipProjectFlow('vitron-forward')")
        pause(page, 1200)
        safe_click(page, ["#ovShipGo", "button:has-text('Run pipeline')"])
        pause(page, 6000)
        # Hold Simulated target
        pause(page, 3000)
        ctx.close()
        browser.close()

    return finalize_video(work, OUT, "act6_openvault")


if __name__ == "__main__":
    run()

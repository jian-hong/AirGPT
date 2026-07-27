"""Act 2 — project share QR defaults to read-only."""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from yc_rec_common import (
    HEADLESS,
    BASE,
    VIEWPORT,
    finalize_video,
    inject_demo_badge,
    pause,
    require_demo_mock,
    safe_click,
)

OUT = Path(__file__).resolve().parents[1] / "03-demo-clips" / "multiplayer" / "act2"


def run() -> Path:
    require_demo_mock()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    work = OUT / f"_pw_{stamp}"
    work.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(work),
            record_video_size=VIEWPORT,
        )
        page = ctx.new_page()
        page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        inject_demo_badge(page)
        pause(page, 1200)
        safe_click(page, ["text=Projects", "button:has-text('Projects')"])
        pause(page, 1200)
        # Prefer Share on a project header
        if not safe_click(page, ["button.proj-share:has-text('Share')", "button:has-text('Share')"]):
            page.evaluate(
                """() => {
                  if (window.MP && MP.shareProject) MP.shareProject('general', 'read_only');
                }"""
            )
        pause(page, 3500)
        # Hold on Read only default
        pause(page, 2500)
        ctx.close()
        browser.close()

    return finalize_video(work, OUT, "act2_share")


if __name__ == "__main__":
    run()

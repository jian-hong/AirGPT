"""Act 4 — mock Cut all AI (visual only) + Cleared."""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from yc_rec_common import (
    BASE,
    VIEWPORT,
    finalize_video,
    inject_demo_badge,
    open_hub,
    pause,
    require_demo_mock,
    safe_click,
)

OUT = Path(__file__).resolve().parents[1] / "03-demo-clips" / "multiplayer" / "act4"


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
        open_hub(page)
        pause(page, 1500)
        page.once("dialog", lambda d: d.accept())
        if not safe_click(page, ["#hubLockdownBtn", "button:has-text('Cut all AI')"]):
            page.evaluate("() => window.MP && MP.setLockdown(true)")
        pause(page, 4500)  # stillness
        if not safe_click(page, ["#lockdownClearBtn", "button:has-text('Cleared')"]):
            page.evaluate("() => window.MP && MP.setLockdown(false)")
        pause(page, 2500)
        ctx.close()
        browser.close()

    return finalize_video(work, OUT, "act4_lockdown_mock")


if __name__ == "__main__":
    run()

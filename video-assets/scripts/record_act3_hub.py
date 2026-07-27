"""Act 3 — Hub Demo mode → red limited peer → drawer → View chat."""
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

OUT = Path(__file__).resolve().parents[1] / "03-demo-clips" / "multiplayer" / "act3"


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
        pause(page, 2000)
        # Demo mode on
        page.evaluate(
            """() => {
              localStorage.setItem('airgpt_hub_demo', '1');
              if (typeof renderHubPage === 'function') renderHubPage();
            }"""
        )
        pause(page, 2500)
        # Click limited / red peer if present
        if not safe_click(page, [".hub-node.state-limited", "text=Jamie Ortiz", "text=Limited"]):
            page.evaluate(
                """() => {
                  const n = document.querySelector('.hub-node.state-limited, .hub-demo-cell .hub-node');
                  if (n) n.click();
                  else if (window.MP) MP.openPeerDrawer('10.10.20.19');
                }"""
            )
        pause(page, 2500)
        safe_click(page, ["button.hub-prompt-row", "text=View chat"])
        pause(page, 3500)
        ctx.close()
        browser.close()

    return finalize_video(work, OUT, "act3_hub")


if __name__ == "__main__":
    run()

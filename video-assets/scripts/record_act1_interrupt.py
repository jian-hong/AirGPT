"""Act 1 — two humans, one agent interrupt (genuine multiplayer)."""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from yc_rec_common import (
    BASE,
    VIEWPORT,
    finalize_video,
    inject_demo_badge,
    open_demo_session,
    pause,
    require_demo_mock,
    set_device_name,
    type_slowly,
)

OUT = Path(__file__).resolve().parents[1] / "03-demo-clips" / "multiplayer" / "act1"


def run() -> Path:
    require_demo_mock()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    work = OUT / f"_pw_{stamp}"
    work.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-notifications"])
        host_ctx = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(work / "host"),
            record_video_size=VIEWPORT,
        )
        peer_ctx = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(work / "peer"),
            record_video_size=VIEWPORT,
        )
        host = host_ctx.new_page()
        peer = peer_ctx.new_page()
        host.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        peer.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        inject_demo_badge(host)
        inject_demo_badge(peer)
        set_device_name(host, "DEMO Host PC")
        set_device_name(peer, "Jordan Lee · Eng")
        pause(host, 1500)
        open_demo_session(host)
        open_demo_session(peer)
        pause(host, 1000)

        type_slowly(
            host,
            "#input, textarea",
            "Sup Netie! Please prepare a slideshow for today's meeting at four",
            delay=28,
        )
        pause(host, 400)
        if host.locator("button:has-text('Send')").count():
            host.locator("button:has-text('Send')").first.click()
        else:
            host.keyboard.press("Enter")
        pause(host, 5000)

        type_slowly(
            peer,
            "#input, textarea",
            "Hey Netie, would you mind to complete the VDML excel referencing RFQ, FCM and PO from our vendor NMD?",
            delay=28,
        )
        if peer.locator("button:has-text('Send')").count():
            peer.locator("button:has-text('Send')").first.click()
        else:
            peer.keyboard.press("Enter")
        pause(host, 5000)
        # Hold on presence + author chip
        pause(host, 3000)

        host_ctx.close()
        peer_ctx.close()
        browser.close()

    host_vids = list((work / "host").glob("*.webm")) + list((work / "host").glob("*.mp4"))
    peer_vids = list((work / "peer").glob("*.webm")) + list((work / "peer").glob("*.mp4"))
    OUT.mkdir(parents=True, exist_ok=True)
    stamp2 = time.strftime("%Y%m%d_%H%M%S")
    if host_vids:
        dest = OUT / f"act1_host_{stamp2}{host_vids[0].suffix}"
        host_vids[0].replace(dest)
        print(f"WROTE {dest}")
    if peer_vids:
        dest = OUT / f"act1_peer_{stamp2}{peer_vids[0].suffix}"
        peer_vids[0].replace(dest)
        print(f"WROTE {dest}")
    return OUT


if __name__ == "__main__":
    run()

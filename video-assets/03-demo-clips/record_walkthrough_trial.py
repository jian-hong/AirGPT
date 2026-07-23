"""
AirGPT local walkthrough recorder — ONE trial video (V2-style moat/connect tour).
Records via Playwright Chromium to video-assets/03-demo-clips/connect-tunnel/
"""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(r"d:\AirGPT")
OUT_DIR = ROOT / "video-assets" / "03-demo-clips" / "connect-tunnel"
OUT_DIR.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8765/"
VIEWPORT = {"width": 1440, "height": 900}


def pause(page, sec: float) -> None:
    page.wait_for_timeout(int(sec * 1000))


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-notifications"])
        context = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(OUT_DIR / "_raw"),
            record_video_size=VIEWPORT,
            device_scale_factor=1,
        )
        page = context.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        pause(page, 2.0)

        # Hard feel: dismiss any obvious overlay by Escape
        page.keyboard.press("Escape")
        pause(page, 0.5)

        # --- Beat 1: brand + main chat idle ---
        page.mouse.move(720, 450)
        pause(page, 1.8)

        # --- Beat 2: ensure connect panel visible ---
        # If collapsed, click connect collapse toggle
        try:
            btn = page.locator("#connectCollapseBtn")
            if btn.count():
                # If connect col is hidden/collapsed, expand
                col = page.locator("#connectCol")
                box = col.bounding_box()
                if box and box["width"] < 40:
                    btn.click()
                    pause(page, 0.8)
        except Exception:
            pass

        # Scroll connect into view / highlight tunnel QR area
        tunnel = page.locator("#qrTunnel")
        if tunnel.count():
            tunnel.scroll_into_view_if_needed()
            pause(page, 0.6)
            box = tunnel.bounding_box()
            if box:
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=20)
        pause(page, 2.2)

        # Tunnel URL box
        url_box = page.locator("#tunnelUrl")
        if url_box.count():
            url_box.scroll_into_view_if_needed()
            pause(page, 1.2)

        # --- Beat 3: new chat / composer focus ---
        # Try sidebar new chat or composer
        for sel in ["#newChatBtn", "button:has-text('New')", "#composerChrome textarea", "textarea", "[contenteditable='true']"]:
            loc = page.locator(sel).first
            if loc.count():
                try:
                    loc.click(timeout=1500)
                    pause(page, 0.4)
                    break
                except Exception:
                    continue

        # Type a demo prompt slowly (visual walkthrough — may or may not send)
        editable = page.locator("textarea, [contenteditable='true']").first
        try:
            if editable.count():
                editable.click()
                pause(page, 0.3)
                text = "Send a whiteboard photo from my phone to this PC."
                for ch in text:
                    editable.type(ch, delay=35)
                pause(page, 1.5)
        except Exception:
            pass

        # --- Beat 4: side nav peek (home/chat feel) ---
        nav = page.locator("#sideNav .nav-item").first
        if nav.count():
            try:
                nav.hover()
                pause(page, 0.8)
            except Exception:
                pass

        # Slow pan across chat area
        page.mouse.move(400, 500, steps=30)
        pause(page, 1.0)
        page.mouse.move(900, 400, steps=30)
        pause(page, 1.5)

        # Hold end frame on QR again
        if tunnel.count():
            tunnel.scroll_into_view_if_needed()
            pause(page, 2.0)

        pause(page, 1.0)
        page.close()
        context.close()
        browser.close()

    # Playwright writes webm into _raw; rename latest
    raw = OUT_DIR / "_raw"
    videos = sorted(raw.glob("*.webm"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not videos:
        raise SystemExit("No video recorded")
    src = videos[0]
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest_webm = OUT_DIR / f"UI_CONNECT_WALKTHROUGH_trial_{stamp}.webm"
    dest_mp4 = OUT_DIR / f"UI_CONNECT_WALKTHROUGH_trial_{stamp}.mp4"
    src.replace(dest_webm)

    # Transcode to mp4 for easy review
    import subprocess

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(dest_webm),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(dest_mp4),
        ],
        check=True,
        capture_output=True,
    )
    print(f"OK_WEBM={dest_webm}")
    print(f"OK_MP4={dest_mp4}")


if __name__ == "__main__":
    main()

"""
AirGPT local walkthrough recorder — SAMPLE #1 (Connect + chat) on DEMO MOCK.

Requires AirGPT running with AIRGPT_DEMO_MOCK=1 (see start_demo_mock.bat).
Refuses to record if /api/info.demo_mock is not true (protects real PII).

Output: video-assets/03-demo-clips/connect-tunnel/UI_CONNECT_WALKTHROUGH_*_MOCK_*.webm
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "video-assets" / "03-demo-clips" / "connect-tunnel"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BASE = "http://127.0.0.1:8765"
VIEWPORT = {"width": 1440, "height": 900}


def pause(page, ms: int = 800) -> None:
    page.wait_for_timeout(ms)


def fetch_info() -> dict:
    try:
        with urllib.request.urlopen(f"{BASE}/api/info", timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise SystemExit(f"AirGPT not reachable at {BASE} — start start_demo_mock.bat first ({e})") from e


def require_demo_mock() -> dict:
    info = fetch_info()
    if not info.get("demo_mock"):
        raise SystemExit(
            "REFUSING to record: /api/info.demo_mock is not true.\n"
            "Real user data may be on camera. Run start_demo_mock.bat (or set AIRGPT_DEMO_MOCK=1)."
        )
    print(f"DEMO_MOCK_OK data_dir={info.get('data_dir')} lan={info.get('ips')} host={info.get('hostname')}")
    return info


def safe_click(page, selectors: list[str], timeout: int = 2500) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=800):
                loc.click(timeout=timeout)
                return True
        except Exception:
            continue
    return False


def type_slowly(page, selector: str, text: str, delay: int = 35) -> None:
    box = page.locator(selector).first
    box.click()
    box.fill("")
    box.type(text, delay=delay)


def inject_demo_badge(page) -> None:
    page.evaluate(
        """() => {
          if (document.getElementById('airgpt-demo-badge')) return;
          const el = document.createElement('div');
          el.id = 'airgpt-demo-badge';
          el.textContent = 'DEMO · BUSINESS MOCK';
          Object.assign(el.style, {
            position: 'fixed', top: '10px', right: '12px', zIndex: '99999',
            padding: '6px 12px', borderRadius: '6px',
            background: 'rgba(20,40,70,.88)', color: '#c8ddff',
            font: '600 11px/1.2 JetBrains Mono, Consolas, monospace',
            letterSpacing: '.04em', pointerEvents: 'none',
            border: '1px solid #4a6fa5'
          });
          document.body.appendChild(el);
        }"""
    )


def open_demo_session(page) -> None:
    # Prefer pinned DEMO sessions in sidebar
    for label in [
        "DEMO · Connect + Tunnel",
        "DEMO · Engineering",
        "DEMO · Whiteboard",
        "DEMO",
    ]:
        if safe_click(page, [f"text={label}", f"button:has-text('{label}')"]):
            pause(page, 900)
            return


def run() -> Path:
    require_demo_mock()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    work = OUT_DIR / f"_pw_record_mock_{stamp}"
    work.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-notifications", "--window-size=1440,900"],
        )
        context = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(work),
            record_video_size=VIEWPORT,
            device_scale_factor=1,
        )
        page = context.new_page()
        page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        pause(page, 1500)

        inject_demo_badge(page)
        safe_click(page, ["button:has-text('Got it')", "button:has-text('OK')", "[aria-label='Close']"])
        page.keyboard.press("Escape")
        pause(page, 400)

        # Brand + DEMO session with staged chat
        safe_click(page, ["#appTitle", ".brand", "text=AirGPT"])
        pause(page, 800)
        open_demo_session(page)
        pause(page, 1200)

        # Expand connect / tunnel surface
        try:
            btn = page.locator("#connectCollapseBtn")
            if btn.count():
                col = page.locator("#connectCol")
                box = col.bounding_box()
                if box and box["width"] < 40:
                    btn.click()
                    pause(page, 700)
        except Exception:
            pass

        safe_click(
            page,
            [
                "button:has-text('Connect')",
                "text=Connect",
                "[title*='Connect']",
                "button:has-text('Tunnel')",
                "#connectBtn",
            ],
        )
        pause(page, 1000)

        tunnel = page.locator("#qrTunnel")
        if tunnel.count():
            tunnel.scroll_into_view_if_needed()
            pause(page, 600)
            box = tunnel.bounding_box()
            if box:
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=18)
        pause(page, 1600)

        url_box = page.locator("#tunnelUrl")
        if url_box.count():
            url_box.scroll_into_view_if_needed()
            pause(page, 1000)

        for label in ["Tunnel", "LAN", "Hotspot", "Tunnel"]:
            safe_click(page, [f"button:has-text('{label}')", f"text={label}"])
            pause(page, 750)

        # Composer — safe DEMO prompt only
        for sel in ["#composer", "textarea", "[contenteditable='true']", "input[type='text']"]:
            try:
                if page.locator(sel).first.is_visible(timeout=500):
                    type_slowly(
                        page,
                        sel,
                        "DEMO MOCK: phone → PC clipboard via Tunnel — local-first.",
                    )
                    break
            except Exception:
                continue
        pause(page, 1400)

        # Peek engineering / whiteboard sessions (diagram + whiteboard fixtures)
        for label in ["DEMO · Engineering", "DEMO · Whiteboard", "DEMO · OpenForge"]:
            if safe_click(page, [f"text={label}"]):
                pause(page, 1400)

        page.mouse.wheel(0, 200)
        pause(page, 900)
        page.mouse.wheel(0, -120)
        pause(page, 700)

        # Hold on tunnel QR again
        if tunnel.count():
            tunnel.scroll_into_view_if_needed()
            pause(page, 1800)

        inject_demo_badge(page)
        pause(page, 1200)

        video_path = Path(page.video.path()) if page.video else None
        context.close()
        browser.close()

    webms = list(work.glob("*.webm"))
    if not webms and video_path and video_path.exists():
        webms = [video_path]
    if not webms:
        raise SystemExit(f"No video recorded in {work}")

    dest = OUT_DIR / f"UI_CONNECT_WALKTHROUGH_sample_v01_MOCK_{stamp}.webm"
    webms[0].replace(dest)

    for leftover in work.glob("*"):
        try:
            leftover.unlink()
        except OSError:
            pass
    try:
        work.rmdir()
    except OSError:
        pass

    # Optional mp4 proxy for review
    dest_mp4 = dest.with_suffix(".mp4")
    try:
        import subprocess

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(dest),
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
        print(f"RECORDED_MP4={dest_mp4}")
    except Exception as e:
        print(f"MP4_SKIP={e}")

    print(f"RECORDED={dest}")
    print(f"SIZE_BYTES={dest.stat().st_size}")
    return dest


if __name__ == "__main__":
    run()

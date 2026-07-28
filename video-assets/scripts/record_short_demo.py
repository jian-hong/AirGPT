"""
Short AirGPT multiplayer demo — one continuous ~60s take for review / YC teaser B-roll.

Beats: open chat → peer interrupt → Hub demo grid → limited peer drawer → View chat
       → Cut all AI (mock) → Cleared → brand hold.

Requires demo mock (start_demo_mock / AIRGPT_DEMO_MOCK=1).
Cloud: set AIRGPT_PW_HEADLESS=1.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from yc_rec_common import (
    HEADLESS,
    BASE,
    VIEWPORT,
    inject_demo_badge,
    open_demo_session,
    open_hub,
    pause,
    require_demo_mock,
    safe_click,
    set_device_name,
    type_slowly,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "video-assets" / "03-demo-clips" / "multiplayer" / "short-demo"
EXPORTS = ROOT / "video-assets" / "07-exports"


def _title_card(path: Path, seconds: float = 2.5) -> None:
    """Generate a simple dark title card with ffmpeg drawtext."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=0x0a0a0a:s=1440x900:d={seconds}",
            "-vf",
            "drawtext=text='AirGPT':fontcolor=white:fontsize=72:x=(w-text_w)/2:y=(h-text_h)/2-40:"
            "font=DejaVu\\\\ Sans,"
            "drawtext=text='Multiplayer by default':fontcolor=0xc8ddff:fontsize=28:"
            "x=(w-text_w)/2:y=(h-text_h)/2+40:font=DejaVu\\\\ Sans",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", str(seconds),
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _end_card(path: Path, seconds: float = 2.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=0x0a0a0a:s=1440x900:d={seconds}",
            "-vf",
            "drawtext=text='AirGPT':fontcolor=white:fontsize=64:x=(w-text_w)/2:y=(h-text_h)/2-30:"
            "font=DejaVu\\\\ Sans,"
            "drawtext=text='by NETIE.AI':fontcolor=0x3dd68c:fontsize=26:"
            "x=(w-text_w)/2:y=(h-text_h)/2+40:font=DejaVu\\\\ Sans",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", str(seconds),
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _to_mp4(src: Path, dest: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(src),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
            "-movflags", "+faststart", str(dest),
        ],
        check=True,
        capture_output=True,
    )
    return dest


def _assemble(title: Path, body: Path, end: Path, out: Path) -> Path:
    lst = out.parent / "_concat_list.txt"
    parts = []
    for p in (title, body, end):
        mp4 = p if p.suffix == ".mp4" else p.with_suffix(".mp4")
        if p.suffix != ".mp4":
            _to_mp4(p, mp4)
        parts.append(mp4)
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
            "-movflags", "+faststart", str(out),
        ],
        check=True,
        capture_output=True,
    )
    lst.unlink(missing_ok=True)
    return out


def run() -> Path:
    require_demo_mock()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    OUT.mkdir(parents=True, exist_ok=True)
    work = OUT / f"_pw_{stamp}"
    work.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=["--disable-notifications", "--window-size=1440,900"],
        )
        host_ctx = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(work / "host"),
            record_video_size=VIEWPORT,
            device_scale_factor=1,
        )
        peer_ctx = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(work / "peer"),
            record_video_size=VIEWPORT,
            device_scale_factor=1,
        )
        host = host_ctx.new_page()
        peer = peer_ctx.new_page()
        host.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        peer.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        inject_demo_badge(host)
        inject_demo_badge(peer)
        set_device_name(host, "DEMO Host PC")
        set_device_name(peer, "Jordan Lee · Eng")
        safe_click(host, ["button:has-text('Got it')", "button:has-text('OK')"])
        host.keyboard.press("Escape")
        pause(host, 800)

        open_demo_session(host)
        open_demo_session(peer)
        pause(host, 900)

        # Beat 1 — host asks Netie
        type_slowly(
            host,
            "#input, textarea",
            "Sup Netie! Please prepare a slideshow for today's meeting at four",
            delay=22,
        )
        host.locator("#input").first.press("Enter")
        pause(host, 3500)

        # Beat 2 — peer walks in (interrupt)
        type_slowly(
            peer,
            "#input, textarea",
            "Hey Netie, would you mind to complete the VDML excel referencing RFQ, FCM and PO from our vendor NMD?",
            delay=22,
        )
        peer.locator("#input").first.press("Enter")
        pause(host, 4500)

        # Beat 3 — Hub demo grid + limited peer
        open_hub(host)
        pause(host, 1200)
        host.evaluate(
            """() => {
              localStorage.setItem('airgpt_hub_demo', '1');
              if (typeof renderHubPage === 'function') renderHubPage();
            }"""
        )
        pause(host, 2200)
        if not safe_click(host, [".hub-node.state-limited", "text=Jamie Ortiz", "text=Limited"]):
            host.evaluate(
                """() => {
                  const n = document.querySelector('.hub-node.state-limited, .hub-demo-cell .hub-node');
                  if (n) n.click();
                  else if (window.MP) MP.openPeerDrawer('10.10.20.19');
                }"""
            )
        pause(host, 2200)
        safe_click(host, ["button.hub-prompt-row", "text=View chat"])
        pause(host, 2500)

        # Beat 4 — mock lockdown + clear
        open_hub(host)
        pause(host, 1000)
        host.once("dialog", lambda d: d.accept())
        if not safe_click(host, ["#hubLockdownBtn", "button:has-text('Cut all AI')"]):
            host.evaluate("() => window.MP && MP.setLockdown(true)")
        pause(host, 2800)
        if not safe_click(host, ["#lockdownClearBtn", "button:has-text('Cleared')"]):
            host.evaluate("() => window.MP && MP.setLockdown(false)")
        pause(host, 2000)

        # Brand hold on chat
        open_demo_session(host)
        pause(host, 2000)

        host_ctx.close()
        peer_ctx.close()
        browser.close()

    host_vids = list((work / "host").glob("*.webm")) + list((work / "host").glob("*.mp4"))
    if not host_vids:
        raise SystemExit(f"No host video in {work}")

    raw = OUT / f"short_demo_raw_{stamp}{host_vids[0].suffix}"
    host_vids[0].replace(raw)
    print(f"WROTE_RAW {raw}")

    body_mp4 = OUT / f"short_demo_body_{stamp}.mp4"
    _to_mp4(raw, body_mp4)

    title = OUT / f"_title_{stamp}.mp4"
    end = OUT / f"_end_{stamp}.mp4"
    try:
        _title_card(title)
        _end_card(end)
        assembled = OUT / f"AirGPT_SHORT_DEMO_MOCK_{stamp}.mp4"
        _assemble(title, body_mp4, end, assembled)
    except Exception as e:
        print(f"ASSEMBLE_FALLBACK={e}")
        assembled = body_mp4

    EXPORTS.mkdir(parents=True, exist_ok=True)
    export = EXPORTS / assembled.name
    export.write_bytes(assembled.read_bytes())
    print(f"EXPORT={export}")
    print(f"SIZE_BYTES={export.stat().st_size}")

    # cleanup work + cards
    for p in (title, end):
        p.unlink(missing_ok=True)
    for leftover in work.rglob("*"):
        if leftover.is_file():
            try:
                leftover.unlink()
            except OSError:
                pass
    for d in sorted(work.rglob("*"), reverse=True):
        if d.is_dir():
            try:
                d.rmdir()
            except OSError:
                pass
    try:
        work.rmdir()
    except OSError:
        pass

    return export


if __name__ == "__main__":
    run()

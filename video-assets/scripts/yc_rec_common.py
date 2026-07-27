"""Shared helpers for YC multiplayer Playwright recorders."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8765"
VIEWPORT = {"width": 1440, "height": 900}
ROOT = Path(__file__).resolve().parents[2]
# Cloud / CI: set AIRGPT_PW_HEADLESS=1 when no display is available.
HEADLESS = os.environ.get("AIRGPT_PW_HEADLESS", "").strip() in ("1", "true", "yes")


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
            "Run start_demo_mock.bat (or set AIRGPT_DEMO_MOCK=1)."
        )
    print(f"DEMO_MOCK_OK data_dir={info.get('data_dir')} lan={info.get('ips')}")
    return info


def pause(page, ms: int = 800) -> None:
    page.wait_for_timeout(ms)


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


def set_device_name(page, name: str) -> None:
    page.evaluate(
        """(n) => {
          localStorage.setItem('clipdrop_name', n);
          window.myName = n;
        }""",
        name,
    )


def open_hub(page) -> None:
    if not safe_click(page, ["text=Hub", "button:has-text('Hub')", "a:has-text('Hub')"]):
        page.evaluate("() => { if (typeof showHubPage==='function') showHubPage(); }")
    pause(page, 1200)


def open_demo_session(page, label: str = "DEMO · Connect + Tunnel") -> None:
    if safe_click(page, [f"text={label}", f"button:has-text('{label}')"]):
        pause(page, 900)
        return
    page.evaluate(
        """() => {
          const items = [...document.querySelectorAll('.session-item,.h-title')];
          const hit = items.find(el => /DEMO/i.test(el.textContent||''));
          if (hit) hit.click();
        }"""
    )
    pause(page, 900)


def finalize_video(work: Path, out_dir: Path, prefix: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    vids = list(work.glob("*.webm")) + list(work.glob("*.mp4"))
    if not vids:
        raise SystemExit(f"No video recorded in {work}")
    dest = out_dir / f"{prefix}_{stamp}{vids[0].suffix}"
    vids[0].replace(dest)
    print(f"WROTE {dest}")
    return dest

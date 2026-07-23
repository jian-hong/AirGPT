"""Playwright: light-mode contrast + layout smoke checks for AirGPT."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parents[1] / "data" / "ui_shots"
OUT.mkdir(parents=True, exist_ok=True)


def rel_luminance(rgb: tuple[float, float, float]) -> float:
    def f(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (f(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    l1, l2 = rel_luminance(a), rel_luminance(b)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def parse_rgb(s: str) -> tuple[float, float, float] | None:
    s = (s or "").strip()
    if s.startswith("rgb"):
        nums = s[s.find("(") + 1 : s.rfind(")")].split(",")
        if len(nums) >= 3:
            return float(nums[0]), float(nums[1]), float(nums[2])
    return None


def main() -> int:
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        page.evaluate("() => { localStorage.setItem('airgpt_theme','light'); localStorage.setItem('side_collapsed','0'); }")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        page.evaluate("() => { document.body.classList.add('theme-light'); if (typeof applyTheme==='function') applyTheme('light'); }")
        page.wait_for_timeout(400)

        # Inject a sample AI block if chat empty
        page.evaluate(
            """() => {
            const chat = document.getElementById('chat');
            if (!chat) return;
            if (!chat.querySelector('.msg.ai-msg .ai-block')) {
              chat.innerHTML = `<div class="msg ai-msg"><div class="av">N</div><div class="bub"><div class="body"><div class="ai-block"><h3>1. Physics Foundation</h3><ul><li><strong>Photoelectric Effect:</strong> light frees electrons.</li><li><strong>Semiconductor Physics:</strong> silicon wells.</li></ul></div></div></div></div>`;
            }
            const app = document.querySelector('.app');
            if (app) app.classList.remove('side-collapsed');
            if (typeof syncSideForViewport === 'function') syncSideForViewport();
            if (typeof updateScrollBottomBtn === 'function') {
              const btn = document.getElementById('scrollBottomBtn');
              if (btn) { btn.hidden = false; }
            }
          }"""
        )
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUT / "light_chat.png"), full_page=False)

        checks = [
            (".msg.ai-msg .ai-block", "AI body"),
            (".msg.ai-msg .ai-block h3", "AI heading"),
            (".msg.ai-msg .ai-block strong", "AI strong"),
            (".topbar", "Topbar"),
            ("#appTitle", "Brand title"),
            (".scroll-bottom-btn", "Scroll bottom"),
            (".composer textarea, #prompt", "Composer input"),
        ]
        for sel, name in checks:
            loc = page.locator(sel).first
            if loc.count() == 0:
                results.append({"name": name, "ok": False, "detail": "missing"})
                continue
            styles = loc.evaluate(
                """el => {
                const cs = getComputedStyle(el);
                return {color: cs.color, bg: cs.backgroundColor, display: cs.display, visibility: cs.visibility};
              }"""
            )
            # walk up for non-transparent bg
            bg = parse_rgb(styles["bg"])
            if not bg or bg == (0, 0, 0) and "rgba(0, 0, 0, 0)" in styles["bg"]:
                bg_s = loc.evaluate(
                    """el => {
                    let n = el;
                    while (n) {
                      const b = getComputedStyle(n).backgroundColor;
                      if (b && b !== 'rgba(0, 0, 0, 0)' && b !== 'transparent') return b;
                      n = n.parentElement;
                    }
                    return getComputedStyle(document.body).backgroundColor;
                  }"""
                )
                bg = parse_rgb(bg_s)
            fg = parse_rgb(styles["color"])
            ratio = contrast(fg, bg) if fg and bg else 0
            ok = ratio >= 4.5
            results.append(
                {
                    "name": name,
                    "ok": ok,
                    "ratio": round(ratio, 2),
                    "fg": styles["color"],
                    "bg": str(bg),
                }
            )
            print(f"[{'OK' if ok else 'FAIL'}] {name}: contrast {ratio:.2f}:1  fg={styles['color']}")

        # Sidebar restore on wide viewport
        page.set_viewport_size({"width": 1600, "height": 900})
        page.evaluate("() => { localStorage.setItem('side_collapsed','0'); if (typeof syncSideForViewport==='function') syncSideForViewport(); }")
        page.wait_for_timeout(200)
        collapsed = page.evaluate("() => document.querySelector('.app')?.classList.contains('side-collapsed')")
        side_visible = page.evaluate(
            """() => {
            const s = document.getElementById('side');
            if (!s) return false;
            const cs = getComputedStyle(s);
            return cs.opacity !== '0' && cs.width !== '0px' && cs.display !== 'none';
          }"""
        )
        results.append({"name": "sidebar restored full page", "ok": (not collapsed) and side_visible})
        print(f"[{'OK' if (not collapsed) and side_visible else 'FAIL'}] sidebar restored full page (collapsed={collapsed}, visible={side_visible})")

        # Settings save receipt order
        page.evaluate("() => { if (typeof openSettings==='function') openSettings(); const r=document.getElementById('saveReceipt'); if(r){r.textContent='✓  Saved to D:\\\\AirGPT\\\\env.local'; r.classList.add('show');} }")
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "light_settings_receipt.png"), full_page=False)
        order_ok = page.evaluate(
            """() => {
            const box = document.querySelector('#settingsModal .settings-box');
            if (!box) return false;
            const actions = box.querySelector('.modal-actions');
            const rec = box.querySelector('#saveReceipt');
            if (!actions || !rec) return false;
            return !!(actions.compareDocumentPosition(rec) & Node.DOCUMENT_POSITION_FOLLOWING);
          }"""
        )
        results.append({"name": "Saved to below Save locally", "ok": order_ok})
        print(f"[{'OK' if order_ok else 'FAIL'}] Saved to below Save locally")

        # Receipt text inside box (no overflow left)
        receipt_box = page.evaluate(
            """() => {
            const r = document.getElementById('saveReceipt');
            if (!r) return null;
            const cs = getComputedStyle(r);
            const rect = r.getBoundingClientRect();
            return {radius: cs.borderRadius, pad: cs.padding, display: cs.display, w: rect.width, h: rect.height};
          }"""
        )
        cyl_ok = bool(receipt_box and "999px" in (receipt_box.get("radius") or "") and receipt_box.get("display") == "flex")
        results.append({"name": "Saved to cylinder pill", "ok": cyl_ok, "detail": receipt_box})
        print(f"[{'OK' if cyl_ok else 'FAIL'}] Saved to cylinder pill — {receipt_box}")

        browser.close()

    out = OUT / "light_contrast_report.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    fails = [r for r in results if not r.get("ok")]
    print(f"\nWrote {out} — {len(results)-len(fails)}/{len(results)} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

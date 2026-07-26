"""Capture OpenVault + OpenIDE UI screenshots."""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(r"D:\AirGPT\data\ui_shots")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto("http://127.0.0.1:5000/#mesh", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / "openvault_mesh.png"), full_page=False)
        for tab in ("Vault", "Local Mesh", "Deploy"):
            try:
                page.get_by_role("button", name=tab).click(timeout=2500)
                page.wait_for_timeout(500)
                name = tab.lower().replace(" ", "_")
                page.screenshot(path=str(OUT / f"openvault_{name}.png"), full_page=False)
                print("ok", tab)
            except Exception as exc:
                print("warn", tab, exc)
        page.goto("http://127.0.0.1:8765/#openide", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1000)
        page.keyboard.press("Escape")
        page.evaluate(
            """() => {
              document.querySelectorAll('.modal.open').forEach(m=>m.classList.remove('open'));
              if (typeof showOpenIDEPage==='function') showOpenIDEPage();
            }"""
        )
        page.wait_for_timeout(1400)
        page.screenshot(path=str(OUT / "openide.png"), full_page=False)
        browser.close()
    print("shots", sorted(p.name for p in OUT.glob("*.png")))


if __name__ == "__main__":
    main()

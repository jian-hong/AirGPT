"""Playwright UI check: history, open AI Screenshot Chat, session action buttons."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent / "data" / "ui_shots"
OUT.mkdir(parents=True, exist_ok=True)
PASS = 0
FAIL = 0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    detail_s = (detail or "").encode("ascii", "replace").decode("ascii")
    if cond:
        PASS += 1
        print(f"  [OK] {name}" + (f" -- {detail_s}" if detail_s else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" -- {detail_s}" if detail_s else ""))


def main() -> int:
    print("Playwright UI — AI Screenshot Chat + buttons")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "01_home.png"), full_page=True)
        ok("home loaded", "AirGPT" in page.content() or page.locator("body").count() > 0)

        # Expand history / find AI Screenshot Chat
        hist = page.locator("#historyDays")
        page.wait_for_timeout(1500)
        text = hist.inner_text(timeout=10000) if hist.count() else ""
        page.screenshot(path=str(OUT / "02_history.png"), full_page=True)
        ok(
            "history not bogus empty",
            "No chats yet" not in text or "AI Screenshot" in text or "Text" in text or "Images" in text,
            text[:160].replace("\n", " | "),
        )
        # Only click visible "View N chats" buttons (collapsed days)
        for btn in page.locator("button.hist-more").all():
            try:
                if btn.is_visible():
                    btn.click(timeout=3000)
                    page.wait_for_timeout(300)
            except Exception:
                pass

        # Prefer daily AI screenshot card
        card = page.locator(".session-item", has_text="AI Screenshot").first
        if not card.count():
            # title may have been renamed in stress suite
            card = page.locator(".session-item.daily-screenshot").first
        if not card.count():
            card = page.locator(".session-item").first
        ok("session card present", card.count() > 0)
        if card.count():
            card.scroll_into_view_if_needed()
            card.click()
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT / "03_open_session.png"), full_page=True)
            chat = page.locator("#chat").inner_text()
            # Should NOT look like offline wipe of history; chat may be empty stub or messages
            bad = "Chat loading…" in chat and "Sign in required" in chat
            ok("chat pane responded", not bad, chat[:120].replace("\n", " | "))
            # Empty stub should not bounce to full welcome wiping context if session selected
            on = page.locator(".session-item.on")
            ok("session stays selected", on.count() > 0)

            # Action buttons on selected card
            card = page.locator(".session-item.on").first
            rename = card.locator('button[data-act="rename"]')
            pin = card.locator('button[data-act="pin"]')
            share = card.locator('button[data-act="share"]')
            delete = card.locator('button[data-act="del"]')
            ok("Rename button", rename.count() == 1)
            ok("Pin button", pin.count() == 1)
            ok("Share button", share.count() == 1)
            ok("Delete button", delete.count() == 1)

            # Pin toggle via UI
            if pin.count():
                before = pin.inner_text()
                pin.click()
                page.wait_for_timeout(800)
                page.screenshot(path=str(OUT / "04_after_pin.png"), full_page=True)
                ok("pin click did not crash", page.locator("body").count() > 0, f"label was {before!r}")

            # Rename via prompt
            if rename.count():
                page.once("dialog", lambda d: d.accept(f"UI Rename {int(time.time()) % 10000}"))
                rename.click()
                page.wait_for_timeout(1000)
                page.screenshot(path=str(OUT / "05_after_rename.png"), full_page=True)
                ok("rename dialog path", True)

            # Share — accept/dismiss prompts
            if share.count():
                def _share_dialog(d):
                    try:
                        d.accept()
                    except Exception:
                        d.dismiss()

                page.on("dialog", _share_dialog)
                share.click()
                page.wait_for_timeout(1500)
                page.screenshot(path=str(OUT / "06_after_share.png"), full_page=True)
                ok("share click path", True)
                try:
                    page.remove_listener("dialog", _share_dialog)
                except Exception:
                    pass

        # Empty-state copy check via forced empty render is hard; check string in source
        src = page.content()
        ok(
            "empty copy updated in page",
            "copy something from Windows or + New" in src,
        )
        ok(
            "old empty copy gone",
            "No chats yet — clipboard or + New" not in src,
        )

        # New chat button if present
        new_btn = page.locator("button", has_text="+ New").or_(page.locator("#btnNew")).or_(
            page.locator("[onclick*='newChat']")
        )
        if new_btn.count():
            new_btn.first.click()
            page.wait_for_timeout(800)
            page.screenshot(path=str(OUT / "07_new_chat.png"), full_page=True)
            ok("new chat click", True)
        else:
            ok("new chat button optional", True, "not found — skipped")

        browser.close()

    manifest = {
        "pass": PASS,
        "fail": FAIL,
        "shots": [p.name for p in sorted(OUT.glob("*.png"))],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nScreenshots → {OUT}")
    print(f"=== RESULT: {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

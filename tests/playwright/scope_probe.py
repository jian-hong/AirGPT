import os

from playwright.sync_api import sync_playwright

BASE = (os.environ.get("AIRGPT_BASE") or "http://127.0.0.1:8765").rstrip("/")

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE, timeout=20000)
    pg.wait_for_timeout(3000)
    print("window.openSession:", pg.evaluate("() => typeof window.openSession"))
    print("window.appReady:", pg.evaluate("() => window.appReady"))
    print("chats btn count:", pg.locator("#navChats").count())
    print("agents label:", pg.locator("#navLabelAgents").inner_text())
    print("errors:", errors)
    b.close()

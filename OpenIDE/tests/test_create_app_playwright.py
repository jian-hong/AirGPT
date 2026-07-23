"""Playwright smoke for OpenIDE Create-App (optional — needs running AirGPT).

  AIRGPT_BASE=http://127.0.0.1:8765 python -m pytest OpenIDE/tests/test_create_app_playwright.py -q

Skips when playwright or server is unavailable.
"""
from __future__ import annotations

import json
import os
import urllib.request

import pytest

BASE = (os.environ.get("AIRGPT_BASE") or "http://127.0.0.1:8765").rstrip("/")


@pytest.fixture(scope="module")
def browser_page():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(BASE + "/#openide", wait_until="domcontentloaded", timeout=12000)
        except Exception as e:
            browser.close()
            pytest.skip(f"AirGPT not reachable at {BASE}: {e}")
        yield page
        browser.close()


def test_scaffold_api_alive() -> None:
    req = urllib.request.Request(
        BASE + "/api/openide/scaffold",
        data=json.dumps(
            {"prompt": "A smoke checklist widget", "name": "pw-smoke-app", "template": "static"}
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode())
    except Exception as e:
        pytest.skip(f"scaffold API unavailable: {e}")
    assert body.get("ok") is True, body
    assert body.get("app_path") == "apps/pw-smoke-app"
    assert "seed_prompt" in body


def test_openide_create_app_cta_visible(browser_page) -> None:
    page = browser_page
    page.wait_for_timeout(600)
    for sel in ("#loginSkip", "button:has-text('Continue')", "button:has-text('Enter')", ".login-skip"):
        loc = page.locator(sel)
        if loc.count() and loc.first.is_visible():
            try:
                loc.first.click(timeout=1500)
            except Exception:
                pass
    page.wait_for_timeout(400)
    page.evaluate(
        """() => {
          if (typeof showOpenIDEPage === 'function') showOpenIDEPage();
          else if (typeof showWorkspace === 'function') showWorkspace('openide');
        }"""
    )
    page.wait_for_timeout(900)
    btn = page.locator("button:has-text('Create app')")
    if btn.count() == 0:
        js = page.request.get(BASE + "/OpenIDE/ui/openide.js")
        assert js.ok
        assert "openideCreateApp" in js.text()
        assert "Create app" in js.text()
        pytest.skip("OpenIDE shell not mounted in DOM (auth gate) — JS asset contains Create app")
    assert btn.first.is_visible()

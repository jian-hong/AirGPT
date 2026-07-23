"""Shared fixtures for the AirGPT 'sense and feel' Playwright suite.

Artifacts (screenshots / videos / traces) are written by pytest-playwright's
built-in CLI flags (--screenshot, --video, --output) — see README.md in this
folder or video-assets/00-handoff/DEBUG_STACK.md for the exact invocation.

This file adds:
  * a fixed 1440x900 desktop viewport (matches the existing recorder scripts)
  * a `watch` fixture that records uncaught page errors + console errors so
    tests can assert "no JS exceptions happened while I did X"
  * a small HTML failure snapshot (full DOM dump) next to the screenshot,
    useful for diagnosing "sense and feel" bugs where the screenshot alone
    doesn't show *why* (e.g. duplicated DOM nodes, stuck classes).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEBUG_DIR = REPO_ROOT / "video-assets" / "03-demo-clips" / "_debug"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "viewport": {"width": 1440, "height": 900},
        "device_scale_factor": 1,
    }


@pytest.fixture
def watch(page):
    """Collects uncaught JS exceptions + console.error lines during a test."""
    state = {"page_errors": [], "console_errors": []}

    def on_page_error(exc):
        state["page_errors"].append(str(exc))

    def on_console(msg):
        if msg.type == "error":
            state["console_errors"].append(msg.text)

    page.on("pageerror", on_page_error)
    page.on("console", on_console)
    yield state


@pytest.fixture(autouse=True)
def _dump_dom_on_failure(request, page):
    """Extra artifact: full DOM snapshot next to the pytest-playwright screenshot.

    pytest-playwright already saves a screenshot + video on failure when run
    with --screenshot=only-on-failure --video=retain-on-failure. We piggyback
    on the same naming scheme so files are easy to correlate.
    """
    yield
    rep = getattr(request.node, "_report_outcome", None)
    if rep != "failed":
        return
    try:
        safe_name = request.node.name.replace(os.sep, "_").replace("/", "_")
        out = DEBUG_DIR / f"{safe_name}_DOM.html"
        out.write_text(page.content(), encoding="utf-8")
    except Exception:
        pass


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call":
        item._report_outcome = "failed" if rep.failed else "passed"

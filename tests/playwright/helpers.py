"""Small helpers shared across the AirGPT Playwright 'sense and feel' tests.

Deliberately dependency-light: no extra HTTP client, we reuse Playwright's
own `page.request` (APIRequestContext) for read-only API calls used to pick
realistic test fixtures (existing sessions) out of the live SQLite-backed
server, instead of hard-coding session ids that will rot.
"""
from __future__ import annotations

import time
from typing import Any


def wait_for_boot(page, timeout: int = 20000) -> None:
    """Wait for bootApp() to finish its first paint of chat + sidebar."""
    page.wait_for_selector("#chat", timeout=timeout)
    page.wait_for_function(
        "() => { const c = document.getElementById('chat'); "
        "return !!c && !c.textContent.includes('Loading chat'); }",
        timeout=timeout,
    )
    page.wait_for_selector("#historyDays", timeout=timeout)
    page.wait_for_function(
        "() => { const h = document.getElementById('historyDays'); "
        "return !!h && !h.textContent.includes('Loading'); }",
        timeout=timeout,
    )


def get_sessions(page, base_url: str, min_messages: int = 0, limit: int = 25) -> list[dict[str, Any]]:
    resp = page.request.get(f"{base_url}/api/sessions")
    data = resp.json()
    sessions = data.get("sessions", []) or []
    if min_messages:
        sessions = [s for s in sessions if (s.get("msg_count") or 0) >= min_messages]
    sessions.sort(key=lambda s: s.get("updated_at") or 0, reverse=True)
    return sessions[:limit]


def expand_all_history_groups(page, max_rounds: int = 6) -> None:
    """The sidebar groups sessions by day/project and collapses older groups.
    Click every collapsed group header so any session-item can be located."""
    for _ in range(max_rounds):
        headers = page.locator("#historyDays .hist-day:not(.open) .hist-day-hdr")
        n = headers.count()
        if n == 0:
            return
        for i in range(n):
            try:
                headers.nth(i).click(timeout=1000)
            except Exception:
                pass
        page.wait_for_timeout(120)


def open_session_via_sidebar(page, sid: int, timeout: int = 10000) -> None:
    """Click a chat in the left sidebar the way a real user would."""
    nav = page.locator("#navChats")
    cls = nav.get_attribute("class") or ""
    if "on" not in cls:
        nav.click()
        page.wait_for_timeout(150)

    sel = f'.session-item[data-sid="{sid}"]'
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        if page.locator(sel).count() > 0:
            break
        expand_all_history_groups(page)
        page.wait_for_timeout(150)
    page.wait_for_selector(sel, timeout=3000)
    page.locator(sel).first.click()


def chat_scroll_state(page) -> dict | None:
    return page.evaluate(
        "() => { const el = document.getElementById('chat'); if (!el) return null; "
        "return {scrollTop: el.scrollTop, scrollHeight: el.scrollHeight, clientHeight: el.clientHeight}; }"
    )


def is_chat_near_bottom(page, margin: int = 48) -> bool:
    s = chat_scroll_state(page)
    if not s:
        return True
    return (s["scrollHeight"] - s["scrollTop"] - s["clientHeight"]) < margin


def wait_chat_settled(page, timeout: int = 8000) -> None:
    """Wait until #chat has painted real content (messages or an explicit
    empty state) — i.e. not stuck on the transient 'Loading chat…' spinner."""
    page.wait_for_function(
        "() => { const c = document.getElementById('chat'); "
        "return !!c && !c.textContent.trim().startsWith('Loading chat'); }",
        timeout=timeout,
    )


def current_session_id(page) -> int:
    # `currentSession` is a top-level `let` in index.html's inline script, so
    # it lives in the page's global lexical scope, NOT on `window`.
    return page.evaluate("() => (typeof currentSession !== 'undefined') ? (currentSession || 0) : 0")


def ls_session_id(page) -> str:
    return page.evaluate("() => localStorage.getItem('clipdrop_session')")


def count_duplicate_ids(page) -> list[str]:
    """Return any element ids that appear more than once in the DOM — a
    reliable 'something didn't clean up after itself' smell for an app that
    leans on getElementById for its live chat/stream bubbles."""
    return page.evaluate(
        """() => {
            const seen = {};
            document.querySelectorAll('[id]').forEach(el => {
                seen[el.id] = (seen[el.id]||0) + 1;
            });
            return Object.entries(seen).filter(([,c]) => c > 1).map(([id]) => id);
        }"""
    )

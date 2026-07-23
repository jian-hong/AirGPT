"""#2 — Open chat -> must land at bottom (latest message).

renderChat()/scrollChatIfPinned() are supposed to snap #chat to
scrollHeight on first paint of a session. This test opens a handful of
chats that have enough history to actually scroll, and asserts we land
within a small margin of the bottom every time — and that the floating
'scroll to bottom' pill stays hidden (it's only meant to show once the
user has scrolled *up*).
"""
from __future__ import annotations

from helpers import (
    chat_scroll_state,
    expand_all_history_groups,
    get_sessions,
    is_chat_near_bottom,
    open_session_via_sidebar,
    wait_chat_settled,
    wait_for_boot,
)


def test_open_chat_lands_at_bottom(page, base_url, watch):
    page.goto(base_url)
    wait_for_boot(page)

    sessions = get_sessions(page, base_url, min_messages=4, limit=5)
    assert sessions, "Need a chat with several messages to verify bottom-anchoring"

    for target in sessions:
        expand_all_history_groups(page)
        open_session_via_sidebar(page, target["id"])
        wait_chat_settled(page)
        page.wait_for_timeout(500)  # smooth-scroll behavior:'smooth' settle time

        assert is_chat_near_bottom(page, margin=60), (
            f"Chat {target['id']} did not land at the bottom after opening "
            f"(scroll state: {chat_scroll_state(page)})"
        )
        assert page.locator("#scrollBottomBtn").is_hidden(), (
            f"'Scroll to bottom' pill is visible right after opening chat {target['id']} — "
            "implies we did NOT actually land at the bottom"
        )

    assert watch["page_errors"] == []

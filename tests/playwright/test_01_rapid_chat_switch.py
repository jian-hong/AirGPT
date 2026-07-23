"""#1 — Rapid chat switch: no full reset / white flash / lost scroll.

Clicks through several existing chats in the sidebar much faster than a
human would comfortably do, then checks that the UI settled on the chat
that was actually clicked last (no stale-async-response race), that no
DOM nodes were duplicated/leaked (id collisions), and that the chat pane
never ends up completely blank.
"""
from __future__ import annotations

from helpers import (
    count_duplicate_ids,
    current_session_id,
    expand_all_history_groups,
    get_sessions,
    open_session_via_sidebar,
    wait_chat_settled,
    wait_for_boot,
)


def test_rapid_chat_switch_settles_on_last_click(page, base_url, watch):
    page.goto(base_url)
    wait_for_boot(page)

    sessions = get_sessions(page, base_url, min_messages=1, limit=6)
    assert len(sessions) >= 3, "Need >= 3 existing chats with messages to stress-switch between"
    ids = [s["id"] for s in sessions[:4]]

    expand_all_history_groups(page)

    # Deliberately short pauses (well under the ~0.28s chat-page-enter
    # animation) to mimic a user impatiently clicking through history.
    sequence = ids + list(reversed(ids)) + ids[:2]
    for sid in sequence:
        open_session_via_sidebar(page, sid, timeout=4000)
        page.wait_for_timeout(80)

    wait_chat_settled(page)
    page.wait_for_timeout(400)

    final_id = sequence[-1]
    got = current_session_id(page)
    assert got == final_id, (
        f"currentSession is {got} but the last click was on chat {final_id} — "
        "a slower, stale openSession()/pullChat() response likely won a race "
        "and clobbered the UI after navigation had already moved on"
    )


def test_rapid_chat_switch_no_leaked_dom_or_blank_pane(page, base_url, watch):
    page.goto(base_url)
    wait_for_boot(page)

    sessions = get_sessions(page, base_url, min_messages=1, limit=6)
    assert len(sessions) >= 3, "Need >= 3 existing chats with messages to stress-switch between"
    ids = [s["id"] for s in sessions[:4]]
    expand_all_history_groups(page)

    for sid in ids * 3:
        open_session_via_sidebar(page, sid, timeout=4000)
        page.wait_for_timeout(70)

    wait_chat_settled(page)
    page.wait_for_timeout(400)

    dupes = count_duplicate_ids(page)
    assert not dupes, f"Duplicate DOM ids after rapid switching (leaked nodes): {dupes}"

    chat_html = page.locator("#chat").inner_html()
    assert chat_html.strip(), "Chat pane is completely blank after rapid switching (white-flash / full reset)"

    assert watch["page_errors"] == [], f"Uncaught JS errors during rapid switching: {watch['page_errors']}"

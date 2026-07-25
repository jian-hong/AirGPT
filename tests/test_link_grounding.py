"""A blocked link must never become an invented biography.

Regression: asking about a LinkedIn profile plus a company site produced
confident, contradictory biographical claims (different degrees, employers,
and two different descriptions of the same company). LinkedIn serves a bot
check that is long enough to pass a length test, so it was handed to the model
as if it were the page, and the model filled the gap from memory.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ai_engine as ae


WALLS = [
    "Checking your browser before accessing linkedin.com ... please wait",
    "Attention Required! | Cloudflare. Please enable cookies to continue.",
    "Sign in to continue to LinkedIn",
    "Verify you are a human by completing the CAPTCHA below",
    "Unusual traffic from your computer network",
]

REAL_PAGES = [
    "Netie is an encrypted AI platform for enterprise. Automate sales and marketing, "
    "monitor projects and operations, and deliver intelligence with one click.",
    "Jian Hong is a founder working on analog design and AI systems in Malaysia.",
    "This page documents the slew rate test setup for the RS622XK operational amplifier.",
]


@pytest.mark.parametrize("text", WALLS)
def test_access_walls_detected(text):
    assert ae._looks_like_access_wall(text) is True


@pytest.mark.parametrize("text", REAL_PAGES)
def test_real_content_not_flagged(text):
    assert ae._looks_like_access_wall(text) is False


def test_blocked_link_yields_do_not_describe_instruction(monkeypatch):
    """A walled page must produce an explicit 'could not read' line, not an excerpt."""
    wall = "Checking your browser before accessing linkedin.com " + ("x " * 100)

    class _Resp:
        headers = {"Content-Type": "text/html"}

        def read(self, *a):
            return f"<html><body>{wall}</body></html>".encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ae.urllib.request, "urlopen", lambda *a, **k: _Resp())
    block = ae._fetch_url_evidence(["https://linkedin.com/in/someone"])
    assert "blocked by a login or bot check" in block
    assert "do not describe the person" in block
    # The wall text itself must not be presented as page content.
    assert "Excerpt:" not in block


def test_readable_page_is_still_quoted(monkeypatch):
    body = (
        "Netie is an encrypted AI platform for enterprise. "
        "Automate sales and marketing, monitor projects and operations. " * 3
    )

    class _Resp:
        headers = {"Content-Type": "text/html"}

        def read(self, *a):
            return f"<html><head><title>Netie.AI</title></head><body>{body}</body></html>".encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ae.urllib.request, "urlopen", lambda *a, **k: _Resp())
    block = ae._fetch_url_evidence(["http://netie.ai/"])
    assert "Excerpt:" in block
    assert "encrypted AI platform" in block
    assert "blocked by a login or bot check" not in block


def test_truthfulness_rule_is_in_the_chat_template():
    tpl = ae.TEXT_CHAT_TEMPLATE
    assert "Truthfulness (non-negotiable)" in tpl
    assert "Never invent biographical facts about real people" in tpl

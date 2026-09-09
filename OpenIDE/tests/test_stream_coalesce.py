"""S5: consecutive tokens merge; a tool_call flushes the buffer."""

from OpenIDE.stream_coalesce import TokenBuffer, coalesce_tokens


def test_consecutive_tokens_merge() -> None:
    events = [
        {"type": "token", "text": "Hel"},
        {"type": "token", "text": "lo"},
        {"type": "done", "analysis": "ok"},
    ]
    out = list(coalesce_tokens(events))
    assert out == [
        {"type": "token", "text": "Hello"},
        {"type": "done", "analysis": "ok"},
    ]


def test_tool_call_flushes_tokens() -> None:
    events = [
        {"type": "token", "text": "a"},
        {"type": "tool_call", "name": "fs_read"},
        {"type": "token", "text": "b"},
        {"type": "token", "text": "c"},
    ]
    out = list(coalesce_tokens(events))
    assert out == [
        {"type": "token", "text": "a"},
        {"type": "tool_call", "name": "fs_read"},
        {"type": "token", "text": "bc"},
    ]


def test_max_chars_flushes_mid_stream() -> None:
    buf = TokenBuffer(max_chars=4)
    assert buf.feed({"type": "token", "text": "abcd"}) == [{"type": "token", "text": "abcd"}]
    assert buf.feed({"type": "token", "text": "xy"}) == []
    assert buf.flush() == [{"type": "token", "text": "xy"}]

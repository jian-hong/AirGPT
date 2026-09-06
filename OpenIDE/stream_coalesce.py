"""Token / tool-loop timing coalescing for OpenIDE agent streams.

Cursor SDK and SSE can emit many tiny `token` events. Painting each one stalls
the UI. Merge consecutive tokens; flush on any other event type (tool_call,
thinking, done, error).
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

Event = dict[str, Any]


def coalesce_tokens(
    events: Iterator[Mapping[str, Any]] | list[Mapping[str, Any]],
    *,
    max_chars: int = 400,
) -> Iterator[Event]:
    """Merge consecutive token events. Non-token events flush the buffer first."""
    buf = TokenBuffer(max_chars=max_chars)
    for ev in events:
        yield from buf.feed(dict(ev))
    yield from buf.flush()


class TokenBuffer:
    """Streaming coalescer. `feed` returns zero or more events to yield now."""

    def __init__(self, *, max_chars: int = 400) -> None:
        self.max_chars = max(1, int(max_chars))
        self._parts: list[str] = []
        self._n = 0

    def feed(self, ev: Mapping[str, Any]) -> list[Event]:
        if ev.get("type") == "token":
            text = str(ev.get("text") or "")
            if not text:
                return []
            self._parts.append(text)
            self._n += len(text)
            if self._n >= self.max_chars:
                return self.flush()
            return []
        out = self.flush()
        out.append(dict(ev))
        return out

    def flush(self) -> list[Event]:
        if not self._parts:
            return []
        text = "".join(self._parts)
        self._parts = []
        self._n = 0
        return [{"type": "token", "text": text}]

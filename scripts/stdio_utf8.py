"""Make stdout/stderr carry non-ASCII on Windows consoles.

`tests/RAG/reasoning_chain_live.py` already imported `ensure_utf8_stdio` from
here inside a `try/except Exception: pass`. The module did not exist in this
repo - it lives in Netie-KB - so the import failed on every run and the except
swallowed it. The guard read as protection and did nothing (R-0011).

It shows up the moment a bench prints a real corpus: a U+2014 in a fixture
header came back as `?` from `oracle_bench.py`, which looks exactly like data
corruption and is not. Under any multilingual corpus every non-Latin answer
would be unreadable in the output, and the bench would be blamed for it.

`PYTHONUTF8=1` fixes this too but only when the caller remembers to set it, so
this does not rely on it (R-0012).
"""
from __future__ import annotations

import sys


def ensure_utf8_stdio() -> bool:
    """Reconfigure stdout/stderr to UTF-8. True if both are UTF-8 afterwards.

    Returns a value rather than staying silent so a caller that cares can say
    out loud that its output may be lossy, instead of printing mojibake and
    letting the reader decide whether the data or the terminal is broken.
    """
    ok = True
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if enc in ("utf8", "utf8mb4"):
            continue
        try:
            # Python 3.7+. errors="replace" so a stray unencodable byte degrades
            # one character instead of killing a long benchmark run at 90%.
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            ok = False
    return ok


if __name__ == "__main__":
    print("utf8:", ensure_utf8_stdio())
    print("sample: em dash — cjk 中文 arabic العربية")

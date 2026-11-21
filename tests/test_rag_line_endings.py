"""A file saved with Windows line endings is read exactly like the same file saved on Linux.

The Windows CI wrote the multilingual bench's files in text mode (so every line ended in
CRLF) and refused 5 Japanese name questions where Linux refused 3: only the source hash
folded CRLF, while the text handed to the chunker kept every carriage return, so chunk
edges and word pieces differed by platform. Real users on Windows upload CRLF files.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag import ingest  # noqa: E402

TEXT = (
    "# Register\n\n"
    "The retention period for the Halvorsen account is ZQ-4471.\n"
    "The Halvorsen account is headquartered in Tromso.\n\n"
    "## Notes\n\n"
    "ハルヴォルセン口座の保存期間は ZQ-4471 です。\n"
)
CSV = "account,attribute,value\nHalvorsen,retention period,ZQ-4471\n\"Multi\nline\",note,\"a\nb\"\n"


@pytest.mark.parametrize(
    "name, body",
    [("register.md", TEXT), ("register.txt", TEXT), ("register.html", "<h1>R</h1>\n<p>" + TEXT + "</p>\n"),
     ("register.csv", CSV), ("server.log", "2026-01-01 INFO start\n2026-01-01 WARN slow\n")],
)
def test_windows_and_old_mac_line_endings_read_like_unix(tmp_path, name, body):
    # Same file name in three folders: a sheet is named after its file.
    for sub in ("unix", "windows", "mac"):
        (tmp_path / sub).mkdir()
    unix = tmp_path / "unix" / name
    unix.write_bytes(body.encode("utf-8"))
    windows = tmp_path / "windows" / name
    windows.write_bytes(body.replace("\n", "\r\n").encode("utf-8"))
    old_mac = tmp_path / "mac" / name
    old_mac.write_bytes(body.replace("\n", "\r").encode("utf-8"))

    text_unix, digest_unix = ingest.read_text_file(unix)
    for other in (windows, old_mac):
        text, digest = ingest.read_text_file(other)
        where = other.parent.name
        assert "\r" not in text, f"{where} {name}: a carriage return reached the chunker"
        assert text == text_unix, f"{where} {name} is read differently from the Unix file"
        assert digest == digest_unix, f"{where} {name} hashes differently from the Unix file"

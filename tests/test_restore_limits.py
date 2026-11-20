"""Restore refuses a wrong-table database, a zip bomb and a very long path, and changes nothing.

Run on any disk. Sizes are small: the cap is lowered for the test, the code path is the same.
"""
from __future__ import annotations

import io
import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402


def _zip(files: dict, compress=False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED) as z:
        for n, b in files.items():
            z.writestr(n, b)
    return buf.getvalue()


def _db(path: Path, tables) -> bytes:
    con = sqlite3.connect(path)
    for t in tables:
        con.execute(f"create table {t}(a)")
    con.commit()
    con.close()
    b = path.read_bytes()
    path.unlink()
    return b


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dd = Path(self.tmp.name) / "data"
        self.dd.mkdir()
        self.scratch = Path(self.tmp.name)
        self._old = clipdrop.DATA_DIR
        clipdrop.DATA_DIR = self.dd
        (self.dd / "notes.txt").write_text("keep")

    def tearDown(self):
        clipdrop.DATA_DIR = self._old
        self.tmp.cleanup()

    def files(self):
        return {str(p.relative_to(self.dd)).replace("\\", "/"): p.read_bytes()
                for p in self.dd.rglob("*") if p.is_file() and not p.name.startswith("pre-restore-")}

    def refuse(self, blob, word=None):
        before = self.files()
        code, out = clipdrop._restore_package(blob)
        self.assertEqual(code, 400, out)
        self.assertEqual(self.files(), before)
        self.assertFalse([p for p in self.dd.rglob("*.restoring")])
        if word:
            self.assertIn(word, out["error"])
        return out


class WrongTables(Base):
    def test_valid_sqlite_with_wrong_tables_is_refused(self):
        self.refuse(_zip({"data/clipdrop.db": _db(self.scratch / "a.db", ["x"])}), "messages")

    def test_corrupt_and_empty_are_refused(self):
        self.refuse(_zip({"data/clipdrop.db": b"SQLite format 3\x00" + b"\xff" * 5000}))
        self.refuse(_zip({"data/clipdrop.db": b""}))

    def test_other_databases_are_checked(self):
        self.refuse(_zip({"data/agents.db": _db(self.scratch / "b.db", ["x"])}), "agents")
        self.refuse(_zip({"data/rag/rag.db": _db(self.scratch / "c.db", ["x"])}), "knowledge_spaces")

    def test_a_real_database_still_restores(self):
        good = _db(self.scratch / "d.db", ["messages", "devices", "chat_sessions", "seen_hashes"])
        code, out = clipdrop._restore_package(_zip({"data/clipdrop.db": good, "data/rag/rag.db": _db(self.scratch / "e.db", ["knowledge_spaces", "sources", "chunks"])}))
        self.assertEqual(code, 200, out)
        self.assertEqual((self.dd / "clipdrop.db").read_bytes(), good)


class SizeCap(Base):
    def setUp(self):
        super().setUp()
        self._cap = clipdrop._RESTORE_MIN_CAP
        clipdrop._RESTORE_MIN_CAP = 100_000  # stands in for 1 GiB

    def tearDown(self):
        clipdrop._RESTORE_MIN_CAP = self._cap
        super().tearDown()

    def test_bomb_is_refused_at_every_ratio(self):
        for size in (200_000, 1_000_000, 50_000_000):
            self.refuse(_zip({"data/big.bin": b"\0" * size}, compress=True), "far more")

    def test_a_lying_header_is_caught_while_copying(self):
        blob = bytearray(_zip({"data/big.bin": b"\0" * 400_000}, compress=True))
        # Rewrite the declared size to 10 bytes in both headers, as a doctored zip would.
        import struct
        for sig, off in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):
            i = bytes(blob).find(sig)
            struct.pack_into("<I", blob, i + off, 10)
        before = self.files()
        code, out = clipdrop._restore_package(bytes(blob))
        self.assertIn(code, (400, 500), out)
        self.assertEqual(self.files(), before)

    def test_a_normal_backup_under_the_cap_restores(self):
        code, out = clipdrop._restore_package(_zip({"data/ok.bin": b"x" * 50_000}))
        self.assertEqual(code, 200, out)


class LongPath(Base):
    def test_long_path_is_a_plain_400(self):
        self.refuse(_zip({"data/" + "a" * 4100: "x", "data/ok.txt": "y"}), "too long")
        self.refuse(_zip({"data/" + "/".join(["d" * 200] * 25) + "/f": "x"}), "too long")
        self.refuse(_zip({"data/" + "a" * 300: "x"}), "too long")


if __name__ == "__main__":
    unittest.main()

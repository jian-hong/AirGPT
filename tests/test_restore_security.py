"""Restore findings: security-control files, Windows aliases, all-or-nothing.

Run on any disk: names are compared with os.listdir and JSON text is compared as text.
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


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in files.items():
            z.writestr(n, b)
    return buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dd = Path(self.tmp.name) / "elsewhere"
        self.dd.mkdir()
        self._old = clipdrop.DATA_DIR
        clipdrop.DATA_DIR = self.dd

    def tearDown(self):
        clipdrop.DATA_DIR = self._old
        self.tmp.cleanup()

    def listing(self):
        return sorted(str(p.relative_to(self.dd)).replace("\\", "/") for p in self.dd.rglob("*"))


class SecurityControlFiles(Base):
    FILES = ["openvault.local.json", "access_policy.json", "cortex_settings.json", "network.json",
             "admin_state.json", "host_routines.json", "audit.jsonl", "openvault_connect_pack.json"]

    def test_doctored_control_files_are_skipped_with_a_reason(self):
        for n in self.FILES:
            (self.dd / n).write_text("ORIGINAL")
        blob = _zip({**{"data/" + n: "EVIL" for n in self.FILES}, "data/notes.txt": "fine"})
        code, out = clipdrop._restore_package(blob)
        self.assertEqual(code, 200, out)
        for n in self.FILES:
            self.assertEqual((self.dd / n).read_text(), "ORIGINAL", n)
        self.assertEqual((self.dd / "notes.txt").read_text(), "fine")
        skipped = {s["file"]: s["why"] for s in out["skipped"]}
        for n in self.FILES:
            self.assertIn("data/" + n, skipped)
            self.assertTrue(skipped["data/" + n])
        self.assertEqual(out["restored"], 1)

    def test_a_real_backup_round_trips(self):
        (self.dd / "clipdrop.db").write_bytes(b"")
        con = sqlite3.connect(self.dd / "clipdrop.db")
        con.execute("create table t(a)")
        con.execute("insert into t values (1)")
        con.commit()
        con.close()
        (self.dd / "files").mkdir()
        (self.dd / "files" / "a.txt").write_text("A")
        (self.dd / "rag").mkdir()
        (self.dd / "rag" / "x.json").write_text("{}")
        (self.dd / "workspace.json").write_text("PASS")
        blob = clipdrop._export_package()
        (self.dd / "files" / "a.txt").write_text("CHANGED")
        (self.dd / "files" / "later.txt").write_text("later")
        code, out = clipdrop._restore_package(blob)
        self.assertEqual(code, 200, out)
        self.assertEqual((self.dd / "files" / "a.txt").read_text(), "A")
        self.assertEqual((self.dd / "rag" / "x.json").read_text(), "{}")
        self.assertEqual((self.dd / "workspace.json").read_text(), "PASS")
        con = sqlite3.connect(self.dd / "clipdrop.db")
        self.assertEqual(con.execute("select a from t").fetchall(), [(1,)])
        con.close()


class WindowsAliases(Base):
    NAMES = ["data/WORKSP~1.JSO", "data/AUTH_T~1.JSO", "data/CON", "data/con.txt", "data/PRN", "data/AUX.json",
             "data/NUL", "data/COM1", "data/com9.log", "data/LPT1", "data/lpt9.txt", "data/sub/NUL.x",
             "data/. ", "data/...", "data/ /x", "data/a.", "data/a ", "data/sub./x",
             "data/..%2fworkspace.json", "data/..%2Fworkspace.json", "data/%2e%2e%5cworkspace.json",
             "data/a<b", "data/a|b", "data/a?b", "data/a*b", 'data/a"b', "data/x\x01y"]

    def test_every_alias_is_skipped(self):
        for n in ("workspace.json", "auth_tokens.json"):
            (self.dd / n).write_text("ORIGINAL")
        blob = _zip({**{n: "EVIL" for n in self.NAMES}, "data/ok.txt": "fine", "data/sub/ok2.txt": "fine2"})
        code, out = clipdrop._restore_package(blob)
        self.assertEqual(code, 200, out)
        skipped = {s["file"]: s["why"] for s in out["skipped"]}
        for n in self.NAMES:
            self.assertIn(n, skipped, n)
        self.assertEqual(out["restored"], 2)
        self.assertEqual(sorted(os.listdir(self.dd)), sorted(["workspace.json", "auth_tokens.json", "ok.txt", "sub",
                                                              out["safety_copy"].replace("\\", "/").split("/")[-1]]))
        self.assertEqual((self.dd / "workspace.json").read_text(), "ORIGINAL")


class AllOrNothing(Base):
    def _snapshot(self):
        return {p: (self.dd / p).read_bytes() for p in self.listing() if (self.dd / p).is_file() and not p.startswith("pre-restore-")}

    def test_file_and_folder_with_the_same_name_changes_nothing(self):
        (self.dd / "a_first.txt").write_text("keep")
        before = self._snapshot()
        blob = _zip({"data/a_first.txt": "new", "data/clipdrop.db": "not a database", "data/zz": "file", "data/zz/inner": "x"})
        code, out = clipdrop._restore_package(blob)
        self.assertIn(code, (400, 500))
        self.assertTrue(out.get("error"))
        self.assertEqual(self._snapshot(), before)
        self.assertEqual([p for p in self.listing() if p.endswith(".restoring")], [])
        self.assertFalse((self.dd / "zz").exists())

    def test_a_junk_database_changes_nothing_and_names_the_safety_copy(self):
        (self.dd / "a_first.txt").write_text("keep")
        con = sqlite3.connect(self.dd / "clipdrop.db")
        con.execute("create table t(a)")
        con.commit()
        con.close()
        before = self._snapshot()
        code, out = clipdrop._restore_package(_zip({"data/a_first.txt": "new", "data/clipdrop.db": "not a database"}))
        self.assertEqual(code, 400, out)
        self.assertIn("database", out["error"])
        self.assertEqual(self._snapshot(), before)
        self.assertEqual([p for p in self.listing() if p.endswith(".restoring")], [])
        if out.get("safety_copy"):
            self.assertIn(out["safety_copy"], out["error"])

    def test_a_failure_while_swapping_rolls_everything_back(self):
        (self.dd / "a.txt").write_text("old-a")
        (self.dd / "b.txt").write_text("old-b")
        before = self._snapshot()
        calls = {"n": 0}
        real = clipdrop.app_auth._swap

        def flaky(tmp, target):
            calls["n"] += 1
            if calls["n"] == 3:
                raise PermissionError("locked")
            return real(tmp, target)
        clipdrop.app_auth._swap = flaky
        try:
            code, out = clipdrop._restore_package(_zip({"data/a.txt": "new-a", "data/b.txt": "new-b", "data/sub/c.txt": "new-c"}))
        finally:
            clipdrop.app_auth._swap = real
        self.assertEqual(code, 500, out)
        self.assertIn(out["safety_copy"], out["error"])
        self.assertEqual(self._snapshot(), before)
        self.assertEqual([p for p in self.listing() if p.endswith(".restoring")], [])
        self.assertFalse((self.dd / "sub").exists())


if __name__ == "__main__":
    unittest.main()

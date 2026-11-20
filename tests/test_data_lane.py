"""Backups leak nothing, a restore loses nothing, a deleted chat is really gone.

Each class replays one audit finding (data-integrity.0 to .6) and pins the normal path.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import auth  # noqa: E402
import clipdrop  # noqa: E402
import db  # noqa: E402
import memory_index  # noqa: E402
import vault  # noqa: E402
from config import DATA_DIR  # noqa: E402
from tests.test_guest_scope import GuestScopeBase  # noqa: E402

CODE = "ZEBRAQUARTZ7781"


def _multipart(fields: dict, filename: str, blob: bytes):
    b = "----t" + os.urandom(4).hex()
    out = b""
    for k, v in fields.items():
        out += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    out += f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/zip\r\n\r\n'.encode()
    out += blob + f"\r\n--{b}--\r\n".encode()
    return out, f"multipart/form-data; boundary={b}"


class ExportIsHostOnly(GuestScopeBase):
    def test_joined_phone_cannot_pull_a_backup_or_restore(self):  # data-integrity.0
        for path in ("/api/export?package=1", "/api/export"):
            st, _ = self.req("GET", path, self.joined)
            self.assertEqual(st, 403, path)
        body, ctype = _multipart({"confirm": "1"}, "b.zip", b"x")
        st, _ = self.req("POST", "/api/import", self.joined, body, headers={"Content-Type": ctype})
        self.assertEqual(st, 403)
        st, _ = self.req("GET", "/api/export?package=1", self.view)
        self.assertEqual(st, 403)

    def test_host_backup_has_no_secrets_and_says_what_was_left_out(self):
        env = clipdrop.ROOT / "env.local"
        had = env.read_bytes() if env.is_file() else None
        env.write_text("OPENAI_API_KEY=sk-SECRETSECRET\n")
        try:
            st, hdrs, blob = self.req("GET", "/api/export?package=1", self.host_tok, remote=False, raw=True)
        finally:
            env.unlink()
            if had is not None:
                env.write_bytes(had)
        self.assertEqual(st, 200)
        zf = zipfile.ZipFile(io.BytesIO(blob))
        names = zf.namelist()
        self.assertNotIn("env.local", names)
        for secret in ("auth_tokens.json", "workspace.json", "session_shares.json", "token_session_acl.json",
                       "token_meta.json", "license.json", "join_codes.json"):
            self.assertNotIn("data/" + secret, names)
        self.assertIn("data/clipdrop.db", names)
        everything = b"".join(zf.read(n) for n in names)
        self.assertNotIn(b"sk-SECRETSECRET", everything)
        self.assertNotIn(self.host_tok.encode(), everything)
        left = {x["file"] for x in json.loads(zf.read("MANIFEST.json"))["left_out"]}
        self.assertTrue({"env.local", "workspace.json", "auth_tokens.json"} <= left)

    def test_host_import_needs_the_confirm_flag(self):
        body, ctype = _multipart({}, "b.zip", b"x")
        st, out = self.req("POST", "/api/import", self.host_tok, body, remote=False, headers={"Content-Type": ctype})
        self.assertEqual(st, 400)
        self.assertIn("Confirm", out["error"])


class RestoreIsSafe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dd = Path(self.tmp.name) / "elsewhere"
        self.dd.mkdir()
        self._old = clipdrop.DATA_DIR
        clipdrop.DATA_DIR = self.dd

    def tearDown(self):
        clipdrop.DATA_DIR = self._old
        self.tmp.cleanup()

    def _zip(self, files: dict) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n, b in files.items():
                z.writestr(n, b)
        return buf.getvalue()

    def test_restore_goes_into_the_real_data_folder_with_a_safety_copy(self):  # .2 and .3
        (self.dd / "notes.txt").write_text("written after the backup")
        (self.dd / "workspace.json").write_text('{"pass_hash":"keep-me"}')
        blob = self._zip({
            "data/notes.txt": "from backup", "data/sub/new.txt": "new",
            "data/workspace.json": '{"pass_hash":"attacker"}', "env.local": "KEY=1",
            "data/../../evil.txt": "x", "MANIFEST.json": "{}",
        })
        code, out = clipdrop._restore_package(blob)
        self.assertEqual(code, 200, out)
        self.assertEqual((self.dd / "notes.txt").read_text(), "from backup")
        self.assertEqual((self.dd / "sub" / "new.txt").read_text(), "new")
        self.assertEqual((self.dd / "workspace.json").read_text(), '{"pass_hash":"keep-me"}')
        self.assertFalse((Path(self.tmp.name) / "evil.txt").exists())
        self.assertFalse(list(self.dd.rglob("*.restoring")))
        self.assertEqual(out["restored"], 2)
        skipped = {s["file"] for s in out["skipped"]}
        self.assertTrue({"env.local", "data/workspace.json", "data/../../evil.txt"} <= skipped)
        safety = Path(out["safety_copy"])
        self.assertEqual(safety.parent, self.dd)
        with zipfile.ZipFile(safety) as z:
            self.assertEqual(z.read("data/notes.txt"), b"written after the backup")
        self.assertIn(str(safety), out["message"])

    def test_a_bad_zip_changes_nothing(self):
        (self.dd / "notes.txt").write_text("keep")
        code, out = clipdrop._restore_package(b"not a zip")
        self.assertEqual(code, 400)
        code, out = clipdrop._restore_package(self._zip({"env.local": "K=1"}))
        self.assertEqual(code, 400)
        self.assertEqual((self.dd / "notes.txt").read_text(), "keep")
        self.assertFalse(list(self.dd.glob("pre-restore-*")))

    def test_two_restores_in_one_second_keep_both_safety_copies(self):
        (self.dd / "notes.txt").write_text("first")
        c1, o1 = clipdrop._restore_package(self._zip({"data/notes.txt": "second"}))
        c2, o2 = clipdrop._restore_package(self._zip({"data/notes.txt": "third"}))
        self.assertEqual((c1, c2), (200, 200))
        self.assertNotEqual(o1["safety_copy"], o2["safety_copy"])
        with zipfile.ZipFile(o1["safety_copy"]) as z:
            self.assertEqual(z.read("data/notes.txt"), b"first")

    def test_a_backup_too_big_for_the_disk_is_refused_before_anything_changes(self):
        (self.dd / "notes.txt").write_text("keep")
        real = clipdrop.shutil.disk_usage
        clipdrop.shutil.disk_usage = lambda p: type("U", (), {"free": 10})()
        try:
            code, out = clipdrop._restore_package(self._zip({"data/big.bin": b"x" * 1000}))
        finally:
            clipdrop.shutil.disk_usage = real
        self.assertEqual(code, 400)
        self.assertIn("free space", out["error"])
        self.assertEqual((self.dd / "notes.txt").read_text(), "keep")
        self.assertFalse(list(self.dd.glob("pre-restore-*")))

    def test_backup_leaves_out_safety_copies_and_keeps_data(self):
        (self.dd / "a.txt").write_text("A")
        (self.dd / "pre-restore-1.zip").write_bytes(b"old")
        names = zipfile.ZipFile(io.BytesIO(clipdrop._export_package())).namelist()
        self.assertIn("data/a.txt", names)
        self.assertNotIn("data/pre-restore-1.zip", names)


class DeletedChatIsGone(unittest.TestCase):
    def _chat_with_memory(self, text):
        sid = db.create_session("mem chat")["id"]
        memory_index.add_memory(kind="memory", title=text[:40], body=f"Q: {text}\nA: noted", project="general",
                                session_id=sid, folder="session", source="chat_turn")
        return sid

    def _count(self, sid):
        with memory_index._conn() as c:
            return c.execute("SELECT COUNT(*) FROM memories WHERE session_id=?", (sid,)).fetchone()[0]

    def _vault_has(self, needle):
        return [p for p in vault.VAULT.rglob("*.md") if needle in p.read_text(encoding="utf-8", errors="ignore")]

    def test_delete_chat_takes_memory_and_vault_notes(self):  # data-integrity.1
        word = CODE + os.urandom(2).hex()
        sid = self._chat_with_memory("remember " + word)
        other = self._chat_with_memory("keep this " + word[:6] + "OTHER")
        vault.write_drawer(project="general", title=f"turn-{sid}", body="remember " + word, room="session",
                           source="chat", session_id=sid)
        self.assertEqual(self._count(sid), 1)
        self.assertTrue(self._vault_has(word))
        db.delete_session(sid)
        self.assertEqual(self._count(sid), 0)
        self.assertEqual(self._vault_has(word), [])
        self.assertNotIn(word, json.dumps(memory_index.search(word, project="general", k=8)))
        self.assertEqual(self._count(other), 1, "another chat's memory stays")
        db.delete_session(other)

    def test_old_notes_without_a_chat_id_are_still_found(self):
        word = "LEGACYWORD" + os.urandom(2).hex()
        sid = self._chat_with_memory("hello " + word)
        body = f"Q: hello {word}\nA: noted"
        # written the old way: no session_id in the front matter, title is the question
        p = vault.write_drawer(project="general", title="hello " + word, body=body, room="session", source="memory_index")
        self.assertNotIn("session_id:", (DATA_DIR / p).read_text())
        db.delete_session(sid)
        self.assertFalse((DATA_DIR / p).exists())

    def test_clear_all_history_clears_memory_too(self):
        word = "CLEARWORD" + os.urandom(2).hex()
        sid = self._chat_with_memory(word)
        vault.write_drawer(project="general", title="t", body=word, room="session", source="chat", session_id=sid)
        db.clear_all_messages()
        self.assertEqual(self._count(sid), 0)
        self.assertEqual(self._vault_has(word), [])

    def test_a_note_written_from_a_chat_carries_its_id(self):
        p = vault.write_drawer(project="general", title="x", body="b", session_id=7)
        self.assertIn("session_id: 7", (DATA_DIR / p).read_text())
        (DATA_DIR / p).unlink()


class SameFileInTwoChats(unittest.TestCase):
    def test_second_chat_gets_the_file_and_the_same_chat_is_told(self):  # data-integrity.4
        a = db.create_session("A")["id"]
        b = db.create_session("B")["id"]
        blob = b"the same document " + os.urandom(8)
        m1 = clipdrop.post_message("1.1.1.1", "d", file_data=blob, filename="d.txt", session_id=a, auto_analyze=False)
        m2 = clipdrop.post_message("1.1.1.1", "d", file_data=blob, filename="d.txt", session_id=b, auto_analyze=False)
        self.assertTrue(m1 and m2)
        self.assertEqual((m1["session_id"], m2["session_id"]), (a, b))
        self.assertTrue((DATA_DIR / m2["filepath"]).is_file())
        self.assertIsNone(clipdrop.post_message("1.1.1.1", "d", file_data=blob, filename="d.txt", session_id=a, auto_analyze=False))

    def test_typed_note_is_never_a_duplicate(self):
        a = db.create_session("A")["id"]
        b = db.create_session("B")["id"]
        for sid in (a, a, b):
            self.assertTrue(clipdrop.post_message("1.1.1.1", "d", text="yes please", session_id=sid))


class HalfWrittenPasscodeFile(unittest.TestCase):
    def setUp(self):
        self.f = auth.WORKSPACE_FILE
        self.keep = self.f.read_bytes() if self.f.is_file() else None
        self.toks = dict(auth._tokens)
        if self.f.is_file():
            self.f.unlink()

    def tearDown(self):
        for x in (self.f, self.f.with_name(self.f.name + ".bad")):
            if x.is_file():
                x.unlink()
        if self.keep is not None:
            self.f.write_bytes(self.keep)
        auth._tokens.clear()
        auth._tokens.update(self.toks)

    def test_damaged_file_fails_closed_and_is_kept(self):  # data-integrity.5
        tok = auth.init_workspace("host@example.com", "abcd1")["token"]
        full = self.f.read_text()
        self.f.write_text(full[: len(full) // 2])
        self.assertTrue(auth.passcode_required())
        r = auth.join_workspace("abcd1")
        self.assertFalse(r["ok"])
        self.assertIn("damaged", r["error"])
        self.assertFalse(auth.verify_token(tok))
        self.assertTrue(auth.status()["damaged"])
        self.assertTrue(self.f.with_name(self.f.name + ".bad").is_file())
        self.assertFalse(auth.set_passcode_required(False)["ok"])
        self.assertFalse(auth.init_workspace("a@b.co", "zzzz1")["ok"])
        self.assertEqual(self.f.read_text(), full[: len(full) // 2], "never overwritten")

    def test_normal_use_still_works_and_writes_are_atomic(self):
        auth.init_workspace("host@example.com", "abcd1")
        self.assertTrue(auth.join_workspace("abcd1")["ok"])
        self.assertFalse(auth.join_workspace("wrong")["ok"])
        self.assertFalse(self.f.with_name(self.f.name + ".tmp").exists())
        self.assertFalse(auth.status()["damaged"])


class ForkKeepsInstructions(unittest.TestCase):
    def test_db_fork_copies_instructions(self):  # data-integrity.6
        import chat_prefs

        sid = db.create_session("src")["id"]
        m = db.add_message(device_ip="1", device_name="d", text="hi", source="chat", session_id=sid)
        chat_prefs.set(sid, "be terse")
        out = db.fork_session(sid, m["id"])
        self.assertEqual(chat_prefs.get(int(out["session"]["id"])), "be terse")
        self.assertTrue(out["instructions_copied"])


if __name__ == "__main__":
    unittest.main()

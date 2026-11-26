"""Saved prompts: storage rules and the HTTP trust boundary."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402
import config  # noqa: E402
import snippets  # noqa: E402


class _TempData(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_dir = config.DATA_DIR
        config.DATA_DIR = self._tmp.name

    def tearDown(self):
        config.DATA_DIR = self._orig_dir
        self._tmp.cleanup()


class StorageTest(_TempData):
    def test_create_update_delete(self):
        a = snippets.save("Weekly note", "Hi {{name}}")
        self.assertEqual([i["title"] for i in snippets.list_all()], ["Weekly note"])
        snippets.save("Weekly update", "Hello {{name}}", a["id"])
        got = snippets.list_all()
        self.assertEqual((len(got), got[0]["title"], got[0]["body"]), (1, "Weekly update", "Hello {{name}}"))
        snippets.delete(a["id"])
        self.assertEqual(snippets.list_all(), [])

    def test_survives_a_reload_and_leaves_no_temp_files(self):
        snippets.save("Keep", "body")
        import importlib
        importlib.reload(snippets)
        self.assertEqual(snippets.list_all()[0]["title"], "Keep")
        self.assertEqual(os.listdir(self._tmp.name), ["snippets.json"])

    def test_limits_are_refused_with_a_message(self):
        with self.assertRaisesRegex(snippets.SnippetError, "title is too long"):
            snippets.save("t" * 81, "b")
        snippets.save("t" * 80, "b" * 8000)
        with self.assertRaisesRegex(snippets.SnippetError, "too long"):
            snippets.save("t", "b" * 8001)
        with self.assertRaises(snippets.SnippetError):
            snippets.save("", "b")
        with self.assertRaises(snippets.SnippetError):
            snippets.save("t", "   ")
        with self.assertRaises(snippets.SnippetError):
            snippets.save(5, "b")

    def test_at_most_200_prompts(self):
        for i in range(snippets.MAX_ITEMS):
            snippets.save(f"p{i}", "b")
        with self.assertRaisesRegex(snippets.SnippetError, "limit"):
            snippets.save("one more", "b")
        self.assertEqual(len(snippets.list_all()), snippets.MAX_ITEMS)

    def test_unknown_id_is_a_404(self):
        with self.assertRaises(snippets.SnippetError) as c:
            snippets.save("t", "b", "nope")
        self.assertEqual(c.exception.status, 404)
        with self.assertRaises(snippets.SnippetError) as c:
            snippets.delete("nope")
        self.assertEqual(c.exception.status, 404)

    def test_corrupt_file_is_reported_and_never_replaced(self):
        p = os.path.join(self._tmp.name, "snippets.json")
        with open(p, "w") as f:
            f.write("{not json")
        with self.assertRaisesRegex(snippets.SnippetError, "could not be read"):
            snippets.list_all()
        with self.assertRaises(snippets.SnippetError):
            snippets.save("t", "b")
        with self.assertRaises(snippets.SnippetError):
            snippets.delete("x")
        with open(p) as f:
            self.assertEqual(f.read(), "{not json")

    def test_wrong_shape_is_reported_too(self):
        p = os.path.join(self._tmp.name, "snippets.json")
        with open(p, "w") as f:
            f.write('{"a": 1}')
        with self.assertRaises(snippets.SnippetError):
            snippets.list_all()


class HttpTest(_TempData):
    def setUp(self):
        super().setUp()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def _call(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def test_full_round_trip(self):
        code, got = self._call("/api/snippets")
        self.assertEqual((code, got["items"]), (200, []))
        code, got = self._call("/api/snippets", {"title": "A", "body": "x {{y}}"})
        self.assertEqual(code, 200)
        sid = got["item"]["id"]
        code, got = self._call("/api/snippets", {"id": sid, "title": "B", "body": "z"})
        self.assertEqual(got["item"]["title"], "B")
        self.assertEqual(self._call("/api/snippets")[1]["items"][0]["body"], "z")
        self.assertEqual(self._call("/api/snippets/delete", {"id": sid})[0], 200)
        self.assertEqual(self._call("/api/snippets")[1]["items"], [])

    def test_over_limit_gets_a_400_with_words(self):
        code, got = self._call("/api/snippets", {"title": "t" * 81, "body": "b"})
        self.assertEqual(code, 400)
        self.assertIn("too long", got["error"])

    def test_bad_json_body_is_a_400(self):
        req = urllib.request.Request(self.base + "/api/snippets", data=b"[1]",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as c:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(c.exception.code, 400)

    def test_corrupt_file_reads_as_an_error_not_an_empty_list(self):
        with open(os.path.join(self._tmp.name, "snippets.json"), "w") as f:
            f.write("garbage")
        code, got = self._call("/api/snippets")
        self.assertEqual(code, 500)
        self.assertIn("could not be read", got["error"])

    def test_share_guest_can_read_but_not_write(self):
        mine = snippets.save("Mine", "body")
        orig = clipdrop.app_auth.token_session_acl
        clipdrop.app_auth.token_session_acl = lambda tok: {"session_id": 1, "acl": "post"}
        try:
            self.assertEqual(self._call("/api/snippets")[0], 200)
            self.assertEqual(self._call("/api/snippets", {"title": "x", "body": "y"})[0], 403)
            self.assertEqual(self._call("/api/snippets", {"id": mine["id"], "title": "x", "body": "y"})[0], 403)
            self.assertEqual(self._call("/api/snippets/delete", {"id": mine["id"]})[0], 403)
        finally:
            clipdrop.app_auth.token_session_acl = orig
        self.assertEqual([i["title"] for i in snippets.list_all()], ["Mine"])


if __name__ == "__main__":
    unittest.main()

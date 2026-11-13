"""Settings controls must do what they say.

The skill Delete button posted an action the server did not have, and Edit opened a
box with the wrong text because the list never carried the skill body. These tests
pin the server half over real HTTP, and pin the page half (dead checkboxes, the
silent AI_AUTO write, the Plan badge) so they cannot quietly come back.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402
import invoke_registry  # noqa: E402

INDEX = (ROOT / "index.html").read_text(encoding="utf-8")


class SkillRoundTripHttpTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self._pin = mock.patch.object(invoke_registry, "SKILLS_DIR", self.root)
        self._pin.start()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self._pin.stop()
        self._td.cleanup()

    def _post(self, payload):
        req = urllib.request.Request(
            self.base + "/api/invoke/skills", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def _list(self):
        with urllib.request.urlopen(self.base + "/api/invoke/skills", timeout=10) as r:
            return {s["id"]: s for s in json.loads(r.read().decode())["skills"]}

    def test_create_edit_delete_reload(self):
        code, out = self._post({"id": "probe-one", "title": "Probe One", "body": "do stuff"})
        self.assertTrue(out.get("ok"), out)
        # Edit needs the real title and the real text back from the list.
        entry = self._list()["probe-one"]
        self.assertEqual(entry["name"], "Probe One")
        self.assertIn("do stuff", entry["body"])
        code, out = self._post({"id": "probe-one", "title": "Probe One", "body": "# Probe One\ndo other stuff"})
        self.assertTrue(out.get("ok"), out)
        self.assertIn("do other stuff", self._list()["probe-one"]["body"])
        # Delete must delete.
        code, out = self._post({"action": "delete", "id": "probe-one"})
        self.assertEqual((code, out.get("ok")), (200, True), out)
        self.assertFalse((self.root / "probe-one.md").exists())
        self.assertNotIn("probe-one", self._list())

    def test_saving_a_skill_with_front_matter_keeps_it_readable(self):
        # Editing an imported skill re-saves its text; a heading must not be put in front of the
        # front matter, or its name and description stop being read.
        body = "---\nname: Fancy\ndescription: does things\n---\nHello"
        self._post({"id": "fm", "title": "Other", "body": body})
        entry = self._list()["fm"]
        self.assertTrue(entry["body"].startswith("---"), entry["body"])
        self.assertEqual(entry["name"], "Fancy")
        self.assertEqual(entry["description"], "does things")

    def test_delete_also_forgets_its_on_off_state(self):
        self._post({"id": "keepme", "body": "text"})
        self._post({"action": "enable", "id": "keepme", "scope": "global"})
        self._post({"action": "delete", "id": "keepme"})
        state = json.loads((self.root / "_state.json").read_text())
        self.assertNotIn("keepme", state)

    def test_delete_unknown_or_hostile_id_says_so_and_touches_nothing(self):
        outside = self.root.parent / "outside-skill.md"
        outside.write_text("keep", encoding="utf-8")
        try:
            _, out = self._post({"action": "delete", "id": "nope"})
            self.assertFalse(out["ok"])
            self.assertIn("not found", out["error"])
            _, out = self._post({"action": "delete", "id": "../outside-skill"})
            self.assertTrue(outside.exists(), "path traversal must not reach files outside the skills folder")
        finally:
            outside.unlink(missing_ok=True)

    def test_a_guest_device_cannot_delete(self):
        self._post({"id": "guarded", "body": "text"})
        orig = (clipdrop._is_host_request, clipdrop._s1_remote_open)
        clipdrop._is_host_request = lambda headers, ip: False
        clipdrop._s1_remote_open = lambda: True
        try:
            code, _ = self._post({"action": "delete", "id": "guarded"})
        finally:
            clipdrop._is_host_request, clipdrop._s1_remote_open = orig
        self.assertIn(code, (401, 403))
        self.assertTrue((self.root / "guarded.md").exists())


class SettingsPageTest(unittest.TestCase):
    def test_dead_checkboxes_are_gone(self):
        for key in ("airgpt_tips", "airgpt_notif_done", "airgpt_notif_warn", "airgpt_agent_autodetect",
                    "airgpt_agent_autocreate", "airgpt_subagent_autodetect", "airgpt_subagent_autocreate"):
            self.assertFalse(key in INDEX, key + " is saved by a checkbox that nothing reads")

    def test_plan_badge_opens_the_plan_panel(self):
        body = re.search(r"function openSkuSettings\(\)\{(.*?)\n\}", INDEX, re.S).group(1)
        self.assertIn("openSettings('plan')", body)

    def test_ai_auto_is_only_saved_when_the_user_changed_it(self):
        save = INDEX[INDEX.index("async function saveSettings("):INDEX.index("async function activateLicense(")]
        self.assertNotIn("&&aiMode", save, "a transient switch must not be folded into a saved value")
        self.assertIn("_aiAutoDirty&&", save)

    def test_a_failed_save_is_not_reported_as_saved(self):
        save = INDEX[INDEX.index("async function saveSettings("):INDEX.index("async function activateLicense(")]
        self.assertIn("Could not save", save)
        self.assertIn("!x.ok", save)

    def test_hidden_overflow_menu_is_gone_and_history_has_a_real_button(self):
        self.assertFalse("topbarOverflow" in INDEX)
        self.assertFalse("buildTopbarOverflowMenu" in INDEX)
        self.assertRegex(INDEX, r'id="clearAllHistoryBtn"[^>]*onclick="clearAllHistory\(\)"')

    def test_hooks_panel_says_they_are_not_applied(self):
        self.assertIn("saved in this browser only and are not applied yet", INDEX)

    def test_lan_hint_uses_the_real_port(self):
        src = (ROOT / "clipdrop.py").read_text(encoding="utf-8")
        self.assertNotIn("port 8765", src)


if __name__ == "__main__":
    unittest.main()

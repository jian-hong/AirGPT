"""Page copy and wiring that a first-time user relies on (source-level checks)."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
PREFS = (ROOT / "ui" / "chatprefs.js").read_text(encoding="utf-8")


class ClarityUiTests(unittest.TestCase):
    def test_new_chat_button_exists_and_empty_text_matches(self):
        self.assertIn('id="navNewChat"', HTML)
        self.assertIn("New chat\n      </button>", HTML)
        self.assertNotIn("+ New", HTML)

    def test_effort_button_opens_on_click_and_has_one_name(self):
        self.assertNotIn("onpointerdown=\"modelBtnDown", HTML)
        self.assertIn('onclick="modelBtnClick()"', HTML)
        self.assertIn("toast('Effort: '", HTML)
        self.assertNotIn("toast('Model: '", HTML)

    def test_manual_mode_is_explained(self):
        self.assertIn('id="manualNote"', HTML)
        self.assertIn("mode-manual #modelDd", HTML)

    def test_web_search_has_visible_state(self):
        self.assertIn('id="webChip"', HTML)

    def test_archive_toast_offers_undo(self):
        self.assertIn("archived:false", HTML)

    def test_instructions_disabled_with_reason_on_empty_chat(self):
        self.assertIn("btn.disabled=none", PREFS)

    def test_clipboard_card_says_what_it_does(self):
        self.assertNotIn("sync to this PC", HTML)


if __name__ == "__main__":
    unittest.main()

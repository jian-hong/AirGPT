"""SHELL-03: /skill and /anthropic-skills peel the pack; remainder is the job."""
from __future__ import annotations

import unittest
from pathlib import Path

import commands

_INDEX = Path(__file__).resolve().parents[1] / "index.html"


class PeelSkillSlashTests(unittest.TestCase):
    def test_skill_space_form_keeps_the_job(self):
        p = commands.peel_skill_slash("/skill research write the weekly digest")
        self.assertEqual(p["pack"], "research")
        self.assertEqual(p["scope"], "")
        self.assertEqual(p["rest"], "write the weekly digest")

    def test_skill_colon_form(self):
        p = commands.peel_skill_slash("/skill:visual-diagrams draw the pipeline")
        self.assertEqual(p["pack"], "visual-diagrams")
        self.assertEqual(p["rest"], "draw the pipeline")

    def test_anthropic_colon_form(self):
        p = commands.peel_skill_slash("/anthropic-skills:lazy-senior-dev patch the host")
        self.assertEqual(p["pack"], "lazy-senior-dev")
        self.assertEqual(p["form"], "anthropic-skills")
        self.assertEqual(p["rest"], "patch the host")

    def test_hyphen_pack_form(self):
        p = commands.peel_skill_slash("/skill-general summarize this")
        self.assertEqual(p["pack"], "general")
        self.assertEqual(p["rest"], "summarize this")

    def test_scope_then_job(self):
        p = commands.peel_skill_slash("/skill research global write a brief")
        self.assertEqual(p["pack"], "research")
        self.assertEqual(p["scope"], "global")
        self.assertEqual(p["rest"], "write a brief")

    def test_arm_only_has_empty_rest(self):
        p = commands.peel_skill_slash("/skill research")
        self.assertEqual(p["pack"], "research")
        self.assertEqual(p["rest"], "")

    def test_bare_skill_is_usage(self):
        p = commands.peel_skill_slash("/skill")
        self.assertEqual(p["pack"], "")
        self.assertEqual(p["rest"], "")

    def test_not_a_skill_slash(self):
        self.assertIsNone(commands.peel_skill_slash("/rules edit"))
        self.assertIsNone(commands.peel_skill_slash("skill research hello"))

    def test_parse_slash_keeps_legacy_args(self):
        parsed = commands.parse_slash("/skill research")
        self.assertEqual(parsed["command"], "skill")
        self.assertEqual(parsed["args"], "research")
        self.assertEqual(parsed["rest"], "")

    def test_parse_slash_anthropic_exposes_pack_and_rest(self):
        parsed = commands.parse_slash("/anthropic-skills:lazy-senior-dev patch the host")
        self.assertEqual(parsed["command"], "anthropic-skills")
        self.assertEqual(parsed["pack"], "lazy-senior-dev")
        self.assertEqual(parsed["rest"], "patch the host")

    def test_auto_wire_does_not_count_as_a_slash(self):
        self.assertIsNone(commands.peel_skill_slash("write the weekly digest from the vault"))


class Shell03IndexHtmlTests(unittest.TestCase):
    def test_gallery_is_force_not_use(self):
        t = _INDEX.read_text(encoding="utf-8")
        self.assertIn("Armed':'Force'", t)
        self.assertIn("Force a skill", t)
        self.assertIn("function peelSkillSlash", t)
        self.assertNotIn("Armed':'Use'", t)
        self.assertIn("cortexWireHint", t)


if __name__ == "__main__":
    unittest.main()

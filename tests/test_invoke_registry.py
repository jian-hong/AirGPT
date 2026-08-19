"""Tests for unified invoke registry (rules / skills / slash / catalog)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import invoke_registry

# Product packs live under gitignored data/skills. These tests pin to committed
# fixtures so a clean clone and a laptop with extra packs see the same catalog.
_FIXTURE_SKILLS = Path(__file__).resolve().parent / "fixtures" / "skills"


class InvokeRegistryTests(unittest.TestCase):
    def setUp(self):
        self._skills_dir = mock.patch.object(invoke_registry, "SKILLS_DIR", _FIXTURE_SKILLS)
        self._skills_dir.start()
        self.addCleanup(self._skills_dir.stop)

    def test_list_and_load_skills(self):
        skills = invoke_registry.list_skills()
        ids = {s["id"] for s in skills}
        self.assertIn("general", ids)
        self.assertIn("research", ids)
        body = invoke_registry.load_skill("general")
        self.assertTrue(body.strip())
        self.assertEqual(invoke_registry.load_skill("../etc/passwd"), "")
        self.assertEqual(invoke_registry.load_skill(""), "")

    def test_rules_context_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Prefer .airgpt/rules.md
            (root / ".airgpt").mkdir()
            (root / ".airgpt" / "rules.md").write_text("# Project rules\nBe careful.\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("# Agents\nFallback only.\n", encoding="utf-8")
            ctx = invoke_registry.rules_context(root)
            self.assertTrue(ctx["present"])
            self.assertEqual(ctx["source"], ".airgpt/rules.md")
            self.assertIn("Be careful", ctx["text"])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "AGENTS.md").write_text("# Agents\nUse AGENTS.md.\n", encoding="utf-8")
            ctx = invoke_registry.rules_context(root)
            self.assertTrue(ctx["present"])
            self.assertEqual(ctx["source"], "AGENTS.md")
            self.assertIn("AGENTS.md", ctx["text"])

        with tempfile.TemporaryDirectory() as td:
            ctx = invoke_registry.rules_context(Path(td))
            self.assertFalse(ctx["present"])
            self.assertEqual(ctx["text"], "")

    def test_slash_skill_parse(self):
        import commands

        parsed = commands.parse_slash("/skill research")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["command"], "skill")
        self.assertEqual(parsed["args"], "research")

        parsed2 = commands.parse_slash("/skill-general")
        self.assertIsNotNone(parsed2)
        self.assertEqual(parsed2["command"], "skill-general")

        cmds = commands.list_commands("skill")
        names = {c["name"] for c in cmds}
        self.assertIn("skill", names)
        self.assertTrue(any(n.startswith("skill-") for n in names))

    def test_catalog_shape(self):
        cat = invoke_registry.catalog()
        self.assertTrue(cat.get("ok"))
        self.assertEqual(cat.get("invoke"), ["rules", "skills", "slash", "subagents"])
        self.assertIn("rules", cat)
        self.assertIn("skills", cat)
        self.assertIn("commands", cat)
        self.assertIn("agents", cat)
        self.assertIsInstance(cat["skills"], list)
        self.assertTrue(any(s["id"] == "general" for s in cat["skills"]))

    def test_empty_product_dir_is_an_empty_catalog(self):
        """No user packs is a valid product state. Fixtures are a test pin, not a default."""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(invoke_registry, "SKILLS_DIR", Path(td)):
                self.assertEqual(invoke_registry.list_skills(), [])
                self.assertEqual(invoke_registry.load_skill("general"), "")

    def test_save_skill(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.object(invoke_registry, "SKILLS_DIR", root):
                out = invoke_registry.save_skill("demo-pack", "Do the thing carefully.", title="Demo")
                self.assertTrue(out.get("ok"), out)
                self.assertEqual(out["id"], "demo-pack")
                self.assertTrue((root / "demo-pack.md").is_file())
                body = invoke_registry.load_skill("demo-pack")
                self.assertIn("Demo", body)
                self.assertIn("carefully", body)

    def test_subagent_fanout_cap(self):
        import agent_runtime

        # Assist / child path: spawn rejected when max_children=0
        out = agent_runtime._spawn_subagent(
            "do a thing",
            parent_run_id=1,
            children_spawned=0,
            max_children=0,
        )
        self.assertFalse(out.get("ok"))
        self.assertIn("fan-out", (out.get("error") or "").lower())

        out2 = agent_runtime._spawn_subagent(
            "",
            parent_run_id=1,
            children_spawned=0,
            max_children=2,
        )
        self.assertFalse(out2.get("ok"))


if __name__ == "__main__":
    unittest.main()

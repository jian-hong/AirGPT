"""Guards for the non-chat workspaces (Projects, Cortex, Apps hub, Hub access, Memory).

Each check pins a defect that was seen live: it reads the shipped page source,
because these screens are drawn by index.html and have no server side to test.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "index.html").read_text(encoding="utf-8")


def _body(name: str) -> str:
    """Source of function `name` up to the next top-level function."""
    m = re.search(r"(?:async )?function %s\(" % re.escape(name), PAGE)
    assert m, name
    nxt = re.search(r"\n(?:async )?function \w+\(", PAGE[m.end():])
    return PAGE[m.start(): m.end() + (nxt.start() if nxt else 4000)]


class WorkspaceGuards(unittest.TestCase):
    def test_new_project_is_listed(self):
        self.assertIn("_customProjects", _body("showProjectsPage"))
        self.assertIn("showProjectsPage", _body("addProject"))
        self.assertIn("/api/projects", _body("loadCustomProjects"))

    def test_agent_create_does_not_open_settings(self):
        self.assertNotIn("toggleConnect", _body("handleCortexChatCreate"))

    def test_cortex_home_echoes_and_scrolls(self):
        card = _body("ensureCortexLiveCard")
        self.assertIn("cortexOrchEcho", card)
        self.assertIn("scrollIntoView", card)
        self.assertIn("cortexOrchEngine", card)
        self.assertIn("not running on this computer", card)

    def test_access_hook_is_defined(self):
        self.assertRegex(PAGE, r"window\.__openAccessPopover\s*=\s*openAccessPopover")

    def test_apps_hub_only_offers_working_actions(self):
        hub = _body("showAppsHubPage")
        self.assertIn("a.can_start", hub)
        self.assertIn("location.port", hub)

    def test_retry_health_does_not_navigate(self):
        self.assertNotRegex(PAGE, r"showHostingPage\(\)\">Retry health")
        self.assertIn("retryCortexHealth", _body("cortexCrmBannerHtml"))

    def test_memory_fab_is_gone(self):
        self.assertNotIn('id="memFab"', PAGE)
        self.assertNotIn(".mem-fab", PAGE)
        self.assertNotIn("canShowMemPanel", PAGE)

    def test_no_placeholder_built_suggestions(self):
        self.assertNotIn("airgpt_taste", _body("habitAgentActions"))
        self.assertNotIn("QUESTIONS_OF_THE_DAY", _body("habitAgentActions"))

    def test_no_developer_paths_in_user_copy(self):
        self.assertNotIn("Start D:\\\\Cortex first", PAGE)
        self.assertNotIn("Cortex offline — start D:", PAGE)
        self.assertNotIn("Launching D:", PAGE)


if __name__ == "__main__":
    unittest.main()

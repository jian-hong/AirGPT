"""The Routines control says what actually happened (SHELL-02 #60, EPIC-D09 #56).

`cortex_client` was made honest on the wire by #60; these are the four surface fixes
that were owed to `index.html` and could not land in the same pass. Each one existed
as a defect first:

  * a host-clock row rendered identically to a Cortex routine, so `hr-25660b22` looked
    scheduled while `last_status` was `fired_no_agent`
  * the Routines page created routines with no `agent_id`, so every one of them was
    permanently `fired_no_agent`
  * the offline banner guessed "start :8010" instead of naming the reason the wire now
    carries (`cortex_down` / `wrong_surface` / `no_scheduler`)
  * Run now toasted "Running..." on HTTP 200 even when the clock did not advance

That last shape - a control reporting success over a no-op - is R-0011, the defect
EPIC-D08 #38 is named after. Asserted on the page source, the way the sibling shell
gates do it.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

_INDEX = Path(__file__).resolve().parents[1] / "index.html"


def _src() -> str:
    return _INDEX.read_text(encoding="utf-8", errors="replace")


def _body(src: str, name: str) -> str:
    """The source of one top-level function, up to the next one."""
    start = src.index(f"function {name}(")
    nxt = src.find("\nfunction ", start + 1)
    nxt = nxt if nxt != -1 else start + 4000
    return src[start:nxt]


class _SourceCase(unittest.TestCase):
    def present(self, needle: str, hay: str, why: str = "") -> None:
        self.assertIn(needle, hay, f"missing from index.html: {needle!r} {why}")

    def absent(self, pattern: str, hay: str, why: str = "") -> None:
        self.assertIsNone(
            re.search(pattern, hay), f"still present in index.html: {pattern!r} {why}"
        )


class HostClockIsMarkedTests(_SourceCase):
    def test_card_distinguishes_a_host_row_from_a_cortex_routine(self):
        body = _body(_src(), "routineCardHtml")
        self.present("'airgpt_host'", body, "- the card cannot tell the two apart")
        self.present("Host clock", body)

    def test_legacy_host_rows_are_reachable_on_the_page(self):
        """They are no longer creatable; if they are also invisible the founder
        cannot delete the ones already on disk, which is a second silent no-op."""
        body = _body(_src(), "showRoutinesPage")
        self.present("host_routines", body)
        self.present("Host clock (legacy)", body)


class CreateDoesNotNeedAirGptAgentTests(_SourceCase):
    def test_create_posts_the_goal_alone(self):
        body = _body(_src(), "routineCreateFromPreview")
        self.present("JSON.stringify({goal})", body)
        self.absent(r"if\(!aid\)\{toast\(", body, "- Cortex routines run without an AirGPT agent")

    def test_create_does_not_block_on_a_local_agent_chip(self):
        body = _body(_src(), "routineCreateFromPreview")
        self.assertNotIn("Pick an agent first", body)


class OfflineBannerNamesTheReasonTests(_SourceCase):
    def test_banner_uses_the_reason_from_the_wire(self):
        body = _body(_src(), "showRoutinesPage")
        # Assert on the RENDER, not the declaration. `offlineWhy` staying in the
        # variable list while the banner goes back to a hardcoded string is exactly
        # the shape this whole file is about, and an earlier cut of this test passed
        # over that mutation.
        banner = body[body.index("${offline?"):]
        banner = banner[: banner.index("\n")]
        self.present("offlineWhy", banner, "- the banner does not render the reason")
        self.assertNotIn(
            "start :8010, then refresh</p>",
            banner,
            "banner hardcodes a guess instead of the reason routines_list returns",
        )

    def test_the_wire_reason_is_captured_from_the_response(self):
        body = _body(_src(), "showRoutinesPage")
        self.assertRegex(body, r"offlineWhy=\(d&&\(d\.error\|\|d\.hint\)\)")


class RunNowReportsWhatHappenedTests(_SourceCase):
    def test_two_hundred_is_not_treated_as_fired(self):
        body = _body(_src(), "routineRunNow")
        self.present("fired", body, "- 200 is not evidence the routine ran")
        self.present("Did not fire", body)
        self.absent(
            r"toast\(r\.ok\?'Running…'",
            body,
            "- reports success over a run that did not advance the clock (R-0011)",
        )


if __name__ == "__main__":
    unittest.main()

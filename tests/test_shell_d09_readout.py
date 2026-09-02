"""SHELL-01 / F20a: the Cortex live readout is grouped, expandable, and not clobbered.

`index.html` is a static file, so most of this asserts on its source (the idiom used by
`tests/test_skill_slash_peel.py::Shell03IndexHtmlTests`). The last class goes further:
the summary formatter is a pure function, so it is lifted out of the page and executed
under node when node is on PATH, which pins the actual rendered string rather than the
presence of a token.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_INDEX = Path(__file__).resolve().parents[1] / "index.html"


def _src() -> str:
    return _INDEX.read_text(encoding="utf-8")


def _slice(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i)]


class _SourceCase(unittest.TestCase):
    """assertIn on a 900 KB file dumps the whole file on failure. These do not."""

    def present(self, needle: str, hay: str, where: str = "index.html"):
        self.assertGreaterEqual(hay.count(needle), 1, f"missing from {where}: {needle!r}")

    def absent(self, needle: str, hay: str, where: str = "index.html"):
        self.assertEqual(hay.count(needle), 0, f"still present in {where}: {needle!r}")


class ExpandableRowsTests(_SourceCase):
    """GAP 1 — a collapsed row must still hold every call it summarises."""

    def test_readout_target_is_not_a_flat_pre(self):
        t = _src()
        self.absent('<pre id="cortexOrchLive"', t)
        self.present('<div id="cortexOrchRows"', t)

    def test_rows_are_details_summary(self):
        build = _slice(_src(), "function cortexLogAppend", "function resetCortexLiveLog")
        self.present("'details'", build)
        self.present("<summary", build)
        self.present("cortex-row-body", build)

    def test_per_call_payloads_are_retained_for_the_expanded_body(self):
        t = _src()
        detail = _slice(t, "function cortexCallDetailHtml", "function cortexLogPaint")
        # args and results, not just the name
        self.present("c.params", detail)
        self.present("c.result", detail)
        self.present("esc(c.name)", detail)
        stream = _slice(t, "async function runCortexAgentStream", "async function ensureCortexAgent")
        self.present("noteCall(openSeg(),name,j.params)", stream)
        self.present("params:params||null", stream)
        self.present("call.result=j.result", stream)


class PerKindAggregateTests(_SourceCase):
    """GAP 2 — kinds and counts, not one token per call instance."""

    def test_no_regex_reparse_of_the_rendered_row(self):
        t = _src()
        self.absent("tools?: (.+)$", t)
        self.absent("m[2].split(', ')", t)

    def test_counts_live_in_a_per_kind_map(self):
        stream = _slice(_src(), "async function runCortexAgentStream", "async function ensureCortexAgent")
        self.present("kinds:new Map()", stream)
        self.present("seg.kinds.get(name)", stream)

    def test_summary_multiplies_kinds(self):
        summary = _slice(_src(), "function cortexToolSummary", "function cortexCallDetailHtml")
        self.present("' ×'+v.n", summary)
        self.present("v.added", summary)
        self.present("v.removed", summary)
        # the row-count contract the HTTP test also pins
        self.present("tools:", summary)

    def test_tool_call_and_tool_are_paired_not_counted_twice(self):
        t = _src()
        self.absent("j.type==='tool'||j.type==='tool_call'", t)
        stream = _slice(t, "async function runCortexAgentStream", "async function ensureCortexAgent")
        self.present("j.type==='tool_call'", stream)
        self.present("pending", stream)
        self.present("q.shift()", stream)


class FinalDoesNotClobberTests(_SourceCase):
    """GAP 3 — the answer renders below the rows, never over them."""

    def test_the_clobbering_assignment_is_gone(self):
        t = _src()
        self.absent("if(final&&live)live.textContent=final.slice(0,8000)", t)
        self.absent("live.textContent=log", t)

    def test_final_has_its_own_host(self):
        t = _src()
        self.present('id="cortexOrchFinal"', t)
        stream = _slice(t, "async function runCortexAgentStream", "async function ensureCortexAgent")
        self.present("$('cortexOrchFinal')", stream)
        self.present("paintFinal()", stream)


class PerKindMarkerTests(_SourceCase):
    """The 🔎 marker regressed to a generic ⚙ for every kind."""

    def test_web_search_has_its_own_marker(self):
        marks = _slice(_src(), "const CORTEX_TOOL_MARKS=", "function cortexToolMark")
        self.present("web_search:'🔎'", marks)
        self.present("fs_write:", marks)

    def test_generic_marker_is_only_the_fallback(self):
        mark = _slice(_src(), "function cortexToolMark", "function cortexToolSummary")
        self.present("⚙", mark)
        self.present("marks.length===1", mark)


class ChatComposerToolRowsTests(_SourceCase):
    """Main chat (not the Cortex tab) must paint AGENT_TASK tool events."""

    def test_send_stream_renders_tool_events(self):
        stream = _slice(_src(), "async function sendStream", "window.openItem=")
        self.present("j.type==='tool'", stream)
        self.present("thinkSteps.push(step)", stream)


class CrossTestPinTests(_SourceCase):
    """`tests/test_shell_d09_http.py::test_index_is_not_a_use_shop` greps index.html for
    these tokens. They are pinned here too so the file that changes index.html is the one
    that fails, instead of a stale grep in a server test."""

    def test_tokens_the_http_test_greps_for_survive(self):
        t = _src()
        # `tools?:` is deliberately absent: the regex round-trip it named is gone, and
        # the http test no longer greps for it (it survived only inside a comment).
        for tok in ("⚙", "tools:", "Force a skill", "function peelSkillSlash"):
            self.present(tok, t)


@unittest.skipUnless(shutil.which("node"), "node not on PATH")
class SummaryBehaviourTests(unittest.TestCase):
    """Execute the pure formatter out of the page — pins the rendered string."""

    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        js = _slice(_src(), "const CORTEX_TOOL_MARKS=", "function cortexCallDetailHtml")
        driver = (
            js
            + "\nconst seg=JSON.parse(process.argv[2]);"
            + "\nseg.kinds=new Map(seg.kinds);"
            + "\nconsole.log(cortexToolSummary(seg));\n"
        )
        cls.path = Path(cls._td.name) / "summary.js"
        cls.path.write_text(driver, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def _render(self, kinds, calls):
        seg = {"kinds": kinds, "calls": calls}
        out = subprocess.run(
            ["node", str(self.path), json.dumps(seg)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def test_three_writes_render_as_one_kind_with_a_count(self):
        row = self._render(
            [["fs_write", {"n": 3, "added": 8, "removed": 1, "hasDelta": True, "failed": False}]],
            [{"result": {}}, {"result": {}}, {"result": {}}],
        )
        self.assertEqual(row, "✎ 3 tools: fs_write ×3 +8 -1")

    def test_pure_web_search_segment_keeps_its_marker(self):
        row = self._render(
            [["web_search", {"n": 2, "added": 0, "removed": 0, "hasDelta": False, "failed": False}]],
            [{"result": {}}, {"result": {}}],
        )
        self.assertEqual(row, "🔎 2 tools: web_search ×2")

    def test_mixed_kinds_fall_back_to_the_generic_marker(self):
        row = self._render(
            [
                ["web_search", {"n": 1, "added": 0, "removed": 0, "hasDelta": False, "failed": False}],
                ["fs_write", {"n": 1, "added": 2, "removed": 0, "hasDelta": True, "failed": True}],
            ],
            [{"result": {}}, {"result": {}}],
        )
        self.assertEqual(row, "⚙ 2 tools: web_search, fs_write +2 -0 (fallback)")

    def test_fallback_suffix_is_not_absorbed_into_a_name(self):
        # the old re-parse split on ', ' and glued ' (fallback)' onto the first token
        row = self._render(
            [
                ["fs_write", {"n": 1, "added": 1, "removed": 0, "hasDelta": True, "failed": True}],
                ["fs_read", {"n": 1, "added": 0, "removed": 0, "hasDelta": False, "failed": False}],
            ],
            [{"result": {}}, {"result": {}}],
        )
        self.assertIn("fs_write +1 -0 (fallback)", row)
        self.assertIn(", fs_read", row)

    def test_single_call_reads_singular(self):
        row = self._render(
            [["vault_read", {"n": 1, "added": 0, "removed": 0, "hasDelta": False, "failed": False}]],
            [{"result": {}}],
        )
        self.assertEqual(row, "📚 1 tool: vault_read")


if __name__ == "__main__":
    unittest.main()

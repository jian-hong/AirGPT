"""Idea-to-Paper spine: facts gate, software score, skill pack, HTTP start."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402
import idea_to_paper  # noqa: E402
import invoke_registry  # noqa: E402


def _serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class IdeaToPaperUnit(unittest.TestCase):
    def test_extract_files_from_fences(self):
        text = "```python\n# citegate.py\nX=1\n```\n```python\n# test\nY=2\n```"
        files = idea_to_paper.extract_files(text)
        self.assertIn("citegate.py", files)
        self.assertIn("test_citegate.py", files)
        data = idea_to_paper.extract_json('noise\n```json\n{"files": {"a.py": "x"}}\n```\n')
        self.assertEqual(data["files"]["a.py"], "x")
        messy = r'{"files": {"citegate.py": "ARXIV_RE = re.compile(r\'\\d{4}\')\n"}}'
        parsed = idea_to_paper.extract_json(messy)
        self.assertIn("citegate.py", (parsed or {}).get("files") or {})

    def test_score_poc_green(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "mod.py").write_text("def add(a,b):\n    return a+b\n", encoding="utf-8")
            (root / "test_mod.py").write_text(
                "from mod import add\n\ndef test_add():\n    assert add(1,2)==3\n",
                encoding="utf-8",
            )
            sc = idea_to_paper.score_poc(root)
            self.assertTrue(sc["lint_ok"])
            self.assertGreaterEqual(sc["score"], 80)
            self.assertTrue(sc["pass"])

    def test_paper_ok_rejects_stub(self):
        stub = idea_to_paper._fallback_tex("idea", Path("."), [])
        self.assertFalse(idea_to_paper.paper_ok(stub))
        good = (
            "\\documentclass[conference]{IEEEtran}\n\\begin{document}\n"
            "\\section{Introduction}\n" + ("prose " * 400) + "\n"
            "\\section{Related Work}\n" + ("cite " * 400) + "\n"
            "\\section{Method}\n" + ("gate " * 400) + "\n"
            "\\section{Limitations}\nPending silicon.\n\\end{document}\n"
        )
        self.assertTrue(idea_to_paper.paper_ok(good))
        leak = good.replace("Pending silicon.", "Python 3.11.x test_gate.py")
        self.assertFalse(idea_to_paper.paper_ok(leak))
        invent = good.replace("Pending silicon.", "http://nonexistent-domain-example-123.org _INVALID")
        self.assertFalse(idea_to_paper.paper_ok(invent))
        broken = 'ARXIV_RE = re.compile(r"https?://[^"]+")\n'
        self.assertIn(r"\S+", idea_to_paper._repair_generated_py(broken))
        doubled = "'''mod'''\\n\\nfrom __future__ import annotations\\nimport urllib.error\\n"
        fixed_py = idea_to_paper._repair_generated_py(doubled)
        self.assertIn("\nfrom __future__", fixed_py)
        self.assertTrue(fixed_py.startswith("import urllib\n"))
        facts_lim = "# Verified facts\nCaptured: x\n## Limitations\n- Digital-only software PoC.\n"
        bare = (
            "\\documentclass[conference]{IEEEtran}\n\\begin{document}\n"
            "\\section{Introduction}\n" + ("prose " * 400) + "\n"
            "\\section{Related Work}\n" + ("cite " * 400) + "\n"
            "\\section{Method}\n" + ("gate " * 400) + "\n"
            "\\section{Conclusion}\nDone.\n\\end{document}\n"
        )
        filled = idea_to_paper.inject_limitations(bare, facts_lim)
        self.assertIn("\\section{Limitations}", filled)
        self.assertTrue(idea_to_paper.paper_ok(filled))
        empty_bib = (
            filled + "\n\\begin{thebibliography}{1}\n% Bibliography entries would be placed here.\n"
            "\\end{thebibliography}\n"
        )
        bib = (
            "@misc{c1,\n  title={https://www.crossref.org/services/metadata-delivery/},\n"
            "  url={https://www.crossref.org/services/metadata-delivery/},\n}\n"
        )
        wired = idea_to_paper.inject_bibliography(empty_bib, bib)
        self.assertIn("\\bibitem{c1}", wired)
        self.assertIn("\\cite{c1}", wired)
        self.assertNotIn("would be placed here", wired)
        wrong_lim = bare.replace(
            "\\section{Conclusion}",
            "\\section{Limitations}\nOffline drops everything.\n\\section{Conclusion}",
        )
        fixed = idea_to_paper.inject_limitations(wrong_lim, facts_lim)
        self.assertIn("Digital-only software PoC", fixed)
        self.assertNotIn("Offline drops everything", fixed)
        facts_sample = "- P1: score 100/100 (lint 20, tests 50, all-green 30, passed 4, failed 0). Source: poc/"
        parsed = idea_to_paper.scores_from_facts(facts_sample)
        self.assertEqual(parsed[0]["passed"], 4)
        self.assertEqual(parsed[0]["score"], 100)
        self.assertFalse(idea_to_paper._md_ready("## Related Work\n" + ("x" * 2500)))
        self.assertTrue(
            idea_to_paper._md_ready("## Related Work\n" + ("x" * 2500) + "\n## Limitations\nNone.\n")
        )
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "00_verified_facts.md"
            p.write_text("# Verified facts\nNo stamp\n", encoding="utf-8")
            self.assertFalse(idea_to_paper.facts_has_captured(p))
            p.write_text("# Verified facts\nCaptured: 2026-08-27T00:00:00Z\n", encoding="utf-8")
            self.assertTrue(idea_to_paper.facts_has_captured(p))

    def test_cx_recommend_retries_generate_405(self):
        hits = {"gen": 0}

        def rec(_n, _e):
            return {"ok": True, "status": 200, "recommendation": {"pattern": "single_agent"}}

        def gen(_p, nodes=None, edges=None):
            hits["gen"] += 1
            if hits["gen"] == 1:
                return {"ok": False, "status": 405, "error": "Method Not Allowed"}
            return {"ok": True, "status": 200, "pattern": "orchestrator_subagent"}

        with mock.patch("cortex_client.constructor_recommend", rec), mock.patch(
            "cortex_client.constructor_generate", gen
        ):
            out = idea_to_paper.cx_recommend("citation gate")
        self.assertGreaterEqual(hits["gen"], 2)
        self.assertEqual((out.get("generate") or {}).get("pattern"), "orchestrator_subagent")

    def test_cx_chat_sends_cortex_prompt_id(self):
        seen = {}

        def fake_loop(prompt, **k):
            seen["prompt"] = prompt
            seen.update(k)
            return {
                "ok": True,
                "content": '{"brief_md":"# x","claims":[]}',
                "telemetry": {"tokens": 12, "model": "cortex-agent"},
            }

        import cortex_client

        with mock.patch.object(cortex_client, "engine_agent_loop", fake_loop):
            out = idea_to_paper.cx_chat("Idea: gate", stage="research", idea="gate")
        self.assertTrue(out["ok"])
        self.assertEqual(seen.get("prompt_id"), "research.idea_to_paper")
        self.assertEqual((seen.get("params") or {}).get("stage"), "research")
        self.assertEqual(out.get("via"), "cortex-agent")
        self.assertIn("Idea: gate", seen.get("prompt") or "")

    def test_cursor_skill_pack_in_product_mode(self):
        with tempfile.TemporaryDirectory() as td:
            product = Path(td) / "data_skills"
            product.mkdir()
            cursor = Path(td) / "cursor_skills" / "idea-to-paper"
            cursor.mkdir(parents=True)
            (cursor / "SKILL.md").write_text(
                "---\nname: idea-to-paper\ndescription: >-\n  Runs the Cortex Idea-to-Paper pipeline with gates.\n---\n"
                "# Idea to Paper\n\nAct as Orchestrator.\n",
                encoding="utf-8",
            )
            with mock.patch.object(invoke_registry, "_PRODUCT_SKILLS_DIR", product):
                with mock.patch.object(invoke_registry, "SKILLS_DIR", product):
                    with mock.patch.object(invoke_registry, "CURSOR_SKILLS_ROOT", Path(td) / "cursor_skills"):
                        ids = {s["id"] for s in invoke_registry.list_skills()}
                        self.assertIn("idea-to-paper", ids)
                        body = invoke_registry.load_skill("idea-to-paper")
                        self.assertIn("Idea to Paper", body)
                        card = next(s for s in invoke_registry.list_skills() if s["id"] == "idea-to-paper")
                        self.assertGreaterEqual(len(card["description"]), 24)


class IdeaToPaperHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.base = _serve()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_post_queues_run(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(idea_to_paper, "RUNS_DIR", Path(td)):
                with mock.patch.object(idea_to_paper, "run_pipeline", return_value={"status": "pass"}):
                    req = __import__("urllib.request").request.Request(
                        self.base + "/api/research/idea-to-paper",
                        data=json.dumps({"idea": "test idea", "sync": False}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with __import__("urllib.request").request.urlopen(req, timeout=15) as r:
                        data = json.loads(r.read().decode())
                    self.assertTrue(data.get("ok"), data)
                    self.assertTrue(data.get("run_id"))

    def test_post_resume_queues(self):
        with mock.patch.object(idea_to_paper, "start_run", return_value={"ok": True, "run_id": "rid1", "resume": True}) as sr:
            req = __import__("urllib.request").request.Request(
                self.base + "/api/research/idea-to-paper",
                data=json.dumps({"run_id": "rid1", "resume": True}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with __import__("urllib.request").request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode())
            self.assertTrue(data.get("ok"), data)
            self.assertTrue(data.get("resume"))
            self.assertEqual(sr.call_args.kwargs.get("resume_id"), "rid1")


if __name__ == "__main__":
    unittest.main()

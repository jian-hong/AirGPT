"""Phase 0/1 foundation tests for AirGPT RAG Agent (offline, no Docker)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock


class RagFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        root = Path(self._tmpdir.name)
        self.data = root / "data"
        self.data.mkdir()
        self.fixture = root / "corpus"
        self.fixture.mkdir()
        (self.fixture / "alpha.md").write_text(
            "# Alpha Protocol\n\nAirGPT uses local-first RAG with parent-child chunks.\n\n"
            "## Hybrid search\n\nDense and sparse retrieval fuse with RRF.\n",
            encoding="utf-8",
        )
        (self.fixture / "beta.py").write_text(
            '"""Beta module for file-level search."""\n\n'
            "def build_rag_index(space_id: int) -> dict:\n"
            "    return {'ok': True, 'space_id': space_id}\n",
            encoding="utf-8",
        )

        import rag.store as store

        self.store = store
        self._orig_dir = store.RAG_DIR
        self._orig_db = store.DB_PATH
        self._orig_blob = store.BLOB_DIR
        store.RAG_DIR = self.data / "rag"
        store.DB_PATH = store.RAG_DIR / "rag.db"
        store.BLOB_DIR = store.RAG_DIR
        store.init()

    def tearDown(self) -> None:
        self.store.RAG_DIR = self._orig_dir
        self.store.DB_PATH = self._orig_db
        self.store.BLOB_DIR = self._orig_blob

    def test_chunk_parent_child(self):
        from rag.chunking import parent_child_chunk

        text = (self.fixture / "alpha.md").read_text(encoding="utf-8")
        parents, children = parent_child_chunk(text)
        self.assertGreaterEqual(len(parents), 1)
        self.assertGreaterEqual(len(children), 1)
        self.assertTrue(any(c.parent_index >= 0 for c in children))

    def test_ingest_search_answer(self):
        from rag import answer, ingest, retrieve

        space = self.store.create_space("Fixture RAG", depth_default="high")
        sid = int(space["id"])
        out = ingest.ingest_paths(sid, [self.fixture], force=True)
        self.assertTrue(out.get("ok"), out)
        self.assertGreater(out.get("chunks") or 0, 0)
        self.assertGreaterEqual((out.get("metrics") or {}).get("embedded") or 0, 1)
        from rag import vectors

        st = vectors.available()
        self.assertTrue(st.get("ok"))
        self.assertIn(st.get("mode"), ("blob_cosine", "sqlite_vec"))

        hit = retrieve.search(sid, "hybrid search RRF", depth="high", top_k=5, debug=True)
        self.assertTrue(hit.get("ok"), hit)
        self.assertGreater(len(hit.get("hits") or []), 0)
        self.assertTrue(hit.get("trace_id"))

        file_hit = retrieve.search(sid, "build_rag_index", depth="high", top_k=5)
        self.assertTrue(file_hit.get("ok"))
        paths = " ".join(str(h.get("path") or "") for h in (file_hit.get("hits") or []))
        self.assertIn("beta.py", paths)

        ans = answer.answer(sid, "hybrid search RRF fusion", depth="high")
        self.assertTrue(ans.get("ok"))
        self.assertTrue(ans.get("citations"), ans)
        blob = (ans.get("answer") or "") + (ans.get("context") or "")
        self.assertTrue("RRF" in blob or "hybrid" in blob.lower(), blob[:400])

        # Streaming event sequence (extractive — no provider required)
        types = []
        deltas = 0
        for ev in answer.answer_events(sid, "hybrid search RRF", depth="high", use_llm=False):
            types.append(ev.get("type"))
            if ev.get("type") == "delta":
                deltas += 1
        self.assertIn("meta", types)
        self.assertIn("citations", types)
        self.assertIn("done", types)
        self.assertGreaterEqual(deltas, 1)

    def test_recall_at5_smoke(self):
        """Golden-set Recall@5 over a small fixture corpus (acceptance #10)."""
        from rag import ingest, retrieve

        # Distractor docs so top-5 ranking is non-trivial (not just the 2 base files)
        (self.fixture / "gamma.md").write_text(
            "# Gamma Vectors\n\nGamma covers vector embeddings and cosine similarity scoring.\n",
            encoding="utf-8",
        )
        (self.fixture / "delta.md").write_text(
            "# Delta Rerank\n\nDelta describes the reranker cross-encoder BGE pass over fused hits.\n",
            encoding="utf-8",
        )
        (self.fixture / "epsilon.md").write_text(
            "# Epsilon Cache\n\nEpsilon notes the RAM and SSD cache layers for cited answers.\n",
            encoding="utf-8",
        )

        space = self.store.create_space("Recall RAG", depth_default="high")
        sid = int(space["id"])
        out = ingest.ingest_paths(sid, [self.fixture], force=True)
        self.assertTrue(out.get("ok"), out)

        golden = [
            ("hybrid dense sparse RRF fusion", "alpha.md"),
            ("parent child chunks local-first", "alpha.md"),
            ("build_rag_index function definition", "beta.py"),
            ("gamma vector embeddings cosine similarity", "gamma.md"),
            ("delta reranker cross encoder BGE", "delta.md"),
        ]
        hits_ok = 0
        for query, expect in golden:
            res = retrieve.search(sid, query, depth="high", top_k=5)
            self.assertTrue(res.get("ok"), res)
            paths = " ".join(str(c.get("path") or "") for c in (res.get("citations") or []))
            if expect in paths:
                hits_ok += 1
        recall = hits_ok / len(golden)
        self.assertGreaterEqual(recall, 0.8, f"Recall@5={recall:.2f} below floor (hits={hits_ok}/{len(golden)})")

    def test_depth_tiers_and_manual(self):
        """Basic = one-pass hybrid; Manual maps a preset architecture to a base pipeline."""
        from rag import ingest, retrieve

        basic = self.store.create_space("Basic RAG", depth_default="basic")
        self.assertEqual(basic["depth_default"], "basic")
        sid = int(basic["id"])
        out = ingest.ingest_paths(sid, [self.fixture], force=True)
        self.assertTrue(out.get("ok"), out)
        res = retrieve.search(sid, "hybrid search RRF", depth="basic", top_k=5)
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(res.get("template_id"), "modular_hybrid_basic")
        self.assertGreater(len(res.get("hits") or []), 0)
        # Basic skips SiRA expansion
        self.assertEqual((res.get("debug") or {}).get("expand_terms"), [])

        manual = self.store.create_space(
            "Manual RAG", depth_default="manual", config={"architecture": "graph"}
        )
        self.assertEqual(manual["depth_default"], "manual")
        mid = int(manual["id"])
        ingest.ingest_paths(mid, [self.fixture], force=True)
        mres = retrieve.search(mid, "hybrid search RRF", depth="manual", top_k=5)
        self.assertTrue(mres.get("ok"), mres)
        self.assertEqual(mres.get("template_id"), "manual_graph")

        # settings update flow
        updated = self.store.update_space_settings(mid, name="Renamed RAG", depth_default="high")
        self.assertEqual(updated["name"], "Renamed RAG")
        self.assertEqual(updated["depth_default"], "high")

    def test_corrective_loop_caps(self):
        """High runs ≤1 bounded corrective retrieve; Basic never loops; gaps disclosed."""
        from rag import answer, ingest

        space = self.store.create_space("Loop RAG", depth_default="high")
        sid = int(space["id"])
        out = ingest.ingest_paths(sid, [self.fixture], force=True)
        self.assertTrue(out.get("ok"), out)

        # Two salient tokens that exist nowhere → coverage stays low → one
        # constrained corrective round, then stop with disclosure.
        q = "hybrid zzzalphaterm zzzbetaterm"
        hi = answer.answer(sid, q, depth="high", use_llm=False)
        self.assertTrue(hi.get("ok"), hi)
        self.assertEqual(hi.get("rounds"), 2)
        self.assertEqual(hi.get("stop_reason"), "gaps_disclosed")
        self.assertIn("may not cover", hi.get("answer") or "")
        self.assertIn("zzzalphaterm", hi.get("answer") or "")

        ba = answer.answer(sid, q, depth="basic", use_llm=False)
        self.assertEqual(ba.get("rounds"), 1)

        # Well-covered query stops at round 1 with evidence_ok
        ok = answer.answer(sid, "hybrid search RRF", depth="high", use_llm=False)
        self.assertEqual(ok.get("rounds"), 1)
        self.assertEqual(ok.get("stop_reason"), "evidence_ok")
        self.assertGreaterEqual(ok.get("coverage") or 0, 0.6)

        # Max cap is 3 — with nothing retrievable at all it must not exceed it
        none = answer.answer(sid, "zzzgamma zzzdelta zzzepsilon", depth="max", use_llm=False)
        self.assertLessEqual(none.get("rounds") or 0, 3)
        self.assertIn(none.get("stop_reason"), ("no_evidence", "gaps_disclosed"))

    def test_space_summary_from_chunks(self):
        """Overview blurb is content-derived (not pipeline boilerplate)."""
        from rag import answer, ingest

        space = self.store.create_space("Summary RAG", depth_default="basic")
        sid = int(space["id"])
        out = ingest.ingest_paths(sid, [self.fixture], force=True)
        self.assertTrue(out.get("ok"), out)
        summ = answer.summarize_space(sid, use_llm=False, force=True)
        self.assertTrue(summ.get("ok"), summ)
        text = (summ.get("summary") or "").lower()
        self.assertTrue(text)
        self.assertNotIn("chunk → enrich", text)
        self.assertNotIn("no cloud corpus", text)
        # Themes come from fixture headings / titles
        self.assertTrue(
            "hybrid" in text or "rrf" in text or "parent" in text or "summary rag" in text,
            text[:300],
        )

    def test_session_transcript_ingest(self):
        """Chats attach as markdown transcript sources via the pure helper."""
        from rag import ingest, retrieve

        space = self.store.create_space("Chat RAG", depth_default="high")
        sid = int(space["id"])
        files = ingest.write_session_transcripts(
            sid,
            [
                {
                    "id": 7,
                    "title": "Serdes bringup notes",
                    "messages": [
                        {"role": "user", "text": "How do we calibrate the serdes eye diagram?"},
                        {"role": "assistant", "text": "Use the golden loopback fixture and sweep pre-emphasis taps."},
                    ],
                },
                {"id": 8, "title": "Empty chat", "messages": [{"role": "user", "text": "   "}]},
            ],
        )
        self.assertEqual(len(files), 1)  # empty chat skipped
        self.assertTrue(files[0].name == "chat_7.md")
        out = ingest.ingest_paths(sid, files, force=True)
        self.assertTrue(out.get("ok"), out)
        res = retrieve.search(sid, "serdes eye diagram calibration", depth="high", top_k=5)
        self.assertTrue(res.get("ok"))
        paths = " ".join(str(c.get("path") or "") for c in (res.get("citations") or []))
        self.assertIn("chat_7.md", paths)

        # source delete cleans chunks
        sources = self.store.list_sources(sid)
        self.assertTrue(sources)
        deleted = self.store.delete_source(int(sources[0]["id"]))
        self.assertTrue(deleted.get("ok"), deleted)
        self.assertGreater(deleted.get("chunks_removed") or 0, 0)

    def test_research_bridge_and_urls(self):
        """Research→Add-to-RAG validates library paths; URL ingest validates schemes."""
        from rag import ingest, retrieve
        import research as research_lib

        space = self.store.create_space("Bridge RAG", depth_default="high")
        sid = int(space["id"])

        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        papers = root / "papers" / "general"
        papers.mkdir(parents=True)
        (papers / "paper1.md").write_text(
            "# Paper One\n\nQuantum serdes calibration protocol details.\n", encoding="utf-8"
        )
        (papers / "scan.pdf").write_bytes(b"%PDF-1.4 fake")
        outside = root.parent / "evil.md"

        with mock.patch.object(research_lib, "RESEARCH", root):
            out = ingest.ingest_research(
                sid, [str(papers / "paper1.md"), str(papers / "scan.pdf"), str(outside)]
            )
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out.get("research_attached"), 1)
        reasons = " ".join(s["reason"] for s in out.get("skipped") or [])
        self.assertIn("outside research library", reasons)
        if not ingest.pdf_supported():
            self.assertIn("pdf needs text extract", reasons)

        r = retrieve.search(sid, "quantum serdes calibration", depth="high", top_k=5)
        paths = " ".join(str(c.get("path") or "") for c in r.get("citations") or [])
        self.assertIn("paper1.md", paths)

        # URL scheme validation (offline — no fetch happens for rejected schemes)
        bad = ingest.ingest_urls(sid, ["ftp://host/x", "file:///etc/passwd"])
        self.assertFalse(bad.get("ok"))
        self.assertEqual(len(bad.get("failed_urls") or []), 2)

        title, text = ingest.html_to_text(
            "<html><head><title>T1</title><script>x()</script></head>"
            "<body><h1>Head</h1><p>Alpha beta.</p></body></html>"
        )
        self.assertEqual(title, "T1")
        self.assertIn("Alpha beta.", text)
        self.assertNotIn("x()", text)

    def test_benchmark_modes(self):
        """Per-mode benchmark reports task-type metrics + a recommendation."""
        from rag import evaluate, ingest

        space = self.store.create_space("Bench RAG", depth_default="high")
        sid = int(space["id"])
        out = ingest.ingest_paths(sid, [self.fixture], force=True)
        self.assertTrue(out.get("ok"), out)

        golden = [
            {"query": "hybrid dense sparse RRF fusion", "expect_path": "alpha.md", "task_type": "fact_lookup"},
            {"query": "parent child chunks local-first", "expect_path": "alpha.md", "task_type": "fact_lookup"},
            {"query": "build_rag_index function", "expect_path": "beta.py", "task_type": "file_find"},
        ]
        bench = evaluate.benchmark_modes(sid, golden, depths=("basic", "high"), k=5)
        self.assertTrue(bench.get("ok"), bench)
        self.assertEqual(set(bench["depths"]), {"basic", "high"})
        for d in ("basic", "high"):
            self.assertIn("fact_lookup", bench["results"][d]["tasks"])
            self.assertIn("file_find", bench["results"][d]["tasks"])
            self.assertIn("avg_ms", bench["results"][d]["overall"])
        self.assertGreaterEqual(bench["results"]["high"]["overall"]["recall_at_k"], 0.66)
        self.assertIn(bench["recommend"].get("fact_lookup"), ("basic", "high"))
        self.assertIn(bench["recommend"].get("file_find"), ("basic", "high"))

    def test_sira_df_guard(self):
        from rag.sira import expand_query, filter_phrases_by_df

        df = {"alpha": 1, "the": 10, "missing": 0}
        kept = filter_phrases_by_df(["Alpha", "the", "missing"], df, n_docs=10, max_df_ratio=0.5)
        self.assertIn("Alpha", kept)
        self.assertNotIn("the", kept)
        self.assertNotIn("missing", kept)
        terms = expand_query("alpha protocol", index_phrases=["Alpha Protocol", "unrelated"], df=df, n_docs=10)
        self.assertTrue(any("alpha" in t.lower() for t in terms))

    def test_sira_llm_enrich_soft_fail(self):
        """Default==heuristic; mocked LLM merges; raise→fallback. Env opt-in only."""
        from unittest import mock

        from rag import sira

        text = "# Alpha Protocol\n\nDense and sparse retrieval fuse with RRF.\n"
        base = sira.heuristic_index_phrases(text)
        # Default / no env → identical to heuristic
        with mock.patch.dict("os.environ", {"AIRGPT_RAG_ENRICH": ""}, clear=False):
            self.assertEqual(sira.index_phrases(text), base)

        with mock.patch.dict("os.environ", {"AIRGPT_RAG_ENRICH": "llm"}, clear=False):
            with mock.patch.object(sira, "llm_index_phrases", return_value=["RRF fusion", "Alpha Protocol"]):
                merged = sira.index_phrases(text, use_llm=True)
            self.assertIn("RRF fusion", merged)
            self.assertTrue(any("alpha" in p.lower() for p in merged))

            with mock.patch.object(sira, "llm_index_phrases", side_effect=RuntimeError("No text LLM")):
                fallback = sira.index_phrases(text, use_llm=True)
            self.assertEqual(fallback, base)

        # Explicit use_llm=False ignores env
        with mock.patch.dict("os.environ", {"AIRGPT_RAG_ENRICH": "llm"}, clear=False):
            self.assertEqual(sira.index_phrases(text, use_llm=False), base)

    def test_intent_and_commands(self):
        from rag.intents import classify_intent
        import commands
        import mentions

        rag_i = classify_intent("please index this folder into a knowledge base")
        self.assertEqual(rag_i["intent"], "rag")
        self.assertIsNotNone(rag_i["suggest"])
        mem_i = classify_intent("what did we decide last time from memory")
        self.assertEqual(mem_i["intent"], "memory")

        parsed = commands.parse_slash("/depth max")
        self.assertEqual(parsed["command"], "depth")
        self.assertEqual(parsed["args"], "max")

        skill = commands.parse_slash("/skill research")
        self.assertEqual(skill["command"], "skill")
        self.assertEqual(skill["args"], "research")

        found = mentions.find_mentions("use @rag:fixture and @memory please")
        kinds = {m["kind"] for m in found}
        self.assertIn("rag", kinds)
        self.assertIn("memory", kinds)

    def test_seed_agents(self):
        import agent_store
        from rag.agents import seed_rag_agents

        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        db = Path(td.name) / "agents.db"
        with mock.patch.object(agent_store, "DB_PATH", db):
            agent_store.init()
            out = seed_rag_agents()
            self.assertTrue(out.get("ok"), out)
            agents = agent_store.list_agents()
            names = {a["name"] for a in agents}
            # Memory is a product panel (memFab), not a Cortex agent
            self.assertNotIn("Memory", names)
            self.assertIn("RAG", names)
            rag = next(a for a in agents if a["name"] == "RAG")
            self.assertTrue(rag.get("pinned"))


if __name__ == "__main__":
    unittest.main()

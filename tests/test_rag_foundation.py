"""Phase 0/1 foundation tests for AirGPT RAG Agent (offline, no Docker)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class RagFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        # Keep the suite on the hash embedder — BGE is enabled for the app via
        # env.local / auto-cache, but 4k+ encode calls would make CI unusable.
        self._embed_env = mock.patch.dict(os.environ, {"AIRGPT_RAG_EMBED": "hash"}, clear=False)
        self._embed_env.start()
        self.addCleanup(self._embed_env.stop)
        from rag import embed as _embed

        _embed.reset_embedder_cache()
        self.addCleanup(_embed.reset_embedder_cache)

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
        parents, children, _ = parent_child_chunk(text)
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
        # Disclosure is now quantified by rag.goal instead of a bare "may not cover"
        # note: the answer states how much of the question the sources actually reach
        # and names the terms that are missing.
        body = hi.get("answer") or ""
        self.assertIn("zzzalphaterm", body)
        self.assertIn("zzzbetaterm", body)
        self.assertRegex(body, r"\d+% of the asked terms")
        g = hi.get("goal") or {}
        self.assertEqual(g.get("verdict"), "partial")
        self.assertIn("zzzalphaterm", g.get("missing") or [])

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

    def test_ingest_progress_callback(self):
        """ingest_paths drives a monotonic progress bar ending at 100 / ready."""
        from rag import ingest

        space = self.store.create_space("Progress RAG", depth_default="high")
        sid = int(space["id"])
        events = []
        out = ingest.ingest_paths(
            sid, [self.fixture], force=True,
            progress=lambda stage, pct, detail: events.append((stage, pct)),
        )
        self.assertTrue(out.get("ok"), out)
        self.assertTrue(events, "no progress events")
        pcts = [p for _, p in events]
        self.assertEqual(pcts, sorted(pcts), "progress went backwards")
        self.assertEqual(pcts[-1], 100)
        stages = {s for s, _ in events}
        self.assertTrue({"chunk", "embed", "publish"} <= stages, stages)

    def test_self_score_autogolden(self):
        """Auto-generated test cases score retrieval per mode with a headline recall."""
        from rag import evaluate, ingest

        # A few distinct docs so the auto-golden has discriminative queries
        (self.fixture / "gamma.md").write_text(
            "# Gamma Vectors\n\nGamma covers vector embeddings cosine similarity scoring nearest neighbours.\n",
            encoding="utf-8",
        )
        (self.fixture / "delta.md").write_text(
            "# Delta Rerank\n\nDelta describes the reranker cross encoder BGE pass over fused candidate hits.\n",
            encoding="utf-8",
        )
        space = self.store.create_space("Score RAG", depth_default="high")
        sid = int(space["id"])
        self.assertTrue(ingest.ingest_paths(sid, [self.fixture], force=True).get("ok"))

        golden = evaluate.autogenerate_golden(sid, n=8)
        self.assertGreaterEqual(len(golden), 3)
        for g in golden:
            self.assertTrue(g["query"] and g["expect_path"] and g["task_type"])

        out = evaluate.self_score(sid, n=8, k=5, depths=("basic", "high"))
        self.assertTrue(out.get("ok"), out)
        self.assertIn("headline", out)
        self.assertIn(out["headline"]["best_mode"], ("basic", "high"))
        self.assertGreaterEqual(out["headline"]["best_recall_at_k"], 0.5)
        self.assertGreaterEqual(out.get("golden_size") or 0, 3)
        self.assertTrue(out.get("sample_cases"))

    def test_neighbor_window_expansion(self):
        """Adjacent chunks are pulled around a hit to widen long-passage context."""
        from rag import answer, ingest

        doc = self.fixture / "long.md"
        doc.write_text(
            "# Neighbours\n\n"
            "## One\n\nSection ONE talks about apples and orchard irrigation schedules in detail here.\n\n"
            "## Two\n\nSection TWO talks about bananas and tropical ripening chambers in detail here.\n\n"
            "## Three\n\nSection THREE talks about cherries and cold-chain logistics in detail here.\n\n"
            "## Four\n\nSection FOUR talks about durians and controlled fermentation in detail here.\n\n"
            "## Five\n\nSection FIVE talks about elderberries and pectin extraction in detail here.\n",
            encoding="utf-8",
        )
        space = self.store.create_space("Neighbour RAG", depth_default="high")
        sid = int(space["id"])
        self.assertTrue(ingest.ingest_paths(sid, [doc], force=True).get("ok"))

        # a middle child chunk should have neighbours on both sides
        children = [
            c for c in self.store.get_chunks_by_ids(
                [r["id"] for r in self._all_child_ids(sid)]
            )
        ]
        self.assertGreaterEqual(len(children), 3, "need multiple child chunks")
        mid = sorted(children, key=lambda c: c["span_start"])[len(children) // 2]
        nb = self.store.neighbor_window(int(mid["id"]), radius=1)
        self.assertTrue(nb, "no neighbours returned")
        self.assertNotIn(int(mid["id"]), [int(n["id"]) for n in nb])

        # context with neighbours is richer than the bare hit
        hit = {"chunk_id": int(mid["id"]), "path": mid["path"], "heading": mid["heading"], "text": mid["text"], "span_start": mid["span_start"]}
        bare = answer.build_context_block([hit], neighbors=False)
        wide = answer.build_context_block([hit], neighbors=True)
        self.assertGreater(len(wide), len(bare), "neighbour expansion did not widen context")

    def _all_child_ids(self, sid):
        with self.store._conn() as conn:
            return conn.execute(
                "SELECT id FROM chunks WHERE space_id=? AND kind='child'", (int(sid),)
            ).fetchall()

    def test_structured_html_json_ingest(self):
        """HTML/JSON parsed structure-aware — no tag/brace soup or scripts; retrievable."""
        from rag import ingest, retrieve

        (self.fixture / "page.html").write_text(
            "<html><head><title>Serdes Guide</title><style>.x{color:red}</style></head>"
            "<body><h1>Eye Diagram</h1><p>Calibrate serdes with golden loopback sweeps.</p>"
            "<script>tracker()</script></body></html>",
            encoding="utf-8",
        )
        (self.fixture / "config.json").write_text(
            '{"service":"embedder","backend":"bge","dims":384}', encoding="utf-8"
        )
        space = self.store.create_space("Struct RAG", depth_default="high")
        sid = int(space["id"])
        self.assertTrue(ingest.ingest_paths(sid, [self.fixture], force=True).get("ok"))

        with self.store._conn() as c:
            blob = " ".join(
                r["text"] for r in c.execute(
                    "SELECT text FROM chunks WHERE space_id=? AND "
                    "(path LIKE '%page.html' OR path LIKE '%config.json')",
                    (sid,),
                )
            )
        self.assertNotIn("<script", blob)
        self.assertNotIn("tracker()", blob)
        self.assertNotIn("</p>", blob)
        self.assertIn("golden loopback", blob)
        self.assertIn("backend: bge", blob)  # JSON flattened to key: value

        r = retrieve.search(sid, "serdes eye diagram loopback calibration", depth="high", top_k=5)
        self.assertIn("page.html", " ".join(str(c.get("path") or "") for c in r.get("citations") or []))
        j = retrieve.search(sid, "embedder backend bge dims", depth="high", top_k=5)
        self.assertIn("config.json", " ".join(str(c.get("path") or "") for c in j.get("citations") or []))

    def test_multi_query_expansion(self):
        """Synonym rephrasings recover paraphrase recall; no-expander path is identity."""
        from rag import expand, ingest, retrieve

        (self.fixture / "watering.md").write_text(
            "# Module watering\n\nThe irrigation scheduler waters crops based on soil moisture sensors.\n",
            encoding="utf-8",
        )
        (self.fixture / "ripening.md").write_text(
            "# Module ripening\n\nThe controller ripens bananas inside warm tropical chambers.\n",
            encoding="utf-8",
        )
        space = self.store.create_space("Expand RAG", depth_default="high")
        sid = int(space["id"])
        self.assertTrue(ingest.ingest_paths(sid, [self.fixture], force=True).get("ok"))

        # Paraphrase (synonyms, ~0 keyword overlap). A good expander bridges it.
        q = "device that matures plantains in heated humid enclosures"
        stub = lambda x: ["banana ripening warm tropical chamber controller"]
        exp = expand.multi_query_search(sid, q, depth="high", top_k=3, expander=stub)
        paths = " ".join(str(c.get("path") or "") for c in exp.get("citations") or [])
        self.assertIn("ripening.md", paths)
        self.assertTrue(exp.get("expanded_queries"))

        # No-expander → identity: byte-for-byte the same result as retrieve.search (no regression)
        ident = expand.multi_query_search(sid, "banana ripening", depth="high", top_k=3, expander=lambda x: [])
        base = retrieve.search(sid, "banana ripening", depth="high", top_k=3)
        self.assertEqual(
            [c.get("chunk_id") for c in ident.get("citations") or []],
            [c.get("chunk_id") for c in base.get("citations") or []],
        )

    def test_expansion_preserves_exact_rank(self):
        """SiRA expansion (high/max) must not demote an exact heading match below rank 1."""
        from rag import ingest, retrieve

        mods = [
            ("quantum_flux", "Quantum Flux Calibrator"),
            ("orchard_irrig", "Orchard Irrigation Scheduler"),
            ("banana_ripen", "Banana Ripening Controller"),
            ("serdes_eye", "Serdes Eye Diagram Analyzer"),
        ]
        for slug, title in mods:
            (self.fixture / f"{slug}.md").write_text(
                f"# {title}\n\nThis module processes input through the standard configurable "
                f"pipeline with options for tuning, validation, and reporting.\n",
                encoding="utf-8",
            )
        space = self.store.create_space("Rank RAG", depth_default="high")
        sid = int(space["id"])
        self.assertTrue(ingest.ingest_paths(sid, [self.fixture], force=True).get("ok"))

        for slug, title in (mods[0], mods[3]):
            for depth in ("basic", "high", "max"):
                cites = retrieve.search(sid, title, depth=depth, top_k=5).get("citations") or []
                top = Path(str((cites[0] if cites else {}).get("path") or "")).name
                self.assertEqual(top, f"{slug}.md", f"{depth}: {title!r} ranked {top} at #1, expected {slug}.md")

    def test_faithfulness_verify(self):
        """Unsupported (hallucinated) claims are flagged; grounded answers score high."""
        from rag import answer, ingest

        context = (
            "[1] rrf.md\nReciprocal Rank Fusion combines multiple ranked lists by summing "
            "reciprocal ranks. It is used in hybrid search to merge dense and sparse results."
        )
        good = "Reciprocal Rank Fusion merges dense and sparse ranked lists by summing reciprocal ranks."
        r1 = answer.verify_faithfulness(good, context)
        self.assertGreaterEqual(r1["score"], 0.9)
        self.assertEqual(r1["unsupported"], [])

        bad = (
            "Reciprocal Rank Fusion merges ranked lists. "
            "It was invented by Napoleon Bonaparte in 1823 for artillery targeting."
        )
        r2 = answer.verify_faithfulness(bad, context)
        self.assertLess(r2["score"], 1.0)
        self.assertTrue(any("Napoleon" in s for s in r2["unsupported"]))

        # flows through the answer() API (extractive path is grounded by construction)
        space = self.store.create_space("Faith RAG", depth_default="high")
        sid = int(space["id"])
        ingest.ingest_paths(sid, [self.fixture], force=True)
        out = answer.answer(sid, "hybrid search RRF fusion", depth="high", use_llm=False)
        self.assertIn("faithfulness", out)
        self.assertEqual(out["faithfulness"], 1.0)

    def test_hard_mode_golden(self):
        """Hard difficulty drops headings + uses mid-frequency tokens → real discrimination."""
        from rag import evaluate, ingest

        for slug in ("modone", "modtwo", "modthree", "modfour"):
            (self.fixture / f"{slug}.md").write_text(
                f"# {slug.title()} Service\n\nThe {slug} component processes streaming data through "
                f"configurable pipelines with validation, caching and reporting options.\n",
                encoding="utf-8",
            )
        space = self.store.create_space("Hard RAG", depth_default="high")
        sid = int(space["id"])
        self.assertTrue(ingest.ingest_paths(sid, [self.fixture], force=True).get("ok"))

        easy = evaluate.autogenerate_golden(sid, n=8, hard=False)
        hard = evaluate.autogenerate_golden(sid, n=8, hard=True)
        self.assertTrue(easy and hard)
        # the difficulty knob must actually change the generated queries
        self.assertNotEqual([g["query"] for g in easy], [g["query"] for g in hard])
        # hard queries drop the heading word ("Service") that file-level search trivially matches
        self.assertTrue(any("Service" in g["query"] for g in easy))
        self.assertFalse(any("Service" in g["query"] for g in hard))

        sc = evaluate.self_score(sid, n=6, k=5, depths=("high",), hard=True)
        self.assertTrue(sc.get("ok"), sc)
        self.assertEqual(sc.get("difficulty"), "hard")

    def test_lexical_rerank(self):
        """Full-coverage target beats a higher-score low-coverage distractor; neutral on no-overlap."""
        from rag.answer import _lexical_rerank

        hits = [
            {"chunk_id": 1, "text": "generic port for research", "heading": "", "score": 0.06},          # cov 1/3, top score
            {"chunk_id": 2, "text": "idempotent activation port handshake described", "heading": "", "score": 0.04},  # cov 3/3 (target)
            {"chunk_id": 3, "text": "unrelated content about video plans", "heading": "", "score": 0.01},  # cov 0
        ]
        ranked = _lexical_rerank("idempotent activation port", hits)
        self.assertEqual(ranked[0]["chunk_id"], 2, "full-coverage target should rank first")

        # no query-term overlap → falls back to retrieval-score order (paraphrase-neutral)
        neutral = _lexical_rerank("bananas grapes elderberry", hits)
        self.assertEqual(neutral[0]["chunk_id"], 1, "no overlap → highest score wins")

    def test_code_symbol_chunking(self):
        """Code splits on def/class boundaries (not '#' comments) → coherent chunks."""
        from rag.chunking import parent_child_chunk

        code = (
            '"""Module docstring."""\n\n'
            'import os\n\n'
            '# a comment that must NOT become a chunk boundary\n'
            'def alpha(x):\n    return x + 1\n\n'
            'def bravo(y):\n    # inner comment\n    return y * 2\n\n'
            'class Charlie:\n    def method(self):\n        return 3\n'
        )
        parents, _, _ = parent_child_chunk(code, code=True)
        heads = [p.text.strip().splitlines()[0] for p in parents]
        self.assertTrue(any(h.startswith("def alpha") for h in heads))
        self.assertTrue(any(h.startswith("def bravo") for h in heads))
        self.assertTrue(any(h.startswith("class Charlie") for h in heads))
        # the '#' comment must NOT have become its own section head
        self.assertFalse(any(h.startswith("# a comment") for h in heads))

        # markdown path unaffected: '#' headings still split prose
        md, _, _ = parent_child_chunk("# Title\n\nbody text here\n\n# Two\n\nmore text here\n", code=False)
        self.assertGreaterEqual(len(md), 2)

    # Row shape for the table gate: five fields, a marker that only survives an
    # uncut row, and no blank lines anywhere (the shape that used to char-split).
    ROW_FIELDS = 5
    ROW_END = "<eor>"

    def _sheet_body(self, n_rows: int = 40) -> str:
        tail = ("x" * 74) + self.ROW_END
        return "## Sheet: Carrier\n" + "\n".join(
            f"r{i} | CarrierA | 12.5 | true | {tail}" for i in range(n_rows)
        )

    def _broken_rows(self, chunks) -> list[str]:
        """Every chunk line that is not the sheet heading and not a WHOLE row.

        Checked positively over ALL lines: a truncated row must be REPORTED, not
        silently skipped by an `if needle in line` that a cut row cannot match.
        """
        bad: list[str] = []
        for ch in chunks:
            for line in (getattr(ch, "text", "") or "").splitlines():
                line = line.strip()
                if not line or line.startswith("## "):
                    continue
                whole = (
                    line.startswith("r")
                    and line.count(" | ") == self.ROW_FIELDS - 1
                    and line.endswith(self.ROW_END)
                )
                if not whole:
                    bad.append(line[:60])
        return bad

    def test_table_chunking_never_splits_row(self):
        """Sheet extract: heading parents, whole-row children, never mid-row cut."""
        from rag.chunking import parent_child_chunk

        body = self._sheet_body(40)
        parents, children, metrics = parent_child_chunk(
            body, table=True, child_tokens=80, parent_max_tokens=200
        )
        self.assertTrue(metrics["table"])
        self.assertGreaterEqual(len(parents), 1)
        self.assertGreaterEqual(len(children), 2)
        self.assertEqual(self._broken_rows(children), [], "child window cut a row")
        self.assertEqual(self._broken_rows(parents), [], "parent window cut a row")
        # …and no row was dropped on the way through the windower.
        seen = {
            line.split(" | ", 1)[0]
            for ch in children
            for line in (ln.strip() for ln in ch.text.splitlines())
            if line.startswith("r")
        }
        self.assertEqual(seen, {f"r{i}" for i in range(40)}, "rows lost, not just intact")

        # CONTROL — the same body through the prose windower MUST break rows. Without
        # this the gate above could pass with _window_rows deleted (R-0007: a gate that
        # cannot fail is not a gate).
        _, prose_children, prose_m = parent_child_chunk(body, table=False, child_tokens=80)
        self.assertFalse(prose_m["table"])
        self.assertGreaterEqual(len(prose_children), 1)
        self.assertTrue(
            self._broken_rows(prose_children),
            "control produced no broken row — the row gate proves nothing",
        )

    def test_csv_gets_sheet_parents(self):
        """.csv extracts as `## Sheet:` + pipe rows, so parents carry a heading (#57)."""
        from rag import ingest
        from rag.chunking import parent_child_chunk

        csv_path = self.fixture / "carriers.csv"
        csv_path.write_text(
            'code,rate,note\nA1,12.5,"plain, quoted"\nB2,7.25,second\nC3,9.0,third\n',
            encoding="utf-8",
        )
        text, _digest = ingest.read_text_file(csv_path)
        self.assertIn("## Sheet: carriers", text)
        # the quoted comma stayed inside its cell (stdlib csv, not a split on ',')
        self.assertIn("A1 | 12.5 | plain, quoted", text)
        self.assertTrue(ingest.is_table_text(csv_path, text))

        parents, _children, _m = parent_child_chunk(text, table=True)
        headings = [p.heading for p in parents]
        self.assertTrue(any(h.startswith("Sheet: carriers") for h in headings), headings)
        self.assertNotEqual(headings, [""] * len(headings))

    def test_rebuild_blob_still_chunks_as_table(self):
        """Rebuild re-ingests the .txt blob — table-ness must survive the lost suffix."""
        from rag import chunking, ingest

        sheet = self.fixture / "sheet.csv"
        sheet.write_text(
            "code,rate,flag,note\n"
            + "\n".join(f"r{i},12.5,true,{'x' * 60}" for i in range(60))
            + "\n",
            encoding="utf-8",
        )
        space = self.store.create_space("Rebuild RAG", depth_default="high")
        sid = int(space["id"])
        self.assertTrue(ingest.ingest_paths(sid, [sheet], force=True).get("ok"))
        src = [s for s in self.store.list_sources(sid) if s["title"] == "sheet.csv"][0]
        self.assertTrue((src.get("meta") or {}).get("table"), "table-ness not persisted")

        # Original AND its Docs copy gone: rebuild falls back to the .txt blob.
        sheet.unlink()
        docs_copy = (src.get("meta") or {}).get("docs_path")
        if docs_copy and Path(docs_copy).is_file():
            Path(docs_copy).unlink()
        paths = ingest.rebuild_source_paths([src])
        self.assertEqual(len(paths), 1, paths)
        self.assertTrue(paths[0].endswith(".txt"), paths)
        blob_text = Path(paths[0]).read_text(encoding="utf-8")
        self.assertTrue(ingest.is_table_text(Path(paths[0]), blob_text))

        real = chunking.parent_child_chunk
        calls: list[tuple[bool, tuple]] = []

        def _spy(text, **kw):
            out = real(text, **kw)
            calls.append((bool(kw.get("table")), out))
            return out

        with mock.patch.object(chunking, "parent_child_chunk", _spy):
            self.assertTrue(ingest.ingest_paths(sid, paths, force=True).get("ok"))
        self.assertEqual([c[0] for c in calls], [True], "rebuild re-split the blob as prose")

        # Every chunk line is either a line the blob itself holds verbatim outside the
        # rows (index / sheet heading / csv header) or a WHOLE data row — matched
        # exactly, so a fragment can never slip through the skip.
        non_rows = {ln.strip() for ln in blob_text.splitlines() if not ln.strip().startswith("r")}

        def _check(texts, where):
            for body in texts:
                for line in (body or "").splitlines():
                    line = line.strip()
                    if not line or line in non_rows:
                        continue
                    self.assertTrue(
                        line.count(" | ") == 3 and line.endswith("x" * 60),
                        f"{where} cut a row: {line[:70]!r}",
                    )

        rebuilt_parents, rebuilt_children, _m = calls[0][1]
        _check([c.text for c in rebuilt_children], "rebuild child")
        _check([p.text for p in rebuilt_parents], "rebuild parent")
        rows = self.store.sample_parent_chunks(sid, limit=50)
        self.assertTrue(rows)
        _check([r.get("text") for r in rows], "stored chunk")

    def test_diversify_evidence(self):
        """Per-source cap + near-dup drop surface complementary evidence in top-k."""
        from rag.answer import _diversify

        hits = [
            {"chunk_id": i, "source_id": 1, "path": "a.md", "heading": "",
             "text": "the pipeline ranks with reciprocal rank fusion again"}
            for i in range(5)
        ] + [
            {"chunk_id": 10, "source_id": 2, "path": "b.md", "heading": "",
             "text": "the pipeline reranks with a cross encoder pass"},
            {"chunk_id": 11, "source_id": 3, "path": "c.md", "heading": "",
             "text": "unrelated video plan uses ltx2 cinematic motion"},
        ]
        out = _diversify(hits, k=4, max_per_source=2)
        srcs = [h["source_id"] for h in out]
        self.assertEqual(len(out), 4)
        self.assertLessEqual(srcs.count(1), 2, "source A not capped")
        self.assertIn(2, srcs, "complementary source B was crowded out")

        # backfill: a single-source corpus still returns k (doesn't starve)
        single = [
            {"chunk_id": i, "source_id": 1, "path": "a.md", "heading": "",
             "text": f"section {i} covers a distinct topic number {i}alpha here"}
            for i in range(6)
        ]
        self.assertEqual(len(_diversify(single, k=4, max_per_source=2)), 4)

    def test_spell_correct(self):
        """OOV (typo) tokens map to the closest corpus term; valid terms untouched."""
        from rag import ingest, spell

        (self.fixture / "sec.md").write_text(
            "# Security\n\nThe security hardening guide covers idempotent authentication and provider tokens.\n",
            encoding="utf-8",
        )
        space = self.store.create_space("Spell RAG", depth_default="high")
        sid = int(space["id"])
        self.assertTrue(ingest.ingest_paths(sid, [self.fixture], force=True).get("ok"))

        r = spell.correct_query("secuirty hardning", sid)
        self.assertIn("security", r)
        self.assertIn("hardening", r)
        self.assertIn("authentication", spell.correct_query("authentcation flow", sid))
        # valid corpus terms are left exactly as-is
        self.assertEqual(spell.correct_query("security hardening", sid), "security hardening")
        # short tokens and words with no close match are not corrupted
        self.assertEqual(spell.correct_query("xyz zzzzq", sid), "xyz zzzzq")
        # inflection guard: valid word forms must NOT be "corrected" to a corpus variant
        # ('provide' → 'provider' is a prefix relationship = inflection, not a typo)
        self.assertEqual(spell.correct_query("provide the tokens", sid), "provide the tokens")

    def test_embedder_upgrade_detect(self):
        """Under AIRGPT_RAG_EMBED=hash, surface an installed-but-inactive upgrade."""
        from rag import embed, vectors

        self.assertEqual(embed.backend_name(), "hash")
        up = embed.upgrade_available()
        self.assertIn("available", up)
        self.assertIn("active", up)
        v = vectors.available()
        self.assertIn("upgrade_available", v)
        self.assertIn("upgrade_hint", v)
        self.assertEqual(v["upgrade_available"], bool(up.get("available")))
        if up.get("available"):
            self.assertEqual(up["active"], "hash")
            self.assertTrue(up.get("hint"))
            self.assertTrue(v["upgrade_hint"])

    def test_embedder_bge_opt_in(self):
        """Explicit AIRGPT_RAG_EMBED=st loads BGE when sentence-transformers is present."""
        from rag import embed

        if not embed._st_installed():
            self.skipTest("sentence-transformers not installed")
        embed.reset_embedder_cache()
        with mock.patch.dict(os.environ, {"AIRGPT_RAG_EMBED": "st"}, clear=False):
            embed.reset_embedder_cache()
            # Prefer local cache; skip if weights missing (no download in CI).
            if not embed._bge_cached():
                self.skipTest("BGE weights not cached")
            name = embed.backend_name()
            self.assertEqual(name, "model", "st opt-in should activate real embedder")
            v = embed.embed_text("hybrid search reciprocal rank fusion")
            self.assertGreaterEqual(len(v), 64)
            self.assertNotEqual(len(v), embed.DEFAULT_DIM)  # BGE is 384-d, not hash-64
        embed.reset_embedder_cache()

    def test_self_score_skips_llm(self):
        """Scoring measures retrieval only — it must never invoke LLM generation."""
        from rag import answer as answer_mod
        from rag import evaluate, ingest

        space = self.store.create_space("EvalFast", depth_default="high")
        sid = int(space["id"])
        self.assertTrue(ingest.ingest_paths(sid, [self.fixture], force=True).get("ok"))

        seen: list = []
        orig = answer_mod.answer

        def spy(space_id, query, **kw):
            seen.append(kw.get("use_llm"))
            return orig(space_id, query, **kw)

        with mock.patch.object(answer_mod, "answer", spy):
            out = evaluate.self_score(sid, n=4, k=5, depths=("high",))
        self.assertTrue(out.get("ok"), out)
        self.assertTrue(seen, "scorer never called answer()")
        self.assertTrue(all(v is False for v in seen), f"scorer invoked the LLM: {seen}")

    def test_dense_scan_has_no_row_cap(self):
        """Dense search must scan every vector — a hard LIMIT silently hides later
        chunks from retrieval on large corpora (regression guard for LIMIT 4000)."""
        import struct

        from rag import embed, vectors

        space = self.store.create_space("Cap RAG", depth_default="high")
        sid = int(space["id"])
        vectors.available()  # ensure vector tables exist
        dim = len(embed.embed_text("probe"))

        rows = []
        for i in range(1, 4301):  # > the old 4000-row cap
            v = embed.embed_text(f"filler chunk number {i} with generic pipeline content")
            rows.append((i, sid, dim, "hash", struct.pack(f"{dim}f", *v)))
        target_id = 4301
        tv = embed.embed_text("zqxwv unique marker protocol")
        rows.append((target_id, sid, dim, "hash", struct.pack(f"{dim}f", *tv)))
        with self.store._conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO chunk_vectors(chunk_id,space_id,dim,backend,vec) "
                "VALUES(?,?,?,?,?)",
                rows,
            )

        hits = vectors.search(sid, "zqxwv unique marker protocol", k=5)
        ids = [c for c, _ in hits]
        self.assertIn(target_id, ids, "vector past the old 4000-row scan cap was unreachable")
        self.assertEqual(ids[0], target_id, "exact-text match should rank first")

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

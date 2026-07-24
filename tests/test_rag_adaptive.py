"""Tests for benchmark-backed automatic RAG depth selection."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


class AdaptiveRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        data = Path(self._tmpdir.name) / "data"

        from rag import store

        self.store = store
        self._orig_dir = store.RAG_DIR
        self._orig_db = store.DB_PATH
        self._orig_blob = store.BLOB_DIR
        store.RAG_DIR = data / "rag"
        store.DB_PATH = store.RAG_DIR / "rag.db"
        store.BLOB_DIR = store.RAG_DIR
        store.init()

    def tearDown(self) -> None:
        self.store.RAG_DIR = self._orig_dir
        self.store.DB_PATH = self._orig_db
        self.store.BLOB_DIR = self._orig_blob

    def test_recommended_and_resolved_depths(self) -> None:
        from rag import retrieve
        from rag.adaptive import recommended_depth, resolve_depth

        space = self.store.create_space("Adaptive", depth_default="max")
        space_id = int(space["id"])
        self.store.update_space_settings(
            space_id,
            config={
                "adaptive_recommend": {
                    "general": "high",
                    "fact_lookup": "basic",
                }
            },
        )

        self.assertEqual(recommended_depth(space_id, "fact_lookup"), "basic")
        self.assertEqual(recommended_depth(space_id, "unknown"), "high")
        self.assertEqual(resolve_depth(space_id, "auto", "fact_lookup"), "basic")
        self.assertEqual(resolve_depth(space_id, None), "high")
        self.assertEqual(resolve_depth(space_id, "manual"), "manual")

        search = retrieve.search(space_id, "unindexed query", depth="auto")
        self.assertTrue(search["ok"])
        self.assertEqual(search["depth"], "high")

    def test_resolve_falls_back_to_space_default(self) -> None:
        from rag.adaptive import recommended_depth, resolve_depth

        space = self.store.create_space("Default", depth_default="basic")
        space_id = int(space["id"])

        self.assertIsNone(recommended_depth(space_id))
        self.assertEqual(resolve_depth(space_id, ""), "basic")

    def test_benchmark_persists_recommendations(self) -> None:
        from rag import evaluate

        space = self.store.create_space("Benchmark", depth_default="high")
        space_id = int(space["id"])
        before = time.time()
        with mock.patch.object(
            evaluate,
            "_score_query",
            return_value={"hit": 1, "rr": 1.0, "rounds": 1, "coverage": 1.0, "ms": 1.0},
        ):
            result = evaluate.benchmark_modes(
                space_id,
                [{"query": "lookup", "expect_path": "doc.md", "task_type": "fact_lookup"}],
                depths=("basic", "high"),
            )

        saved = self.store.get_space(space_id)
        self.assertTrue(result["ok"])
        self.assertEqual(saved["config"]["adaptive_recommend"], result["recommend"])
        self.assertGreaterEqual(saved["config"]["adaptive_benchmark_at"], before)


if __name__ == "__main__":
    unittest.main()

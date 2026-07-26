"""Tests for profile-selected vector backends and semantic cache soft-fail."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock


class VectorBackendsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        root = Path(self._tmpdir.name)
        data = root / "data"
        data.mkdir()
        self._patchers = [
            mock.patch("rag.store.RAG_DIR", data / "rag"),
            mock.patch("rag.store.DB_PATH", data / "rag" / "rag.db"),
            mock.patch("rag.store.BLOB_DIR", data / "rag"),
        ]
        for p in self._patchers:
            p.start()
            self.addCleanup(p.stop)
        from rag import store, vectors

        store.init()
        # Reset vec ready flag when DB path changes
        vectors._VEC_READY = None
        self.store = store
        self.space = store.create_space("Backend Test", profile="local")
        self.sid = int(self.space["id"])

    def test_normalize_profile_aliases(self) -> None:
        from rag.vector_backends import normalize_profile

        self.assertEqual(normalize_profile("local+"), "local_qdrant")
        self.assertEqual(normalize_profile("local_plus"), "local_qdrant")
        self.assertEqual(normalize_profile("weird"), "local")

    def test_local_upsert_and_search(self) -> None:
        from rag import store, vectors

        cid = store.insert_chunk(
            space_id=self.sid,
            source_id=1,
            revision_id=1,
            text="AirGPT local hybrid retrieval uses sqlite vectors.",
            kind="child",
            path="a.md",
            heading="Hybrid",
        )
        self.assertTrue(vectors.upsert_chunk_vector(cid, self.sid, "AirGPT local hybrid retrieval"))
        hits = vectors.search(self.sid, "hybrid retrieval", k=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0][0], cid)

    def test_local_qdrant_ingest_fails_loudly_without_client(self) -> None:
        from rag.vector_backends import ProfileNotBuiltError, require_upsert_backend

        self.store.update_space_settings(self.sid, profile="local_qdrant")
        with self.assertRaises(ProfileNotBuiltError):
            require_upsert_backend(self.sid)

    def test_local_qdrant_search_soft_falls_to_local(self) -> None:
        from rag import store, vectors
        from rag.vector_backends import last_search_meta

        cid = store.insert_chunk(
            space_id=self.sid,
            source_id=1,
            revision_id=1,
            text="Qdrant soft fail still finds local vectors.",
            kind="child",
            path="b.md",
        )
        # Write via local path while profile is still local
        vectors._local_upsert_chunk_vector(cid, self.sid, "Qdrant soft fail still finds local vectors.")
        self.store.update_space_settings(self.sid, profile="local_qdrant")
        hits = vectors.search(self.sid, "soft fail local", k=5)
        meta = last_search_meta()
        self.assertEqual(meta.get("backend_fallback"), "local")
        self.assertTrue(hits)

    def test_business_not_built(self) -> None:
        from rag.vector_backends import ProfileNotBuiltError, require_upsert_backend

        self.store.update_space_settings(self.sid, profile="business")
        with self.assertRaises(ProfileNotBuiltError):
            require_upsert_backend(self.sid)

    def test_semantic_cache_miss_without_redis(self) -> None:
        from rag import semantic_cache

        with mock.patch.dict("os.environ", {"REDIS_URL": ""}, clear=False):
            # Force re-init of client flags
            semantic_cache._CLIENT = None
            semantic_cache._CLIENT_FAILED = False
            self.assertIsNone(semantic_cache.get_chunk_ids(self.sid, 1, "hello"))
            info = semantic_cache.available()
            self.assertFalse(info.get("ok"))

    def test_available_lists_profiles(self) -> None:
        from rag import vectors

        info = vectors.available()
        self.assertIn("profiles", info)
        self.assertTrue(info["profiles"]["local"]["built"])
        self.assertIn("local_qdrant", info["profiles"])
        self.assertIn("business", info["profiles"])


if __name__ == "__main__":
    unittest.main()

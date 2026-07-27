"""Origin-keyed authority scrub for spaces indexed before ingest-time tags."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag import authority, store  # noqa: E402


class ScrubAuthorityTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
        store.RAG_DIR = self.root / "rag"
        store.DB_PATH = store.RAG_DIR / "rag.db"
        store.BLOB_DIR = store.RAG_DIR
        store.reset_init_cache()
        store.init()

    def tearDown(self):
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = self._orig
        store.reset_init_cache()
        self._tmp.cleanup()

    def test_scrub_uses_original_path_when_live_name_is_pack_prefixed(self):
        sid = int(store.create_space("Laundry")["id"])
        src = store.add_source(
            sid,
            path=str(self.root / "sources" / "0001__chat_126.md"),
            title="0001__chat_126.md",
            meta={"original_path": "chat_126.md", "authority": authority.CONVERSATION},
            status="ready",
        )
        # Simulate a bad migration that trusted the pack-prefixed path.
        store.insert_chunk(
            space_id=sid,
            source_id=int(src["id"]),
            revision_id=1,
            text="An earlier guess about a company.",
            kind="child",
            path=str(src["path"]),
            authority=authority.DOCUMENT,
        )
        before = store.source_authority(int(src["id"]))
        self.assertEqual(before, authority.DOCUMENT)

        out = store.scrub_authority(sid, dry_run=False)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["chunks_updated"], 1)
        self.assertEqual(store.source_authority(int(src["id"])), authority.CONVERSATION)

        refreshed = store.list_sources(sid)[0]
        meta = refreshed.get("meta") or {}
        self.assertEqual(meta.get("authority"), authority.CONVERSATION)
        self.assertEqual(meta.get("original_path"), "chat_126.md")

    def test_resolve_prefers_declared_meta_over_path(self):
        src = {
            "path": "uploads/0001__chat_126.md",
            "title": "0001__chat_126.md",
            "meta": {"authority": authority.CONVERSATION, "original_path": "chat_126.md"},
        }
        self.assertEqual(store.resolve_source_authority(src), authority.CONVERSATION)
        # Without meta, pack prefix still fools the path classifier (by design).
        bare = {"path": "uploads/0001__chat_126.md", "title": "0001__chat_126.md", "meta": {}}
        self.assertEqual(store.resolve_source_authority(bare), authority.DOCUMENT)
        # original_path alone is enough.
        via_orig = {
            "path": "uploads/0001__chat_126.md",
            "title": "0001__chat_126.md",
            "meta": {"original_path": "chat_126.md"},
        }
        self.assertEqual(store.resolve_source_authority(via_orig), authority.CONVERSATION)


if __name__ == "__main__":
    unittest.main()

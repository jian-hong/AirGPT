"""Silent ANN backfill: pack existing blobs into sqlite-vec without re-embed."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rag import store, vectors


class AnnBackfillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        store.DB_PATH = Path(self.tmp.name) / "rag.db"
        vectors._VEC_READY = None
        vectors._USE_SQLITE_VEC = False
        vectors._VEC_DIM = 0
        vectors._VEC_TABLE = ""
        store.init()
        self.space = store.create_space("ann-test")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_status_without_vec_is_safe(self) -> None:
        with mock.patch.object(vectors, "_USE_SQLITE_VEC", False):
            st = vectors.ann_index_status(self.space["id"])
        self.assertTrue(st["ok"])
        self.assertFalse(st.get("needs_backfill"))

    def test_backfill_noop_when_synced(self) -> None:
        # No blobs → nothing to fill
        out = vectors.backfill_ann_index(self.space["id"])
        self.assertEqual(out.get("inserted"), 0)


if __name__ == "__main__":
    unittest.main()

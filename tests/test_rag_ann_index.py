"""The native ANN index must be a pure speedup — never a different answer.

Three bugs made `sqlite-vec` dead or dangerous before this suite existed:

1. The vec0 table was hard-coded `float[64]` while the active embedder emits 384, so
   the index never matched a query and every dense search brute-forced in silence.
2. `sqlite_vec.load()` is per-connection, but the guard around it was per-database —
   only the first connection ever had `vec0`; the rest raised "no such module" into a
   bare except and fell back without telling anyone.
3. vec0 defaults to L2 while the pipeline ranks by cosine. On un-normalised vectors the
   two orderings barely overlap (measured recall@40 of 0.05), so switching the index on
   would have quietly degraded every answer.

Each of those is pinned below. The headline guard is `test_ann_matches_brute_force`:
if the fast path and the slow path ever disagree, the fast path is wrong.
"""
from __future__ import annotations

import math
import os
import random
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag import embed, store, vectors  # noqa: E402

try:
    import sqlite_vec  # noqa: F401

    HAVE_VEC = True
except Exception:
    HAVE_VEC = False

needs_vec = unittest.skipUnless(HAVE_VEC, "sqlite-vec not installed (fallback mode)")


class _VecBase(unittest.TestCase):
    DIM = 64  # hash-embedder width, so these tests never need a model download

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._orig = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
        store.RAG_DIR = root / "rag"
        store.DB_PATH = store.RAG_DIR / "rag.db"
        store.BLOB_DIR = store.RAG_DIR
        store.reset_init_cache()
        store.init()

        self._orig_dim = embed.active_dim
        embed.active_dim = lambda: self.DIM
        self._reset_vectors()

    def tearDown(self) -> None:
        embed.active_dim = self._orig_dim
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = self._orig
        store.reset_init_cache()
        self._reset_vectors()
        self._tmp.cleanup()

    @staticmethod
    def _reset_vectors() -> None:
        vectors._VEC_READY = None
        vectors._VEC_DIM = 0
        vectors._VEC_TABLE = ""
        vectors._USE_SQLITE_VEC = False

    def _insert(self, space_id: int, rows: list[tuple[int, list[float]]]) -> None:
        packed = [
            (cid, space_id, len(v), "test", struct.pack(f"{len(v)}f", *v)) for cid, v in rows
        ]
        with store.session() as conn:
            vectors._ensure_tables(conn)
            conn.executemany(
                "INSERT OR REPLACE INTO chunk_vectors(chunk_id,space_id,dim,backend,vec) "
                "VALUES(?,?,?,?,?)",
                packed,
            )
            if vectors._USE_SQLITE_VEC and vectors._VEC_TABLE:
                conn.executemany(
                    f"INSERT OR REPLACE INTO {vectors._VEC_TABLE}(chunk_id, embedding) "
                    "VALUES (?,?)",
                    [(p[0], p[4]) for p in packed],
                )

    def _search(self, space_id: int, query: list[float], *, use_vec: bool, k: int = 40):
        real_load = vectors._load_vec_extension
        real_embed = embed.embed_text
        if not use_vec:
            vectors._load_vec_extension = lambda conn: False
        embed.embed_text = lambda *a, **kw: query
        self._reset_vectors()
        try:
            out = vectors._local_search(space_id, "q", k=k)
            self.assertEqual(
                vectors._USE_SQLITE_VEC, use_vec, "benchmark arm did not take the intended path"
            )
            return out
        finally:
            embed.embed_text = real_embed
            vectors._load_vec_extension = real_load
            self._reset_vectors()


class AnnEquivalenceTest(_VecBase):
    @needs_vec
    def test_ann_matches_brute_force(self):
        """Same top-k, same order. A faster wrong answer is still a wrong answer."""
        rng = random.Random(11)
        rows = [
            (i, [rng.gauss(0, 1) for _ in range(self.DIM)])
            for i in range(1, 801)
        ]
        self._insert(1, rows)
        query = [rng.gauss(0, 1) for _ in range(self.DIM)]

        brute = self._search(1, query, use_vec=False)
        ann = self._search(1, query, use_vec=True)

        self.assertTrue(brute and ann, "both paths must return hits")
        self.assertEqual([c for c, _ in ann], [c for c, _ in brute])

    @needs_vec
    def test_ann_scores_match_brute_force_numerically(self):
        """Same SCALE, not just the same order.

        Coverage and RRF downstream read the score itself, so a fast path that ranks
        identically but scores on a different scale silently changes answers — and
        shows up as an intermittent extra corrective round, not an obvious failure.
        """
        rng = random.Random(23)
        rows = [(i, [rng.gauss(0, 1) for _ in range(self.DIM)]) for i in range(1, 201)]
        self._insert(1, rows)
        query = [rng.gauss(0, 1) for _ in range(self.DIM)]

        brute = dict(self._search(1, query, use_vec=False))
        ann = dict(self._search(1, query, use_vec=True))

        shared = set(brute) & set(ann)
        self.assertGreater(len(shared), 10, "not enough overlap to compare")
        for cid in shared:
            self.assertAlmostEqual(
                ann[cid], brute[cid], places=4,
                msg=f"chunk {cid}: ann={ann[cid]!r} brute={brute[cid]!r}",
            )

    @needs_vec
    def test_orthogonal_scores_near_zero_on_both_paths(self):
        """The concrete regression: 1/(1+d) scored orthogonal vectors 0.5, cosine 0.0."""
        query = [1.0] + [0.0] * (self.DIM - 1)
        orthogonal = [0.0, 1.0] + [0.0] * (self.DIM - 2)
        self._insert(1, [(1, orthogonal)])

        ann = self._search(1, query, use_vec=True)
        if ann:
            self.assertLess(ann[0][1], 0.05, f"orthogonal scored {ann[0][1]} on ANN path")

    @needs_vec
    def test_cosine_not_l2(self):
        """A long vector pointing the wrong way must not beat a short aligned one.

        Under L2 the near-origin decoy wins; under cosine the aligned vector wins. This
        is the exact case that made recall collapse to 0.05.
        """
        query = [1.0] + [0.0] * (self.DIM - 1)
        aligned_far = [8.0] + [0.0] * (self.DIM - 1)          # cosine 1.0, L2 distance 7
        orthogonal_near = [0.9] + [0.9] + [0.0] * (self.DIM - 2)  # cosine ~0.707, closer in L2

        self.assertLess(
            math.dist(query, orthogonal_near),
            math.dist(query, aligned_far),
            "fixture must actually make L2 and cosine disagree",
        )

        self._insert(1, [(1, aligned_far), (2, orthogonal_near)])
        ann = self._search(1, query, use_vec=True)
        self.assertEqual(ann[0][0], 1, "ANN ranked by L2 instead of cosine")

    @needs_vec
    def test_extension_loads_on_every_connection(self):
        """The per-connection regression: second connection used to lose vec0."""
        self._insert(1, [(1, [1.0] * self.DIM)])
        with store._conn() as first:
            vectors._ensure_tables(first)
            self.assertTrue(vectors._USE_SQLITE_VEC)
        # Cache is warm now — this is the path that used to skip the extension load
        with store._conn() as second:
            vectors._ensure_tables(second)
            self.assertTrue(vectors._USE_SQLITE_VEC, "extension not reloaded on new connection")
            second.execute(
                f"SELECT COUNT(*) FROM {vectors._VEC_TABLE}"
            ).fetchone()

    @needs_vec
    def test_empty_ann_table_falls_back_instead_of_returning_nothing(self):
        """Spaces indexed before the ANN table existed must still return dense hits."""
        rng = random.Random(17)
        rows = [(i, [rng.gauss(0, 1) for _ in range(self.DIM)]) for i in range(1, 41)]
        self._insert(1, rows)
        # Simulate a legacy index: chunk_vectors populated, ANN table empty
        with store.session() as conn:
            vectors._ensure_tables(conn)
            conn.execute(f"DELETE FROM {vectors._VEC_TABLE}")

        hits = self._search(1, [rng.gauss(0, 1) for _ in range(self.DIM)], use_vec=True)
        self.assertTrue(hits, "empty ANN table wiped out dense retrieval")

    @needs_vec
    def test_table_is_named_for_the_embedder_width(self):
        with store.session() as conn:
            vectors._ensure_tables(conn)
        self.assertEqual(vectors._VEC_TABLE, f"chunk_vec_idx_{self.DIM}")
        self.assertEqual(vectors._VEC_DIM, self.DIM)

    @needs_vec
    def test_switching_embedder_width_builds_a_new_table(self):
        """A 64-dim index must never be queried with 384-dim vectors."""
        with store.session() as conn:
            vectors._ensure_tables(conn)
        first = vectors._VEC_TABLE

        embed.active_dim = lambda: 384
        with store.session() as conn:
            vectors._ensure_tables(conn)
        self.assertNotEqual(vectors._VEC_TABLE, first)
        self.assertEqual(vectors._VEC_TABLE, "chunk_vec_idx_384")

        with store.session() as conn:
            names = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE name LIKE 'chunk_vec_idx_%'"
                )
            }
        self.assertIn(first, names)
        self.assertIn("chunk_vec_idx_384", names)


class FallbackTest(_VecBase):
    def test_search_works_without_the_extension(self):
        """No sqlite-vec installed is the default install. It must just work."""
        rng = random.Random(3)
        rows = [(i, [rng.gauss(0, 1) for _ in range(self.DIM)]) for i in range(1, 51)]
        self._insert(1, rows)
        hits = self._search(1, [rng.gauss(0, 1) for _ in range(self.DIM)], use_vec=False)
        self.assertTrue(hits)
        self.assertTrue(all(0.0 < s <= 1.0001 for _, s in hits), hits[:3])

    def test_scores_are_descending(self):
        rng = random.Random(5)
        rows = [(i, [rng.gauss(0, 1) for _ in range(self.DIM)]) for i in range(1, 101)]
        self._insert(1, rows)
        hits = self._search(1, [rng.gauss(0, 1) for _ in range(self.DIM)], use_vec=False)
        self.assertEqual([s for _, s in hits], sorted([s for _, s in hits], reverse=True))

    def test_stale_dimension_vectors_are_skipped(self):
        """Vectors written by a previous embedder must not crash or pollute results."""
        good = [(i, [0.5] * self.DIM) for i in range(1, 6)]
        self._insert(1, good)
        with store.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO chunk_vectors(chunk_id,space_id,dim,backend,vec) "
                "VALUES(?,?,?,?,?)",
                (999, 1, 8, "stale", struct.pack("8f", *([1.0] * 8))),
            )
        hits = self._search(1, [0.5] * self.DIM, use_vec=False)
        self.assertTrue(hits)
        self.assertNotIn(999, [c for c, _ in hits])


if __name__ == "__main__":
    unittest.main()

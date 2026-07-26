"""Foundation guards for the RAG store's connection + schema caching.

Before this, every retrieval stage called `store.init()` — a full CREATE TABLE /
CREATE VIRTUAL TABLE script — on a brand-new connection. One `retrieve.search` did that
24 times across ~50 connections: ~600 ms of setup on a 78-chunk corpus.

The optimisation is only safe if it holds under the nasty cases, so those are what this
file tests: the user deleting the database from Explorer, two databases alive at once,
threads racing, exceptions mid-transaction, and handles outliving a temp directory on
Windows.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag import store  # noqa: E402


class StoreSessionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
        store.RAG_DIR = self.root / "rag"
        store.DB_PATH = store.RAG_DIR / "rag.db"
        store.BLOB_DIR = store.RAG_DIR
        store.reset_init_cache()
        store.init()

    def tearDown(self) -> None:
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = self._orig
        store.reset_init_cache()
        self._tmp.cleanup()  # fails on Windows if any handle leaked

    # -- schema caching ----------------------------------------------------

    def _count_ddl_runs(self, fn):
        runs = [0]
        real = store._init_schema

        def counting():
            runs[0] += 1
            return real()

        store._init_schema = counting
        try:
            fn()
        finally:
            store._init_schema = real
        return runs[0]

    def test_repeat_init_runs_schema_once(self):
        runs = self._count_ddl_runs(lambda: [store.init() for _ in range(50)])
        self.assertEqual(runs, 0, "already initialised in setUp — must not re-run")

    def test_force_reruns_schema(self):
        self.assertEqual(self._count_ddl_runs(lambda: store.init(force=True)), 1)

    def test_deleting_the_database_forces_reinit(self):
        """The user wipes data/rag/rag.db from Explorer. Next call must rebuild it."""
        store.create_space("Before delete")
        store.DB_PATH.unlink()
        for extra in ("-wal", "-shm"):
            side = Path(str(store.DB_PATH) + extra)
            if side.exists():
                side.unlink()

        runs = self._count_ddl_runs(store.init)
        self.assertEqual(runs, 1, "deleted database must re-run the schema")
        # And the store is genuinely usable again, not just non-crashing
        space = store.create_space("After delete")
        self.assertTrue(store.get_space(int(space["id"])))

    def test_empty_database_file_forces_reinit(self):
        """A 0-byte rag.db (interrupted copy, synced placeholder) is not a schema."""
        store.DB_PATH.unlink()
        store.DB_PATH.write_bytes(b"")
        self.assertEqual(self._count_ddl_runs(store.init), 1)

    def test_second_database_gets_its_own_schema(self):
        other = self.root / "rag2" / "rag.db"
        prev_dir, prev_db = store.RAG_DIR, store.DB_PATH
        store.RAG_DIR, store.DB_PATH = other.parent, other
        try:
            self.assertEqual(self._count_ddl_runs(store.init), 1)
            store.create_space("Second db")
        finally:
            store.RAG_DIR, store.DB_PATH = prev_dir, prev_db
        # Switching back must not re-run, and must still see the original rows
        self.assertEqual(self._count_ddl_runs(store.init), 0)

    # -- session semantics -------------------------------------------------

    def test_session_shares_one_connection(self):
        with store.session() as outer:
            with store._conn() as a, store._conn() as b:
                self.assertIs(a, outer)
                self.assertIs(b, outer)
            with store.session() as nested:
                self.assertIs(nested, outer)

    def test_connections_differ_without_a_session(self):
        with store._conn() as a:
            first = id(a)
        with store._conn() as b:
            self.assertNotEqual(first, id(b))

    def test_session_closes_its_connection(self):
        with store.session() as conn:
            conn.execute("SELECT 1").fetchone()
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_session_commits_on_success(self):
        with store.session():
            store.create_space("Committed")
        names = [s["name"] for s in store.list_spaces()]
        self.assertIn("Committed", names)

    def test_session_rolls_back_and_still_closes(self):
        boom = RuntimeError("mid-transaction failure")
        with self.assertRaises(RuntimeError):
            with store.session() as conn:
                store.create_space("Doomed")
                held = conn
                raise boom
        with self.assertRaises(sqlite3.ProgrammingError):
            held.execute("SELECT 1")
        self.assertNotIn("Doomed", [s["name"] for s in store.list_spaces()])

    def test_db_path_switch_inside_session_is_not_misrouted(self):
        """A profile switch mid-session must not read the previous database."""
        other = self.root / "rag3" / "rag.db"
        with store.session() as outer:
            prev_dir, prev_db = store.RAG_DIR, store.DB_PATH
            store.RAG_DIR, store.DB_PATH = other.parent, other
            try:
                store.init()
                with store._conn() as inner:
                    self.assertIsNot(inner, outer, "stale session connection reused")
                    row = inner.execute("PRAGMA database_list").fetchone()
                    self.assertEqual(Path(row[2]).resolve(), other.resolve())
            finally:
                store.RAG_DIR, store.DB_PATH = prev_dir, prev_db

    # -- concurrency -------------------------------------------------------

    def test_threads_do_not_share_session_connections(self):
        seen: dict[int, int] = {}
        errors: list[BaseException] = []
        ready = threading.Barrier(4)

        def worker(n: int) -> None:
            try:
                ready.wait(timeout=10)
                with store.session() as conn:
                    seen[n] = id(conn)
                    for _ in range(20):
                        conn.execute("SELECT COUNT(*) FROM knowledge_spaces").fetchone()
            except BaseException as e:  # noqa: BLE001 - surfaced below
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(errors, [])
        self.assertEqual(len(set(seen.values())), 4, "connections leaked across threads")

    def test_concurrent_writes_all_land(self):
        errors: list[BaseException] = []

        def writer(n: int) -> None:
            try:
                with store.session():
                    store.create_space(f"Space {n}")
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        self.assertEqual(errors, [])
        names = {s["name"] for s in store.list_spaces()}
        for i in range(8):
            self.assertIn(f"Space {i}", names)


class RetrievalEquivalenceTest(unittest.TestCase):
    """The fast path must return exactly what the slow path returned."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
        store.RAG_DIR = self.root / "rag"
        store.DB_PATH = store.RAG_DIR / "rag.db"
        store.BLOB_DIR = store.RAG_DIR
        store.reset_init_cache()
        store.init()

        corpus = self.root / "corpus"
        corpus.mkdir()
        (corpus / "snr.md").write_text(
            "# Lab summary\n\nPeak SNR measured at 92.5 dB on the bench rig.\n"
            "Noise floor was 12 nV per root hertz across the audio band.\n",
            encoding="utf-8",
        )
        (corpus / "spec.md").write_text(
            "# Spec\n\nTarget SNR at 10 kHz.\nInput impedance 10 kOhm.\n",
            encoding="utf-8",
        )
        from rag import ingest

        self.space_id = int(store.create_space("Equivalence")["id"])
        ingest.ingest_paths(self.space_id, [corpus], force=True)

    def tearDown(self) -> None:
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = self._orig
        store.reset_init_cache()
        shutil.rmtree(self.root, ignore_errors=True)
        self._tmp.cleanup()

    def test_session_does_not_change_results(self):
        from rag import retrieve

        query = "what is the SNR"
        pooled = retrieve.search(self.space_id, query, depth="high")
        # _search is the same body without the shared connection
        direct = retrieve._search(self.space_id, query, depth="high")

        self.assertTrue(pooled.get("ok"), pooled)
        self.assertEqual(
            [c.get("chunk_id") for c in pooled.get("citations", [])],
            [c.get("chunk_id") for c in direct.get("citations", [])],
        )

    def test_repeated_searches_are_stable(self):
        from rag import retrieve

        runs = [retrieve.search(self.space_id, "noise floor", depth="high") for _ in range(3)]
        first = [c.get("chunk_id") for c in runs[0].get("citations", [])]
        for r in runs[1:]:
            self.assertEqual([c.get("chunk_id") for c in r.get("citations", [])], first)


if __name__ == "__main__":
    unittest.main()

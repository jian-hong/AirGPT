"""EPIC-D06 #37: the /api/rag/spaces/<id>/build `paths` override must not be a
file-read primitive.

The handler took a client-supplied `paths` array and used it *instead of* the
space's registered sources, unvalidated. Whatever it named was ingested, and the
file's text then came back as retrievable answer material.

Severity, stated plainly: `/api/rag` is in clipdrop._HOST_ONLY_PREFIXES, so today
this needs host-level access — it is NOT a remote hole as shipped. It turns into a
remote arbitrary file read the moment level-based access grants (DR-0003) let a
client reach `/api/rag`, which is why the gate lands before those grants.

These tests drive the real handler over HTTP (same ThreadingHTTPServer pattern as
tests/test_ops_http_gate.py) and assert on the chunk rows in the database, not on
the response message — an endpoint that says "refused" while the ingest happened
anyway is the exact failure this gate exists to catch (R-0011).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402
from rag import ingest as rag_ingest  # noqa: E402
from rag import store as rag_store  # noqa: E402

INSIDE_MARKER = "QZ41-INSIDE-REGISTERED-SOURCE"
OUTSIDE_MARKER = "QZ41-OUTSIDE-SECRET-NEVER-INDEX"


class RagBuildPathOverrideTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)

        # Point the whole RAG system of record at a throwaway tree.
        self._orig = (rag_store.RAG_DIR, rag_store.DB_PATH, rag_store.BLOB_DIR)
        rag_store.RAG_DIR = tmp / "rag"
        rag_store.DB_PATH = tmp / "rag" / "rag.db"
        rag_store.BLOB_DIR = tmp / "rag"
        rag_store.reset_init_cache()
        rag_store.init()

        # No embedding backend in a unit gate; the hybrid/sparse index is enough
        # to prove whether text became retrievable.
        self._orig_vec = (
            rag_ingest.vectors.clear_space,
            rag_ingest.vectors.index_children,
            rag_ingest.vectors.available,
        )
        rag_ingest.vectors.clear_space = lambda *a, **k: None
        rag_ingest.vectors.index_children = lambda *a, **k: 0
        rag_ingest.vectors.available = lambda *a, **k: {"ok": False}

        # A file the space legitimately owns...
        self.inside = tmp / "workspace" / "handbook.txt"
        self.inside.parent.mkdir(parents=True, exist_ok=True)
        self.inside.write_text(
            f"Company handbook. Leave policy section. {INSIDE_MARKER}\n" * 4,
            encoding="utf-8",
        )
        # ...and one it does not, sitting outside every space directory.
        self.outside = tmp / "elsewhere" / "id_rsa_notes.txt"
        self.outside.parent.mkdir(parents=True, exist_ok=True)
        self.outside.write_text(
            f"Private host file the space was never given. {OUTSIDE_MARKER}\n" * 4,
            encoding="utf-8",
        )

        space = rag_store.create_space("Gate Space")
        self.sid = int(space["id"])
        out = rag_ingest.ingest_paths(self.sid, [str(self.inside)], force=True)
        self.assertTrue(out.get("ok"), f"fixture ingest failed: {out}")
        self.assertTrue(self._chunks_matching(INSIDE_MARKER), "fixture never indexed")
        self.baseline_chunks = self._chunk_count()

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        (
            rag_ingest.vectors.clear_space,
            rag_ingest.vectors.index_children,
            rag_ingest.vectors.available,
        ) = self._orig_vec
        rag_store.RAG_DIR, rag_store.DB_PATH, rag_store.BLOB_DIR = self._orig
        rag_store.reset_init_cache()
        self._tmp.cleanup()

    # --- real state, read straight from SQLite (no handler involved) -----------

    def _chunks_matching(self, marker: str) -> int:
        conn = sqlite3.connect(str(rag_store.DB_PATH))
        try:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM chunks WHERE space_id=? AND text LIKE ?",
                    (self.sid, f"%{marker}%"),
                ).fetchone()[0]
            )
        finally:
            conn.close()

    def _chunk_count(self) -> int:
        conn = sqlite3.connect(str(rag_store.DB_PATH))
        try:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM chunks WHERE space_id=?", (self.sid,)
                ).fetchone()[0]
            )
        finally:
            conn.close()

    def _source_paths(self) -> list[str]:
        return [str(s.get("path") or "") for s in rag_store.list_sources(self.sid)]

    def _docs_dir(self) -> Path:
        d = Path(rag_store.BLOB_DIR) / str(self.sid) / "Docs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # --- HTTP ------------------------------------------------------------------

    def _post(self, path, payload):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def _build(self, payload):
        return self._post(f"/api/rag/spaces/{self.sid}/build", payload)

    def _assert_outside_never_indexed(self, where: str):
        """The refusal has to be real: no chunk of the outside file, and the
        legitimate index untouched (ingest_paths(force=True) clears chunks before
        it writes, so a build that got as far as running would show here)."""
        self.assertEqual(
            self._chunks_matching(OUTSIDE_MARKER), 0,
            f"{where}: outside file became retrievable — the ingest actually ran",
        )
        self.assertEqual(
            self._chunks_matching(INSIDE_MARKER) > 0, True,
            f"{where}: the space's own material disappeared",
        )
        self.assertEqual(
            self._chunk_count(), self.baseline_chunks,
            f"{where}: index changed on a refused build",
        )

    # --- (a) + (b) outside path is refused, and the refusal is real -----------

    def test_build_refuses_paths_outside_the_spaces_sources(self):
        code, out = self._build({"paths": [str(self.outside)]})
        self.assertEqual(code, 400, out)
        self.assertFalse(out.get("ok"), out)
        err = str(out.get("error") or "")
        self.assertIn(
            self.outside.name, err,
            f"error must name the rejected path, got: {err!r}",
        )
        self.assertIn("not a registered source", err, err)
        self._assert_outside_never_indexed("outside path")

    def test_build_stream_refuses_paths_outside_the_spaces_sources(self):
        # Same override existed on the SSE sibling; it must refuse identically,
        # and before the stream opens, so the caller reads a plain 400.
        code, out = self._post(
            f"/api/rag/spaces/{self.sid}/build-stream", {"paths": [str(self.outside)]}
        )
        self.assertEqual(code, 400, out)
        self.assertIn(self.outside.name, str(out.get("error") or ""), out)
        self._assert_outside_never_indexed("build-stream outside path")

    # --- (c) the legitimate subset rebuild still works -------------------------

    def test_build_still_accepts_a_registered_source_path(self):
        registered = self._source_paths()
        self.assertTrue(registered, "fixture registered no source")
        code, out = self._build({"paths": registered})
        self.assertEqual(code, 200, out)
        self.assertTrue(out.get("ok"), out)
        self.assertGreater(
            self._chunks_matching(INSIDE_MARKER), 0,
            "subset rebuild of a registered source must still index it",
        )
        self.assertEqual(self._chunks_matching(OUTSIDE_MARKER), 0)

    def test_build_with_no_paths_still_rebuilds_everything(self):
        code, out = self._build({})
        self.assertEqual(code, 200, out)
        self.assertTrue(out.get("ok"), out)
        self.assertGreater(self._chunks_matching(INSIDE_MARKER), 0)

    # --- (d) traversal and symlink ---------------------------------------------

    def test_build_refuses_dotdot_traversal_out_of_the_docs_dir(self):
        # Textually this sits under the space's own Docs/; resolved, it does not.
        docs = self._docs_dir()
        rel = os.path.relpath(str(self.outside), str(docs))
        traversal = str(docs / rel)
        self.assertIn("..", traversal, f"fixture did not produce a traversal: {traversal}")

        code, out = self._build({"paths": [traversal]})
        self.assertEqual(code, 400, out)
        self.assertFalse(out.get("ok"), out)
        err = str(out.get("error") or "")
        self.assertIn(self.outside.name, err, err)
        self.assertIn("resolves to", err, f"error should name where it resolved: {err!r}")
        self._assert_outside_never_indexed("dotdot traversal")

    def test_build_refuses_a_symlink_from_the_docs_dir_to_an_outside_file(self):
        link = self._docs_dir() / "looks_legit.txt"
        try:
            os.symlink(str(self.outside), str(link))
        except (OSError, NotImplementedError, AttributeError) as e:
            # Loudly, never silently: on Windows this needs Developer Mode or admin.
            msg = (
                "SYMLINK CASE NOT EXERCISED: this OS/account cannot create a symlink "
                f"({type(e).__name__}: {e}). The `..` traversal case above still ran. "
                "Re-run with symlink privilege to cover the symlink route."
            )
            print(f"\n!!! {msg}", file=sys.stderr)
            self.skipTest(msg)

        self.assertTrue(link.is_symlink(), "fixture symlink not created")
        code, out = self._build({"paths": [str(link)]})
        self.assertEqual(code, 400, out)
        self.assertFalse(out.get("ok"), out)
        err = str(out.get("error") or "")
        self.assertIn("looks_legit.txt", err, err)
        self._assert_outside_never_indexed("symlink out of Docs/")

    # --- fail loudly, do not silently drop the bad half -----------------------

    def test_a_mixed_batch_is_refused_whole_not_partially_built(self):
        """Half-good/half-bad must not report success having built only the good
        half — a control that says OK while doing something else is R-0011."""
        registered = self._source_paths()
        code, out = self._build({"paths": registered + [str(self.outside)]})
        self.assertEqual(code, 400, out)
        self.assertIn(self.outside.name, str(out.get("error") or ""), out)
        self._assert_outside_never_indexed("mixed batch")


if __name__ == "__main__":
    unittest.main()

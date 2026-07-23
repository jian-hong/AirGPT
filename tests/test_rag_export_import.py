"""RAG pack export/import tests (offline, temp RAG_DIR)."""
from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


class RagExportImportTests(unittest.TestCase):
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

    def _ingest_fixture(self, name: str = "Pack RAG") -> int:
        from rag import ingest

        space = self.store.create_space(name, depth_default="high")
        sid = int(space["id"])
        out = ingest.ingest_paths(sid, [self.fixture], force=True)
        self.assertTrue(out.get("ok"), out)
        return sid

    def test_round_trip_search(self):
        from rag import export_import, retrieve

        sid = self._ingest_fixture()
        pack = export_import.export_space(sid, include_chats=False)
        self.assertTrue(pack.startswith(b"PK"))

        imported = export_import.import_pack(pack, name="Imported Pack")
        self.assertTrue(imported.get("ok"), imported)
        new_id = int(imported["space"]["id"])
        self.assertNotEqual(new_id, sid)
        self.assertGreaterEqual(imported.get("sources") or 0, 2)

        hit = retrieve.search(new_id, "hybrid search RRF", depth="high", top_k=5)
        self.assertTrue(hit.get("ok"), hit)
        self.assertGreater(len(hit.get("hits") or []), 0)
        paths = " ".join(str(h.get("path") or "") for h in (hit.get("hits") or []))
        self.assertTrue("alpha" in paths.lower() or "RRF" in paths or len(hit["hits"]) > 0)

        # Known content must surface in answerable corpus
        file_hit = retrieve.search(new_id, "build_rag_index", depth="high", top_k=5)
        self.assertTrue(file_hit.get("ok"))
        blob = " ".join(
            str(h.get("path") or "") + " " + str(h.get("text") or "")
            for h in (file_hit.get("hits") or [])
        )
        self.assertIn("beta", blob.lower())

    def test_chats_round_trip(self):
        from rag import export_import

        sid = self._ingest_fixture("Chat Pack")
        chat = self.store.create_chat(sid, "Hybrid Q")
        self.store.add_message(int(chat["id"]), "user", "What is RRF?", depth="high")
        self.store.add_message(
            int(chat["id"]),
            "assistant",
            "Reciprocal Rank Fusion.",
            citations=[{"path": "alpha.md"}],
            depth="high",
        )

        pack = export_import.export_space(sid, include_chats=True)
        imported = export_import.import_pack(pack)
        self.assertTrue(imported.get("ok"), imported)
        self.assertGreaterEqual(imported.get("chats") or 0, 1)
        new_id = int(imported["space"]["id"])
        chats = self.store.list_chats(new_id)
        self.assertTrue(any(c.get("title") == "Hybrid Q" for c in chats))
        msgs = self.store.list_messages(int(chats[0]["id"]))
        contents = " ".join(m.get("content") or "" for m in msgs)
        self.assertIn("RRF", contents)

    def test_no_chats_option(self):
        from rag import export_import

        sid = self._ingest_fixture("NoChat")
        self.store.create_chat(sid, "Skip me")
        pack = export_import.export_space(sid, include_chats=False)
        with zipfile.ZipFile(io.BytesIO(pack)) as zf:
            self.assertNotIn("chats.json", zf.namelist())
        imported = export_import.import_pack(pack)
        self.assertEqual(imported.get("chats") or 0, 0)

    def test_zip_slip_rejected(self):
        from rag import export_import

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            manifest = {
                "format": export_import.PACK_FORMAT,
                "version": 1,
                "space": {"name": "Evil", "depth_default": "high", "modalities": ["text"], "profile": "local", "config": {}},
                "sources": [{"pack_path": "sources/0001__ok.md", "title": "ok.md", "content_hash": "", "meta": {}}],
                "integrity": {"algo": "sha256", "files": {}},
            }
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("sources/0001__ok.md", b"# ok\n")
            zf.writestr("../../evil.txt", b"pwned")
        with self.assertRaises(ValueError):
            export_import.import_pack(buf.getvalue())

    def test_outside_path_ignored_blob_exported(self):
        from rag import export_import, ingest

        space = self.store.create_space("Jail Pack")
        sid = int(space["id"])
        ingest.ingest_paths(sid, [self.fixture / "alpha.md"], force=True)
        sources = self.store.list_sources(sid)
        self.assertTrue(sources)
        src = sources[0]
        # Point path outside jail; blob must still export
        outside = Path(self._tmpdir.name) / "outside_secret.md"
        outside.write_text("SHOULD_NOT_APPEAR_AS_PACK_ROOT", encoding="utf-8")
        with self.store._conn() as conn:
            conn.execute(
                "UPDATE sources SET path=? WHERE id=?",
                (str(outside), int(src["id"])),
            )

        pack = export_import.export_space(sid, include_chats=False)
        with zipfile.ZipFile(io.BytesIO(pack)) as zf:
            names = zf.namelist()
            self.assertTrue(any(n.startswith("sources/") for n in names))
            self.assertFalse(any("outside_secret" in n for n in names))
            # Blob content is the ingested alpha text, not the outside file
            src_members = [n for n in names if n.startswith("sources/")]
            blob = zf.read(src_members[0]).decode("utf-8", errors="replace")
            self.assertIn("Alpha Protocol", blob)
            self.assertNotIn("SHOULD_NOT_APPEAR", blob)

    def test_missing_space_export(self):
        from rag import export_import

        with self.assertRaises(ValueError):
            export_import.export_space(999999)

    def test_corrupt_manifest(self):
        from rag import export_import

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("manifest.json", b"{not json")
        with self.assertRaises(ValueError):
            export_import.import_pack(buf.getvalue())

    def test_hash_mismatch(self):
        from rag import export_import

        sid = self._ingest_fixture("Hash Pack")
        pack = export_import.export_space(sid, include_chats=False)
        # Tamper a source file inside the zip
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(pack), "r") as zin, zipfile.ZipFile(buf, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.startswith("sources/"):
                    data = data + b"\nTAMPER"
                zout.writestr(item, data)
        with self.assertRaises(ValueError):
            export_import.import_pack(buf.getvalue())

    def test_slug_collision_second_import(self):
        from rag import export_import

        sid = self._ingest_fixture("Same Name")
        pack = export_import.export_space(sid, include_chats=False)
        a = export_import.import_pack(pack, name="Same Name")
        b = export_import.import_pack(pack, name="Same Name")
        self.assertTrue(a.get("ok") and b.get("ok"))
        self.assertNotEqual(a["space"]["id"], b["space"]["id"])
        self.assertNotEqual(a["space"]["slug"], b["space"]["slug"])


if __name__ == "__main__":
    unittest.main()

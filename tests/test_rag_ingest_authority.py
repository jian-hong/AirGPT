"""Chat-ingest scrub, stored authority, and file-scoped retrieval.

The netie.ai fabrication got into the index by a specific route worth naming: the model
wrote it, the human pasted that reply into a later chat, and the chat was frozen as
`chat_126.md` under a `## user` heading. Filtering by role alone would have sailed
straight past it — the scrub has to catch assistant output wearing a human's turn.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag import authority, ingest, store  # noqa: E402

PASTED_REPORT = """═══ AirGPT ════

Netie.ai focuses on AI-powered search and knowledge discovery, with semantic search
and knowledge graphs.

═══ END ═══"""


class ScrubTest(unittest.TestCase):
    def test_pasted_report_block_is_removed(self):
        text = "here is what you said:\n\n" + PASTED_REPORT + "\n\nplease fix it"
        out = ingest.scrub_assistant_text(text)
        self.assertNotIn("knowledge graphs", out)
        self.assertNotIn("═══", out)
        self.assertIn("please fix it", out, "the human's own words must survive")
        self.assertIn("here is what you said", out)

    def test_plain_human_text_is_untouched(self):
        text = "can you check the SNR figure in the lab report please"
        self.assertEqual(ingest.scrub_assistant_text(text), text)

    def test_assistant_turns_are_dropped_by_default(self):
        sessions = [{
            "id": 7,
            "title": "Netie",
            "messages": [
                {"role": "user", "text": "what is netie ai"},
                {"role": "assistant", "text": "Netie.ai does semantic search and knowledge graphs."},
            ],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            orig = store.BLOB_DIR
            store.BLOB_DIR = Path(tmp)
            try:
                files = ingest.write_session_transcripts(1, sessions)
                body = files[0].read_text(encoding="utf-8")
            finally:
                store.BLOB_DIR = orig
        self.assertIn("what is netie ai", body)
        self.assertNotIn("knowledge graphs", body, "assistant output was indexed")
        self.assertIn("omitted", body, "the omission should be recorded in the file")

    def test_keep_assistant_is_available_when_explicitly_wanted(self):
        sessions = [{
            "id": 8,
            "title": "Decisions",
            "messages": [
                {"role": "user", "text": "what did we settle on"},
                {"role": "assistant", "text": "We settled on parent-child chunking."},
            ],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            orig = store.BLOB_DIR
            store.BLOB_DIR = Path(tmp)
            try:
                files = ingest.write_session_transcripts(1, sessions, keep_assistant=True)
                body = files[0].read_text(encoding="utf-8")
            finally:
                store.BLOB_DIR = orig
        self.assertIn("parent-child chunking", body)

    def test_a_chat_of_only_assistant_output_produces_no_file(self):
        sessions = [{
            "id": 9,
            "title": "All model",
            "messages": [{"role": "assistant", "text": "Some invented facts."}],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            orig = store.BLOB_DIR
            store.BLOB_DIR = Path(tmp)
            try:
                files = ingest.write_session_transcripts(1, sessions)
            finally:
                store.BLOB_DIR = orig
        self.assertEqual(files, [], "nothing human was said — nothing to index")


class _SpaceCase(unittest.TestCase):
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


class StoredAuthorityTest(_SpaceCase):
    def test_authority_is_written_at_ingest(self):
        corpus = self.root / "c"
        corpus.mkdir()
        (corpus / "spec.md").write_text("Input impedance is 10 kOhm.", encoding="utf-8")
        sid = int(store.create_space("Docs")["id"])
        ingest.ingest_paths(sid, [corpus], force=True)

        with store.session() as c:
            vals = {r[0] for r in c.execute(
                "SELECT DISTINCT authority FROM chunks WHERE space_id=?", (sid,)
            )}
        self.assertEqual(vals, {authority.DOCUMENT})

    def test_migration_backfills_legacy_rows_through_the_classifier(self):
        sid = int(store.create_space("Legacy")["id"])
        with store.session() as c:
            for path in (
                "sources/chat_126.md",       # transcript
                "sources/url_example-com.md",  # fetched page
                "uploads/spec.md",            # document
                "docs/chat_ui_notes.md",      # document ABOUT chat, not a transcript
            ):
                c.execute(
                    "INSERT INTO chunks(space_id,source_id,revision_id,parent_id,kind,text,"
                    "path,heading,page,span_start,span_end,token_est,meta,authority,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, 1, 1, 0, "child", "x", path, "", 0, 0, 0, 0, "{}", "", 0.0),
                )
            store._migrate_authority(c)
            got = {
                r[0]: r[1]
                for r in c.execute(
                    "SELECT path, authority FROM chunks WHERE space_id=?", (sid,)
                )
            }
        self.assertEqual(got["sources/chat_126.md"], authority.CONVERSATION)
        self.assertEqual(got["sources/url_example-com.md"], authority.WEB)
        self.assertEqual(got["uploads/spec.md"], authority.DOCUMENT)
        self.assertEqual(
            got["docs/chat_ui_notes.md"], authority.DOCUMENT,
            "a LIKE '%chat_%' backfill would have mislabelled this",
        )


class FileScopedRetrieveTest(_SpaceCase):
    def setUp(self):
        super().setUp()
        corpus = self.root / "c"
        corpus.mkdir()
        (corpus / "alpha.md").write_text(
            "# Alpha\n\nThe amplifier noise floor is 12 nV per root hertz.\n", encoding="utf-8"
        )
        (corpus / "beta.md").write_text(
            "# Beta\n\nThe amplifier noise floor is 40 nV per root hertz.\n", encoding="utf-8"
        )
        self.sid = int(store.create_space("Scoped")["id"])
        ingest.ingest_paths(self.sid, [corpus], force=True)
        with store.session() as c:
            self.by_name = {
                Path(r[1]).name: int(r[0])
                for r in c.execute("SELECT id, path FROM sources WHERE space_id=?", (self.sid,))
            }

    def test_unscoped_search_sees_both_files(self):
        from rag import retrieve

        out = retrieve.search(self.sid, "amplifier noise floor", depth="high")
        names = {Path(str(h.get("path") or "")).name for h in out.get("hits") or []}
        self.assertGreaterEqual(len(names & {"alpha.md", "beta.md"}), 2, names)

    def test_scoping_to_one_file_excludes_the_other(self):
        from rag import retrieve

        out = retrieve.search(
            self.sid, "amplifier noise floor", depth="high",
            source_ids=[self.by_name["alpha.md"]],
        )
        names = {Path(str(h.get("path") or "")).name for h in out.get("hits") or []}
        self.assertTrue(names, "scoped search returned nothing at all")
        self.assertNotIn("beta.md", names)

    def test_empty_scope_is_ignored_rather_than_returning_nothing(self):
        from rag import retrieve

        out = retrieve.search(self.sid, "amplifier noise floor", depth="high", source_ids=[])
        self.assertTrue(out.get("hits"), "an empty scope must mean 'no filter', not 'no results'")

    def test_answer_honours_the_scope(self):
        from rag import answer

        out = answer.answer(
            self.sid, "what is the amplifier noise floor", depth="high", use_llm=False,
            use_web=False, source_ids=[self.by_name["beta.md"]],
        )
        cited = {Path(str(c.get("path_full") or c.get("path") or "")).name
                 for c in out.get("citations") or []}
        self.assertNotIn("alpha.md", cited, cited)


if __name__ == "__main__":
    unittest.main()

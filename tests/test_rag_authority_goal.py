"""Source authority + goal distance.

The bug these guard against, in full: the assistant invented a description of a company,
that answer was saved to a chat, the chat was ingested into the knowledge space as
`chat_126.md`, and a later question retrieved it and presented the invention back to the
user *with a citation*. A correction sitting in `chat_134.md` lost the ranking. Nothing
in the pipeline distinguished "a document says this" from "I said this once".

So: conversation text is never citable, confidence never counts it, and when a question
cannot be supported the engine says how far short it fell and what to do about it.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag import authority, goal, store  # noqa: E402

FABRICATION = (
    "Netie.ai focuses on AI-powered search and knowledge discovery. Their website "
    "highlights features like semantic search, knowledge graphs, and AI agents."
)


class ClassifyTest(unittest.TestCase):
    def test_chat_transcripts_are_conversation(self):
        for p in (
            r"D:\AirGPT\data\rag\5\sources\chat_126.md",
            "data/rag/5/sources/chat_4.md",
            "chat_134.md",
        ):
            self.assertEqual(authority.classify(p), authority.CONVERSATION, p)

    def test_fetched_pages_are_web(self):
        self.assertEqual(
            authority.classify(r"D:\AirGPT\data\rag\5\sources\url_cognition4ai-com.md"),
            authority.WEB,
        )

    def test_uploads_are_documents(self):
        for p in ("uploads/JH_RS622XK_Lab_Report.xlsx", "spec.html", "meeting_notes.md"):
            self.assertEqual(authority.classify(p), authority.DOCUMENT, p)

    def test_a_file_merely_mentioning_chat_is_not_conversation(self):
        """`chat_ui_notes.md` is a document about chat, not a transcript."""
        self.assertEqual(authority.classify("docs/chat_ui_notes.md"), authority.DOCUMENT)
        self.assertEqual(authority.classify("live_chat.md"), authority.DOCUMENT)

    def test_only_documents_and_web_are_evidence(self):
        self.assertTrue(authority.is_evidence(authority.DOCUMENT))
        self.assertTrue(authority.is_evidence(authority.WEB))
        self.assertFalse(authority.is_evidence(authority.CONVERSATION))

    def test_conversation_is_downweighted_not_deleted(self):
        self.assertLess(authority.weight(authority.CONVERSATION), authority.weight(authority.WEB))
        self.assertGreater(authority.weight(authority.CONVERSATION), 0.0)

    def test_split_evidence_separates_the_fabrication(self):
        hits = [
            {"path": "sources/chat_126.md", "text": FABRICATION},
            {"path": "sources/url_netie-ai.md", "text": "Unified AI x Web3 x Hardware."},
            {"path": "uploads/spec.md", "text": "Input impedance 10 kOhm."},
        ]
        evidence, convo = authority.split_evidence(hits)
        self.assertEqual(len(evidence), 2)
        self.assertEqual(len(convo), 1)
        self.assertIn(FABRICATION, convo[0]["text"])
        self.assertNotIn(FABRICATION, " ".join(h["text"] for h in evidence))


class GoalDistanceTest(unittest.TestCase):
    def test_no_evidence_is_maximum_distance(self):
        a = goal.assess("what is netie ai", evidence=[], conversation=[])
        self.assertEqual(a.distance, 1.0)
        self.assertEqual(a.verdict, "unsupported")
        self.assertFalse(a.answerable)

    def test_conversation_only_is_still_unsupported(self):
        """The exact shape of the netie.ai failure."""
        convo = [{"path": "sources/chat_126.md", "text": FABRICATION}]
        a = goal.assess("what is netie ai", evidence=[], conversation=convo)
        self.assertEqual(a.verdict, "unsupported")
        self.assertTrue(a.conversation_only)
        self.assertEqual(a.evidence_count, 0)
        joined = " ".join(a.diagnosis).lower()
        self.assertIn("not evidence", joined)
        self.assertIn("build tab", joined)

    def test_covered_question_is_answerable(self):
        ev = [{"path": "url_jepa.md", "text": "JEPA is a joint embedding predictive architecture from LeCun."}]
        a = goal.assess("what is jepa architecture", evidence=ev)
        self.assertEqual(a.verdict, "answerable")
        self.assertLess(a.distance, goal.ANSWERABLE_MAX_DISTANCE)

    def test_missing_terms_are_named(self):
        ev = [{"path": "url_jepa.md", "text": "JEPA predicts in embedding space."}]
        a = goal.assess("does cortex use jepa for edge deployment", evidence=ev)
        self.assertIn("cortex", a.missing)
        self.assertIn("jepa", a.covered)

    def test_question_words_are_not_treated_as_content(self):
        for noise in ("hmm", "yup", "please", "what", "how", "web", "search"):
            self.assertNotIn(noise, goal.salient_terms(f"{noise} what is jepa"))

    def test_summary_line_is_quantified_not_apologetic(self):
        a = goal.assess("what is netie ai", evidence=[])
        line = goal.summary_line(a)
        self.assertIn("%", line)
        self.assertNotIn("sorry", line.lower())
        self.assertEqual(goal.summary_line(
            goal.assess("jepa", evidence=[{"text": "jepa explained", "path": "url_x.md"}])
        ), "")

    def test_diagnosis_suggests_web_search_when_it_never_ran(self):
        a = goal.assess("what is jepa", evidence=[], web_ran=False)
        self.assertTrue(any("web search" in d.lower() for d in a.diagnosis), a.diagnosis)

    def test_diagnosis_reports_web_failure_instead_of_suggesting_it_again(self):
        a = goal.assess("what is jepa", evidence=[], web_ran=True, web_error="rate limited")
        joined = " ".join(a.diagnosis).lower()
        self.assertIn("rate limited", joined)

    def test_refine_query_targets_the_gap(self):
        ev = [{"path": "url_jepa.md", "text": "JEPA predicts in embedding space."}]
        a = goal.assess("does cortex use jepa", evidence=ev)
        self.assertEqual(goal.refine_query("does cortex use jepa", a), "cortex")

    def test_assessment_is_json_safe(self):
        import json

        json.dumps(goal.assess("what is jepa", evidence=[]).as_dict())


class EndToEndAuthorityTest(unittest.TestCase):
    """A space containing only a transcript of a past hallucination must not cite it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._orig = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
        store.RAG_DIR = root / "rag"
        store.DB_PATH = store.RAG_DIR / "rag.db"
        store.BLOB_DIR = store.RAG_DIR
        store.reset_init_cache()
        store.init()

        corpus = root / "corpus"
        corpus.mkdir()
        (corpus / "chat_126.md").write_text(
            "# Chat: Text\n\n## assistant\n" + FABRICATION + "\n", encoding="utf-8"
        )
        from rag import ingest

        self.sid = int(store.create_space("Recycled")["id"])
        ingest.ingest_paths(self.sid, [corpus], force=True)

    def tearDown(self):
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = self._orig
        store.reset_init_cache()
        self._tmp.cleanup()

    def test_transcript_is_never_cited_and_answer_admits_the_gap(self):
        from rag import answer

        out = answer.answer(self.sid, "what is netie ai", depth="high", use_llm=False, use_web=False)
        self.assertEqual(out.get("citations"), [], "a chat transcript was cited as evidence")
        self.assertEqual((out.get("goal") or {}).get("verdict"), "unsupported")
        body = (out.get("answer") or "").lower()
        self.assertNotIn("knowledge graph", body, "the fabrication was repeated")
        self.assertNotIn("semantic search", body, "the fabrication was repeated")

    def test_confidence_does_not_count_conversation(self):
        from rag import answer

        out = answer.answer(self.sid, "what is netie ai", depth="high", use_llm=False, use_web=False)
        self.assertEqual(out.get("confidence") or 0.0, 0.0)


if __name__ == "__main__":
    unittest.main()

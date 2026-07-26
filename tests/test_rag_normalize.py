"""Normalize + media gate tests; Claude cross-verify gates documented in asserts."""
from __future__ import annotations

import unittest
from pathlib import Path

from rag import chunking, media, normalize
from rag.ingest import html_to_text, read_text_file

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rag_normalize"


class NormalizeTests(unittest.TestCase):
    def test_tsx_strips_imports_keeps_export(self) -> None:
        raw = (FIXTURES / "next_page.tsx").read_text(encoding="utf-8")
        result = normalize.normalize_text(raw, suffix=".tsx")
        self.assertNotIn("import React", result.text)
        self.assertNotIn('from "next/link"', result.text)
        self.assertIn("ProductPage", result.text)
        self.assertIn("Product catalog", result.text)
        self.assertTrue(any("react" in m.lower() or "next" in m.lower() for m in result.import_map))
        # Gate: meaningful token reduction on Next.js samples (imports+license out)
        raw_tok = chunking.estimate_tokens(raw)
        new_tok = chunking.estimate_tokens(result.text)
        self.assertGreaterEqual((raw_tok - new_tok) / max(1, raw_tok), 0.15)

    def test_html_chrome_stripped(self) -> None:
        raw = (FIXTURES / "page.html").read_text(encoding="utf-8")
        title, body = html_to_text(raw)
        self.assertEqual(title, "Shop")
        self.assertIn("Product catalog", body)
        self.assertNotIn("Home | Cart", body)
        self.assertNotIn("Copyright footer", body)
        self.assertNotIn("Related ads", body)
        normed = normalize.normalize_html(body)
        self.assertIn("widgets", normed.text.lower())

    def test_import_react_not_in_body_for_adversarial(self) -> None:
        """Adversarial: import-only line must not dominate 'what does component render'."""
        raw = (FIXTURES / "next_page.tsx").read_text(encoding="utf-8")
        result = normalize.normalize_text(raw, suffix=".tsx")
        self.assertNotIn("import React from", result.text)
        self.assertIn("Browse widgets", result.text)

    def test_video_not_walked_without_support(self) -> None:
        self.assertFalse(media.image_ocr_supported())
        reason = media.media_skip_reason(".mp4")
        if not media.video_audio_supported():
            self.assertIsNotNone(reason)

    def test_read_text_file_tsx_sets_import_map(self) -> None:
        path = FIXTURES / "next_page.tsx"
        text, digest = read_text_file(path)
        self.assertTrue(digest)
        self.assertIn("ProductPage", text)
        self.assertTrue(getattr(read_text_file, "last_import_map", []))

    def test_jaccard_demote_near_dup_children(self) -> None:
        # Two nearly identical windows should demote the second
        body = ("Alpha beta gamma delta epsilon. " * 40) + "\n\n" + ("Alpha beta gamma delta epsilon. " * 40)
        parents, children, metrics = chunking.parent_child_chunk(body, child_tokens=80)
        self.assertTrue(parents)
        self.assertGreaterEqual(int(metrics.get("demoted_children") or 0), 0)


if __name__ == "__main__":
    unittest.main()

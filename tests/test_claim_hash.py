"""Unit tests for atomic content-hash claiming (clipboard/screenshot dedup)."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path


class ClaimHashTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        import db

        self.db = db
        self._orig = db.DB_PATH
        db.DB_PATH = Path(self._tmpdir.name) / "clipdrop.db"
        db.init_db()

    def tearDown(self) -> None:
        self.db.DB_PATH = self._orig

    def test_claim_hash_winner_loser(self) -> None:
        h = "a" * 64
        self.assertTrue(self.db.claim_hash(h))
        self.assertFalse(self.db.claim_hash(h))
        self.assertTrue(self.db.hash_seen(h))

    def test_claim_hash_empty(self) -> None:
        self.assertFalse(self.db.claim_hash(""))
        self.assertFalse(self.db.claim_hash(None))  # type: ignore[arg-type]

    def test_claim_hash_concurrent_one_winner(self) -> None:
        h = "b" * 64
        wins: list[bool] = []
        lock = threading.Lock()

        def worker() -> None:
            ok = self.db.claim_hash(h)
            with lock:
                wins.append(ok)

        threads = [threading.Thread(target=worker) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(1 for w in wins if w), 1)
        self.assertEqual(len(wins), 16)
        self.assertTrue(self.db.hash_seen(h))

    def test_claim_after_message_content_hash(self) -> None:
        h = "c" * 64
        msg = self.db.add_message(
            device_ip="127.0.0.1",
            device_name="test",
            text="x",
            kind="text",
            source="chat",
            content_hash=h,
        )
        self.assertIsNotNone(msg)
        self.assertFalse(self.db.claim_hash(h))


class ImageContentHashTests(unittest.TestCase):
    def test_identical_pixels_different_icc_same_hash(self) -> None:
        import io

        from PIL import Image, ImageCms

        import clipdrop

        im = Image.new("RGB", (32, 24), (12, 34, 56))
        plain = io.BytesIO()
        im.save(plain, format="PNG")
        plain_bytes = plain.getvalue()

        # Embed a tiny sRGB ICC so PNG bytes differ while pixels match.
        try:
            profile = ImageCms.createProfile("sRGB")
            icc = ImageCms.ImageCmsProfile(profile).tobytes()
        except Exception:
            self.skipTest("Pillow ICC profile unavailable")
        with_icc = io.BytesIO()
        im.save(with_icc, format="PNG", icc_profile=icc)
        icc_bytes = with_icc.getvalue()

        self.assertNotEqual(
            __import__("hashlib").sha256(plain_bytes).hexdigest(),
            __import__("hashlib").sha256(icc_bytes).hexdigest(),
            "precondition: PNG file hashes must differ when ICC is present",
        )
        self.assertEqual(
            clipdrop._image_content_hash(plain_bytes),
            clipdrop._image_content_hash(icc_bytes),
        )


class UrlGroundingTests(unittest.TestCase):
    def test_extract_urls(self) -> None:
        import ai_engine

        urls = ai_engine._extract_urls(
            "see https://example.com/a and https://example.com/a again http://x.test/y."
        )
        self.assertEqual(urls, ["https://example.com/a", "http://x.test/y"])

    def test_fetch_url_evidence_marks_failure(self) -> None:
        import ai_engine

        block = ai_engine._fetch_url_evidence(["http://127.0.0.1:1/nope"])
        self.assertIn("fetch failed", block.lower())
        self.assertIn("do not invent", block.lower())


if __name__ == "__main__":
    unittest.main()

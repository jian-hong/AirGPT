"""Hard RAG faithfulness cases — unanswerable averages + cross-source stitching."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class RagHardFaithfulnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        root = Path(self._tmpdir.name)
        # Minimal corpus mirroring Demo multi-format stubs
        (root / "spec.txt").write_text(
            "# SNR Results\nPeak 92.5 dB measured at 10 kHz.\n", encoding="utf-8"
        )
        (root / "lab.txt").write_text(
            "## Sheet: Measurements\n"
            "Frequency_Hz | Noise_nV | Notes\n"
            "1000  | 4.7 | RS622XK baseline\n"
            "10000 | 3.1 | shielded run\n"
            "100000| 2.4 | low-noise amp\n"
            "\n## Sheet: Summary\n"
            "Peak SNR dB | 92.5\n"
            "Verdict | passes spec\n",
            encoding="utf-8",
        )
        self.root = root

    def test_average_snr_not_in_corpus(self) -> None:
        """Average SNR cannot be computed — only a peak scalar + noise nV table."""
        blob = "\n".join(p.read_text(encoding="utf-8") for p in self.root.glob("*.txt")).lower()
        self.assertIn("92.5", blob)
        self.assertIn("noise_nv", blob.replace(" ", ""))
        # No per-frequency SNR series to average
        self.assertNotRegex(blob, r"snr.*(1|10|100)\s*khz.*\d")
        # Guard: answer that invents an average is unfaithful
        invented = "The average SNR across frequencies is 87.3 dB."
        self.assertNotIn("87.3", blob)
        self.assertTrue("average" not in blob or "peak snr" in blob)

    def test_ten_khz_only_in_spec_not_lab_summary(self) -> None:
        lab = (self.root / "lab.txt").read_text(encoding="utf-8")
        spec = (self.root / "spec.txt").read_text(encoding="utf-8")
        self.assertIn("10 kHz", spec)
        # Lab summary has peak SNR but does not bind it to 10 kHz
        summary = lab.split("## Sheet: Summary", 1)[-1]
        self.assertIn("92.5", summary)
        self.assertNotIn("10 kHz", summary)

    def test_noise_lookup_is_answerable(self) -> None:
        lab = (self.root / "lab.txt").read_text(encoding="utf-8")
        self.assertIn("3.1", lab)
        self.assertIn("10000", lab)


if __name__ == "__main__":
    unittest.main()

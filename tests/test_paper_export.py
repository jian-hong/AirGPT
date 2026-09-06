"""Research-agent paper package: long md + path figures + stdlib docx."""
from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

import paper_export


TEX = r"""
\documentclass[conference]{IEEEtran}
\begin{document}
\title{Local Citation Gate}
\begin{abstract}
A local gate drops unresolved DOIs. Related work and limitations follow.
\end{abstract}
\begin{IEEEkeywords}
citation, HTTP
\end{IEEEkeywords}
\section{Introduction}
""" + ("prose " * 240) + r"""
\section{Related Work}
""" + ("cite " * 240) + r"""
\section{Method}
\textbf{strict} and \emph{local}.
\includegraphics[width=0.48\textwidth]{fig5_score_progression}
\section{Limitations}
Pending silicon.
\end{document}
"""


class PaperExportTests(unittest.TestCase):
    def test_tex_to_markdown_is_long_and_structured(self):
        md = paper_export.tex_to_markdown(TEX)
        self.assertGreater(len(md), 2500)
        self.assertIn("## Abstract", md)
        self.assertIn("Related Work", md)
        self.assertIn("**strict**", md)
        self.assertIn("*local*", md)
        self.assertIn("figures/fig5_score_progression", md)

    def test_package_writes_md_and_docx_with_image(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td)
            pkg = run / "arxiv_package"
            figs = pkg / "figures"
            figs.mkdir(parents=True)
            (pkg / "paper.tex").write_text(TEX, encoding="utf-8")
            llm = run / "llm"
            llm.mkdir()
            long_md = (
                "# Gate\n\n## Abstract\n\n" + ("body " * 400) + "\n\n## Related Work\n\n"
                + ("cite " * 400) + "\n\n## Limitations\nPending.\n"
            )
            (llm / "paper-md-1.txt").write_text(long_md, encoding="utf-8")
            png = figs / "fig5_score_progression.png"
            png.write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\nIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x01\x00"
                b"\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            packed = paper_export.package_run(run, idea="A local citation gate")
            self.assertTrue(packed["ok"], packed)
            self.assertGreaterEqual(packed["md_chars"], 2500)
            md_path = Path(packed["md"])
            docx = Path(packed["docx"])
            self.assertTrue(md_path.is_file())
            self.assertTrue(docx.is_file())
            text = md_path.read_text(encoding="utf-8")
            self.assertIn("Related Work", text)
            self.assertIn("```mermaid", text)
            self.assertGreater(docx.stat().st_size, 1000)
            with zipfile.ZipFile(docx) as zf:
                names = zf.namelist()
                self.assertIn("word/document.xml", names)
                xml = zf.read("word/document.xml").decode("utf-8")
                self.assertIn("w:cols", xml)
                self.assertTrue(any(n.startswith("word/media/") for n in names))
            self.assertFalse(packed.get("ui_exports"))
            self.assertFalse((Path("ui") / "exports" / run.name).is_dir())


if __name__ == "__main__":
    unittest.main()

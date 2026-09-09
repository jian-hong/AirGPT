"""Research-agent paper package: long markdown, path figures, Word.

Cortex still owns generation. This module only packages artifacts that
already exist on disk (tex, LLM markdown, matplotlib PNG). Stdlib OOXML
plus Pillow (already a product dep) for image size and a local architecture
diagram. No python-docx, no pandoc, no OpenHBM unpark.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

_NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS_PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"

_TITLE_RE = re.compile(r"\\title\{([^}]*)\}", re.S)
_ABS_RE = re.compile(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.S)
_KW_RE = re.compile(r"\\begin\{IEEEkeywords\}(.*?)\\end\{IEEEkeywords\}", re.S)
_SEC_RE = re.compile(r"\\(sub)*section\{([^}]*)\}")
_INC_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_CITE_RE = re.compile(r"\\cite\{([^}]+)\}")
_CMD_RE = re.compile(r"\\[a-zA-Z]+\*?\{([^{}]*)\}")
_CMD_BARE = re.compile(r"\\[a-zA-Z]+\*?")
_MD_IMG = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_MD_ITAL = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_MD_CODE = re.compile(r"`([^`]+)`")


def _untex_inline(s: str) -> str:
    t = s or ""
    t = t.replace("~\\", " ")
    t = _CITE_RE.sub(r"[\1]", t)
    t = re.sub(r"\\textbf\{([^}]*)\}", r"**\1**", t)
    t = re.sub(r"\\emph\{([^}]*)\}", r"*\1*", t)
    t = re.sub(r"\\textit\{([^}]*)\}", r"*\1*", t)
    t = re.sub(r"\\texttt\{([^}]*)\}", r"`\1`", t)
    t = t.replace("\\&", "&").replace("\\%", "%").replace("\\_", "_")
    t = t.replace("\\,", " ").replace("\\;", " ").replace("\\ ", " ")
    for _ in range(4):
        t = _CMD_RE.sub(r"\1", t)
    t = _CMD_BARE.sub("", t)
    t = t.replace("{", "").replace("}", "")
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def tex_to_markdown(tex: str) -> str:
    """IEEEtran -> long markdown. Venue structure, not a blog rewrite."""
    raw = tex or ""
    title = _untex_inline(m.group(1) if (m := _TITLE_RE.search(raw)) else "Untitled")
    abs_ = _untex_inline(m.group(1) if (m := _ABS_RE.search(raw)) else "")
    kws = _untex_inline(m.group(1) if (m := _KW_RE.search(raw)) else "")
    kws = re.sub(r"\s+", " ", kws.replace(";", ","))
    body = raw
    for pat in (_ABS_RE, _KW_RE, _TITLE_RE):
        body = pat.sub("", body)
    body = re.sub(r"\\documentclass.*?\\begin\{document\}", "", body, flags=re.S)
    body = re.sub(r"\\end\{document\}.*", "", body, flags=re.S)
    body = re.sub(r"\\maketitle", "", body)
    body = re.sub(r"\\author\{.*?\}", "", body, flags=re.S)
    body = re.sub(r"\\IEEEauthorblock[A-Za-z]*\{.*?\}", "", body, flags=re.S)
    body = re.sub(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", "", body, flags=re.S)
    body = re.sub(
        r"\\begin\{figure\}.*?\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}.*?\\caption\{([^}]*)\}.*?\\end\{figure\}",
        lambda m: f"\n\n![{_untex_inline(m.group(2))}](figures/{Path(m.group(1)).name})\n\n",
        body,
        flags=re.S,
    )
    body = _INC_RE.sub(lambda m: f"\n\n![](figures/{Path(m.group(1)).stem}.png)\n\n", body)
    body = re.sub(
        r"\\begin\{verbatim\}(.*?)\\end\{verbatim\}",
        lambda m: "\n```\n" + m.group(1).strip() + "\n```\n",
        body,
        flags=re.S,
    )
    lines = ["# " + (title or "Untitled"), ""]
    if abs_:
        lines += ["## Abstract", "", "*" + abs_ + "*", ""]
    if kws:
        lines += ["**Keywords.** " + kws, ""]
    for line in body.splitlines():
        s = line.strip()
        if not s:
            lines.append("")
            continue
        m = re.match(r"\\(sub)*section\{([^}]*)\}", s)
        if m:
            depth = 2 + (s.count("sub"))
            lines.append("#" * depth + " " + _untex_inline(m.group(2)))
            continue
        if s.startswith("%") or s.startswith("\\begin{") or s.startswith("\\end{"):
            continue
        lines.append(_untex_inline(s))
    md = "\n".join(lines)
    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    return md


def pick_markdown(run_dir: Path, tex: str = "") -> str:
    llm = run_dir / "llm"
    best = ""
    if llm.is_dir():
        for f in sorted(llm.glob("paper-md-*.txt"), key=lambda p: p.stat().st_mtime):
            cand = f.read_text(encoding="utf-8") if f.is_file() else ""
            if len(cand) > len(best):
                best = cand
    if len(best) >= 2500 and "related" in best.lower() and (
        "limitation" in best.lower() or "threats to validity" in best.lower()
    ):
        return best if best.endswith("\n") else best + "\n"
    converted = tex_to_markdown(tex or _read(run_dir / "arxiv_package" / "paper.tex"))
    if len(converted) >= len(best):
        return converted
    return best or converted


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def ensure_architecture_png(figs: Path) -> Path | None:
    """Local architecture figure (Pillow). Decorative; no invented metrics."""
    figs.mkdir(parents=True, exist_ok=True)
    out = figs / "fig_architecture.png"
    if out.is_file() and out.stat().st_size > 80:
        return out
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return out if out.is_file() else None
    img = Image.new("RGB", (920, 220), "#f7f7f4")
    dr = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("times.ttf", 16)
        small = ImageFont.truetype("times.ttf", 13)
    except Exception:
        font = ImageFont.load_default()
        small = font
    boxes = [
        (30, 70, 210, 150, "Bibliography"),
        (250, 70, 430, 150, "Extract IDs"),
        (470, 70, 650, 150, "HTTP resolve"),
        (690, 70, 890, 150, "Gate / drop"),
    ]
    for x0, y0, x1, y1, lab in boxes:
        dr.rounded_rectangle([x0, y0, x1, y1], radius=8, outline="#1a365d", width=2, fill="#ffffff")
        dr.text((x0 + 16, y0 + 28), lab, fill="#1a365d", font=font)
    for i in range(3):
        x = boxes[i][2] + 4
        dr.line([(x, 110), (boxes[i + 1][0] - 4, 110)], fill="#1a365d", width=2)
    dr.text((30, 16), "Figure 1. Local citation-gate pipeline (generated, not a metric source).", fill="#4a5568", font=small)
    img.save(out, "PNG")
    return out


def inject_figures(md: str, figs: Path) -> str:
    text = md or ""
    pngs = []
    arch = ensure_architecture_png(figs)
    if arch and arch.is_file():
        pngs.append(arch)
    score = figs / "fig5_score_progression.png"
    if score.is_file():
        pngs.append(score)
    for p in sorted(figs.glob("*.png")):
        if p not in pngs:
            pngs.append(p)
    for p in pngs:
        token = f"](figures/{p.name})"
        if token not in text and p.name not in text:
            cap = "Phase harness scores from Captured facts." if "score" in p.name else "Architecture overview."
            text = text.rstrip() + f"\n\n![{cap}](figures/{p.name})\n"
    if "```mermaid" not in text.lower():
        text = text.rstrip() + (
            "\n\n## Method graph\n\n"
            "```mermaid\n"
            "flowchart LR\n"
            "  bib[Bibliography] --> extract[Extract DOI/arXiv/URL]\n"
            "  extract --> http[HTTP resolve-or-drop]\n"
            "  http --> gate[Manuscript gate]\n"
            "  gate --> paper[Filtered preprint]\n"
            "```\n"
        )
    return text if text.endswith("\n") else text + "\n"


def copy_figures_next_to_md(md_path: Path, figs: Path) -> None:
    dest = md_path.parent / "figures"
    dest.mkdir(parents=True, exist_ok=True)
    if not figs.is_dir():
        return
    for p in figs.glob("*.png"):
        target = dest / p.name
        if p.resolve() != target.resolve():
            target.write_bytes(p.read_bytes())


def _xml_t(text: str) -> str:
    return escape(text or "", {"'": "&apos;", '"': "&quot;"})


def _runs_from_md(s: str, *, italic_all: bool = False, size_half: int = 20) -> str:
    """Very small markdown span parser: **bold** *italic* `code`."""
    parts: list[tuple[str, str]] = []
    i = 0
    buf = s or ""
    while i < len(buf):
        m_b = _MD_BOLD.search(buf, i)
        m_i = _MD_ITAL.search(buf, i)
        m_c = _MD_CODE.search(buf, i)
        cands = [(m.start(), "b", m) for m in (m_b,) if m]
        cands += [(m.start(), "i", m) for m in (m_i,) if m]
        cands += [(m.start(), "c", m) for m in (m_c,) if m]
        if not cands:
            parts.append(("t", buf[i:]))
            break
        cands.sort()
        start, kind, m = cands[0]
        if start > i:
            parts.append(("t", buf[i:start]))
        parts.append((kind, m.group(1)))
        i = m.end()
    xml = []
    for kind, t in parts:
        if not t:
            continue
        rpr = [f'<w:sz w:val="{size_half}"/>', f'<w:szCs w:val="{size_half}"/>', '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/>']
        if italic_all or kind == "i":
            rpr.append("<w:i/>")
        if kind == "b":
            rpr.append("<w:b/>")
        if kind == "c":
            rpr.append('<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New"/>')
        xml.append(f'<w:r><w:rPr>{"".join(rpr)}</w:rPr><w:t xml:space="preserve">{_xml_t(t)}</w:t></w:r>')
    return "".join(xml) or f'<w:r><w:t xml:space="preserve">{_xml_t(s)}</w:t></w:r>'


def _p(style: str, inner: str, *, jc: str = "") -> str:
    jc_xml = f'<w:jc w:val="{jc}"/>' if jc else ""
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/>{jc_xml}</w:pPr>{inner}</w:p>'


def _img_extent(path: Path, max_w_in: float = 3.2) -> tuple[int, int]:
    w_in, h_in = max_w_in, max_w_in * 0.45
    try:
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
            if w > 0:
                h_in = max_w_in * (h / w)
    except Exception:
        pass
    emu = 914400
    return int(w_in * emu), int(h_in * emu)


def _drawing(rid: str, cx: int, cy: int, name: str) -> str:
    return (
        f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:docPr id="{rid[3:]}" name="{_xml_t(name)}"/>'
        f'<a:graphic xmlns:a="{_NS_A}"><a:graphicData uri="{_NS_PIC}">'
        f'<pic:pic xmlns:pic="{_NS_PIC}"><pic:nvPicPr><pic:cNvPr id="0" name="{_xml_t(name)}"/>'
        f"<pic:cNvPicPr/></pic:nvPicPr>"
        f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        f"</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"
    )


def markdown_to_docx(md: str, dest: Path, media_root: Path) -> Path:
    """Write an IEEE-ish two-column .docx. Images resolved relative to media_root."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    images: list[Path] = []
    body_xml: list[str] = []
    in_code = False
    code_buf: list[str] = []
    first = True
    for raw in (md or "").splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                body_xml.append(_p("Code", _runs_from_md("\n".join(code_buf), size_half=16)))
                code_buf = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue
        img = _MD_IMG.search(line)
        if img:
            pth = (media_root / img.group(2)).resolve()
            if not str(pth).startswith(str(media_root.resolve())):
                alt = (media_root / "figures" / Path(img.group(2)).name)
                pth = alt if alt.is_file() else pth
            if pth.is_file():
                images.append(pth)
                rid = f"rId{len(images) + 4}"
                cx, cy = _img_extent(pth)
                cap = img.group(1) or pth.stem
                body_xml.append(_p("Normal", _drawing(rid, cx, cy, pth.name), jc="center"))
                body_xml.append(_p("Caption", _runs_from_md("*" + cap + "*", italic_all=True, size_half=16), jc="center"))
            continue
        if not line.strip():
            continue
        if line.startswith("# "):
            body_xml.append(_p("Title", _runs_from_md(line[2:].strip(), size_half=28), jc="center"))
            continue
        if line.lower().startswith("## abstract"):
            body_xml.append(_p("Heading1", _runs_from_md("Abstract", size_half=20)))
            first = False
            continue
        if line.startswith("### "):
            body_xml.append(_p("Heading2", _runs_from_md(line[4:].strip(), size_half=20)))
            continue
        if line.startswith("## "):
            body_xml.append(_p("Heading1", _runs_from_md(line[3:].strip(), size_half=22)))
            continue
        # Abstract body: small italic (IEEE abstract).
        if any("Abstract" in x and "Heading1" in x for x in body_xml[-2:]):
            body_xml.append(_p("Abstract", _runs_from_md(line.strip("* "), italic_all=True, size_half=18)))
            continue
        body_xml.append(_p("Normal", _runs_from_md(line, size_half=20)))
        first = False

    sect = (
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080"/>'
        '<w:cols w:num="2" w:space="720"/>'
        "</w:sectPr>"
    )
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_NS_W}" xmlns:r="{_NS_R}" xmlns:wp="{_NS_WP}" xmlns:a="{_NS_A}">'
        f"<w:body>{''.join(body_xml)}{sect}</w:body></w:document>"
    )
    styles = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{_NS_W}">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/>
    <w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/><w:sz w:val="20"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/>
    <w:pPr><w:jc w:val="center"/><w:spacing w:after="200"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="28"/><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
    <w:rPr><w:b/><w:sz w:val="22"/><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>
    <w:rPr><w:b/><w:i/><w:sz w:val="20"/><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Abstract"><w:name w:val="Abstract"/>
    <w:rPr><w:i/><w:sz w:val="18"/><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="Caption"/>
    <w:rPr><w:i/><w:sz w:val="16"/><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/>
    <w:rPr><w:sz w:val="16"/><w:rFonts w:ascii="Courier New" w:hAnsi="Courier New"/></w:rPr></w:style>
</w:styles>
"""
    rels_extra = []
    for i, pth in enumerate(images, start=1):
        rid = f"rId{i + 4}"
        rels_extra.append(
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{pth.name}"/>'
        )
    doc_rels = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  {''.join(rels_extra)}
</Relationships>
"""
    pkg_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
    ctypes_overrides = "".join(
        f'<Override PartName="/word/media/{p.name}" ContentType="image/png"/>' for p in images
    )
    content_types = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  {ctypes_overrides}
</Types>
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", pkg_rels)
        zf.writestr("word/document.xml", document)
        zf.writestr("word/styles.xml", styles)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)
        used = set()
        for pth in images:
            name = pth.name
            if name in used:
                continue
            used.add(name)
            zf.writestr(f"word/media/{name}", pth.read_bytes())
    dest.write_bytes(buf.getvalue())
    return dest


def publish_ui_exports(run_dir: Path, files: list[Path]) -> str:
    """Copy packaged files under /ui/exports so a live clipdrop can serve them.

    /ui/ is re-read from disk on every request. New /api/research/artifact
    routes only exist after a clipdrop reload. Skip temp test dirs.
    """
    try:
        from config import DATA_DIR, ROOT

        run_dir.resolve().relative_to((DATA_DIR / "research" / "runs").resolve())
    except (ValueError, OSError, ImportError):
        return ""
    rid = run_dir.name
    if not rid or rid in (".", "..") or "/" in rid or "\\" in rid:
        return ""
    dest = ROOT / "ui" / "exports" / rid
    dest.mkdir(parents=True, exist_ok=True)
    for src in files:
        if src and src.is_file():
            shutil.copy2(src, dest / src.name)
    fig_src = run_dir / "paper" / "figures"
    if fig_src.is_dir():
        fig_dest = dest / "figures"
        fig_dest.mkdir(parents=True, exist_ok=True)
        for p in fig_src.glob("*.png"):
            shutil.copy2(p, fig_dest / p.name)
    idx_path = ROOT / "ui" / "exports" / "index.json"
    rows: list[dict[str, Any]] = []
    if idx_path.is_file():
        try:
            prev = json.loads(idx_path.read_text(encoding="utf-8"))
            rows = [r for r in (prev.get("runs") or []) if isinstance(r, dict) and r.get("id") != rid]
        except Exception:
            rows = []
    md_p = dest / "paper.md"
    docx_p = dest / "paper.docx"
    pdf_p = dest / "paper.pdf"
    rows.insert(
        0,
        {
            "id": rid,
            "md": md_p.is_file(),
            "docx": docx_p.is_file(),
            "pdf": pdf_p.is_file(),
            "md_chars": md_p.stat().st_size if md_p.is_file() else 0,
            "docx_bytes": docx_p.stat().st_size if docx_p.is_file() else 0,
        },
    )
    idx_path.write_text(json.dumps({"ok": True, "runs": rows[:40]}, indent=2), encoding="utf-8")
    return str(dest.as_posix())


def package_run(run_dir: Path, *, idea: str = "", tex: str = "") -> dict[str, Any]:
    """Write paper/paper.md + paper/paper.docx + copy figures. No LLM calls."""
    run_dir = Path(run_dir)
    pkg = run_dir / "arxiv_package"
    figs = pkg / "figures"
    script = figs / "fig_score_progression.py"
    png = figs / "fig5_score_progression.png"
    if script.is_file() and not png.is_file():
        import subprocess
        import sys

        subprocess.run(
            [sys.executable, str(script)],
            cwd=str(figs),
            capture_output=True,
            text=True,
            timeout=30,
        )
    tex_txt = tex or _read(pkg / "paper.tex")
    md = inject_figures(pick_markdown(run_dir, tex_txt), figs)
    md_path = run_dir / "paper" / "paper.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    copy_figures_next_to_md(md_path, figs)
    docx_path = run_dir / "paper" / "paper.docx"
    markdown_to_docx(md, docx_path, md_path.parent)
    pdf = pkg / "paper.pdf"
    out = {
        "ok": len(md) >= 2500 and docx_path.is_file(),
        "md": str(md_path.as_posix()),
        "md_chars": len(md),
        "docx": str(docx_path.as_posix()) if docx_path.is_file() else "",
        "pdf": str(pdf.as_posix()) if pdf.is_file() else "",
        "figures": [p.name for p in sorted((md_path.parent / "figures").glob("*.png"))] if (md_path.parent / "figures").is_dir() else [],
        "idea": (idea or "")[:120],
    }
    try:
        import research as research_lib

        research_lib.save_draft(idea[:80] or md_path.stem, md, category="idea-to-paper")
    except Exception:
        pass
    out["ui_exports"] = publish_ui_exports(run_dir, [md_path, docx_path, pdf])
    return out

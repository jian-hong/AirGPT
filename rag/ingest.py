"""Deterministic ingest: authorize → extract → chunk → enrich → index → publish."""
from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

from rag import chunking, sira, store, vectors


_ARCH_SAFE = re.compile(r"[^a-z0-9_]+")


def revision_profile(space: dict | None) -> str:
    """Stamp profile + saved architecture + depth onto the revision row.

    Ingest still builds one hybrid index (DR-0006). Architecture is
    retrieve-time until a later epic owns a second indexer. The label must
    still name what Settings saved, or Rebuild after Manual/graph is a lie.
    """
    space = space or {}
    space_profile = str(space.get("profile") or "local").strip() or "local"
    depth = str(space.get("depth_default") or "high").strip() or "high"
    cfg = space.get("config") if isinstance(space.get("config"), dict) else {}
    arch = str((cfg or {}).get("architecture") or "hybrid").strip().lower() or "hybrid"
    arch = _ARCH_SAFE.sub("", arch)[:32] or "hybrid"
    return f"{space_profile}_{arch}_{depth}"[:80]


def _blob_dir(space_id: int) -> Path:
    return store.BLOB_DIR / str(int(space_id)) / "sources"


def _is_extracted_blob(path: Path, space_id: int) -> bool:
    try:
        return path.parent.resolve() == _blob_dir(space_id).resolve() and path.suffix.lower() == ".txt"
    except Exception:
        return False


def _docs_dir(space_id: int) -> Path:
    return store.BLOB_DIR / str(int(space_id)) / "Docs"


def _original_basename(path: Path, space_id: int) -> str:
    """User filename. Docs copies are stored as {8hex}_{original_name}."""
    try:
        if path.parent.resolve() == _docs_dir(space_id).resolve():
            name = path.name
            hex8 = name[:8].lower()
            if len(name) > 9 and name[8] == "_" and all(c in "0123456789abcdef" for c in hex8):
                return name[9:]
    except Exception:
        pass
    return path.name


def rebuild_source_paths(srcs: list | None) -> list[str]:
    """Paths to re-ingest. Live original, then Docs original, then .txt blob."""
    out: list[str] = []
    for s in srcs or []:
        meta = s.get("meta") if isinstance(s.get("meta"), dict) else {}
        try:
            sid = int(s.get("space_id") or 0)
        except (TypeError, ValueError):
            sid = 0
        chosen = ""
        for raw in (s.get("path"), meta.get("original_path"), meta.get("docs_path")):
            if not raw:
                continue
            p = Path(str(raw))
            try:
                if p.is_file() and not (sid and _is_extracted_blob(p, sid)):
                    chosen = str(p)
                    break
            except Exception:
                continue
        if not chosen:
            blob = meta.get("blob")
            if blob and Path(str(blob)).is_file():
                chosen = str(blob)
        if chosen:
            out.append(chosen)
    return out


def backfill_docs_originals(space_id: int) -> dict:
    """Fill missing meta.docs_path from a still-live original (#34). Cannot invent bytes."""
    filled = 0
    already = 0
    missing = 0
    for src in store.list_sources(int(space_id)):
        meta = dict(src.get("meta") or {}) if isinstance(src.get("meta"), dict) else {}
        existing = str(meta.get("docs_path") or "")
        if existing and Path(existing).is_file():
            already += 1
            continue
        digest = str(src.get("content_hash") or "")
        dest = ""
        for raw in (src.get("path"), meta.get("original_path")):
            if not raw:
                continue
            p = Path(str(raw))
            if not p.is_file() or _is_extracted_blob(p, int(space_id)):
                continue
            dest = _retain_docs_original(int(space_id), p, digest)
            if dest:
                break
        if dest:
            meta["docs_path"] = dest
            store.update_source_status(
                int(src["id"]),
                str(src.get("status") or "ready"),
                meta=meta,
            )
            filled += 1
        else:
            missing += 1
    return {
        "ok": True,
        "space_id": int(space_id),
        "filled": filled,
        "already": already,
        "missing": missing,
    }


def _retain_docs_original(space_id: int, path: Path, digest: str) -> str:
    """Byte-faithful copy under space Docs/ for audit (RAG-BENCH-09). No encryption (P9)."""
    try:
        if not path.is_file():
            return ""
        docs_dir = store.BLOB_DIR / str(int(space_id)) / "Docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        # Already living in this space Docs/ — that IS the backup path.
        if path.parent.resolve() == docs_dir.resolve():
            return str(path.resolve())
        safe = f"{(digest or 'x')[:8]}_{path.name}"
        safe = safe.replace("/", "_").replace("\\", "_")
        dest = docs_dir / safe
        if dest.resolve() == path.resolve():
            return str(dest)
        if not dest.exists():
            shutil.copy2(path, dest)
        return str(dest)
    except Exception:
        return ""

TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
    ".html",
    ".css",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".sql",
    ".sh",
    ".ps1",
    ".xlsx",
    ".xlsm",
    ".docx",
    ".pptx",
    ".eml",
}


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pdf_supported() -> bool:
    """PDF text extraction is opportunistic — pypdf if the user installed it."""
    try:
        import pypdf  # noqa: F401

        return True
    except Exception:
        try:
            import PyPDF2  # noqa: F401

            return True
        except Exception:
            return False


def _pdf_text(path: Path) -> str:
    try:
        try:
            from pypdf import PdfReader
        except Exception:
            from PyPDF2 import PdfReader  # type: ignore[no-redef]
        reader = PdfReader(str(path))
        # One heading per page: the chunker carries it into every hit, so an answer
        # can say "page 7" instead of only naming a 200-page file.
        pages = [(i, (pg.extract_text() or "").strip()) for i, pg in enumerate(reader.pages[:200], 1)]
        return "\n\n".join(f"## Page {i}\n{t}" for i, t in pages if t)
    except Exception:
        return ""


def xlsx_supported() -> bool:
    """Spreadsheet extraction needs openpyxl. Declared in requirements, checked anyway."""
    try:
        import openpyxl  # noqa: F401

        return True
    except Exception:
        return False


# Binary lanes whose extractor rides a third-party package. An install that lacks the
# package must SAY the lane is down, never hand back an empty string that retrieval
# reports as "no evidence" (R-0011 — a silent fallback is a lie). Stdlib-only lanes
# (.docx, .pptx) are absent on purpose: they cannot go missing.
_EXTRACTOR_GATES: list[tuple[frozenset[str], str, object]] = [
    (frozenset({".pdf"}), "pdf needs text extract - pip install pypdf", pdf_supported),
    (
        frozenset({".xlsx", ".xlsm"}),
        "spreadsheet needs text extract - pip install openpyxl",
        xlsx_supported,
    ),
]


def extractor_gap(suffix: str) -> str:
    """Reason this suffix cannot be extracted here, or "" when the lane is healthy."""
    suffix = (suffix or "").lower()
    for suffixes, reason, probe in _EXTRACTOR_GATES:
        if suffix in suffixes and not probe():  # type: ignore[operator]
            return reason
    return ""


def _xlsx_text(path: Path) -> str:
    """Every sheet's cells as readable rows, so embeddings see the data, not zip bytes.

    Small sheets (Summary/KPI) are emitted first so parent-child chunking keeps
    them intact near the top instead of burying them under detail-row dumps.
    """
    try:
        import openpyxl
    except Exception:
        return ""
    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception:
        return ""
    sheets: list[tuple[int, str, list[str]]] = []
    try:
        for ws in wb.worksheets:
            title = (ws.title or "").strip()
            if title.casefold() in {"questions", "readme"}:
                continue
            rows: list[str] = []
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None and str(c).strip() != ""]
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                sheets.append((len(rows), title, rows))
    finally:
        try:
            wb.close()
        except Exception:
            pass
    if not sheets:
        return ""
    # Smallest sheets first (KPIs), then large fact tables
    sheets.sort(key=lambda t: (t[0], t[1].casefold()))
    index_lines = [f"- {title} ({n} rows)" for n, title, _ in sheets]
    out: list[str] = ["## Spreadsheet index\n" + "\n".join(index_lines)]
    for _n, title, rows in sheets:
        out.append(f"## Sheet: {title}\n" + "\n".join(rows))
    return "\n\n".join(out).strip()


def _csv_text(path: Path, raw_text: str) -> str:
    """Delimited rows as a sheet extract, same shape as `_xlsx_text`.

    Without this a .csv fell through to raw bytes: no `## Sheet:` line, so every
    parent heading came back empty and the header row never travelled with the
    later row windows. Rows stayed intact, but "whole-row children under sheet
    parents" was only half true. Stdlib csv, never a split on ',' — a quoted
    comma has to stay inside its cell.
    """
    import csv as _csv
    import io

    rows: list[str] = []
    try:
        for row in _csv.reader(io.StringIO(raw_text, newline="")):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip() != ""]
            if cells:
                rows.append(" | ".join(cells))
    except Exception:
        return ""
    if not rows:
        return ""
    title = (path.stem or path.name).strip() or "csv"
    index = f"## Spreadsheet index\n- {title} ({len(rows)} rows)"
    return f"{index}\n\n## Sheet: {title}\n" + "\n".join(rows)


# Suffixes whose extract is sheet rows, so chunking packs whole rows. `.xls` is
# gone on purpose: it is absent from TEXT_SUFFIXES and has no extractor branch, so
# naming it here only advertised support that never existed.
TABLE_SUFFIXES = {".xlsx", ".xlsm", ".csv"}

_SHEET_MARKERS = ("## Sheet:", "## Spreadsheet index")


def is_table_text(path: Path, text: str) -> bool:
    """Is this extract sheet rows? Decided on provenance/content, never on suffix.

    The rebuild path re-ingests the extracted `{digest}_{stem}.txt` blob (see
    `rebuild_source_paths`), whose suffix is `.txt`. Keying table-ness off the
    suffix there sent sheet rows back through the paragraph windower, which
    char-splits mid-row — the exact defect `chunking._window_rows` exists to
    prevent, returning on every rebuild after the original file was gone.
    """
    suffix = Path(path).suffix.lower()
    if suffix in TABLE_SUFFIXES:
        return True
    # The sniff is scoped to .txt on purpose. That is the shape the blob is written
    # in, and widening it would re-chunk every markdown file that happens to hold a
    # pipe table — a silent boundary move on an already-scored corpus.
    if suffix != ".txt":
        return False
    head = (text or "")[:20000]
    if any(marker in head for marker in _SHEET_MARKERS):
        return True
    # No marker (an extract whose header scrolled past the window): call it a table
    # only when most lines really are rows.
    lines = [ln for ln in head.splitlines() if ln.strip()]
    if len(lines) < 4:
        return False
    piped = sum(1 for ln in lines if " | " in ln)
    return piped >= max(4, int(0.6 * len(lines)))


def _ooxml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _docx_text(path: Path) -> str:
    """Body text in document order. Stdlib only.

    Heading styles become markdown headings (so chunks and citations carry the
    section) and a table becomes one line per row instead of one line per cell.
    """
    import re
    import zipfile
    from xml.etree import ElementTree as ET

    try:
        with zipfile.ZipFile(str(path)) as z:
            root = ET.fromstring(z.read("word/document.xml"))
    except Exception:
        return ""

    def para_text(p) -> str:
        return "".join(t.text for t in p.iter() if _ooxml_local(t.tag) == "t" and t.text).strip()

    def heading_level(p) -> int:
        for el in p.iter():
            if _ooxml_local(el.tag) == "pStyle":
                val = next((v for k, v in el.attrib.items() if _ooxml_local(k) == "val"), "")
                if val.lower() == "title":
                    return 1
                m = re.match(r"heading\s*(\d)", val, re.I)
                return min(6, int(m.group(1))) if m else 0
        return 0

    out: list[str] = []

    def walk(node) -> None:
        for el in node:
            tag = _ooxml_local(el.tag)
            if tag == "p":
                text = para_text(el)
                if text:
                    level = heading_level(el)
                    out.append(f"\n{'#' * level} {text}\n" if level else text)
            elif tag == "tbl":
                for tr in (r for r in el if _ooxml_local(r.tag) == "tr"):
                    cells = [
                        " ".join(filter(None, (para_text(p) for p in tc.iter() if _ooxml_local(p.tag) == "p")))
                        for tc in tr if _ooxml_local(tc.tag) == "tc"
                    ]
                    if any(cells):
                        out.append(" | ".join(cells))
            else:
                walk(el)  # body, sdt content, etc.

    walk(root)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _pptx_notes(z, slide_name: str) -> list[str]:
    """Speaker-notes text for one slide, found through the slide's relationships.

    Notes files are not numbered like their slides, so the .rels is the only pairing.
    """
    import posixpath
    from xml.etree import ElementTree as ET

    folder, base = posixpath.split(slide_name)
    try:
        rels = ET.fromstring(z.read(f"{folder}/_rels/{base}.rels"))
    except Exception:
        return []
    for rel in rels:
        if str(rel.attrib.get("Type", "")).endswith("/notesSlide"):
            target = posixpath.normpath(posixpath.join(folder, rel.attrib.get("Target", "")))
            try:
                root = ET.fromstring(z.read(target))
            except Exception:
                return []
            # A bare number in the notes pane is the slide-number placeholder.
            return [t.text.strip() for t in root.iter()
                    if _ooxml_local(t.tag) == "t" and t.text and t.text.strip() and not t.text.strip().isdigit()]
    return []


def _eml_text(raw: bytes) -> str:
    """An email as text: subject as the heading, then who/when, body, attachment names."""
    import email
    from email import policy

    try:
        msg = email.message_from_bytes(raw, policy=policy.default)
        body = msg.get_body(preferencelist=("plain", "html"))
        text = body.get_content() if body is not None else ""
        if body is not None and body.get_content_subtype() == "html":
            text = html_to_text(text)[1]
    except Exception:
        return ""
    head = [f"# {msg.get('Subject') or '(no subject)'}"]
    head += [f"{k}: {msg[k]}" for k in ("From", "To", "Cc", "Date") if msg.get(k)]
    names = [a.get_filename() for a in msg.iter_attachments() if a.get_filename()]
    tail = f"\n\nAttachments (not indexed): {', '.join(names)}" if names else ""
    return "\n".join(head) + "\n\n" + str(text).strip() + tail


def _pptx_text(path: Path) -> str:
    """Per-slide text from <a:t> runs across ppt/slides/slideN.xml. Stdlib only."""
    import fnmatch
    import re
    import zipfile
    from xml.etree import ElementTree as ET

    out: list[str] = []
    try:
        with zipfile.ZipFile(str(path)) as z:
            names = [n for n in z.namelist() if fnmatch.fnmatch(n, "ppt/slides/slide*.xml")]
            names.sort(key=lambda n: int((re.search(r"(\d+)", n) or [0, 0])[1]))
            for i, name in enumerate(names, 1):
                try:
                    root = ET.fromstring(z.read(name))
                except Exception:
                    continue
                texts = [t.text for t in root.iter() if _ooxml_local(t.tag) == "t" and t.text]
                notes = _pptx_notes(z, name)
                if notes:
                    texts.append("Speaker notes: " + " ".join(notes))
                if texts:
                    out.append(f"## Slide {i}\n" + "\n".join(texts))
    except Exception:
        return ""
    return "\n\n".join(out).strip()


def _flatten_json(obj, prefix: str = "") -> list[str]:
    """Structure-aware JSON → readable 'key path: value' lines for embedding."""
    lines: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                lines.extend(_flatten_json(v, key))
            else:
                lines.append(f"{key}: {v}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            key = f"{prefix}[{i}]"
            if isinstance(v, (dict, list)):
                lines.extend(_flatten_json(v, key))
                if isinstance(v, dict):
                    # Blank line after each record: the chunker cuts on paragraphs,
                    # so a record's fields are never split across two chunks.
                    lines.append("")
            else:
                lines.append(f"{key}: {v}")
    else:
        lines.append(f"{prefix}: {obj}" if prefix else str(obj))
    return lines


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_text_file(path: Path) -> tuple[str, str]:
    """Return (extracted_text, sha256). Applies type-aware normalize after extract."""
    from rag import normalize as norm
    from rag import media as media_mod

    raw = path.read_bytes()
    suffix = path.suffix.lower()
    text = ""
    if suffix == ".pdf":
        text = _pdf_text(path)
    elif suffix in (".xlsx", ".xlsm"):
        text = _xlsx_text(path)
    elif suffix == ".csv":
        text = _csv_text(path, _decode(raw)) or _decode(raw)
    elif suffix == ".docx":
        text = _docx_text(path)
    elif suffix == ".pptx":
        text = _pptx_text(path)
    elif suffix == ".eml":
        text = _eml_text(raw)
    elif suffix in media_mod.VIDEO_SUFFIXES | media_mod.AUDIO_SUFFIXES:
        text = media_mod.transcribe_media(path)
    elif suffix in media_mod.IMAGE_SUFFIXES:
        text = media_mod.ocr_image(path)
    elif suffix in (".html", ".htm"):
        title, body = html_to_text(_decode(raw))
        text = (f"# {title}\n\n{body}" if title else body).strip() or _decode(raw)
    elif suffix == ".json":
        import json as _json
        try:
            text = "\n".join(_flatten_json(_json.loads(_decode(raw))))
            if not text.strip():
                text = _decode(raw)
        except Exception:
            text = _decode(raw)
    else:
        text = _decode(raw)

    result = norm.normalize_text(text, path=path, suffix=suffix)
    # Identity is the EXTRACTED TEXT, not the container bytes. Re-ingesting an
    # .xlsx and re-ingesting its extracted .txt blob (the rebuild path) must
    # resolve to the same source, otherwise every rebuild duplicates the row.
    # Newline-agnostic so a blob written on Windows hashes like its source.
    digest = _hash_bytes(result.text.replace("\r\n", "\n").encode("utf-8", errors="replace"))
    # Stash import map on a thread-local-ish attribute for ingest to pick up
    read_text_file.last_import_map = list(result.import_map)  # type: ignore[attr-defined]
    read_text_file.last_meta = dict(result.meta)  # type: ignore[attr-defined]
    return result.text, digest


read_text_file.last_import_map = []  # type: ignore[attr-defined]
read_text_file.last_meta = {}  # type: ignore[attr-defined]


def iter_files(root: Path, *, max_files: int = 500) -> Iterable[Path]:
    root = Path(root)
    from rag import media as media_mod

    suffixes = TEXT_SUFFIXES | ({".pdf"} if pdf_supported() else set())
    if media_mod.video_audio_supported():
        suffixes |= media_mod.VIDEO_SUFFIXES | media_mod.AUDIO_SUFFIXES
    if media_mod.image_ocr_supported():
        suffixes |= media_mod.IMAGE_SUFFIXES
    if root.is_file():
        yield root
        return
    n = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf not in suffixes:
            continue
        if any(part.startswith(".") for part in p.parts):
            continue
        if "node_modules" in p.parts or "__pycache__" in p.parts or ".git" in p.parts:
            continue
        yield p
        n += 1
        if n >= max_files:
            break


def ingest_paths(
    space_id: int,
    paths: list[str | Path],
    *,
    force: bool = False,
    progress=None,
    authority: str = "",
) -> dict:
    """Ingest files/folders into a knowledge space and rebuild the local hybrid index.

    progress(stage, percent, detail) is called through the pipeline so callers
    (e.g. the SSE build endpoint) can drive a real "ready for retrieval" bar.

    ``authority`` records how the material entered rather than what it is called.
    A caller that knows it is writing chat transcripts says so, and the class then
    survives renaming, export and re-import. Left empty, each file is classified
    from its path, which is only a fallback: an export pack names members
    ``0001__chat_126.md``, and the chat regex needs ``chat_`` right after a
    separator, so a round trip would otherwise promote a transcript to citable
    evidence.
    """
    def _p(stage, pct, detail=""):
        if progress:
            try:
                progress(stage, int(pct), str(detail))
            except Exception:
                pass

    space = store.get_space(space_id)
    if not space:
        return {"ok": False, "error": "space not found"}

    if force:
        try:
            backfill_docs_originals(int(space_id))
        except Exception:
            pass

    job = store.create_job(space_id, stage="authorize")
    job_id = int(job["id"])
    store.touch_space(space_id, status="indexing")
    space_profile = str(space.get("profile") or "local")
    rev_profile = revision_profile(space)
    revision = store.create_revision(space_id, profile=rev_profile[:80])
    rev_id = int(revision["id"])
    _p("authorize", 3, "checking sources")

    # Fail early if non-local profile cannot upsert on this install
    try:
        from rag.vector_backends import ProfileNotBuiltError, require_upsert_backend

        require_upsert_backend(int(space_id))
    except ProfileNotBuiltError as e:
        store.update_job(job_id, stage="done", status="error", error=str(e)[:240])
        store.touch_space(space_id, status="error")
        return {"ok": False, "error": str(e), "job_id": job_id}
    except Exception:
        pass

    collected: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            continue
        collected.extend(list(iter_files(p)))

    if not collected:
        store.update_job(job_id, stage="done", status="error", error="no readable text files")
        store.touch_space(space_id, status="error")
        return {"ok": False, "error": "no readable text files", "job_id": job_id}

    store.update_job(job_id, stage="extract", detail=f"{len(collected)} files")
    _p("extract", 8, f"{len(collected)} files")
    if force:
        store.clear_chunks(space_id)
        try:
            vectors.clear_space(space_id)
        except Exception:
            pass

    source_ids: list[int] = []
    skipped: list[dict] = []
    chunk_count = 0
    phrases_by_doc: list[list[str]] = []
    child_pairs: list[tuple[int, str]] = []
    demoted_total = 0

    n_files = len(collected)
    try:
        for _fi, path in enumerate(collected, start=1):
            store.update_job(job_id, stage="normalize", detail=str(path))
            _p("chunk", 10 + int(40 * _fi / max(1, n_files)), f"{path.name} ({_fi}/{n_files})")
            # Gate BEFORE extracting: a missing extractor and a genuinely blank file
            # both yield "", and only the gate can tell them apart. Without this the
            # file is dropped here and the space looks like it was never given the
            # document at all.
            gap = extractor_gap(path.suffix)
            if gap:
                skipped.append({"path": path.name, "reason": gap, "lane_unavailable": True})
                continue
            text, digest = read_text_file(path)
            if not text.strip():
                reason = (
                    "no text layer - this PDF looks scanned and needs OCR"
                    if path.suffix.lower() == ".pdf"
                    else "no extractable text"
                )
                skipped.append({"path": path.name, "reason": reason, "lane_unavailable": False})
                continue
            mime = mimetypes.guess_type(str(path))[0] or "text/plain"
            # copy into blob store. The blob is post-extraction TEXT, so store
            # it as .txt — a rebuild or import then re-ingests it as text rather
            # than re-running a binary extractor (e.g. _xlsx_text) on plain text.
            dest_dir = store.BLOB_DIR / str(space_id) / "sources"
            dest_dir.mkdir(parents=True, exist_ok=True)
            docs_path = ""
            try:
                orig_resolved = str(path.resolve())
            except Exception:
                orig_resolved = str(path)
            if path.parent.resolve() == dest_dir.resolve():
                # Already this space's blob (rebuild re-reads it): use in place,
                # never copy it onto itself with a stacked digest prefix.
                dest = path
            else:
                stem = Path(_original_basename(path, space_id)).stem
                dest = dest_dir / f"{digest[:12]}_{stem}.txt"
                if not dest.exists():
                    # newline="\n": Windows would translate to \r\n, so re-reading
                    # the blob on rebuild would hash differently and duplicate the row.
                    dest.write_text(text, encoding="utf-8", newline="\n")
                # Real user file (not extracted .txt blob): keep Docs original for audit.
                docs_path = _retain_docs_original(space_id, path, digest)

            orig_name = _original_basename(path, space_id)
            file_authority = (authority or "").strip() or ""
            if not file_authority:
                from rag import authority as authority_mod

                file_authority = authority_mod.classify(str(path), path.name)
            # Recorded now, while the ORIGINAL suffix is still in hand. On a
            # rebuild the only file left is the .txt blob, and its name cannot
            # say it used to be a sheet.
            table_src = is_table_text(path, text)
            meta_src = {
                "blob": str(dest),
                "authority": file_authority,
                "original_path": orig_resolved,
                "original_name": orig_name,
                "table": table_src,
            }
            if docs_path:
                meta_src["docs_path"] = docs_path
            src = store.add_source(
                space_id,
                path=str(path),
                title=path.name,
                content_hash=digest,
                mime=mime,
                bytes_n=len(text.encode("utf-8", errors="replace")),
                meta=meta_src,
                status="indexing",
            )
            # Content-hash hit returns prior row — merge Docs/original meta so audit paths stick.
            prev_meta = src.get("meta") if isinstance(src.get("meta"), dict) else {}
            merged_meta = {**prev_meta, **meta_src}
            if docs_path:
                merged_meta["docs_path"] = docs_path
            # Table-ness only ever latches ON: the prior ingest saw the .xlsx/.csv,
            # this one may only be seeing its .txt blob.
            if prev_meta.get("table"):
                merged_meta["table"] = True
            if merged_meta != prev_meta:
                store.update_source_status(
                    int(src["id"]),
                    str(src.get("status") or "indexing"),
                    meta=merged_meta,
                )
                src = {**src, "meta": merged_meta}
            source_id = int(src["id"])
            if src.get("status") == "ready" and not force and src.get("content_hash") == digest:
                # already indexed identical content — still ok to skip rebuild pieces
                pass
            source_ids.append(source_id)

            store.update_job(job_id, stage="chunk", detail=path.name)
            is_code = path.suffix.lower() in {
                ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
                ".c", ".h", ".cpp", ".hpp", ".sql", ".sh", ".ps1",
            }
            # Provenance first (a rebuild re-ingesting the .txt blob inherits the
            # flag the original ingest recorded), then this file's own content.
            is_table = (not is_code) and (bool(merged_meta.get("table")) or table_src)
            import_map = list(getattr(read_text_file, "last_import_map", []) or [])
            cfg = space.get("config") if isinstance(space.get("config"), dict) else {}
            chunk_cfg = cfg.get("chunk") if isinstance(cfg.get("chunk"), dict) else {}
            child_tok = int(chunk_cfg.get("child_tokens") or cfg.get("child_tokens") or 200)
            parent_tok = int(chunk_cfg.get("parent_tokens") or cfg.get("parent_tokens") or 900)
            child_tok = max(80, min(child_tok, 600))
            parent_tok = max(200, min(parent_tok, 2000))
            parents, children, chunk_metrics = chunking.parent_child_chunk(
                text,
                code=is_code,
                table=is_table,
                salience_terms=import_map[:40] or None,
                child_tokens=child_tok,
                parent_max_tokens=parent_tok,
            )
            demoted_total += int(chunk_metrics.get("demoted_children") or 0)
            parent_row_ids: list[int] = []
            for pdraft in parents:
                pid = store.insert_chunk(
                    space_id=space_id,
                    source_id=source_id,
                    revision_id=rev_id,
                    text=pdraft.text,
                    kind="parent",
                    path=str(path),
                    heading=pdraft.heading,
                    span_start=pdraft.span_start,
                    span_end=pdraft.span_end,
                    token_est=pdraft.token_est,
                    meta=pdraft.meta,
                    authority=file_authority,
                )
                parent_row_ids.append(pid)
                chunk_count += 1
            for cdraft in children:
                parent_id = parent_row_ids[cdraft.parent_index] if 0 <= cdraft.parent_index < len(parent_row_ids) else 0
                cid = store.insert_chunk(
                    space_id=space_id,
                    source_id=source_id,
                    revision_id=rev_id,
                    text=cdraft.text,
                    kind="child",
                    parent_id=parent_id,
                    path=str(path),
                    heading=cdraft.heading,
                    span_start=cdraft.span_start,
                    span_end=cdraft.span_end,
                    token_est=cdraft.token_est,
                    authority=file_authority,
                )
                chunk_count += 1
                child_pairs.append((cid, f"{cdraft.heading}\n{cdraft.text}"))

            store.update_job(job_id, stage="enrich", detail=path.name)
            phrases = sira.index_phrases(text)
            # Import map sidecar — retrieval can find "who imports X" without embedding spam
            for mod in import_map[:40]:
                if mod and mod not in phrases:
                    phrases.append(f"import:{mod}")
            phrases_by_doc.append(phrases)
            headings = chunking.extract_headings(text)
            store.insert_file_index(
                space_id=space_id,
                source_id=source_id,
                path=str(path),
                title=path.name,
                phrases=phrases,
                headings=headings,
            )
            # Merge — never wipe prior docs_path (rebuild-from-blob leaves docs_path "").
            prior = src.get("meta") if isinstance(src.get("meta"), dict) else {}
            ready_meta = {
                **prior,
                "blob": str(dest),
                "phrases": phrases[:12],
                "import_map": import_map[:24],
                "authority": file_authority,
                "original_path": orig_resolved,
                "original_name": orig_name,
            }
            if docs_path:
                ready_meta["docs_path"] = docs_path
            elif prior.get("docs_path"):
                ready_meta["docs_path"] = prior["docs_path"]
            store.update_source_status(source_id, "ready", meta=ready_meta)

        store.update_job(job_id, stage="embed", detail=f"{len(child_pairs)} children")
        _p("embed", 55, f"embedding {len(child_pairs)} vectors")
        embedded = 0
        try:
            def _emb(done, tot):
                _p("embed", 55 + int(35 * done / max(1, tot)), f"{done}/{tot} vectors")
            embedded = vectors.index_children(space_id, child_pairs, progress=_emb)
        except Exception as e:
            from rag.vector_backends import ProfileNotBuiltError

            if isinstance(e, ProfileNotBuiltError):
                store.update_job(job_id, stage="done", status="error", error=str(e)[:240])
                store.touch_space(space_id, status="error")
                return {"ok": False, "error": str(e), "job_id": job_id}
            embedded = 0
        _p("index", 92, "building hybrid index")
        vec_info = {}
        try:
            vec_info = vectors.available()
        except Exception:
            vec_info = {}

        _p("validate", 96, "validating counts")
        store.update_job(job_id, stage="validate", counts={"sources": len(source_ids), "chunks": chunk_count, "embedded": embedded})
        metrics = {
            "sources": len(source_ids),
            "chunks": chunk_count,
            "embedded": embedded,
            "vector_mode": vec_info.get("mode"),
            "embedder": vec_info.get("embedder"),
            "phrase_docs": len(phrases_by_doc),
            "df_terms": len(sira.corpus_df(phrases_by_doc)),
            "demoted_children": demoted_total,
            "profile": space_profile,
            "architecture": str(
                ((space.get("config") if isinstance(space.get("config"), dict) else {}) or {}).get(
                    "architecture"
                )
                or "hybrid"
            ),
            "depth_default": str(space.get("depth_default") or "high"),
        }
        store.publish_revision(rev_id, chunk_count=chunk_count, source_count=len(source_ids), metrics=metrics)
        store.update_job(
            job_id,
            stage="publish",
            status="done",
            detail="ok",
            counts=metrics,
        )
        try:
            store.update_space_settings(int(space_id), config={"corpus_summary": ""})
        except Exception:
            pass
        _p("publish", 100, "ready for retrieval")
        # A run that indexed nothing because a lane is down is a failure that STATES
        # itself, not an empty success the caller renders as "no evidence found".
        down = [s for s in skipped if s.get("lane_unavailable")]
        if not source_ids and down:
            error = "; ".join(sorted({str(s["reason"]) for s in down}))
            store.update_job(job_id, stage="done", status="error", error=error[:240])
            store.touch_space(space_id, status="error")
            return {"ok": False, "error": error, "job_id": job_id, "skipped": skipped}
        return {
            "ok": True,
            "job_id": job_id,
            "revision_id": rev_id,
            "revision_profile": rev_profile,
            "sources": len(source_ids),
            "chunks": chunk_count,
            "metrics": metrics,
            "skipped": skipped,
            "lanes_unavailable": sorted({str(s["reason"]) for s in down}),
        }
    except Exception as e:
        store.update_job(job_id, stage="error", status="error", error=str(e)[:500])
        store.touch_space(space_id, status="error")
        return {"ok": False, "error": str(e)[:500], "job_id": job_id}


# Assistant output pasted back into a user turn. The netie.ai fabrication reached the
# index exactly this way: the model wrote it, the human pasted the reply into a chat,
# and the chat was frozen as `chat_126.md` under a `## user` heading — so filtering by
# role alone would have missed it entirely.
_PASTED_REPORT_RE = re.compile(
    r"^[ \t]*[═=]{3,}.*?$.*?^[ \t]*[═=]{3,}[ \t]*(?:END[ \t]*)?[═=]*[ \t]*$",
    re.DOTALL | re.MULTILINE | re.IGNORECASE,
)
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def scrub_assistant_text(text: str) -> str:
    """Strip assistant-authored blocks that were pasted into a human turn."""
    out = _PASTED_REPORT_RE.sub("", text or "")
    return _BLANK_RUN_RE.sub("\n\n", out).strip()


def write_session_transcripts(
    space_id: int, sessions: list[dict], *, keep_assistant: bool = False
) -> list[Path]:
    """Freeze chat sessions as markdown transcript files in the space blob dir.

    sessions: [{id, title, messages: [{role, text}]}] — pure (no db import) so
    tests can exercise it offline; ingest_sessions is the db-backed wrapper.

    By default the assistant's own words are NOT written. A transcript is the one
    source class that can contain the model's previous guesses, and once indexed those
    guesses come back looking like evidence. Keeping only the human side means a chat
    can still say what *you* asked for and decided, without re-importing what the model
    made up. Pass keep_assistant=True to index replies too.
    """
    out_dir = store.BLOB_DIR / str(int(space_id)) / "sources"
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for s in sessions:
        sid = int(s.get("id") or 0)
        title = str(s.get("title") or f"Chat {sid}").strip()
        lines = [f"# Chat: {title}", ""]
        dropped = 0
        for m in s.get("messages") or []:
            text = str(m.get("text") or "").strip()
            if not text:
                continue
            role = str(m.get("role") or "user")
            if role == "assistant" and not keep_assistant:
                dropped += 1
                continue
            if not keep_assistant:
                cleaned = scrub_assistant_text(text)
                if cleaned != text:
                    dropped += 1
                text = cleaned
                if not text:
                    continue
            lines.append(f"## {role}")
            lines.append(text)
            lines.append("")
        if dropped:
            lines.append(
                f"<!-- {dropped} assistant block(s) omitted: model output is not evidence -->"
            )
        if len([ln for ln in lines if ln.startswith("## ")]) == 0:
            continue
        p = out_dir / f"chat_{sid}.md"
        p.write_text("\n".join(lines), encoding="utf-8")
        files.append(p)
    return files


def ingest_sessions(space_id: int, session_ids: list[int], *, force: bool = False) -> dict:
    """Attach previous AirGPT chat sessions as knowledge sources."""
    space = store.get_space(space_id)
    if not space:
        return {"ok": False, "error": "space not found"}
    try:
        import db as dbm
    except Exception as e:
        return {"ok": False, "error": f"chat db unavailable: {str(e)[:120]}"}

    titles: dict[int, str] = {}
    try:
        for s in dbm.list_sessions(500):
            titles[int(s.get("id") or 0)] = str(s.get("title") or "")
    except Exception:
        pass

    sessions: list[dict] = []
    for sid in session_ids:
        try:
            msgs = dbm.get_messages(session_id=int(sid), limit=500)
        except Exception:
            msgs = []
        norm = []
        for m in msgs:
            # assistant turns are stored with source='ai'; everything else is the user
            role = "assistant" if str(m.get("source") or "") == "ai" else "user"
            norm.append({"role": role, "text": str(m.get("text") or m.get("ai_analysis") or "")})
        sessions.append({"id": int(sid), "title": titles.get(int(sid), ""), "messages": norm})

    files = write_session_transcripts(space_id, sessions)
    if not files:
        return {"ok": False, "error": "selected chats have no text content"}
    # These are transcripts by construction, whatever the files end up being called.
    from rag import authority as authority_mod

    out = ingest_paths(
        space_id, files, force=force, authority=authority_mod.CONVERSATION
    )
    if out.get("ok"):
        out["sessions_attached"] = len(files)
    return out


def ingest_research(space_id: int, research_paths: list[str], *, force: bool = False) -> dict:
    """Research→Add-to-RAG bridge: index library papers/drafts into a space.

    Paths must live under the Research library root (the library stays the
    source of truth — no duplicate upload). PDFs are gated on pdf_supported().
    """
    space = store.get_space(space_id)
    if not space:
        return {"ok": False, "error": "space not found"}
    try:
        import research as research_lib

        root = Path(research_lib.RESEARCH).resolve()
    except Exception as e:
        return {"ok": False, "error": f"research library unavailable: {str(e)[:120]}"}

    indexable: list[Path] = []
    skipped: list[dict] = []
    for raw in research_paths[:50]:
        p = Path(str(raw))
        try:
            p = p.resolve()
            p.relative_to(root)
        except (ValueError, OSError):
            skipped.append({"path": str(raw), "reason": "outside research library"})
            continue
        if not p.is_file():
            skipped.append({"path": str(raw), "reason": "not found"})
            continue
        suffix = p.suffix.lower()
        gap = extractor_gap(suffix)
        if gap:
            skipped.append({"path": str(raw), "reason": gap, "lane_unavailable": True})
            continue
        if suffix != ".pdf" and suffix not in TEXT_SUFFIXES:
            skipped.append({"path": str(raw), "reason": f"unsupported type {suffix or '(none)'}"})
            continue
        indexable.append(p)

    if not indexable:
        return {"ok": False, "error": "no indexable research files", "skipped": skipped}
    out = ingest_paths(space_id, indexable, force=force)
    # Count what was indexed, not what was tried: a scanned PDF passes the checks
    # above and is then dropped by ingest for having no text.
    dropped = len(out.get("skipped") or [])
    # Extend, never assign: ingest_paths reports its own downed lanes and losing
    # those would put the silence back.
    out["skipped"] = skipped + list(out.get("skipped") or [])
    if out.get("ok"):
        out["research_attached"] = len(indexable) - dropped
    return out


class _HtmlText(HTMLParser):
    """Minimal readable-text extraction — stdlib only, no external fetch libs."""

    _SKIP = {"script", "style", "noscript", "template", "svg", "head", "nav", "footer", "aside", "header"}
    _HEAD = {"h1", "h2", "h3", "h4", "h5", "h6"}
    _BREAK = {"p", "div", "br", "li", "tr", "section", "article", "blockquote", "pre", "main"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self._HEAD:
            # Markdown heading, so the chunker and citations carry the section.
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in self._BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in self._HEAD:
            self.parts.append("\n\n")
        elif tag in self._BREAK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:  # title lives inside <head>, which is otherwise skipped
            self.title = (self.title + " " + data.strip()).strip()[:200]
            return
        if self._skip:
            return
        self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """Return (title, text) from an HTML document."""
    p = _HtmlText()
    try:
        p.feed(html or "")
    except Exception:
        pass
    text = "".join(p.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return p.title, text.strip()


def ingest_urls(space_id: int, urls: list[str], *, force: bool = False, max_bytes: int = 2_000_000) -> dict:
    """Fetch web articles/links and index them as sources (link → ingestion)."""
    space = store.get_space(space_id)
    if not space:
        return {"ok": False, "error": "space not found"}

    out_dir = store.BLOB_DIR / str(int(space_id)) / "sources"
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    failed: list[dict] = []
    for raw in urls[:10]:
        u = str(raw).strip()
        if not re.match(r"^https?://", u, re.I):
            failed.append({"url": u, "reason": "only http(s) links"})
            continue
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "AirGPT-RAG/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                ctype = (r.headers.get("Content-Type") or "").lower()
                charset = "utf-8"
                if "charset=" in ctype:
                    charset = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
                data = r.read(max_bytes)
        except Exception as e:
            failed.append({"url": u, "reason": str(e)[:120]})
            continue
        try:
            body = data.decode(charset, errors="replace")
        except Exception:
            body = data.decode("utf-8", errors="replace")
        title = ""
        if "html" in ctype or body.lstrip()[:1] == "<":
            title, body = html_to_text(body)
        elif not any(t in ctype for t in ("text/", "markdown", "json", "xml")):
            failed.append({"url": u, "reason": f"unsupported content-type {ctype[:40] or 'unknown'}"})
            continue
        body = body.strip()
        if len(body) < 80:
            failed.append({
                "url": u,
                "reason": "no extractable text (JS-rendered shell — needs headless browser or yt-dlp for video)",
            })
            continue
        slug = re.sub(r"[^\w-]+", "-", u.split("//", 1)[-1])[:60].strip("-") or "link"
        f = out_dir / f"url_{slug}.md"
        f.write_text(f"# {title or u}\n\nSource: {u}\n\n{body}\n", encoding="utf-8")
        files.append(f)

    if not files:
        return {"ok": False, "error": "no links ingested", "failed_urls": failed}
    from rag import authority as authority_mod

    out = ingest_paths(space_id, files, force=force, authority=authority_mod.WEB)
    out["failed_urls"] = failed
    if out.get("ok"):
        out["urls_attached"] = len(files)
    return out

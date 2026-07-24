"""Deterministic ingest: authorize → extract → chunk → enrich → index → publish."""
from __future__ import annotations

import hashlib
import mimetypes
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

from rag import chunking, sira, store, vectors

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
        return "\n\n".join((pg.extract_text() or "") for pg in reader.pages[:200])
    except Exception:
        return ""


def _xlsx_text(path: Path) -> str:
    """Every sheet's cells as readable rows, so embeddings see the data, not zip bytes."""
    try:
        import openpyxl
    except Exception:
        return ""
    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception:
        return ""
    out: list[str] = []
    try:
        for ws in wb.worksheets:
            rows: list[str] = []
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None and str(c).strip() != ""]
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                out.append(f"## Sheet: {ws.title}\n" + "\n".join(rows))
    finally:
        try:
            wb.close()
        except Exception:
            pass
    return "\n\n".join(out).strip()


def _ooxml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _docx_text(path: Path) -> str:
    """Paragraph text from <w:t> runs in word/document.xml. Stdlib only."""
    import zipfile
    from xml.etree import ElementTree as ET

    try:
        with zipfile.ZipFile(str(path)) as z:
            root = ET.fromstring(z.read("word/document.xml"))
    except Exception:
        return ""
    paras: list[str] = []
    for p in root.iter():
        if _ooxml_local(p.tag) != "p":
            continue
        runs = [t.text for t in p.iter() if _ooxml_local(t.tag) == "t" and t.text]
        if runs:
            paras.append("".join(runs))
    return "\n".join(paras).strip()


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
    raw = path.read_bytes()
    digest = _hash_bytes(raw)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_text(path), digest
    if suffix in (".xlsx", ".xlsm"):
        return _xlsx_text(path), digest
    if suffix == ".docx":
        return _docx_text(path), digest
    if suffix == ".pptx":
        return _pptx_text(path), digest
    # Structure-aware parsing so embeddings see meaning, not markup/braces.
    if suffix in (".html", ".htm"):
        title, body = html_to_text(_decode(raw))
        text = (f"# {title}\n\n{body}" if title else body).strip()
        return (text or _decode(raw)), digest
    if suffix == ".json":
        import json as _json
        try:
            text = "\n".join(_flatten_json(_json.loads(_decode(raw))))
            if text.strip():
                return text, digest
        except Exception:
            pass  # malformed JSON → fall through to raw text
    return _decode(raw), digest


def iter_files(root: Path, *, max_files: int = 500) -> Iterable[Path]:
    root = Path(root)
    suffixes = TEXT_SUFFIXES | ({".pdf"} if pdf_supported() else set())
    if root.is_file():
        yield root
        return
    n = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in suffixes:
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
) -> dict:
    """Ingest files/folders into a knowledge space and rebuild the local hybrid index.

    progress(stage, percent, detail) is called through the pipeline so callers
    (e.g. the SSE build endpoint) can drive a real "ready for retrieval" bar.
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

    job = store.create_job(space_id, stage="authorize")
    job_id = int(job["id"])
    store.touch_space(space_id, status="indexing")
    revision = store.create_revision(space_id, profile="local_hybrid_high")
    rev_id = int(revision["id"])
    _p("authorize", 3, "checking sources")

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
    chunk_count = 0
    phrases_by_doc: list[list[str]] = []
    child_pairs: list[tuple[int, str]] = []

    n_files = len(collected)
    try:
        for _fi, path in enumerate(collected, start=1):
            store.update_job(job_id, stage="normalize", detail=str(path))
            _p("chunk", 10 + int(40 * _fi / max(1, n_files)), f"{path.name} ({_fi}/{n_files})")
            text, digest = read_text_file(path)
            if not text.strip():
                continue
            mime = mimetypes.guess_type(str(path))[0] or "text/plain"
            # copy into blob store
            dest_dir = store.BLOB_DIR / str(space_id) / "sources"
            dest_dir.mkdir(parents=True, exist_ok=True)
            rel = path.name
            dest = dest_dir / f"{digest[:12]}_{rel}"
            if not dest.exists():
                dest.write_text(text, encoding="utf-8")

            src = store.add_source(
                space_id,
                path=str(path),
                title=path.name,
                content_hash=digest,
                mime=mime,
                bytes_n=len(text.encode("utf-8", errors="replace")),
                meta={"blob": str(dest)},
                status="indexing",
            )
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
            parents, children = chunking.parent_child_chunk(text, code=is_code)
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
                )
                chunk_count += 1
                child_pairs.append((cid, f"{cdraft.heading}\n{cdraft.text}"))

            store.update_job(job_id, stage="enrich", detail=path.name)
            phrases = sira.index_phrases(text)
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
            store.update_source_status(source_id, "ready", meta={"blob": str(dest), "phrases": phrases[:12]})

        store.update_job(job_id, stage="embed", detail=f"{len(child_pairs)} children")
        _p("embed", 55, f"embedding {len(child_pairs)} vectors")
        embedded = 0
        try:
            def _emb(done, tot):
                _p("embed", 55 + int(35 * done / max(1, tot)), f"{done}/{tot} vectors")
            embedded = vectors.index_children(space_id, child_pairs, progress=_emb)
        except Exception:
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
        return {
            "ok": True,
            "job_id": job_id,
            "revision_id": rev_id,
            "sources": len(source_ids),
            "chunks": chunk_count,
            "metrics": metrics,
        }
    except Exception as e:
        store.update_job(job_id, stage="error", status="error", error=str(e)[:500])
        store.touch_space(space_id, status="error")
        return {"ok": False, "error": str(e)[:500], "job_id": job_id}


def write_session_transcripts(space_id: int, sessions: list[dict]) -> list[Path]:
    """Freeze chat sessions as markdown transcript files in the space blob dir.

    sessions: [{id, title, messages: [{role, text}]}] — pure (no db import) so
    tests can exercise it offline; ingest_sessions is the db-backed wrapper.
    """
    out_dir = store.BLOB_DIR / str(int(space_id)) / "sources"
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for s in sessions:
        sid = int(s.get("id") or 0)
        title = str(s.get("title") or f"Chat {sid}").strip()
        lines = [f"# Chat: {title}", ""]
        for m in s.get("messages") or []:
            text = str(m.get("text") or "").strip()
            if not text:
                continue
            role = str(m.get("role") or "user")
            lines.append(f"## {role}")
            lines.append(text)
            lines.append("")
        if len(lines) <= 2:
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
    out = ingest_paths(space_id, files, force=force)
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
        if suffix == ".pdf" and not pdf_supported():
            skipped.append({"path": str(raw), "reason": "pdf needs text extract — pip install pypdf"})
            continue
        if suffix != ".pdf" and suffix not in TEXT_SUFFIXES:
            skipped.append({"path": str(raw), "reason": f"unsupported type {suffix or '(none)'}"})
            continue
        indexable.append(p)

    if not indexable:
        return {"ok": False, "error": "no indexable research files", "skipped": skipped}
    out = ingest_paths(space_id, indexable, force=force)
    out["skipped"] = skipped
    if out.get("ok"):
        out["research_attached"] = len(indexable)
    return out


class _HtmlText(HTMLParser):
    """Minimal readable-text extraction — stdlib only, no external fetch libs."""

    _SKIP = {"script", "style", "noscript", "template", "svg", "head"}
    _BREAK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "section", "article", "blockquote", "pre"}

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
        elif tag in self._BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
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
            failed.append({"url": u, "reason": "no extractable text"})
            continue
        slug = re.sub(r"[^\w-]+", "-", u.split("//", 1)[-1])[:60].strip("-") or "link"
        f = out_dir / f"url_{slug}.md"
        f.write_text(f"# {title or u}\n\nSource: {u}\n\n{body}\n", encoding="utf-8")
        files.append(f)

    if not files:
        return {"ok": False, "error": "no links ingested", "failed_urls": failed}
    out = ingest_paths(space_id, files, force=force)
    out["failed_urls"] = failed
    if out.get("ok"):
        out["urls_attached"] = len(files)
    return out

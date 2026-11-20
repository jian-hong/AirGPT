"""RAG knowledge-space pack export / import (local zip, rebuild-on-import).

Pack format v1 (airgpt-rag-pack):
  manifest.json  — space meta, source inventory, sha256 integrity
  sources/NNNN__name.*  — text blobs only
  chats.json     — optional threads

Vectors / FTS / DB slices are omitted; import re-runs ingest_paths.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any

from rag import ingest, store

PACK_FORMAT = "airgpt-rag-pack"
PACK_VERSION = 1
MAX_PACK_BYTES = 512 * 1024 * 1024
MAX_SOURCE_FILES = 5000
MAX_UNCOMPRESSED = 1024 * 1024 * 1024  # 1 GiB total uncompressed

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_title(name: str, *, fallback: str = "source") -> str:
    base = Path(name or fallback).name
    cleaned = _SAFE_NAME_RE.sub("_", base).strip("._") or fallback
    return cleaned[:120]


def _safe_member_name(name: str) -> str | None:
    """Reject zip-slip / absolute / drive paths; return normalized relative POSIX path."""
    if not name or name.endswith("/"):
        return None
    norm = name.replace("\\", "/")
    if ".." in norm.split("/") or norm.startswith("/") or ":" in norm:
        return None
    if norm.startswith("./"):
        norm = norm[2:]
    if not norm or norm.startswith("../"):
        return None
    return norm


def _assert_under_rag(path: Path) -> Path:
    root = store.RAG_DIR.resolve()
    resolved = path.resolve()
    resolved.relative_to(root)
    return resolved


def _space_blob_root(space_id: int) -> Path:
    return store.BLOB_DIR / str(int(space_id))


def _resolve_source_blob(space_id: int, src: dict) -> Path | None:
    """Return jailed blob path for a source row, or None if unreadable / outside jail."""
    root = _space_blob_root(space_id)
    try:
        root_res = root.resolve()
        root_res.relative_to(store.RAG_DIR.resolve())
    except (ValueError, OSError):
        return None

    meta = src.get("meta") if isinstance(src.get("meta"), dict) else {}
    candidates: list[Path] = []
    blob = meta.get("blob")
    if blob:
        candidates.append(Path(str(blob)))
    # Common ingest naming: {hash12}_{title}
    digest = str(src.get("content_hash") or "")
    title = _safe_title(str(src.get("title") or src.get("path") or "source"))
    if digest:
        candidates.append(root / "sources" / f"{digest[:12]}_{title}")
        candidates.append(root / "sources" / f"{digest[:12]}_{Path(str(src.get('path') or title)).name}")
    # Last resort: exact title under sources/
    candidates.append(root / "sources" / title)

    for cand in candidates:
        try:
            resolved = cand.resolve()
            resolved.relative_to(root_res)
        except (ValueError, OSError):
            continue
        if resolved.is_file():
            return resolved
    return None


def validate_pack(zf: zipfile.ZipFile) -> dict:
    """Parse + verify manifest, member names, hashes, size limits. No disk write."""
    names = zf.namelist()
    if len(names) > MAX_SOURCE_FILES + 20:
        raise ValueError(f"too many zip members ({len(names)})")

    total_uncomp = 0
    safe_names: list[str] = []
    for name in names:
        info = zf.getinfo(name)
        total_uncomp += int(info.file_size or 0)
        if total_uncomp > MAX_UNCOMPRESSED:
            raise ValueError("uncompressed pack exceeds size cap")
        if name.endswith("/"):
            continue
        safe = _safe_member_name(name)
        if safe is None:
            raise ValueError(f"unsafe zip member: {name[:80]}")
        safe_names.append(safe)

    if "manifest.json" not in safe_names:
        raise ValueError("missing manifest.json")

    raw = zf.read("manifest.json")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"invalid manifest.json: {e}") from e

    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    if manifest.get("format") != PACK_FORMAT:
        raise ValueError(f"unsupported pack format: {manifest.get('format')!r}")
    ver = int(manifest.get("version") or 0)
    if ver != PACK_VERSION:
        raise ValueError(f"unsupported pack version: {ver}")

    space = manifest.get("space")
    if not isinstance(space, dict) or not str(space.get("name") or "").strip():
        raise ValueError("manifest.space.name required")

    sources = manifest.get("sources")
    if not isinstance(sources, list):
        raise ValueError("manifest.sources must be a list")
    if len(sources) > MAX_SOURCE_FILES:
        raise ValueError("too many sources in manifest")

    integrity = manifest.get("integrity") if isinstance(manifest.get("integrity"), dict) else {}
    file_hashes = integrity.get("files") if isinstance(integrity.get("files"), dict) else {}

    for entry in sources:
        if not isinstance(entry, dict):
            raise ValueError("invalid source entry")
        pack_path = _safe_member_name(str(entry.get("pack_path") or ""))
        if not pack_path or not pack_path.startswith("sources/"):
            raise ValueError(f"bad pack_path: {entry.get('pack_path')!r}")
        if pack_path not in safe_names:
            raise ValueError(f"missing pack member: {pack_path}")
        expected = str(entry.get("content_hash") or "")
        if expected:
            got = _sha256_bytes(zf.read(pack_path))
            if got != expected:
                raise ValueError(f"hash mismatch: {pack_path}")

    # Verify integrity.files when present (covers sources + any extra members)
    for rel, expected in file_hashes.items():
        safe = _safe_member_name(str(rel))
        if safe is None or safe not in safe_names:
            raise ValueError(f"integrity lists missing/unsafe file: {rel}")
        got = _sha256_bytes(zf.read(safe))
        if got != str(expected):
            raise ValueError(f"hash mismatch: {safe}")

    return manifest


_TABLE_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".csv", ".tsv")


def _hidden_parts(path: str) -> list[str]:
    """Plain-words list of hidden sheets / sheets with hidden rows in an .xlsx (empty if none)."""
    if not path.lower().endswith((".xlsx", ".xlsm")):
        return []
    out: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            wb = zf.read("xl/workbook.xml").decode("utf-8", "replace")
            for m in re.finditer(r"<(?:\w+:)?sheet\b[^>]*>", wb):
                tag = m.group(0)
                if re.search(r"\bstate=\"(?:hidden|veryHidden)\"", tag):
                    n = re.search(r"\bname=\"([^\"]*)\"", tag)
                    out.append(f"hidden sheet {n.group(1) if n else ''}".strip())
            rows = 0
            for name in zf.namelist():
                if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                    with zf.open(name) as fh:
                        if re.search(rb"<row\b[^>]*\shidden=\"(?:1|true)\"", fh.read()):
                            rows += 1
            if rows:
                out.append(f"hidden rows in {rows} sheet" + ("s" if rows != 1 else ""))
    except Exception:
        return []
    return out


def _sheet_csvs(src: dict) -> list[tuple[str, bytes]]:
    """(sheet name, CSV bytes) for a spreadsheet source whose original file is still here.

    Cell values only: no author, comments, formulas or other workbook metadata ever
    reach the pack. Empty list means "pack the extracted text instead".
    """
    meta = src.get("meta") if isinstance(src.get("meta"), dict) else {}
    if not meta.get("table"):
        return []
    try:
        import csv

        from rag import reveal
        from rag.xlsx_sql import load_table_file

        path, _origin = reveal.resolve_source_path(src)
        if not path or not path.lower().endswith(_TABLE_SUFFIXES):
            return []
        out: list[tuple[str, bytes]] = []
        sheets = load_table_file(Path(path))
        if path.lower().endswith((".csv", ".tsv")) and len(sheets) == 1:
            # The file on disk is the Docs copy (content-hashed name): the table is named
            # after the file that was uploaded, as the answer lane names it.
            sheets = {Path(str(src.get("title") or path)).stem: next(iter(sheets.values()))}
        for name, df in sheets.items():
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\n")
            w.writerow([str(c) for c in df.columns])
            for row in df.itertuples(index=False):
                w.writerow(["" if v is None or v != v else v for v in row])
            out.append((str(name), buf.getvalue().encode("utf-8")))
        return out
    except Exception:
        return []


def export_space(space_id: int, *, include_chats: bool = True) -> bytes:
    """Build zip bytes for one knowledge space. Raises ValueError if missing."""
    space = store.get_space(int(space_id))
    if not space:
        raise ValueError("space not found")

    sources = store.list_sources(int(space_id))
    # Stable order for deterministic packs
    sources = sorted(sources, key=lambda s: int(s.get("id") or 0))

    buf = io.BytesIO()
    manifest_sources: list[dict[str, Any]] = []
    integrity_files: dict[str, str] = {}
    skipped = 0
    as_text: list[str] = []  # spreadsheets that could only be packed as text

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        member_no = 0
        for src in sources:
            # A spreadsheet travels as one CSV per sheet (cell values only), so the
            # importing space can still calculate from it. Anything else, or a sheet
            # file that is gone from this machine, travels as its extracted text.
            sheet_files = _sheet_csvs(src)
            if sheet_files:
                meta = src.get("meta") if isinstance(src.get("meta"), dict) else {}
                meta_out = _strip_abs_paths({k: v for k, v in meta.items() if k not in ("blob", "docs_path", "table")})
                hidden_note = ""
                try:
                    from rag import reveal

                    hp = _hidden_parts(reveal.resolve_source_path(src)[0] or "")
                    hidden_note = "; ".join(hp)
                except Exception:
                    pass
                for sheet, data in sheet_files:
                    member_no += 1
                    pack_path = f"sources/{member_no:04d}__{_safe_title(str(src.get('title') or 'sheet'))}__{_safe_title(sheet, fallback='sheet')}.csv"
                    digest = _sha256_bytes(data)
                    zf.writestr(pack_path, data)
                    integrity_files[pack_path] = digest
                    manifest_sources.append(
                        {
                            "pack_path": pack_path,
                            "title": str(src.get("title") or sheet),
                            "content_hash": digest,
                            "mime": "text/csv",
                            "bytes": len(data),
                            "original_path": Path(str(src.get("title") or src.get("path") or sheet)).name,
                            "table_workbook": str(src.get("title") or sheet),
                            "table_sheet": sheet,
                            "authority": store.source_authority(int(src.get("id") or 0)),
                            "meta": meta_out,
                            **({"hidden_note": hidden_note} if hidden_note else {}),
                        }
                    )
                continue
            blob = _resolve_source_blob(int(space_id), src)
            if not blob:
                skipped += 1
                continue
            member_no += 1
            i = member_no
            if (src.get("meta") or {}).get("table"):
                as_text.append(str(src.get("title") or blob.name))
            title = _safe_title(str(src.get("title") or blob.name))
            # Packed sources are extracted text; carry .txt so import re-ingests
            # them as text rather than re-running a binary extractor.
            if not title.lower().endswith(".txt"):
                title = f"{title}.txt"
            pack_path = f"sources/{i:04d}__{title}"
            data = blob.read_bytes()
            if len(data) > MAX_PACK_BYTES:
                raise ValueError("source exceeds pack size cap")
            digest = _sha256_bytes(data)
            zf.writestr(pack_path, data)
            integrity_files[pack_path] = digest
            meta = src.get("meta") if isinstance(src.get("meta"), dict) else {}
            # Drop host-local blob path from exported meta
            meta_out = _strip_abs_paths({k: v for k, v in meta.items() if k not in ("blob", "docs_path")})
            manifest_sources.append(
                {
                    "pack_path": pack_path,
                    "title": str(src.get("title") or title),
                    "content_hash": digest,
                    "mime": str(src.get("mime") or "text/plain"),
                    "bytes": int(src.get("bytes") or len(data)),
                    "original_path": Path(str(src.get("path") or title)).name,
                    # How the material entered, so the importing space believes it
                    # exactly as much as this one did. Pack member names are
                    # prefixed (0001__chat_126.md), which defeats the path regex.
                    "authority": store.source_authority(int(src.get("id") or 0)),
                    "meta": meta_out,
                }
            )

        chat_count = 0
        message_count = 0
        if include_chats:
            chats_payload: list[dict[str, Any]] = []
            for chat in store.list_chats(int(space_id)):
                msgs = store.list_messages(int(chat["id"]))
                chat_count += 1
                message_count += len(msgs)
                chats_payload.append(
                    {
                        "title": str(chat.get("title") or "New chat"),
                        "messages": [
                            {
                                "role": str(m.get("role") or "user"),
                                "content": str(m.get("content") or ""),
                                "depth": str(m.get("depth") or "high"),
                                # Citations carry the sender's folders (path_full, and path on
                                # spreadsheet answers); a pack is shared, so they go as names.
                                "citations": _clean_citations(m.get("citations")),
                            }
                            for m in msgs
                        ],
                    }
                )
            if chats_payload:
                zf.writestr(
                    "chats.json",
                    json.dumps({"chats": chats_payload}, ensure_ascii=False, indent=2).encode("utf-8"),
                )

        try:
            from config import APP_VERSION

            app_ver = str(APP_VERSION)
        except Exception:
            app_ver = "unknown"

        manifest = {
            "format": PACK_FORMAT,
            "version": PACK_VERSION,
            "exported_at": time.time(),
            "app_version": app_ver,
            "space": {
                "name": str(space.get("name") or "RAG"),
                "slug_hint": str(space.get("slug") or ""),
                "depth_default": str(space.get("depth_default") or "high"),
                "modalities": space.get("modalities") if isinstance(space.get("modalities"), list) else ["text"],
                "profile": str(space.get("profile") or "local"),
                # The ontology is built from the sender's own files (absolute paths, the
                # sender's space id); the importing space rebuilds its own.
                "config": _strip_abs_paths(
                    {k: v for k, v in (space.get("config") or {}).items() if k != "ontology"}
                )
                if isinstance(space.get("config"), dict)
                else {},
                "original_id": int(space.get("id") or space_id),
            },
            "options": {"include_chats": bool(include_chats), "include_chunks": False},
            "sources": manifest_sources,
            "stats": {
                "source_count": len(manifest_sources),
                "skipped": skipped,
                "spreadsheets_as_text": as_text,
                "chat_count": chat_count,
                "message_count": message_count,
            },
            "integrity": {"algo": "sha256", "files": integrity_files},
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        zf.writestr(
            "README.txt",
            (
                "AirGPT RAG pack (airgpt-rag-pack v1).\n"
                "Import via RAG library → Import, or POST /api/rag/spaces/import.\n"
                "Index rebuilds on import; vectors are not included.\n"
                "Spreadsheets travel as one CSV per sheet (cell values only), so counts and\n"
                "totals still work after import. Hidden sheets and hidden rows travel too and\n"
                "come back visible; the manifest names them under hidden_note. A spreadsheet listed under\n"
                "stats.spreadsheets_as_text travelled as plain text and cannot be calculated\n"
                "from; add the original file again.\n"
            ).encode("utf-8"),
        )

    out = buf.getvalue()
    if len(out) > MAX_PACK_BYTES:
        raise ValueError("pack exceeds size cap")
    return out


_ABS_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")


def _strip_abs_paths(obj: Any) -> Any:
    """A pack is shared with other people: no folder of the sender's machine may be in it."""
    if isinstance(obj, dict):
        return {k: _strip_abs_paths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_abs_paths(v) for v in obj]
    if isinstance(obj, str) and _ABS_PATH.match(obj.strip()):
        return Path(obj.strip().replace("\\", "/")).name
    return obj


_CITE_TEXT_KEYS = ("text", "snippet", "content", "quote", "sql")


def _clean_citations(cites: Any) -> list:
    """Citations with every absolute folder reduced to a file name (text fields untouched)."""
    out = []
    for c in cites if isinstance(cites, list) else []:
        if isinstance(c, dict):
            keep = {k: v for k, v in c.items() if k in _CITE_TEXT_KEYS}
            c = {**_strip_abs_paths({k: v for k, v in c.items() if k not in _CITE_TEXT_KEYS}), **keep}
        else:
            c = _strip_abs_paths(c)
        out.append(c)
    return out


def export_space_to_path(space_id: int, dest: Path, **kw: Any) -> Path:
    dest = Path(dest)
    dest.write_bytes(export_space(space_id, **kw))
    return dest


def _table_name(name: Any) -> str:
    """A spreadsheet's own file name, kept readable (spaces and accents stay) but safe to write."""
    n = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", Path(str(name or "")).name).strip(". ")[:120]
    return n or "sheet.csv"


_PLAIN_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?")


def _typed(cell: str) -> Any:
    """A packed cell back to what it was: a number only when it reads back the same text."""
    if _PLAIN_NUMBER.fullmatch(cell):
        try:
            n = int(cell) if "." not in cell else float(cell)
        except ValueError:
            return cell
        return n if str(n) == cell else cell
    return cell


def _build_workbook(sheets: list[tuple[str, bytes, dict]]) -> bytes:
    """One .xlsx from the packed sheets (cell values only, in their original order)."""
    import csv

    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, data, _entry in sheets:
        ws = wb.create_sheet(re.sub(r"[\[\]:*?/\\]", "_", name)[:31] or "Sheet")
        for row in csv.reader(io.StringIO(data.decode("utf-8", errors="replace"), newline="")):
            ws.append([_typed(c) if c != "" else None for c in row])
            # Text, never a formula: a cell that starts with = + - @ must not become live.
            for cell in ws[ws.max_row]:
                if isinstance(cell.value, str) and cell.value[:1] in "=+-@":
                    cell.data_type = "s"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def import_pack(
    zip_bytes: bytes,
    *,
    name: str | None = None,
    rebuild: bool = True,
) -> dict:
    """Validate → create_space → extract sources → ingest → optional chats."""
    if not zip_bytes:
        raise ValueError("empty pack")
    if len(zip_bytes) > MAX_PACK_BYTES:
        raise ValueError("pack exceeds size cap")

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        manifest = validate_pack(zf)
        space_meta = manifest["space"]
        space_name = (name or str(space_meta.get("name") or "Imported RAG")).strip()[:120]
        depth = str(space_meta.get("depth_default") or "high")
        modalities = space_meta.get("modalities") if isinstance(space_meta.get("modalities"), list) else ["text"]
        profile = str(space_meta.get("profile") or "local")
        config = space_meta.get("config") if isinstance(space_meta.get("config"), dict) else {}
        # The summary and ontology in a pack were written by someone else and are shown
        # to the user as what the space contains. This space builds its own from its own files.
        config = {k: v for k, v in config.items() if k not in ("corpus_summary", "ontology")}

        space = store.create_space(
            space_name,
            depth_default=depth,
            modalities=modalities,
            profile=profile,
            config=config,
        )
        new_id = int(space["id"])
        dest_dir = store.BLOB_DIR / str(new_id) / "sources"
        dest_dir.mkdir(parents=True, exist_ok=True)

        extracted: list[Path] = []
        by_authority: dict[str, list[Path]] = {}
        entry_by_target: dict[str, dict] = {}

        def _place(title: str, data: bytes, entry: dict) -> None:
            target = dest_dir / title
            # Avoid collisions
            n = 2
            while target.exists():
                target = dest_dir / f"{Path(title).stem}_{n}{Path(title).suffix}"
                n += 1
            try:
                _assert_under_rag(target)
            except (ValueError, OSError) as e:
                raise ValueError(f"path jail violation: {target}") from e
            target.write_bytes(data)
            extracted.append(target)
            by_authority.setdefault(str(entry.get("authority") or ""), []).append(target)
            entry_by_target[str(target.resolve())] = entry

        # Sheets of one workbook come back as one workbook again, so a total over
        # "every sheet" still adds all of them up and the answer names the original file.
        workbooks: dict[str, list[tuple[str, bytes, dict]]] = {}
        for entry in manifest.get("sources") or []:
            pack_path = _safe_member_name(str(entry.get("pack_path") or ""))
            if not pack_path:
                continue
            title = _safe_title(str(entry.get("title") or Path(pack_path).name))
            sheet = entry.get("table_sheet")
            if isinstance(sheet, str) and sheet and pack_path.lower().endswith(".csv"):
                wb_name = _table_name(entry.get("table_workbook") or title)
                if wb_name.lower().endswith((".xlsx", ".xlsm")):
                    workbooks.setdefault(wb_name, []).append((sheet, zf.read(pack_path), entry))
                    continue
                # A csv or tsv: one table, a real .csv again.
                title = (Path(wb_name).stem + ".csv") if wb_name.lower().endswith(".tsv") else wb_name
                if not title.lower().endswith(".csv"):
                    title = f"{title}.csv"
            elif not title.lower().endswith(".txt"):
                title = f"{title}.txt"
            _place(title, zf.read(pack_path), entry)
        for wb_name, sheets in workbooks.items():
            _place(wb_name, _build_workbook(sheets), sheets[0][2])

        ingest_out: dict = {"ok": True, "chunks": 0, "sources": 0}
        if extracted and rebuild:
            # Ingest one batch per declared class so a pack holding both documents
            # and transcripts does not flatten them into a single authority.
            ingest_out = {"ok": True, "chunks": 0, "sources": 0}
            for kind, files in by_authority.items():
                if not files:
                    continue
                part = ingest.ingest_paths(new_id, files, force=False, authority=kind)
                if not part.get("ok"):
                    ingest_out = part
                    break
                ingest_out["chunks"] = int(ingest_out.get("chunks") or 0) + int(part.get("chunks") or 0)
                ingest_out["sources"] = int(ingest_out.get("sources") or 0) + int(part.get("sources") or 0)
            # Stamp origin onto each source so a later scrub does not re-derive from
            # the pack-prefixed filename alone.
            for src in store.list_sources(new_id):
                meta = src.get("meta") if isinstance(src.get("meta"), dict) else {}
                entry = None
                for candidate in (src.get("path"), meta.get("blob")):
                    if not candidate:
                        continue
                    try:
                        entry = entry_by_target.get(str(Path(str(candidate)).resolve()))
                    except Exception:
                        entry = None
                    if entry:
                        break
                if not entry:
                    src_name = Path(str(src.get("path") or src.get("title") or "")).name
                    for tpath, ent in entry_by_target.items():
                        if Path(tpath).name == src_name:
                            entry = ent
                            break
                if not entry:
                    continue
                meta = dict(meta)
                meta["authority"] = str(entry.get("authority") or meta.get("authority") or "")
                orig = str(entry.get("original_path") or "").strip()
                if orig:
                    meta["original_path"] = Path(orig).name
                store.update_source_status(
                    int(src["id"]), str(src.get("status") or "ready"), meta=meta
                )
            if not ingest_out.get("ok"):
                return {
                    "ok": False,
                    "error": ingest_out.get("error") or "ingest failed",
                    "space": space,
                    "sources": len(extracted),
                    "chunks": 0,
                    "chats": 0,
                }

        chats_imported = 0
        if "chats.json" in zf.namelist():
            try:
                chats_data = json.loads(zf.read("chats.json").decode("utf-8"))
            except Exception:
                chats_data = {}
            for chat in (chats_data.get("chats") or []) if isinstance(chats_data, dict) else []:
                if not isinstance(chat, dict):
                    continue
                row = store.create_chat(new_id, str(chat.get("title") or "New chat"))
                cid = int(row["id"])
                chats_imported += 1
                for msg in chat.get("messages") or []:
                    if not isinstance(msg, dict):
                        continue
                    store.add_message(
                        cid,
                        str(msg.get("role") or "user"),
                        str(msg.get("content") or ""),
                        citations=_clean_citations(msg.get("citations")) or None,
                        depth=str(msg.get("depth") or "high"),
                        trace_id="",
                        # Written by someone else: kept to read, never handed to the model
                        # as this user's own conversation.
                        imported=True,
                    )

        space = store.get_space(new_id) or space
        as_text = [str(n) for n in ((manifest.get("stats") or {}).get("spreadsheets_as_text") or [])][:50]
        out = {
            "ok": True,
            "space": space,
            "sources": len(extracted),
            "chunks": int(ingest_out.get("chunks") or 0),
            "chats": chats_imported,
        }
        hidden = sorted({f"{e.get('table_workbook')} ({e['hidden_note']})" for e in manifest.get("sources") or [] if e.get("hidden_note")})
        if hidden:
            out["hidden_parts"] = hidden
            out["notice"] = (
                "Hidden sheets or rows were part of the pack and are now visible: " + ", ".join(hidden) + "."
            )
        if as_text:
            # Said, not skipped: these tables are searchable text now, not calculable.
            out["spreadsheets_as_text"] = as_text
            out["notice"] = (out.get("notice", "") + " " if out.get("notice") else "") + (
                "These spreadsheets came back as text and cannot be calculated: " + ", ".join(as_text)
                + ". Add the original files again to get totals and counts."
            )
        return out


def import_pack_file(path: Path, **kw: Any) -> dict:
    return import_pack(Path(path).read_bytes(), **kw)

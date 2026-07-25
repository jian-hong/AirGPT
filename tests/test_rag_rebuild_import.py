"""Rebuild and export/import must not drop uploaded sources.

Blobs are post-extraction text stored as .txt, so a rebuild (or import)
re-ingests them as text instead of re-running a binary extractor. And a
rebuild falls back to the local blob when the original upload path is gone.
Embedder is stubbed so this stays fast; content lands in the chunks table.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MARKER = "RS622XK"


def _rebuild_paths(srcs):
    import os

    out = []
    for s in srcs:
        p = s.get("path")
        if p and os.path.exists(p):
            out.append(p)
            continue
        blob = (s.get("meta") or {}).get("blob")
        if blob and os.path.exists(blob):
            out.append(blob)
    return out


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    import rag.store as store
    from rag import ingest

    monkeypatch.setattr(store, "RAG_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "rag" / "rag.db")
    monkeypatch.setattr(store, "BLOB_DIR", tmp_path / "rag")
    # Stub the dense embedder so we exercise extract -> chunk -> store only.
    monkeypatch.setattr(ingest.vectors, "clear_space", lambda *a, **k: None)
    monkeypatch.setattr(ingest.vectors, "index_children", lambda *a, **k: 0)
    monkeypatch.setattr(ingest.vectors, "available", lambda *a, **k: {"ok": False})
    store.init()
    return store, ingest, tmp_path


def _chunks_text(store, sid):
    with store._conn() as c:
        rows = c.execute("SELECT text FROM chunks WHERE space_id=?", (sid,)).fetchall()
    return "\n".join((r["text"] if hasattr(r, "keys") else r[0]) for r in rows)


def _make_xlsx(path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Measurements"
    ws.append(["Frequency_Hz", "Noise_nV", "Notes"])
    ws.append([1000, 4.7, f"{MARKER} baseline"])
    wb.save(str(path))


def test_blob_is_txt_and_rebuild_survives_deleted_upload(isolated):
    store, ingest, tmp = isolated
    xlsx = tmp / "upload" / "JH_RS622XK_Lab_Report.xlsx"
    xlsx.parent.mkdir(parents=True)
    _make_xlsx(xlsx)

    sid = int(store.create_space(name="e2e", depth_default="high")["id"])
    assert ingest.ingest_paths(sid, [str(xlsx)], force=True).get("ok")

    blob = (store.list_sources(sid)[0].get("meta") or {}).get("blob")
    assert blob and blob.endswith(".txt"), f"blob must be .txt, got {blob}"
    assert MARKER in Path(blob).read_text(encoding="utf-8")
    assert MARKER in _chunks_text(store, sid)

    # Original upload deleted (temp file gone) -> rebuild must use the blob.
    xlsx.unlink()
    paths = _rebuild_paths(store.list_sources(sid))
    assert paths and paths[0].endswith(".txt"), "rebuild should fall back to blob"
    assert ingest.ingest_paths(sid, paths, force=True).get("ok")
    assert MARKER in _chunks_text(store, sid), "rebuild dropped the source"


def test_export_import_round_trips_content(isolated):
    store, ingest, tmp = isolated
    from rag import export_import

    xlsx = tmp / "upload2" / "report.xlsx"
    xlsx.parent.mkdir(parents=True)
    _make_xlsx(xlsx)
    sid = int(store.create_space(name="src", depth_default="high")["id"])
    assert ingest.ingest_paths(sid, [str(xlsx)], force=True).get("ok")

    pack = export_import.export_space(sid)
    assert isinstance(pack, (bytes, bytearray)) and pack

    imp = export_import.import_pack(pack, name="dst")
    new_id = int(imp["space"]["id"])
    assert MARKER in _chunks_text(store, new_id), "export/import lost content"


def test_packaged_source_carries_txt(isolated):
    store, ingest, tmp = isolated
    import zipfile
    from rag import export_import

    xlsx = tmp / "u3" / "sheet.xlsx"
    xlsx.parent.mkdir(parents=True)
    _make_xlsx(xlsx)
    sid = int(store.create_space(name="pk", depth_default="high")["id"])
    ingest.ingest_paths(sid, [str(xlsx)], force=True)

    pack = export_import.export_space(sid)
    import io

    with zipfile.ZipFile(io.BytesIO(pack)) as z:
        src_members = [n for n in z.namelist() if n.startswith("sources/")]
    assert src_members, "no source members in pack"
    assert all(n.endswith(".txt") for n in src_members), src_members


def test_repeated_rebuild_does_not_duplicate_sources(isolated):
    """Rebuilding from blobs must be idempotent.

    Regression: identity was sha256(container bytes), so an .xlsx and its
    extracted .txt blob hashed differently. Every rebuild added a second source
    row and wrote a second blob named {newdigest}_{olddigest}_{name}.txt, so a
    7-file space showed 14 sources after one rebuild.
    """
    store, ingest, tmp = isolated
    up = tmp / "up"
    up.mkdir()
    _make_xlsx(up / "lab.xlsx")
    (up / "notes.md").write_text("# Notes\nShip the fix.\n", encoding="utf-8")

    sid = int(store.create_space(name="idem", depth_default="high")["id"])
    assert ingest.ingest_paths(sid, [str(up)], force=True).get("ok")

    blob_dir = store.BLOB_DIR / str(sid) / "sources"

    def counts():
        return len(store.list_sources(sid)), len(list(blob_dir.glob("*")))

    assert counts() == (2, 2), f"initial ingest: {counts()}"

    # Originals gone (browser upload temp files) -> rebuild reads the blobs.
    import shutil

    shutil.rmtree(up)
    for _ in range(2):
        paths = _rebuild_paths(store.list_sources(sid))
        assert paths, "rebuild found no paths"
        assert ingest.ingest_paths(sid, paths, force=True).get("ok")
        assert counts() == (2, 2), f"rebuild duplicated: {counts()}"

    # No stacked digest prefixes like {12hex}_{12hex}_name.txt
    for p in blob_dir.glob("*"):
        parts = p.name.split("_")
        stacked = len(parts) > 2 and len(parts[0]) == 12 and len(parts[1]) == 12
        assert not stacked, f"stacked digest prefix: {p.name}"

    assert MARKER in _chunks_text(store, sid), "content lost after rebuilds"

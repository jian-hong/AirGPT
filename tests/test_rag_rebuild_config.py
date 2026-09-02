"""#33 Rebuild stamps saved architecture. #34 backfill docs_path from a live original.

DR-0006: ingest still builds the hybrid index; the revision profile must name
what Settings saved. Tests drive ingest_paths, not a forged profile string.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

MARKER = "RS622XK-backfill"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    import rag.store as store
    from rag import ingest

    monkeypatch.setattr(store, "RAG_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "rag" / "rag.db")
    monkeypatch.setattr(store, "BLOB_DIR", tmp_path / "rag")
    monkeypatch.setattr(ingest.vectors, "clear_space", lambda *a, **k: None)
    monkeypatch.setattr(ingest.vectors, "index_children", lambda *a, **k: 0)
    monkeypatch.setattr(ingest.vectors, "available", lambda *a, **k: {"ok": False})
    store.init()
    return store, ingest, tmp_path


def _latest_revision(store, space_id: int):
    with store._conn() as conn:
        row = conn.execute(
            "SELECT * FROM revisions WHERE space_id=? ORDER BY id DESC LIMIT 1",
            (int(space_id),),
        ).fetchone()
    return store._row(row)


def _make_xlsx(path: Path) -> Path:
    openpyxl = pytest.importorskip("openpyxl")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Sample", "Result"])
    ws.append(["RS622XK", MARKER])
    wb.save(str(path))
    return path


def test_revision_profile_default_stays_hybrid():
    from rag import ingest

    assert ingest.revision_profile({"profile": "local", "depth_default": "high"}) == "local_hybrid_high"
    assert ingest.revision_profile(
        {"profile": "local", "depth_default": "manual", "config": {"architecture": "graph"}}
    ) == "local_graph_manual"


def test_rebuild_stamps_saved_architecture(isolated):
    store, ingest, tmp = isolated
    src = tmp / "notes.md"
    src.write_text("# graph space\nThis corpus is about retrieval.\n", encoding="utf-8")
    space = store.create_space(
        "Manual graph",
        depth_default="manual",
        config={"architecture": "graph"},
    )
    sid = int(space["id"])
    out = ingest.ingest_paths(sid, [str(src)], force=True)
    assert out.get("ok")
    assert "graph" in str(out.get("revision_profile") or ""), out
    assert "_hybrid_" not in str(out.get("revision_profile") or "")
    rev = _latest_revision(store, sid)
    assert rev, "ingest must publish a revision"
    assert "graph" in str(rev["profile"])
    assert "_hybrid_" not in str(rev["profile"])
    assert str(rev["profile"]).endswith("_manual")


def test_backfill_docs_path_from_live_original(isolated):
    store, ingest, tmp = isolated
    xlsx = _make_xlsx(tmp / "upload" / "lab.xlsx")
    origin = _sha256(xlsx)
    sid = int(store.create_space("old-space", depth_default="high")["id"])
    assert ingest.ingest_paths(sid, [str(xlsx)], force=True).get("ok")
    src = store.list_sources(sid)[0]
    meta = dict(src.get("meta") or {})
    docs = Path(meta.pop("docs_path"))
    docs.unlink()
    store.update_source_status(int(src["id"]), "ready", meta=meta)
    assert not (store.list_sources(sid)[0].get("meta") or {}).get("docs_path")

    out = ingest.backfill_docs_originals(sid)
    assert out["filled"] == 1, out
    restored = Path((store.list_sources(sid)[0].get("meta") or {})["docs_path"])
    assert restored.is_file()
    assert _sha256(restored) == origin
    assert restored.read_bytes()[:2] == b"PK"


def test_backfill_cannot_invent_bytes_when_original_is_gone(isolated):
    store, ingest, tmp = isolated
    xlsx = _make_xlsx(tmp / "upload" / "gone.xlsx")
    sid = int(store.create_space("lost", depth_default="high")["id"])
    assert ingest.ingest_paths(sid, [str(xlsx)], force=True).get("ok")
    src = store.list_sources(sid)[0]
    meta = dict(src.get("meta") or {})
    Path(meta["docs_path"]).unlink()
    meta.pop("docs_path")
    store.update_source_status(int(src["id"]), "ready", meta=meta)
    xlsx.unlink()

    out = ingest.backfill_docs_originals(sid)
    assert out["filled"] == 0, out
    assert out["missing"] == 1
    assert not (store.list_sources(sid)[0].get("meta") or {}).get("docs_path")


def test_rebuild_toast_names_the_revision_profile():
    """A Saved+Rebuild that stamps graph but toasts only depth is R-0011."""
    src = Path(__file__).resolve().parents[1] / "index.html"
    text = src.read_text(encoding="utf-8", errors="replace")
    assert "r.revision_profile" in text
    assert "ragSaveAndRebuild" in text

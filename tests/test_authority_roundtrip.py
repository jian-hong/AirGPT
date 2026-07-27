"""Authority is decided by how material entered, not by what the file is called.

A chat transcript holds the assistant's own past answers, including any it got
wrong. Those must never become citable evidence. Classifying by path regex
alone loses that guarantee the moment a file is renamed: an export pack names
members `0001__chat_126.md`, and the chat pattern requires `chat_` right after a
separator, so a round trip would promote a transcript to a document.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import authority as A


@pytest.fixture()
def space(tmp_path, monkeypatch):
    import rag.store as store
    from rag import ingest, vectors

    monkeypatch.setattr(store, "RAG_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "rag" / "rag.db")
    monkeypatch.setattr(store, "BLOB_DIR", tmp_path / "rag")
    monkeypatch.setattr(vectors, "clear_space", lambda *a, **k: None)
    monkeypatch.setattr(vectors, "index_children", lambda *a, **k: 0)
    monkeypatch.setattr(vectors, "available", lambda *a, **k: {"ok": False})
    store.reset_init_cache()
    store.init()
    return store, ingest, tmp_path


def _classes(store, space_id):
    with store._conn() as c:
        rows = c.execute(
            "SELECT path, authority FROM chunks WHERE space_id=?", (space_id,)
        ).fetchall()
    return {Path(r["path"]).name: r["authority"] for r in rows}


def test_pack_prefixed_transcript_would_fool_the_path_classifier():
    """The reason authority is stored at ingest rather than re-derived."""
    assert A.classify("sources/chat_126.md", "chat_126.md") == A.CONVERSATION
    # Same transcript, pack-prefixed: the regex no longer matches.
    assert A.classify("sources/0001__chat_126.md", "0001__chat_126.md") == A.DOCUMENT


def test_explicit_authority_is_persisted(space):
    store, ingest, tmp = space
    up = tmp / "up"
    up.mkdir()
    (up / "chat_126.md").write_text("## assistant\nAn earlier guess about a company.\n" * 3, encoding="utf-8")
    (up / "report.md").write_text("# Lab report\nPeak SNR 92.5 dB.\n" * 3, encoding="utf-8")

    sid = int(store.create_space(name="s", depth_default="high")["id"])
    ingest.ingest_paths(sid, [str(up / "chat_126.md")], force=True, authority=A.CONVERSATION)
    ingest.ingest_paths(sid, [str(up / "report.md")], force=False)

    classes = _classes(store, sid)
    assert classes["chat_126.md"] == A.CONVERSATION
    assert classes["report.md"] == A.DOCUMENT


def test_transcript_survives_export_import_as_conversation(space):
    store, ingest, tmp = space
    from rag import export_import

    up = tmp / "up2"
    up.mkdir()
    (up / "chat_126.md").write_text("## assistant\nAn earlier guess about a company.\n" * 3, encoding="utf-8")
    (up / "report.md").write_text("# Lab report\nPeak SNR 92.5 dB.\n" * 3, encoding="utf-8")

    sid = int(store.create_space(name="orig", depth_default="high")["id"])
    ingest.ingest_paths(sid, [str(up / "chat_126.md")], force=True, authority=A.CONVERSATION)
    ingest.ingest_paths(sid, [str(up / "report.md")], force=False)

    imported = export_import.import_pack(export_import.export_space(sid), name="round")
    new_id = int(imported["space"]["id"])

    classes = _classes(store, new_id)
    assert classes, "import produced no chunks"
    for name, kind in classes.items():
        if "chat" in name.lower():
            assert kind == A.CONVERSATION, f"{name} was laundered into {kind}"
            assert not A.is_evidence(kind)
        else:
            assert kind == A.DOCUMENT


def test_url_ingest_declares_web(space):
    store, ingest, tmp = space
    up = tmp / "up3"
    up.mkdir()
    f = up / "url_example.md"
    f.write_text("# Example\nFetched page body.\n" * 3, encoding="utf-8")
    sid = int(store.create_space(name="w", depth_default="high")["id"])
    ingest.ingest_paths(sid, [str(f)], force=True, authority=A.WEB)
    assert _classes(store, sid)["url_example.md"] == A.WEB
    assert A.is_evidence(A.WEB)


def test_conversation_is_never_evidence():
    assert A.is_evidence(A.CONVERSATION) is False
    assert A.is_evidence(A.DOCUMENT) is True
    assert A.is_evidence(A.WEB) is True
    assert A.weight(A.CONVERSATION) < A.weight(A.DOCUMENT)

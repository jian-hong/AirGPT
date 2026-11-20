"""Round 2, lane rag-core: RAG must never lose or corrupt data.

Each test here was seen failing on the base commit before its fix.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402


def _multipart_parts(parts: list[tuple[str, str, str]], fields: dict[str, str] | None = None):
    b = uuid.uuid4().hex
    out = []
    for key, fname, text in parts:
        out.append(
            f'--{b}\r\nContent-Disposition: form-data; name="{key}"; filename="{fname}"\r\n'
            f"Content-Type: text/plain\r\n\r\n{text}\r\n"
        )
    for k, v in (fields or {}).items():
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n')
    return ("".join(out) + f"--{b}--\r\n").encode(), f"multipart/form-data; boundary={b}"


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRGPT_RAG_EMBED", "hash")
    import rag.store as store
    from rag import embed

    embed.reset_embedder_cache()
    monkeypatch.setattr(store, "RAG_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "BLOB_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "rag" / "rag.db")
    store.init()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", store
    srv.shutdown()
    srv.server_close()
    embed.reset_embedder_cache()


def _call(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def _upload(base, sid, parts, fields=None):
    body, ctype = _multipart_parts(parts, fields)
    req = urllib.request.Request(f"{base}/api/rag/spaces/{sid}/upload", data=body,
                                 headers={"Content-Type": ctype}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def _found(sid, needle):
    from rag import retrieve

    hits = retrieve.search(sid, needle, top_k=5).get("hits") or []
    return any(needle in str(h.get("text")) for h in hits)


# --- adding by path must not wipe the space (rag-server.0, rag-journey.13) ------------

def test_add_by_path_keeps_existing_documents(server, tmp_path):
    base, store = server
    sid = int(store.create_space("keep")["id"])
    _upload(base, sid, [("file0", "policy.txt", "The Zorvath refund window is 30 days.\n")], {"force": "0"})
    assert _found(sid, "Zorvath")
    ship = tmp_path / "ship.txt"
    ship.write_text("Brelkin shipments leave on Tuesday.\n")
    code, out = _call(base, "POST", f"/api/rag/spaces/{sid}/sources", {"path": str(ship)})
    assert code == 200 and out["ok"], out
    assert _found(sid, "Brelkin")
    assert _found(sid, "Zorvath"), "adding a file by path wiped the earlier document"


def test_force_on_sources_route_is_refused_not_a_silent_wipe(server, tmp_path):
    base, store = server
    sid = int(store.create_space("noforce")["id"])
    _upload(base, sid, [("file0", "policy.txt", "The Zorvath refund window is 30 days.\n")])
    ship = tmp_path / "ship.txt"
    ship.write_text("Brelkin shipments leave on Tuesday.\n")
    code, out = _call(base, "POST", f"/api/rag/spaces/{sid}/sources", {"path": str(ship), "force": True})
    assert code == 400 and "Rebuild" in out["error"]
    assert _found(sid, "Zorvath")


def test_rebuild_still_clears_and_reingests_everything(server, tmp_path):
    base, store = server
    sid = int(store.create_space("rebuild")["id"])
    _upload(base, sid, [("file0", "a.txt", "The Zorvath refund window is 30 days.\n"),
                        ("file1", "b.txt", "Brelkin shipments leave on Tuesday.\n")])
    code, out = _call(base, "POST", f"/api/rag/spaces/{sid}/build", {})
    assert code == 200 and out["ok"], out
    assert _found(sid, "Zorvath") and _found(sid, "Brelkin")


def test_upload_without_force_field_keeps_earlier_files(server):
    base, store = server
    sid = int(store.create_space("nof")["id"])
    for i in range(3):
        _upload(base, sid, [("file0", f"f{i}.txt", f"Marker{i}Quillon is here.\n")])
    for i in range(3):
        assert _found(sid, f"Marker{i}Quillon"), f"file {i} lost"


def test_page_ingest_path_does_not_send_force_true():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    start = html.index("async function ragIngestPath")
    body = html[start : start + 900]
    assert "force:true" not in body


# --- same name twice in one batch (rag-server.5) --------------------------------------

def test_same_name_twice_in_one_batch_keeps_both(server):
    base, store = server
    sid = int(store.create_space("dup")["id"])
    out = _upload(base, sid, [("file0", "notes.txt", "Alpha project budget is 5000 dollars.\n"),
                              ("file1", "notes.txt", "Beta project deadline is March.\n")])
    assert out["ok"]
    srcs = store.list_sources(sid)
    assert len(srcs) == 2, [s["title"] for s in srcs]
    assert out.get("sources") == 2 or len(out.get("source_ids") or []) == 2
    assert _found(sid, "Alpha") and _found(sid, "Beta")
    names = sorted(Path(s["path"]).name for s in srcs)
    assert names == ["notes.txt", "notes_2.txt"]


# --- deleting a source / a space (rag-journey.9) --------------------------------------

def _files_under(root: Path):
    return [p for p in root.rglob("*") if p.is_file()]


def test_delete_source_removes_files_chunks_summary_ontology(server):
    base, store = server
    sid = int(store.create_space("del")["id"])
    _upload(base, sid, [("file0", "sales.csv", "Region,Amount\nNorth,100\nSouth,50\n"),
                        ("file1", "memo.txt", "The Zorvath memo is long and boring.\n")])
    store.update_space_settings(sid, config={"corpus_summary": "stale summary naming sales.csv"})
    from rag import ontology

    ontology.ontology_for_space(sid, force=True)
    srcs = {Path(s["path"]).name: s for s in store.list_sources(sid)}
    sales = srcs["sales.csv"]
    root = store.BLOB_DIR / str(sid)
    assert any("sales" in p.name for p in _files_under(root))
    code, out = _call(base, "POST", f"/api/rag/sources/{sales['id']}/delete", {})
    assert code == 200 and out["ok"]
    left = [p.name for p in _files_under(root)]
    assert not any("sales" in n for n in left), left
    assert any("memo" in n for n in left), "the other source's files must stay"
    cfg = store.get_space(sid)["config"]
    assert not cfg.get("corpus_summary")
    assert not (cfg.get("ontology") or {}).get("tables")
    assert not _found(sid, "North")
    assert _found(sid, "Zorvath")


def test_delete_space_removes_everything(server):
    base, store = server
    sid = int(store.create_space("gone")["id"])
    other = int(store.create_space("stays")["id"])
    _upload(base, sid, [("file0", "a.txt", "Zorvath refund policy.\n")])
    _upload(base, other, [("file0", "b.txt", "Brelkin shipping notes.\n")])
    chat = store.create_chat(sid, "c")
    store.add_message(chat["id"], "user", "hi")
    root = store.BLOB_DIR / str(sid)
    assert root.exists()
    code, out = _call(base, "DELETE", f"/api/rag/spaces/{sid}")
    assert code == 200 and out["ok"], out
    assert not root.exists()
    assert store.get_space(sid) is None
    assert store.list_chats(sid) == []
    assert _found(other, "Brelkin"), "another space must be untouched"
    assert (store.BLOB_DIR / str(other)).exists()
    code, out = _call(base, "DELETE", f"/api/rag/spaces/{sid}")
    assert code == 404
    import sqlite3

    con = sqlite3.connect(store.DB_PATH)
    for tbl in ("sources", "chunks", "file_index", "rag_chats", "traces", "ingest_jobs", "revisions"):
        assert con.execute(f"SELECT COUNT(*) FROM {tbl} WHERE space_id=?", (sid,)).fetchone()[0] == 0, tbl
    con.close()


# --- exported pack leaks no host paths (rag-server.6) ---------------------------------

def test_export_pack_has_no_absolute_host_paths(server, tmp_path):
    import io
    import zipfile

    base, store = server
    sid = int(store.create_space("pack")["id"])
    _upload(base, sid, [("file0", "sales.csv", "Region,Amount\nNorth,100\nSouth,50\nNorth,25\n"),
                        ("file1", "policy.txt", "The Zorvath refund window is 30 days.\n")])
    from rag import ontology

    ontology.ontology_for_space(sid, force=True)
    assert store.get_space(sid)["config"].get("ontology"), "setup: the space should carry an ontology"
    with urllib.request.urlopen(f"{base}/api/rag/spaces/{sid}/export", timeout=60) as r:
        blob = r.read()
    zf = zipfile.ZipFile(io.BytesIO(blob))
    for name in zf.namelist():
        text = zf.read(name).decode("utf-8", "replace")
        assert str(tmp_path) not in text, f"host path leaked in {name}"
        assert "/uploads/" not in text and "/Docs/" not in text, f"host folder leaked in {name}"
    manifest = json.loads(zf.read("manifest.json"))
    assert "ontology" not in manifest["space"]["config"]
    # the pack still imports and answers
    from rag import export_import

    out = export_import.import_pack(blob)
    assert out["ok"], out
    assert _found(int(out["space"]["id"]), "Zorvath")

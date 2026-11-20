"""Uploading more files must not wipe the files already in the space.

Found by driving the live server, not by a unit test: `/upload` defaulted
`force` ON, so a second upload that did not send force=0 cleared every earlier
chunk. The sources list still showed the old files, and search returned
nothing for them. The UI sends force=0; any other caller lost data silently.
"""
from __future__ import annotations

import json
import os
import sys
import threading
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


def _multipart(files: dict[str, str], fields: dict[str, str] | None = None) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, text in files.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{name}"\r\n'
            f"Content-Type: text/plain\r\n\r\n{text}\r\n"
        )
    for k, v in (fields or {}).items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n')
    return ("".join(parts) + f"--{boundary}--\r\n").encode(), f"multipart/form-data; boundary={boundary}"


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


def _upload(base, sid, files, fields=None):
    body, ctype = _multipart(files, fields)
    req = urllib.request.Request(f"{base}/api/rag/spaces/{sid}/upload", data=body,
                                 headers={"Content-Type": ctype}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _found(sid, needle):
    from rag import retrieve

    hits = retrieve.search(sid, needle, top_k=5).get("hits") or []
    return any(needle in str(h.get("text")) for h in hits)


def test_second_upload_keeps_the_first(server):
    base, store = server
    sid = int(store.create_space("keep")["id"])
    assert _upload(base, sid, {"first.md": "# One\n\nThe Zorvath contract is void.\n"})["ok"]
    assert _upload(base, sid, {"second.md": "# Two\n\nThe Brelkin invoice is paid.\n"})["ok"]
    assert _found(sid, "Brelkin")
    assert _found(sid, "Zorvath"), "the first upload was wiped by the second"


def test_force_still_rebuilds_when_asked(server):
    base, store = server
    sid = int(store.create_space("force")["id"])
    _upload(base, sid, {"first.md": "# One\n\nThe Zorvath contract is void.\n"})
    _upload(base, sid, {"second.md": "# Two\n\nThe Brelkin invoice is paid.\n"}, {"force": "1"})
    assert _found(sid, "Brelkin")
    assert not _found(sid, "Zorvath")


def test_same_name_clash_looks_at_sources_not_leftover_files(server):
    base, store = server
    sid = int(store.create_space("clash")["id"])
    # An empty file is skipped (no source) but its bytes stay in the uploads folder.
    first = _upload(base, sid, {"notes.md": ""})
    assert first["sources"] == 0
    second = _upload(base, sid, {"notes.md": "# Notes\n\nThe Zorvath contract is void.\n"})
    assert second["ok"] and "renamed" not in second
    assert [s["title"] for s in store.list_sources(sid)] == ["notes.md"]
    # a different file with the name of a live source is still kept beside it
    third = _upload(base, sid, {"notes.md": "# Other\n\nThe Brelkin invoice is paid.\n"})
    assert third["renamed"] == [{"from": "notes.md", "to": "notes_2.md"}]

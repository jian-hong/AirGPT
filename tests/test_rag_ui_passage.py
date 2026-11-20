"""The answer page can open a cited passage and the original file (host only, read only).

Expected row numbers are worked out here from the ids written into the sheet, never by
calling the code that reports them.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402

N_ROWS = 140


def _multipart(name: str, data: bytes) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    body = (
        f'--{b}\r\nContent-Disposition: form-data; name="{name}"; filename="{name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + data + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


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


def _upload(base, sid, name, data):
    body, ctype = _multipart(name, data)
    req = urllib.request.Request(f"{base}/api/rag/spaces/{sid}/upload", data=body,
                                 headers={"Content-Type": ctype}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def _xlsx_bytes():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Orders"
    ws.append(["Order", "Region", "Amount"])
    for i in range(1, N_ROWS + 1):
        ws.append([f"O{i:04d}", ["North", "South"][i % 2], i * 3])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_sheet_passage_names_sheet_and_the_rows_it_covers(server):
    base, store = server
    sid = int(store.create_space("sheets")["id"])
    assert _upload(base, sid, "orders.xlsx", _xlsx_bytes())["ok"]
    chunks = [c for c in store.sample_parent_chunks(sid, limit=24) if "O0100" in c["text"]]
    assert chunks
    from rag import retrieve

    hit = next(h for h in retrieve.search(sid, "O0100", top_k=8)["hits"] if "O0100" in h["text"])
    code, _h, raw = _get(f"{base}/api/rag/passages/{hit['chunk_id']}")
    assert code == 200
    p = json.loads(raw)["passage"]
    assert p["file"] == "orders.xlsx" and p["sheet"] == "Orders"
    # Rows in the chunk, worked out from the ids in its own text: id Oxxxx is data row xxxx.
    ids = [int(m) for m in re.findall(r"\bO(\d{4})\b", p["text"])]
    assert ids and p["rows"]["first"] <= min(ids) and p["rows"]["last"] >= max(ids)
    assert p["rows"]["last"] - p["rows"]["first"] <= max(ids) - min(ids) + 2
    assert 100 in range(p["rows"]["first"], p["rows"]["last"] + 1)
    assert p["can_open"] is True and p["source_id"]
    # The first passage starts at the sheet's own heading: still a sheet, starting at row 1.
    top = next(c for c in store.sample_parent_chunks(sid, limit=24) if "O0001" in c["text"] and c["heading"].startswith("Sheet:"))
    q = json.loads(_get(f"{base}/api/rag/passages/{top['id']}")[2])["passage"]
    assert q["sheet"] == "Orders" and q["rows"]["first"] == 1


def test_pdf_style_heading_gives_a_page_and_text_gets_context(server):
    base, store = server
    sid = int(store.create_space("doc")["id"])
    lines = "\n".join(f"Line {i} about the maintenance of rotor {i}." for i in range(60))
    md = f"## Page 1\n{lines}\n\n## Page 2\nThe torque setting is 42 newton metres.\n\n## Page 3\nClosing notes.\n"
    assert _upload(base, sid, "manual.md", md.encode())["ok"]
    from rag import retrieve

    hit = next(h for h in retrieve.search(sid, "torque setting newton", top_k=8)["hits"] if "42 newton" in h["text"])
    p = json.loads(_get(f"{base}/api/rag/passages/{hit['chunk_id']}?around=2")[2])["passage"]
    assert p["page"] == 2 and p["sheet"] is None and p["rows"] is None
    assert "42 newton" in p["text"]
    assert "Page 3" in p["after"] or "Closing notes" in p["after"] or p["after"] == ""


def test_unknown_passage_and_bad_id_are_plain_errors(server):
    base, _store = server
    assert _get(f"{base}/api/rag/passages/999999")[0] == 404
    assert _get(f"{base}/api/rag/passages/abc")[0] == 400
    assert _get(f"{base}/api/rag/sources/999999/file")[0] == 404


def test_original_file_opens_and_script_capable_types_download(server):
    base, store = server
    sid = int(store.create_space("files")["id"])
    _upload(base, sid, "note.txt", b"plain words\n")
    _upload(base, sid, "page.html", b"<html><script>alert(1)</script><p>hello world page</p></html>")
    srcs = {s["title"]: s["id"] for s in store.list_sources(sid)}
    code, h, body = _get(f"{base}/api/rag/sources/{srcs['note.txt']}/file")
    assert code == 200 and body == b"plain words\n" and h["Content-Type"].startswith("text/plain")
    assert h["X-Content-Type-Options"] == "nosniff"
    code, h, body = _get(f"{base}/api/rag/sources/{srcs['page.html']}/file")
    assert code == 200 and h["Content-Type"] == "application/octet-stream"
    assert h["Content-Disposition"].startswith("attachment")


def test_remote_device_is_refused(server, monkeypatch):
    base, store = server
    sid = int(store.create_space("hostonly")["id"])
    _upload(base, sid, "note.txt", b"plain words\n")
    sid_src = store.list_sources(sid)[0]["id"]
    monkeypatch.setattr(clipdrop, "_is_host_request", lambda headers, ip: False)
    for path in (f"/api/rag/sources/{sid_src}/file", "/api/rag/passages/1"):
        code, _h, raw = _get(base + path)
        assert code == 403 and b"plain words" not in raw and b"passage" not in raw


def test_original_file_with_a_non_ascii_name_still_opens(server):
    """A name like "rapport_é.txt" used to break the reply: an empty 200 with no file."""
    base, store = server
    sid = int(store.create_space("unicode")["id"])
    name = "rapport_é_报告.txt"
    _upload(base, sid, name, "les conges: 25 jours\n".encode())
    src = store.list_sources(sid)[0]
    code, h, body = _get(f"{base}/api/rag/sources/{src['id']}/file")
    assert code == 200 and body == "les conges: 25 jours\n".encode()
    assert "filename*=UTF-8''" in h["Content-Disposition"]
    from urllib.parse import quote

    assert quote(name) in h["Content-Disposition"]

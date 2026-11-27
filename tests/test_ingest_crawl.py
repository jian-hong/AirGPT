"""Depth-capped site crawl (RAG-SRC-01). Local HTTP fixture only."""
from __future__ import annotations

import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")


def _page(title: str, marker: str, links: list[str]) -> str:
    anchors = "".join(f'<a href="{href}">{href}</a> ' for href in links)
    text = (
        f"{marker} is recorded on this page so the crawl test can see exactly "
        f"which documents were indexed and which links were left alone."
    )
    return (
        f"<html><head><title>{title}</title></head><body><h1>{title}</h1>"
        f"<p>{text}</p>{anchors}</body></html>"
    )


def _site() -> dict[str, tuple[str, str]]:
    pages = {
        "/": _page("Home", "Hometriple", [
            "/a",
            "/b",
            "https://evil.example/out",
            "/private/secret",
            "/a#section",
        ]),
        "/a": _page("A", "Atriple", ["/a/child"]),
        "/b": _page("B", "Btriple", ["/b/child", "https://other.example/x"]),
        "/a/child": _page("A child", "Achildtriple", ["/a/child/too-deep"]),
        "/b/child": _page("B child", "Bchildtriple", []),
        "/a/child/too-deep": _page("Too deep", "Toodeeptriple", []),
        "/private/secret": _page("Private", "Privatetriple", []),
        "/robots.txt": "User-agent: *\nDisallow: /private/\n",
    }
    out = {}
    for path, body in pages.items():
        ctype = "text/plain" if path == "/robots.txt" else "text/html; charset=utf-8"
        out[path] = (body, ctype)
    return out


class _Handler(BaseHTTPRequestHandler):
    pages: dict = {}
    hits: list = []

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        _Handler.hits.append(path)
        item = _Handler.pages.get(path)
        if item is None:
            self.send_response(404)
            self.end_headers()
            return
        body, ctype = item
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_a):
        return


def _guard_network(monkeypatch):
    real = socket.create_connection

    def guarded(addr, *args, **kwargs):
        host = addr[0] if isinstance(addr, tuple) else addr
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise AssertionError(f"live network connection to {host}")
        return real(addr, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", guarded)


@pytest.fixture()
def space(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRGPT_RAG_EMBED", "hash")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    import rag.store as store
    from rag import embed

    embed.reset_embedder_cache()
    monkeypatch.setattr(store, "RAG_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "BLOB_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "rag" / "rag.db")
    store.init()
    _Handler.pages = _site()
    _Handler.hits = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    sid = int(store.create_space("crawl")["id"])
    yield sid, store, srv.server_address[1]
    srv.shutdown()
    srv.server_close()
    embed.reset_embedder_cache()


def _chunk_blob(store, sid: int) -> str:
    with store._conn() as conn:
        rows = conn.execute("SELECT text FROM chunks WHERE space_id=?", (int(sid),)).fetchall()
    return "\n".join(row["text"] for row in rows)


def test_crawl_flag_off_fetches_nothing(space, monkeypatch):
    sid, store, port = space
    monkeypatch.delenv("AIRGPT_RAG_CRAWL", raising=False)
    _guard_network(monkeypatch)
    from rag import ingest

    out = ingest.ingest_crawl(sid, f"http://127.0.0.1:{port}/", depth=2, max_links=20, allow_private=True)
    assert out["ok"] is False
    assert out.get("disabled") is True
    assert _Handler.hits == []
    assert store.list_sources(sid) == []


def test_depth_two_ingests_exactly_the_site_and_stops(space, monkeypatch):
    sid, store, port = space
    monkeypatch.setenv("AIRGPT_RAG_CRAWL", "1")
    _guard_network(monkeypatch)
    from rag import ingest

    base = f"http://127.0.0.1:{port}"
    expected = {f"{base}/", f"{base}/a", f"{base}/b", f"{base}/a/child", f"{base}/b/child"}
    out = ingest.ingest_crawl(sid, f"{base}/", depth=2, max_links=20, allow_private=True)
    assert out["ok"] is True, out
    assert set(out["urls"]) == expected
    assert out["depth"] == 2
    assert out["max_links"] == 20
    assert out["robots"] == "applied"
    assert any("evil.example" in url for url in out["offsite"])
    assert any("other.example" in url for url in out["offsite"])
    assert any(url.endswith("/private/secret") for url in out["robots_blocked"])
    hits = list(_Handler.hits)
    assert "/robots.txt" in hits
    pages = [hit for hit in hits if hit != "/robots.txt"]
    assert set(pages) == {"/", "/a", "/b", "/a/child", "/b/child"}
    assert "/private/secret" not in hits
    assert "/a/child/too-deep" not in hits
    assert pages.count("/a") == 1
    blob = _chunk_blob(store, sid)
    for marker in ("Hometriple", "Atriple", "Btriple", "Achildtriple", "Bchildtriple"):
        assert marker in blob
    assert "Toodeeptriple" not in blob
    assert "Privatetriple" not in blob

    # Caps are hard: a larger request still stops at depth 2 and 20 pages.
    _Handler.hits = []
    ids = []
    with store._conn() as conn:
        ids = [int(row["id"]) for row in conn.execute("SELECT id FROM chunks WHERE space_id=?", (sid,))]
    again = ingest.ingest_crawl(sid, f"{base}/", depth=9, max_links=50, allow_private=True)
    assert again["depth"] == 2
    assert again["max_links"] == 20
    assert set(again["urls"]) == expected
    assert "/a/child/too-deep" not in _Handler.hits
    with store._conn() as conn:
        again_ids = [int(row["id"]) for row in conn.execute("SELECT id FROM chunks WHERE space_id=? ORDER BY id", (sid,))]
    assert again_ids == sorted(ids)


def test_max_links_hard_cap(space, monkeypatch):
    sid, _store, port = space
    monkeypatch.setenv("AIRGPT_RAG_CRAWL", "1")
    _guard_network(monkeypatch)
    from rag import ingest

    pages = {
        "/": _page("Index", "Indexttriple", [f"/p/{i}" for i in range(25)]),
        "/robots.txt": "User-agent: *\nDisallow:\n",
    }
    for i in range(25):
        pages[f"/p/{i}"] = _page(f"P{i}", f"Pagetriple{i}", [])
    _Handler.pages = {
        path: (body, "text/plain" if path == "/robots.txt" else "text/html; charset=utf-8")
        for path, body in pages.items()
    }
    _Handler.hits = []
    base = f"http://127.0.0.1:{port}"
    out = ingest.ingest_crawl(sid, f"{base}/", depth=5, max_links=100, allow_private=True)
    assert out["ok"] is True, out
    assert out["max_links"] == 20
    assert out["depth"] == 2
    assert len(out["urls"]) == 20
    assert f"{base}/p/18" in out["urls"]
    assert f"{base}/p/19" not in out["urls"]
    assert "/p/19" not in _Handler.hits


def test_private_address_refused_without_allow_private(space, monkeypatch):
    sid, store, port = space
    monkeypatch.setenv("AIRGPT_RAG_CRAWL", "1")
    _guard_network(monkeypatch)
    from rag import ingest

    _Handler.hits = []
    out = ingest.ingest_crawl(sid, f"http://127.0.0.1:{port}/", depth=2, max_links=20)
    assert out["ok"] is False
    assert "private or internal" in out["error"]
    assert _Handler.hits == []
    assert store.list_sources(sid) == []


def test_ingest_urls_stays_single_page_when_crawl_is_on(space, monkeypatch):
    sid, store, port = space
    monkeypatch.setenv("AIRGPT_RAG_CRAWL", "1")
    monkeypatch.delenv("AIRGPT_RAG_SOURCES_GITHUB", raising=False)
    from rag import ingest

    _Handler.hits = []
    out = ingest.ingest_urls(sid, [f"http://127.0.0.1:{port}/"])
    assert out["ok"] is False
    assert "private or internal" in out["failed_urls"][0]["reason"]
    assert store.list_sources(sid) == []
    # The single-page fetch refuses the address before it connects, and it does not crawl.
    assert _Handler.hits == []

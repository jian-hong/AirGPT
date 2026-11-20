"""URL ingest and web augment must not read loopback / private addresses (round 2, rag-core)."""
from __future__ import annotations

import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

SECRET = "Internal admin panel: the vault passphrase is plum-tangerine-9921, do not share it with anyone at all."


class _H(BaseHTTPRequestHandler):
    redirect_to = ""

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/go"):
            self.send_response(302)
            self.send_header("Location", _H.redirect_to)
            self.end_headers()
            return
        body = f"<html><body><p>{SECRET}</p></body></html>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture()
def space(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRGPT_RAG_EMBED", "hash")
    import rag.store as store
    from rag import embed

    embed.reset_embedder_cache()
    monkeypatch.setattr(store, "RAG_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "BLOB_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "rag" / "rag.db")
    store.init()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield int(store.create_space("urls")["id"]), srv.server_address[1], store
    srv.shutdown()
    srv.server_close()
    embed.reset_embedder_cache()


def test_loopback_url_is_refused_and_not_indexed(space):
    sid, port, store = space
    from rag import ingest, retrieve

    out = ingest.ingest_urls(sid, [f"http://127.0.0.1:{port}/page"])
    assert out["ok"] is False
    assert "private or internal" in out["failed_urls"][0]["reason"]
    assert store.list_sources(sid) == []
    assert not (retrieve.search(sid, "vault passphrase plum").get("hits") or [])


def test_redirect_to_loopback_is_refused(space, monkeypatch):
    """A public-looking first hop that redirects to a private address must be stopped."""
    sid, port, store = space
    import ai_engine
    from rag import ingest

    real = ai_engine._check_public_url
    first = {"done": False}

    def allow_first_hop(u):
        if not first["done"]:  # stand in for a genuinely public first URL
            first["done"] = True
            return None
        return real(u)

    monkeypatch.setattr(ai_engine, "_check_public_url", allow_first_hop)
    _H.redirect_to = f"http://127.0.0.1:{port}/secret"
    out = ingest.ingest_urls(sid, [f"http://127.0.0.1:{port}/go"])
    assert out["ok"] is False
    assert "private or internal" in out["failed_urls"][0]["reason"]
    assert store.list_sources(sid) == []


def test_link_local_and_private_literals_are_refused(space):
    sid, _port, _store = space
    from rag import ingest

    out = ingest.ingest_urls(sid, ["http://169.254.169.254/latest/meta-data/", "http://10.0.0.5/x", "http://[::1]/x"])
    assert out["ok"] is False
    assert len(out["failed_urls"]) == 3
    assert all("private or internal" in f["reason"] for f in out["failed_urls"])


def test_web_augment_fetches_go_through_the_same_filter(space, monkeypatch):
    sid, port, store = space
    from rag import answer, websearch

    monkeypatch.setattr(
        websearch, "search_web",
        lambda q, **kw: {"ok": True, "results": [{"title": "x", "url": f"http://127.0.0.1:{port}/p", "snippet": "plum"}]},
    )
    monkeypatch.setattr(answer, "_result_matches_goal", lambda r, g: True)
    aug = answer._web_augment_space(sid, "search the web for plum passphrase")
    assert aug["chunks"] == 0
    assert store.list_sources(sid) == []


def test_public_name_still_passes_the_check(monkeypatch):
    """Normal use: a link that resolves to a public address is not blocked."""
    import socket

    import ai_engine

    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))],
    )
    ai_engine._check_public_url("https://example.com/article")  # must not raise

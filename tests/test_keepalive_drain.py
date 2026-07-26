"""HTTP/1.1 keep-alive must survive early error returns.

Regression guard for the "spam the LLM and the whole backend dies" report. Several POST
routes reply before anyone reads the request body — 429 free-tier rate limit, 403
view-only share ACL, 503 no engine. With protocol_version = "HTTP/1.1" the connection is
reused, so the unread body stayed in the socket and the *next* request on that
connection was parsed starting from mid-JSON. Every later call on that socket failed and
the UI looked like the backend had crashed.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

import pytest

os.environ.setdefault("AIRGPT_NO_BROWSER", "1")
os.environ.setdefault("AIRGPT_DATA_DIR", os.path.join(tempfile.gettempdir(), "airgpt_test_data"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import clipdrop  # noqa: E402

BODY = b'{"text":"hello"}'


class _EarlyError(clipdrop.Handler):
    """Replies 429 without touching the body — the shape of _handle_chat_stream."""

    def do_POST(self):  # noqa: N802
        self._json(429, {"error": "Free tier: 1 AI request/min."})

    def log_message(self, *args, **kwargs):
        pass


class _ReadsBody(clipdrop.Handler):
    """Normal route: consumes the body, then replies."""

    def do_POST(self):  # noqa: N802
        raw = self._body()
        self._json(200, {"echo": raw.decode()})

    def log_message(self, *args, **kwargs):
        pass


def _read_response(sock: socket.socket) -> tuple[int, bytes]:
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise AssertionError(f"connection closed before headers: {buf!r}")
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    status = int(head.split(b"\r\n", 1)[0].split()[1])
    length = 0
    for line in head.split(b"\r\n")[1:]:
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            length = int(value.strip())
    while len(rest) < length:
        chunk = sock.recv(4096)
        if not chunk:
            break
        rest += chunk
    return status, rest[:length]


def _request(sock: socket.socket, body: bytes = BODY) -> None:
    sock.sendall(
        b"POST /api/chat/stream HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"\r\n" + body
    )


@pytest.fixture
def serve():
    servers = []

    def _start(handler):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return srv.server_address

    yield _start
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def test_early_error_does_not_poison_keepalive(serve):
    """Three 429s down one connection: every reply is a well-formed 429."""
    addr = serve(_EarlyError)
    with socket.create_connection(addr, timeout=5) as sock:
        for _ in range(3):
            _request(sock)
            status, payload = _read_response(sock)
            assert status == 429, f"expected 429, got {status} — leftover body was parsed as a request"
            assert "Free tier" in json.loads(payload)["error"]


def test_body_read_is_not_drained_twice(serve):
    """Normal routes still get their body, and the socket stays usable afterwards."""
    addr = serve(_ReadsBody)
    with socket.create_connection(addr, timeout=5) as sock:
        for _ in range(2):
            _request(sock)
            status, payload = _read_response(sock)
            assert status == 200
            assert json.loads(payload)["echo"] == BODY.decode()


def test_oversized_unread_body_closes_instead_of_reading(serve):
    """A 4 MB+ body rejected early drops the socket rather than draining it."""
    addr = serve(_EarlyError)
    with socket.create_connection(addr, timeout=5) as sock:
        sock.sendall(
            b"POST /api/chat/stream HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 8388608\r\n"
            b"\r\n"
        )
        status, _ = _read_response(sock)
        assert status == 429
        assert sock.recv(4096) == b"", "server should close rather than read 8 MB it rejected"

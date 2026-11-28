"""First-run page on 127.0.0.1. Setup replies never include the token."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bundle.api import setup_payload, status_payload
from bundle.posture import LOOPBACK

PAGE = Path(__file__).resolve().parents[1] / "ui" / "onboarding.html"


class WizardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/api/bundle/status", "/api/bundle/status/"):
            self._json(200, status_payload())
            return
        if path in ("/", "/onboarding", "/ui/onboarding.html"):
            if not PAGE.is_file():
                self._json(404, {"ok": False, "error": "onboarding page missing"})
                return
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if path in ("/api/bundle/setup", "/api/bundle/setup/"):
            self._json(200, setup_payload())
            return
        self._json(404, {"ok": False, "error": "not found"})


def serve(port: int) -> None:
    server = ThreadingHTTPServer((LOOPBACK, port), WizardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def serve_background(port: int = 0) -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer((LOOPBACK, port), WizardHandler)
    import threading

    threading.Thread(target=server.serve_forever, daemon=True).start()
    bound = int(server.server_address[1])
    return server, bound

"""#23/#24 HTTP gate: identify+pack, handoff, reveal over the clipdrop routes.

Module tests can pass while the Handler omits the path (same class as #32).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402
from rag import xlsx_orch  # noqa: E402

import openpyxl  # noqa: E402

ENDPOINTS = (
    "/api/rag/xlsx-orch/identify",
    "/api/rag/xlsx-orch/handoff",
    "/api/rag/xlsx-orch/reveal",
)


def _frtr(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Carriers"
    ws.append(["Carrier", "Region", "OnTime", "Cost"])
    ws.append(["Acme", "APAC", True, 310.0])
    ws.append(["Beta", "EMEA", False, 200.0])
    dest = path / "frtr_00027_supply-chain-regional.xlsx"
    wb.save(dest)
    wb.close()
    return dest


def _result(path: Path) -> Path:
    wb = openpyxl.Workbook()
    wb.active.title = "Cover"
    wb.create_sheet("OnTime Export")
    wb.create_sheet("Analysis")
    wb.create_sheet("Presentation Chart")
    dest = path / "result.xlsx"
    wb.save(dest)
    wb.close()
    return dest


class XlsxOrchHttpGateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.orch = Path(self._tmp.name) / "orch"
        self.orch.mkdir()
        self._orig = xlsx_orch.PACK_DIR
        xlsx_orch.PACK_DIR = self.orch
        self.frtr = _frtr(Path(self._tmp.name))
        self.result = _result(Path(self._tmp.name))
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.posted: list[str] = []

    def tearDown(self):
        xlsx_orch.PACK_DIR = self._orig
        self.srv.shutdown()
        self.srv.server_close()
        self._tmp.cleanup()

    def _post(self, path, payload):
        self.posted.append(path)
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def test_identify_pack_handoff_reveal_over_http(self):
        code, identified = self._post(
            "/api/rag/xlsx-orch/identify",
            {
                "path": str(self.frtr),
                "ask": "OnTime=true avg cost + export xlsx + chart for PPT on frtr_00027",
            },
        )
        self.assertEqual(code, 200, identified)
        self.assertEqual(identified.get("status"), "identified", identified)
        self.assertTrue(identified.get("pack"), identified)
        pack_id = identified["pack_id"]
        self.assertEqual(identified["handoff"]["status"], "awaiting_dms_receipt")

        code, waiting = self._post("/api/rag/xlsx-orch/handoff", {"pack_id": pack_id})
        self.assertEqual(code, 200, waiting)
        self.assertEqual(waiting.get("status"), "awaiting_dms_receipt")

        code, blocked = self._post(
            "/api/rag/xlsx-orch/reveal", {"pack_id": pack_id, "which": "result"}
        )
        self.assertEqual(code, 400, blocked)
        self.assertFalse(blocked.get("ok"))

        code, received = self._post(
            "/api/rag/xlsx-orch/handoff",
            {"pack_id": pack_id, "result_path": str(self.result)},
        )
        self.assertEqual(code, 200, received)
        self.assertEqual(received.get("status"), "received", received)

        seen = {}

        def _fake(path: str):
            seen["path"] = path
            return {"ok": True, "path": path, "action": "test_stub"}

        import rag.reveal as rag_reveal

        orig = rag_reveal.reveal_path
        rag_reveal.reveal_path = _fake
        try:
            code, revealed = self._post(
                "/api/rag/xlsx-orch/reveal", {"pack_id": pack_id, "which": "result"}
            )
        finally:
            rag_reveal.reveal_path = orig
        self.assertEqual(code, 200, revealed)
        self.assertTrue(revealed.get("ok"), revealed)
        self.assertEqual(Path(seen["path"]).name, "result.xlsx")
        self.assertEqual(set(self.posted), set(ENDPOINTS))

    def test_routes_exist_on_handler(self):
        src = Path(clipdrop.__file__).read_text(encoding="utf-8")
        for ep in ENDPOINTS:
            self.assertIn(ep, src)


if __name__ == "__main__":
    unittest.main()

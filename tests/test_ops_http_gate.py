"""#32 D02 HTTP gate: the six /api/rag/ops endpoints must be reachable over HTTP.

ops_demo_e2e.py 32/32 imports rag.ops_amend directly, so a broken clipdrop route
could not fail that script. This gate posts the loop a client actually calls
(R-0001) and reads the salary cell back out of the workbook.
"""
from __future__ import annotations

import importlib.util
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

# clipdrop.py currently has an orphaned #15 fragment after _sse_end() (PR #39).
# Do not edit that file here. Load Handler from source, dropping only those
# three lines when the module does not parse.
_ORPHAN = (
    "        self._sse_end()\n"
    "            # Rebuilt from a fixed key list, so anything not named here is dropped\n"
    "            # no matter what answer_events produced. #15's chain was missing.\n"
    '            "reasoning": done.get("reasoning") or {},\n'
)


def _load_clipdrop():
    try:
        import clipdrop

        return clipdrop
    except IndentationError:
        sys.modules.pop("clipdrop", None)
    src = (ROOT / "clipdrop.py").read_text(encoding="utf-8")
    if _ORPHAN not in src:
        raise IndentationError(
            "clipdrop.py does not parse and the known #15 fragment is gone"
        )
    src = src.replace(_ORPHAN, "        self._sse_end()\n", 1)
    spec = importlib.util.spec_from_loader("clipdrop", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(ROOT / "clipdrop.py")
    sys.modules["clipdrop"] = mod
    exec(compile(src, str(ROOT / "clipdrop.py"), "exec"), mod.__dict__)
    return mod


clipdrop = _load_clipdrop()

from rag import ops_amend  # noqa: E402

import openpyxl  # noqa: E402

ENDPOINTS = (
    "/api/rag/ops/identify",
    "/api/rag/ops/confirm-identity",
    "/api/rag/ops/propose-amend",
    "/api/rag/ops/confirm-amend",
    "/api/rag/ops/continue",
    "/api/rag/ops/chain",
)


def _write_payroll(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Payroll_RAW"
    ws.append(["Emp ID", "Name", "Base Salary", "Notes"])
    ws.append(["E-0012", "Ada Ng", 50000.0, ""])
    ws.append(["E-0013", "Ben Ok", 40000.0, ""])
    ws.append(["E-0500", "Cara Yu", 45000.0, ""])
    wb.save(path)
    wb.close()
    return path


def _salary(path: Path, row: int) -> float:
    """Read the salary cell straight from the workbook - no handler involved."""
    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        ws = wb["Payroll_RAW"]
        header = [str(c.value or "").strip() for c in next(ws.iter_rows(max_row=1))]
        col = header.index("Base Salary") + 1
        return float(ws.cell(row, col).value)
    finally:
        wb.close()


class OpsHttpGateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ops_dir = Path(self._tmp.name) / "ops"
        self.ops_dir.mkdir()
        self.payroll = _write_payroll(Path(self._tmp.name) / "payroll.xlsx")
        self._orig_ops = ops_amend.OPS_DIR
        ops_amend.OPS_DIR = self.ops_dir
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.posted: list[str] = []

    def tearDown(self):
        ops_amend.OPS_DIR = self._orig_ops
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

    def test_the_six_ops_endpoints_complete_the_loop_over_http(self):
        before = _salary(self.payroll, 2)

        code, identified = self._post(
            "/api/rag/ops/identify",
            {"path": str(self.payroll), "ask": "salary raise for E-0012"},
        )
        self.assertEqual(code, 200, identified)
        self.assertTrue(identified.get("ok"), identified)
        pending = identified["pending"]
        token = pending["token"]
        self.assertEqual(pending.get("match_basis"), "emp_id")

        code, confirmed = self._post(
            "/api/rag/ops/confirm-identity", {"token": token, "yes": True}
        )
        self.assertEqual(code, 200, confirmed)
        self.assertEqual(confirmed.get("status"), "confirmed")

        code, proposed = self._post(
            "/api/rag/ops/propose-amend", {"token": token, "increment_pct": 8}
        )
        self.assertEqual(code, 200, proposed)
        want = round(before * 1.08, 2)
        self.assertAlmostEqual(proposed["pending"]["proposed_salary"], want, places=2)
        self.assertEqual(_salary(self.payroll, 2), before, "propose must not write")

        code, written = self._post(
            "/api/rag/ops/confirm-amend", {"token": token, "yes": True}
        )
        self.assertEqual(code, 200, written)
        self.assertEqual(written.get("status"), "written")
        self.assertEqual(_salary(self.payroll, 2), want)
        self.assertEqual(_salary(self.payroll, 3), 40000.0, "neighbour row untouched")

        code, cont = self._post(
            "/api/rag/ops/continue", {"token": token, "next_row": True}
        )
        self.assertEqual(code, 200, cont)
        self.assertTrue(cont.get("ok") and cont.get("pending"), cont)
        tok2 = cont["pending"]["token"]
        self.assertNotEqual(tok2, token)
        code, skipped = self._post(
            "/api/rag/ops/confirm-amend", {"token": tok2, "yes": True}
        )
        self.assertEqual(code, 400, skipped)
        self.assertFalse(skipped.get("ok"))

        code, ch = self._post("/api/rag/ops/chain", {"token": token})
        self.assertEqual(code, 200, ch)
        self.assertTrue(ch.get("ok"), ch)
        self.assertEqual(len(ch.get("amended") or []), 1)
        self.assertEqual(set(self.posted), set(ENDPOINTS))

    def test_identify_over_http_does_not_propose_an_unmatched_row(self):
        code, out = self._post(
            "/api/rag/ops/identify",
            {"path": str(self.payroll), "ask": "give the intern a raise"},
        )
        self.assertEqual(code, 200, out)
        self.assertEqual(out.get("status"), "no_match")
        self.assertNotIn("token", out)
        self.assertFalse(out.get("pending"))
        self.assertIn("not proposing", str(out.get("prompt", "")).lower())
        self.assertEqual(_salary(self.payroll, 2), 50000.0)

    def test_propose_before_identity_confirm_is_refused_over_http(self):
        code, identified = self._post(
            "/api/rag/ops/identify",
            {"path": str(self.payroll), "ask": "salary raise for E-0012"},
        )
        self.assertEqual(code, 200, identified)
        token = identified["pending"]["token"]
        code, refused = self._post(
            "/api/rag/ops/propose-amend", {"token": token, "increment_pct": 8}
        )
        self.assertEqual(code, 400, refused)
        self.assertFalse(refused.get("ok"))
        self.assertEqual(_salary(self.payroll, 2), 50000.0)


if __name__ == "__main__":
    unittest.main()

"""#18 acceptance clause: unconfirmed amends must not land.

The two consent gates coerced with `bool(data.get("yes"))`. In Python
`bool("false") is True`, so a JSON *string* "false" — a user saying no in as
many words — read as consent. Observed over real HTTP before the fix:

    confirm-identity yes="false" (string) -> HTTP 200, status='confirmed'
    confirm-amend    yes="false" (string) -> HTTP 200, status='written',
                                             salary 50000.0 -> 54000.0

An unconfirmed amend landed on an explicit no. These tests drive the real
handler over HTTP (same ThreadingHTTPServer pattern as tests/test_ops_http_gate.py)
and assert on the workbook itself — the salary cell read back with openpyxl and
the file's sha256 — never on the response message. An endpoint that says
"aborted" while the bytes changed is exactly what this gate is for.
"""
from __future__ import annotations

import hashlib
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
from rag import ops_amend  # noqa: E402

import openpyxl  # noqa: E402

BASE_SALARY = 50000.0

# Every value that is not a real JSON boolean true. Each must read as NO.
NON_CONSENT = (
    ("string false", "false"),
    ("string zero", "0"),
    ("string true", "true"),   # still a string, still not a boolean
    ("string yes", "yes"),
    ("int one", 1),
    ("int zero", 0),
    ("null", None),
    ("empty list", []),
)


def _write_payroll(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Payroll_RAW"
    ws.append(["Emp ID", "Name", "Base Salary", "Notes"])
    ws.append(["E-0012", "Ada Ng", BASE_SALARY, ""])
    ws.append(["E-0013", "Ben Ok", 40000.0, ""])
    wb.save(path)
    wb.close()
    return path


def _salary(path: Path, row: int = 2) -> float:
    """Straight out of the workbook - no handler involved."""
    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        ws = wb["Payroll_RAW"]
        header = [str(c.value or "").strip() for c in next(ws.iter_rows(max_row=1))]
        return float(ws.cell(row, header.index("Base Salary") + 1).value)
    finally:
        wb.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OpsConfirmStrictnessTest(unittest.TestCase):
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

    def tearDown(self):
        ops_amend.OPS_DIR = self._orig_ops
        self.srv.shutdown()
        self.srv.server_close()
        self._tmp.cleanup()

    def _post(self, path, payload):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def _identify(self) -> str:
        code, out = self._post(
            "/api/rag/ops/identify",
            {"path": str(self.payroll), "ask": "salary raise for E-0012"},
        )
        self.assertEqual(code, 200, out)
        return out["pending"]["token"]

    def _armed_token(self) -> str:
        """A token sitting at awaiting_amend_confirm: one keystroke from a write."""
        token = self._identify()
        code, out = self._post(
            "/api/rag/ops/confirm-identity", {"token": token, "yes": True}
        )
        self.assertEqual(out.get("status"), "confirmed", out)
        code, out = self._post(
            "/api/rag/ops/propose-amend", {"token": token, "increment_pct": 8}
        )
        self.assertEqual(code, 200, out)
        self.assertAlmostEqual(out["pending"]["proposed_salary"], 54000.0, places=2)
        return token

    # --- (a) confirm-identity must not confirm on a non-boolean --------------

    def test_confirm_identity_refuses_every_non_boolean_yes(self):
        for label, value in NON_CONSENT:
            with self.subTest(yes=label):
                token = self._identify()
                code, out = self._post(
                    "/api/rag/ops/confirm-identity", {"token": token, "yes": value}
                )
                self.assertNotEqual(
                    out.get("status"), "confirmed",
                    f"yes={label} ({value!r}) was accepted as consent: {out}",
                )
                # Real state: the gate must still refuse a propose afterwards.
                code, proposed = self._post(
                    "/api/rag/ops/propose-amend", {"token": token, "increment_pct": 8}
                )
                self.assertEqual(
                    code, 400,
                    f"yes={label} left the identity gate open: {proposed}",
                )
                self.assertFalse(proposed.get("ok"), proposed)

    def test_confirm_identity_with_missing_yes_key_does_not_confirm(self):
        token = self._identify()
        code, out = self._post("/api/rag/ops/confirm-identity", {"token": token})
        self.assertNotEqual(out.get("status"), "confirmed", out)
        code, proposed = self._post(
            "/api/rag/ops/propose-amend", {"token": token, "increment_pct": 8}
        )
        self.assertEqual(code, 400, proposed)

    # --- (b)/(c) confirm-amend must not write on a non-boolean ---------------

    def test_confirm_amend_refuses_every_non_boolean_yes_and_the_file_is_untouched(self):
        for label, value in NON_CONSENT:
            with self.subTest(yes=label):
                token = self._armed_token()
                before_sum = _sha256(self.payroll)
                before_salary = _salary(self.payroll)
                self.assertEqual(before_salary, BASE_SALARY)

                code, out = self._post(
                    "/api/rag/ops/confirm-amend", {"token": token, "yes": value}
                )
                self.assertNotEqual(
                    out.get("status"), "written",
                    f"yes={label} ({value!r}) authorised a write: {out}",
                )
                self.assertEqual(
                    _salary(self.payroll), BASE_SALARY,
                    f"yes={label} ({value!r}) moved the salary cell",
                )
                self.assertEqual(
                    _sha256(self.payroll), before_sum,
                    f"yes={label} ({value!r}) changed the file bytes",
                )

    def test_confirm_amend_with_missing_yes_key_does_not_write(self):
        token = self._armed_token()
        before_sum = _sha256(self.payroll)
        code, out = self._post("/api/rag/ops/confirm-amend", {"token": token})
        self.assertNotEqual(out.get("status"), "written", out)
        self.assertEqual(_salary(self.payroll), BASE_SALARY)
        self.assertEqual(_sha256(self.payroll), before_sum)

    def test_the_observed_defect_string_false_end_to_end(self):
        """The exact reported sequence: both gates answered with the string
        "false", which drove 50000.0 -> 54000.0 before the fix."""
        token = self._identify()
        before_sum = _sha256(self.payroll)

        code, ident = self._post(
            "/api/rag/ops/confirm-identity", {"token": token, "yes": "false"}
        )
        self.assertNotEqual(ident.get("status"), "confirmed", ident)

        code, amend = self._post(
            "/api/rag/ops/confirm-amend", {"token": token, "yes": "false"}
        )
        self.assertNotEqual(amend.get("status"), "written", amend)
        self.assertEqual(
            _salary(self.payroll), BASE_SALARY,
            "an explicit NO landed a 54000.0 write",
        )
        self.assertEqual(_sha256(self.payroll), before_sum)

    def test_the_refusal_names_its_cause(self):
        """Fail closed AND say why: a refusal that looks like an ordinary no
        hides a malformed client from whoever has to debug it."""
        token = self._armed_token()
        code, out = self._post(
            "/api/rag/ops/confirm-amend", {"token": token, "yes": "false"}
        )
        warning = str(out.get("consent_warning") or "")
        self.assertIn("boolean", warning.lower(), f"cause not named: {out}")
        self.assertIn("str", warning, warning)

    # --- (d) the legitimate path still works ---------------------------------

    def test_real_boolean_true_still_confirms_and_lands_exactly_one_amend(self):
        token = self._identify()
        code, ident = self._post(
            "/api/rag/ops/confirm-identity", {"token": token, "yes": True}
        )
        self.assertEqual(code, 200, ident)
        self.assertEqual(ident.get("status"), "confirmed", ident)

        code, proposed = self._post(
            "/api/rag/ops/propose-amend", {"token": token, "increment_pct": 8}
        )
        self.assertEqual(code, 200, proposed)
        self.assertEqual(_salary(self.payroll), BASE_SALARY, "propose must not write")

        code, written = self._post(
            "/api/rag/ops/confirm-amend", {"token": token, "yes": True}
        )
        self.assertEqual(code, 200, written)
        self.assertEqual(written.get("status"), "written", written)
        self.assertNotIn("consent_warning", written, written)
        self.assertEqual(_salary(self.payroll), 54000.0)
        self.assertEqual(_salary(self.payroll, 3), 40000.0, "neighbour row untouched")

        # Exactly one: the token is spent, a replay must not write again.
        code, replay = self._post(
            "/api/rag/ops/confirm-amend", {"token": token, "yes": True}
        )
        self.assertEqual(code, 400, replay)
        self.assertEqual(_salary(self.payroll), 54000.0, "replay landed a second amend")

    def test_real_boolean_false_still_aborts_cleanly(self):
        token = self._armed_token()
        before_sum = _sha256(self.payroll)
        code, out = self._post(
            "/api/rag/ops/confirm-amend", {"token": token, "yes": False}
        )
        self.assertEqual(code, 200, out)
        self.assertEqual(out.get("status"), "aborted", out)
        self.assertNotIn("consent_warning", out, "a real false is not malformed")
        self.assertEqual(_salary(self.payroll), BASE_SALARY)
        self.assertEqual(_sha256(self.payroll), before_sum)


if __name__ == "__main__":
    unittest.main()

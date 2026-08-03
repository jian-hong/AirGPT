"""Governed ops amend-confirm loop (EPIC-D02) — identify → confirm → amend.

No silent mutate. Branch-safe: does not touch FRTR score artifacts.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OPS_DIR = ROOT / "tests" / "RAG" / "results" / "ops"
OPS_DIR.mkdir(parents=True, exist_ok=True)

_PENDING: dict[str, dict[str, Any]] = {}


def _load_payroll(path: Path) -> list[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        hdr = [str(h or "").strip() for h in rows[0]]
        out = []
        for i, row in enumerate(rows[1:], start=2):
            d = {hdr[j]: row[j] if j < len(row) else None for j in range(len(hdr))}
            d["_row"] = i
            out.append(d)
        return out
    finally:
        wb.close()


def identify_employee(path: str | Path, ask: str) -> dict:
    """Propose a payroll row and ask 'is it that one?' — no mutate yet."""
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": "payroll file missing"}
    rows = _load_payroll(p)
    q = ask or ""
    m = re.search(r"\bE-?\s*(\d{1,5})\b", q, re.I)
    name_m = re.search(r"for\s+([A-Za-z][A-Za-z0-9 ]{1,40})", q, re.I)
    cand = None
    if m:
        eid = f"E-{int(m.group(1)):04d}"
        cand = next((r for r in rows if str(r.get("Emp ID") or "").upper() == eid), None)
    if cand is None and name_m:
        needle = name_m.group(1).strip().lower()
        cand = next((r for r in rows if needle in str(r.get("Name") or "").lower()), None)
    if cand is None and rows:
        # weak fallback: first match containing digits from ask
        cand = rows[0]
        weak = True
    else:
        weak = False
    if not cand:
        return {"ok": False, "error": "no candidate row"}

    token = f"ops_{int(time.time())}_{cand.get('_row')}"
    pending = {
        "token": token,
        "path": str(p.resolve()),
        "sheet": "Payroll_RAW",
        "row": cand.get("_row"),
        "emp_id": cand.get("Emp ID"),
        "name": cand.get("Name"),
        "base_salary": cand.get("Base Salary"),
        "ask": ask,
        "status": "awaiting_identity_confirm",
        "prompt": f"Is it that one? Emp {cand.get('Emp ID')} / {cand.get('Name')} / salary {cand.get('Base Salary')} (row {cand.get('_row')})",
        "weak_match": weak,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _PENDING[token] = pending
    (OPS_DIR / f"{token}.json").write_text(json.dumps(pending, indent=2), encoding="utf-8")
    return {"ok": True, "phase": "identify", "pending": pending, "honesty": "Cortex-direct demo ops — confirm required before amend"}


def confirm_identity(token: str, yes: bool) -> dict:
    pending = _PENDING.get(token)
    if not pending:
        # reload
        fp = OPS_DIR / f"{token}.json"
        if fp.is_file():
            pending = json.loads(fp.read_text(encoding="utf-8"))
            _PENDING[token] = pending
    if not pending:
        return {"ok": False, "error": "unknown token"}
    if pending.get("status") != "awaiting_identity_confirm":
        return {"ok": False, "error": f"bad status {pending.get('status')}"}
    if not yes:
        pending["status"] = "rejected_identity"
        (OPS_DIR / f"{token}.json").write_text(json.dumps(pending, indent=2), encoding="utf-8")
        return {"ok": True, "phase": "identify", "status": "rejected", "next": "re-identify with Emp ID or name — no amend performed"}
    pending["status"] = "identity_confirmed"
    (OPS_DIR / f"{token}.json").write_text(json.dumps(pending, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "phase": "identify",
        "status": "confirmed",
        "pending": pending,
        "next": "propose_amend with new salary or increment %",
    }


def propose_amend(token: str, *, new_salary: float | None = None, increment_pct: float | None = None) -> dict:
    pending = _PENDING.get(token) or json.loads((OPS_DIR / f"{token}.json").read_text(encoding="utf-8"))
    _PENDING[token] = pending
    if pending.get("status") != "identity_confirmed":
        return {"ok": False, "error": "confirm identity first (is it that one?)"}
    base = float(pending.get("base_salary") or 0)
    if increment_pct is not None:
        new_salary = round(base * (1 + float(increment_pct) / 100.0), 2)
    if new_salary is None:
        return {"ok": False, "error": "new_salary or increment_pct required"}
    pending["proposed_salary"] = float(new_salary)
    pending["status"] = "awaiting_amend_confirm"
    pending["amend_prompt"] = (
        f"Amend {pending.get('emp_id')} salary {base} -> {new_salary}? Confirm yes to write, no to abort."
    )
    (OPS_DIR / f"{token}.json").write_text(json.dumps(pending, indent=2), encoding="utf-8")
    return {"ok": True, "phase": "amend_propose", "pending": pending}


def confirm_amend(token: str, yes: bool) -> dict:
    pending = _PENDING.get(token) or json.loads((OPS_DIR / f"{token}.json").read_text(encoding="utf-8"))
    _PENDING[token] = pending
    if pending.get("status") != "awaiting_amend_confirm":
        return {"ok": False, "error": "no pending amend"}
    if not yes:
        pending["status"] = "amend_aborted"
        (OPS_DIR / f"{token}.json").write_text(json.dumps(pending, indent=2), encoding="utf-8")
        return {"ok": True, "phase": "amend", "status": "aborted", "note": "file unchanged"}

    import openpyxl

    path = Path(pending["path"])
    wb = openpyxl.load_workbook(path)
    try:
        ws = wb[pending.get("sheet") or wb.sheetnames[0]]
        row = int(pending["row"])
        # Base Salary is column 4 in generator
        ws.cell(row, 4).value = float(pending["proposed_salary"])
        ws.cell(row, 6).value = f"amended {time.strftime('%Y-%m-%dT%H:%M:%S')}"
        wb.save(path)
    finally:
        wb.close()
    pending["status"] = "amended"
    pending["amended_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (OPS_DIR / f"{token}.json").write_text(json.dumps(pending, indent=2), encoding="utf-8")
    return {"ok": True, "phase": "amend", "status": "written", "pending": pending, "path": str(path)}

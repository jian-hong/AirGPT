"""Governed ops amend-confirm loop (EPIC-D02) - identify -> confirm -> amend -> continue.

No silent mutate. Branch-safe: does not touch FRTR score artifacts.

Two gates stand between an ask and a written cell: the founder confirms the row
identity ("is it that one?"), then confirms the amended value. Skipping either is
refused by status, not by convention. After a write the loop continues into a fresh
pair of gates rather than staying authorised - a confirm buys one cell, not a session.
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

SALARY_HEADER = "Base Salary"
NOTES_HEADER = "Notes"
SHORTLIST_N = 5

_PENDING: dict[str, dict[str, Any]] = {}


def _load_payroll(path: Path) -> tuple[list[str], list[dict]]:
    """Return (header, rows). `_row` is the spreadsheet row number, not the index."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return [], []
        hdr = [str(h or "").strip() for h in rows[0]]
        out = []
        for i, row in enumerate(rows[1:], start=2):
            d = {hdr[j]: row[j] if j < len(row) else None for j in range(len(hdr))}
            d["_row"] = i
            out.append(d)
        return hdr, out
    finally:
        wb.close()


def _column_index(header: list[str], name: str) -> int:
    """1-based column for `name`. Raises rather than writing to a guessed column -
    a salary written into the wrong column is worse than a refused amend."""
    for i, h in enumerate(header, start=1):
        if h.strip().lower() == name.strip().lower():
            return i
    raise KeyError(f"column {name!r} not found in sheet header {header!r}")


def _save(pending: dict) -> dict:
    _PENDING[pending["token"]] = pending
    (OPS_DIR / f"{pending['token']}.json").write_text(
        json.dumps(pending, indent=2), encoding="utf-8"
    )
    return pending


def _load(token: str) -> dict | None:
    pending = _PENDING.get(token)
    if pending:
        return pending
    fp = OPS_DIR / f"{str(token or '').strip()}.json"
    if not fp.is_file():
        return None
    try:
        pending = json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None
    _PENDING[token] = pending
    return pending


def _match(rows: list[dict], ask: str) -> tuple[dict | None, str]:
    """Find a payroll row for `ask`. Returns (row, basis) where basis names what
    actually matched - 'emp_id', 'name', or 'none' when nothing did."""
    q = ask or ""
    m = re.search(r"\bE-?\s*(\d{1,5})\b", q, re.I)
    if m:
        eid = f"E-{int(m.group(1)):04d}"
        cand = next((r for r in rows if str(r.get("Emp ID") or "").upper() == eid), None)
        if cand:
            return cand, "emp_id"
    name_m = re.search(r"for\s+([A-Za-z][A-Za-z0-9 ]{1,40})", q, re.I)
    if name_m:
        needle = name_m.group(1).strip().lower()
        cand = next((r for r in rows if needle in str(r.get("Name") or "").lower()), None)
        if cand:
            return cand, "name"
    return None, "none"


def identify_employee(path: str | Path, ask: str, *, chain_id: str = "", prev_token: str = "") -> dict:
    """Propose a payroll row and ask 'is it that one?' - no mutate yet."""
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": "payroll file missing"}
    header, rows = _load_payroll(p)
    if not rows:
        return {"ok": False, "error": "payroll sheet has no data rows"}

    cand, basis = _match(rows, ask)
    if cand is None:
        # Nothing matched. Do not dress the first row up as a find (R-0011): say so,
        # and hand back a shortlist the founder can pick from by Emp ID.
        return {
            "ok": True,
            "phase": "identify",
            "status": "no_match",
            "match_basis": "none",
            "prompt": (
                f"No Emp ID or name in the sheet matches {ask!r}. I am not proposing a row - "
                f"re-ask with an Emp ID (for example 'salary raise for E-0012') or a name."
            ),
            "shortlist": [
                {"emp_id": r.get("Emp ID"), "name": r.get("Name"), "row": r.get("_row")}
                for r in rows[:SHORTLIST_N]
            ],
            "honesty": "Cortex-direct demo ops - no candidate proposed, nothing to confirm",
        }

    token = f"ops_{int(time.time() * 1000)}_{cand.get('_row')}"
    pending = {
        "token": token,
        "chain_id": chain_id or token,
        "prev_token": prev_token,
        "path": str(p.resolve()),
        "sheet": "Payroll_RAW",
        "header": header,
        "row": cand.get("_row"),
        "emp_id": cand.get("Emp ID"),
        "name": cand.get("Name"),
        "base_salary": cand.get(SALARY_HEADER),
        "ask": ask,
        "status": "awaiting_identity_confirm",
        "match_basis": basis,
        "prompt": (
            f"Is it that one? Emp {cand.get('Emp ID')} / {cand.get('Name')} / "
            f"salary {cand.get(SALARY_HEADER)} (row {cand.get('_row')}), matched on {basis}."
        ),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _save(pending)
    return {
        "ok": True,
        "phase": "identify",
        "pending": pending,
        "honesty": "Cortex-direct demo ops - confirm required before amend",
    }


def confirm_identity(token: str, yes: bool) -> dict:
    pending = _load(token)
    if not pending:
        return {"ok": False, "error": "unknown token"}
    if pending.get("status") != "awaiting_identity_confirm":
        return {"ok": False, "error": f"bad status {pending.get('status')}"}
    if not yes:
        pending["status"] = "rejected_identity"
        _save(pending)
        return {
            "ok": True,
            "phase": "identify",
            "status": "rejected",
            "next": "re-identify with Emp ID or name - no amend performed",
        }
    pending["status"] = "identity_confirmed"
    _save(pending)
    return {
        "ok": True,
        "phase": "identify",
        "status": "confirmed",
        "pending": pending,
        "next": "propose_amend with new salary or increment %",
    }


def propose_amend(
    token: str, *, new_salary: float | None = None, increment_pct: float | None = None
) -> dict:
    pending = _load(token)
    if not pending:
        return {"ok": False, "error": "unknown token"}
    if pending.get("status") != "identity_confirmed":
        return {"ok": False, "error": "confirm identity first (is it that one?)"}
    base = float(pending.get("base_salary") or 0)
    if increment_pct is not None:
        new_salary = round(base * (1 + float(increment_pct) / 100.0), 2)
    if new_salary is None:
        return {"ok": False, "error": "new_salary or increment_pct required"}
    pending["proposed_salary"] = float(new_salary)
    pending["increment_pct"] = float(increment_pct) if increment_pct is not None else None
    pending["status"] = "awaiting_amend_confirm"
    pending["amend_prompt"] = (
        f"Amend {pending.get('emp_id')} salary {base} -> {new_salary}? Confirm yes to write, no to abort."
    )
    _save(pending)
    return {"ok": True, "phase": "amend_propose", "pending": pending}


def confirm_amend(token: str, yes: bool) -> dict:
    pending = _load(token)
    if not pending:
        return {"ok": False, "error": "unknown token"}
    if pending.get("status") != "awaiting_amend_confirm":
        return {"ok": False, "error": "no pending amend"}
    if not yes:
        pending["status"] = "amend_aborted"
        _save(pending)
        return {"ok": True, "phase": "amend", "status": "aborted", "note": "file unchanged"}

    import openpyxl

    path = Path(pending["path"])
    wb = openpyxl.load_workbook(path)
    try:
        ws = wb[pending.get("sheet") or wb.sheetnames[0]]
        header = pending.get("header") or [
            str(c.value or "").strip() for c in next(ws.iter_rows(max_row=1))
        ]
        salary_col = _column_index(header, SALARY_HEADER)
        notes_col = _column_index(header, NOTES_HEADER)
        row = int(pending["row"])
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        ws.cell(row, salary_col).value = float(pending["proposed_salary"])
        ws.cell(row, notes_col).value = f"amended {stamp} (confirmed, token {pending['token']})"
        wb.save(path)
    finally:
        wb.close()
    pending["status"] = "amended"
    pending["amended_at"] = stamp
    pending["written_column"] = salary_col
    _save(pending)
    return {
        "ok": True,
        "phase": "amend",
        "status": "written",
        "pending": pending,
        "path": str(path),
        "next": "continue_loop for the next row - governance restarts, this token is spent",
    }


def continue_loop(token: str, *, ask: str = "", next_row: bool = False) -> dict:
    """Continue after a landed amend into a fresh pair of gates (OPS-DEMO-03).

    The spent token authorises nothing. Whatever comes next re-enters at identify,
    so the next cell still costs two explicit confirms.
    """
    prev = _load(token)
    if not prev:
        return {"ok": False, "error": "unknown token"}
    if prev.get("status") != "amended":
        return {
            "ok": False,
            "error": f"nothing to continue from - previous step is {prev.get('status')}, not amended",
        }

    chain_id = prev.get("chain_id") or prev["token"]
    if ask:
        out = identify_employee(prev["path"], ask, chain_id=chain_id, prev_token=prev["token"])
        out["continued_from"] = prev["token"]
        return out

    if not next_row:
        return {
            "ok": True,
            "phase": "continue",
            "status": "awaiting_next_action",
            "chain_id": chain_id,
            "last_amended": {
                "emp_id": prev.get("emp_id"),
                "row": prev.get("row"),
                "new_salary": prev.get("proposed_salary"),
            },
            "prompt": (
                f"Amended {prev.get('emp_id')} (row {prev.get('row')}). Next action? "
                f"Name another employee, ask for the next row, or stop."
            ),
            "options": ["ask:<employee>", "next_row", "stop"],
        }

    # next_row: propose the row after the one just amended, still as a proposal.
    header, rows = _load_payroll(Path(prev["path"]))
    nxt = next((r for r in rows if int(r.get("_row") or 0) > int(prev["row"])), None)
    if not nxt:
        return {
            "ok": True,
            "phase": "continue",
            "status": "end_of_sheet",
            "chain_id": chain_id,
            "prompt": "No row after the one just amended - the sheet ends here.",
        }
    out = identify_employee(
        prev["path"], f"salary raise for {nxt.get('Emp ID')}", chain_id=chain_id, prev_token=prev["token"]
    )
    out["continued_from"] = prev["token"]
    return out


def chain(token: str) -> dict:
    """Every step taken in the chain this token belongs to - the audit view."""
    pending = _load(token)
    if not pending:
        return {"ok": False, "error": "unknown token"}
    cid = pending.get("chain_id") or pending["token"]
    steps = []
    for fp in sorted(OPS_DIR.glob("ops_*.json")):
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (d.get("chain_id") or d.get("token")) != cid:
            continue
        steps.append(
            {
                "token": d.get("token"),
                "emp_id": d.get("emp_id"),
                "row": d.get("row"),
                "status": d.get("status"),
                "match_basis": d.get("match_basis"),
                "base_salary": d.get("base_salary"),
                "proposed_salary": d.get("proposed_salary"),
                "amended_at": d.get("amended_at"),
            }
        )
    steps.sort(key=lambda s: str(s.get("token")))
    return {
        "ok": True,
        "chain_id": cid,
        "steps": steps,
        "amended": [s for s in steps if s.get("status") == "amended"],
    }

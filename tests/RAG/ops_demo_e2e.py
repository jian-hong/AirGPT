"""OPS-DEMO-03 end-to-end: identify -> confirm -> amend -> continue (EPIC-D02).

Runs the governed loop against a scratch copy of the payroll fixture and asserts,
at every step, the thing the demo actually claims: that an unconfirmed amend does
not land. Each check reads the salary cell back out of the workbook, so a passing
run is evidence about the file, not about the return value (R-0001).

    python tests\\RAG\\ops_demo_e2e.py

Cortex-direct demo path - not OpenVault-gated. Writes only its own scratch copy and
tests/RAG/results/ops_demo_e2e_latest.json; no D01 score artifact is touched.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag import ops_amend  # noqa: E402

FIXTURE = ROOT / "tests" / "RAG" / "messy" / "ops" / "messy_payroll_ops.xlsx"
RESULTS = ROOT / "tests" / "RAG" / "results"
SCRATCH = RESULTS / "ops" / "e2e_payroll_copy.xlsx"

STEPS: list[dict] = []


class Failed(Exception):
    pass


def check(name: str, ok: bool, detail: str = "") -> None:
    STEPS.append({"step": name, "ok": bool(ok), "detail": detail})
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{(' - ' + detail) if detail else ''}", flush=True)
    if not ok:
        raise Failed(name)


def salary_at(path: Path, row: int) -> float | None:
    """Read the salary cell straight from the workbook - no ops_amend code involved."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        ws = wb["Payroll_RAW"]
        header = [str(c.value or "").strip() for c in next(ws.iter_rows(max_row=1))]
        col = header.index(ops_amend.SALARY_HEADER) + 1
        v = ws.cell(row, col).value
        return float(v) if v is not None else None
    finally:
        wb.close()


def notes_at(path: Path, row: int) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        ws = wb["Payroll_RAW"]
        header = [str(c.value or "").strip() for c in next(ws.iter_rows(max_row=1))]
        col = header.index(ops_amend.NOTES_HEADER) + 1
        return str(ws.cell(row, col).value or "")
    finally:
        wb.close()


def main() -> int:
    if not FIXTURE.is_file():
        print(f"fixture missing: {FIXTURE}")
        print("run: python tests\\RAG\\gen_messy_fixtures.py --target-mb 120")
        return 2

    SCRATCH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FIXTURE, SCRATCH)
    print(f"scratch copy: {SCRATCH}\n")

    # --- 1. an ask that matches nothing must not produce a candidate -------------
    print("1) unmatched ask")
    out = ops_amend.identify_employee(SCRATCH, "give the intern a raise")
    check("no_match status", out.get("status") == "no_match", str(out.get("status")))
    check("no token issued", "token" not in out and not out.get("pending"))
    check("says it is not proposing a row", "not proposing" in str(out.get("prompt", "")).lower())

    # --- 2. reject the identity: nothing may change ------------------------------
    print("\n2) identify then reject")
    out = ops_amend.identify_employee(SCRATCH, "salary raise for E-0012")
    check("identified", out.get("ok") is True)
    p = out["pending"]
    tok_rejected, row = p["token"], int(p["row"])
    before = salary_at(SCRATCH, row)
    check("matched on emp_id, not a guess", p.get("match_basis") == "emp_id", str(p.get("match_basis")))
    r = ops_amend.confirm_identity(tok_rejected, False)
    check("rejection accepted", r.get("status") == "rejected")
    check("file unchanged after reject", salary_at(SCRATCH, row) == before, f"salary still {before}")

    # --- 3. off-rails: skipping a gate must be refused ---------------------------
    print("\n3) off-rails attempts")
    out = ops_amend.identify_employee(SCRATCH, "salary raise for E-0012")
    tok = out["pending"]["token"]
    r = ops_amend.propose_amend(tok, increment_pct=8)
    check("propose before identity confirm refused", r.get("ok") is False, str(r.get("error")))
    r = ops_amend.confirm_amend(tok, True)
    check("confirm-amend with no proposal refused", r.get("ok") is False, str(r.get("error")))
    r = ops_amend.confirm_amend("ops_does_not_exist", True)
    check("unknown token refused", r.get("ok") is False, str(r.get("error")))
    check("file unchanged after off-rails", salary_at(SCRATCH, row) == before, f"salary still {before}")

    # --- 4. abort at the amend gate: still nothing --------------------------------
    print("\n4) confirm identity, then abort the amend")
    check("identity confirmed", ops_amend.confirm_identity(tok, True).get("status") == "confirmed")
    r = ops_amend.propose_amend(tok, increment_pct=8)
    check("amend proposed", r.get("ok") is True)
    proposed = r["pending"]["proposed_salary"]
    check("proposal is +8%", abs(proposed - round(before * 1.08, 2)) < 0.011, f"{before} -> {proposed}")
    r = ops_amend.confirm_amend(tok, False)
    check("abort accepted", r.get("status") == "aborted")
    check("file unchanged after abort", salary_at(SCRATCH, row) == before, f"salary still {before}")

    # --- 5. the confirmed write: exactly one cell, with a stamp -------------------
    print("\n5) confirmed write lands")
    check("re-confirm identity", ops_amend.confirm_identity(tok, True).get("ok") is False,
          "token spent by abort - a new cycle is required")
    out = ops_amend.identify_employee(SCRATCH, "salary raise for E-0012")
    tok = out["pending"]["token"]
    ops_amend.confirm_identity(tok, True)
    r = ops_amend.propose_amend(tok, increment_pct=8)
    proposed = r["pending"]["proposed_salary"]
    r = ops_amend.confirm_amend(tok, True)
    check("write reported", r.get("status") == "written")
    after = salary_at(SCRATCH, row)
    check("salary is the proposed value", after == proposed, f"{before} -> {after}")
    check("audit stamp written", "amended" in notes_at(SCRATCH, row) and tok in notes_at(SCRATCH, row),
          notes_at(SCRATCH, row))
    neighbour = row + 1
    check("neighbour row untouched", salary_at(SCRATCH, neighbour) == salary_at(FIXTURE, neighbour))
    first_token, first_row = tok, row

    # --- 6. continue: the loop goes on, the authorisation does not ---------------
    print("\n6) continue the loop")
    r = ops_amend.continue_loop(tok)
    check("asks for the next action", r.get("status") == "awaiting_next_action", str(r.get("prompt")))
    r = ops_amend.continue_loop(tok, next_row=True)
    check("next row proposed", r.get("ok") is True and r.get("pending"))
    tok2 = r["pending"]["token"]
    row2 = int(r["pending"]["row"])
    before2 = salary_at(SCRATCH, row2)
    check("chained to the first cycle", r["pending"].get("chain_id") == first_token)
    check("new token is not pre-authorised",
          ops_amend.confirm_amend(tok2, True).get("ok") is False,
          "governance restarts at identify")
    check("second row unchanged so far", salary_at(SCRATCH, row2) == before2)

    ops_amend.confirm_identity(tok2, True)
    ops_amend.propose_amend(tok2, increment_pct=8)
    r = ops_amend.confirm_amend(tok2, True)
    check("second write lands", r.get("status") == "written")
    check("second salary is +8%", salary_at(SCRATCH, row2) == round(before2 * 1.08, 2),
          f"{before2} -> {salary_at(SCRATCH, row2)}")

    r = ops_amend.continue_loop(tok2, ask="salary raise for E-0500")
    check("continue by name/id starts a fresh identify",
          r.get("pending", {}).get("status") == "awaiting_identity_confirm")
    check("third cycle still needs both gates",
          ops_amend.propose_amend(r["pending"]["token"], increment_pct=8).get("ok") is False)

    # --- 7. the audit chain -------------------------------------------------------
    print("\n7) audit chain")
    ch = ops_amend.chain(tok2)
    check("chain resolves", ch.get("ok") is True)
    check("exactly two writes in this chain", len(ch.get("amended") or []) == 2,
          f"{len(ch.get('amended') or [])} amended of {len(ch.get('steps') or [])} steps")
    return 0


if __name__ == "__main__":
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        rc = main()
        ok = rc == 0
    except Failed as e:
        print(f"\nFAILED at: {e}")
        ok = False
        rc = 1
    except Exception as e:  # a crash is a failure, never a skip (R-0002)
        print(f"\nERROR: {type(e).__name__}: {e}")
        STEPS.append({"step": "unhandled", "ok": False, "detail": f"{type(e).__name__}: {e}"})
        ok = False
        rc = 1

    RESULTS.mkdir(parents=True, exist_ok=True)
    artifact = RESULTS / "ops_demo_e2e_latest.json"
    artifact.write_text(
        json.dumps(
            {
                "ok": ok,
                "epic": "EPIC-D02",
                "tickets": [17, 18, 19],
                "honesty": "Cortex-direct demo ops - not OpenVault-gated",
                "fixture": str(FIXTURE),
                "scratch": str(SCRATCH),
                "started": started,
                "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "passed": sum(1 for s in STEPS if s["ok"]),
                "total": len(STEPS),
                "steps": STEPS,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n{sum(1 for s in STEPS if s['ok'])}/{len(STEPS)} checks passed -> {artifact}")
    sys.exit(rc)

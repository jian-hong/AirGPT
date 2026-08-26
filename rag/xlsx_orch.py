"""AirGPT half of F15 / EPIC-D04: identify a workbook and emit a Copilot pack.

AirGPT locates an ingested xlsx and drafts a structured Excel Copilot prompt
pack. DMS owns cross-check. Pointer owns paste. AirGPT does not drive Copilot,
does not paste, and does not become a second orchestrator (P3 superseded).

Handoff consume is a posted durable path (DMS XLSX-ORCH-11 when that wire
exists). Until then status is ``awaiting_dms_receipt`` — visible, not silent
(R-0011). Reveal reuses ``rag.reveal`` (#14).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from config import DATA_DIR

PACK_DIR = DATA_DIR / "rag" / "xlsx_orch"
XLSX_SUFFIXES = {".xlsx", ".xlsm"}
HONESTY = (
    "AirGPT candidate pack only. DMS owns governed cross-check. "
    "Pointer owns Excel Copilot paste. AirGPT does not run Copilot or MCP paste."
)
HANDOFF_HONESTY = (
    "No DMS receipt wire in this repo. Status stays awaiting_dms_receipt until "
    "a durable result path is posted (DMS XLSX-ORCH-11). Reveal uses rag/reveal."
)

# Result workbook families from F15 / XLSX-ORCH-02. Names may vary slightly.
RESULT_SHEET_FAMILIES: dict[str, tuple[str, ...]] = {
    "cover": ("cover",),
    "ontime_export": ("ontime export", "on-time export", "ontime_export", "on time export"),
    "analysis": ("analysis", "ontime analysis", "on-time analysis", "on time analysis"),
    "chart": ("presentation chart", "ppt chart", "chart"),
}

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)
_STOP = frozenset(
    {
        "the", "a", "an", "for", "and", "of", "to", "on", "in", "with", "all",
        "by", "as", "or", "is", "it", "be", "at", "from", "that", "this",
        "true", "false", "xlsx", "file", "sheet",
    }
)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if t.lower() not in _STOP and len(t) > 1}


def _meta(src: dict) -> dict:
    m = src.get("meta") or {}
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except Exception:
            m = {}
    return m if isinstance(m, dict) else {}


def _openable_path(src: dict) -> str:
    """Prefer Docs original, then host path — same order as rag.reveal."""
    meta = _meta(src)
    for raw in (meta.get("docs_path"), src.get("path"), meta.get("original_path")):
        cand = str(raw or "").strip()
        if not cand:
            continue
        p = Path(cand).expanduser()
        if p.is_absolute() and p.is_file() and p.suffix.lower() in XLSX_SUFFIXES:
            return str(p)
    return ""


def _basename(src: dict) -> str:
    meta = _meta(src)
    for raw in (src.get("title"), meta.get("original_path"), src.get("path"), _openable_path(src)):
        name = Path(str(raw or "")).name
        if name:
            return name
    return ""


def _is_xlsx_source(src: dict) -> bool:
    name = _basename(src).lower()
    path = str(src.get("path") or "").lower()
    if name.endswith((".xlsx", ".xlsm")) or path.endswith((".xlsx", ".xlsm")):
        return True
    return bool(_openable_path(src))


def schema_snapshot(path: str | Path) -> dict[str, Any]:
    """Sheet names + headers via the production xlsx loader (banner-aware)."""
    from rag.xlsx_sql import load_sheets

    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": f"not found: {p}", "sheets": []}
    try:
        sheets = load_sheets(p)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "sheets": []}
    out = []
    for name, df in sheets.items():
        cols = [str(c) for c in df.columns]
        out.append(
            {
                "name": name,
                "columns": cols,
                "n_rows": int(len(df)),
                "header_excel_row": int(df.attrs.get("header_excel_row") or 1),
            }
        )
    return {"ok": True, "path": str(p), "sheets": out}


def _col_blob(snap: dict) -> str:
    parts = []
    for sh in snap.get("sheets") or []:
        parts.append(str(sh.get("name") or ""))
        parts.extend(str(c) for c in (sh.get("columns") or []))
    return " ".join(parts).lower()


def _pick_sheet_for_filter(snap: dict) -> dict | None:
    """Prefer a body sheet that actually has OnTime/cost — not Summary theater."""
    sheets = list(snap.get("sheets") or [])
    if not sheets:
        return None

    def score(sh: dict) -> int:
        name = str(sh.get("name") or "").lower()
        cols = " ".join(str(c).lower() for c in (sh.get("columns") or []))
        s = 0
        if re.search(r"ontime|on_time|on-time", cols):
            s += 8
        if re.search(r"cost|spend|amount|rate", cols):
            s += 4
        if re.search(r"region|carrier|lane", cols + " " + name):
            s += 2
        if re.search(r"summary|kpi|dashboard|cover", name):
            s -= 6
        s += min(3, int(sh.get("n_rows") or 0) // 500)
        return s

    ranked = sorted(sheets, key=score, reverse=True)
    return ranked[0] if ranked else None


def _find_col(columns: list[str], *pats: str) -> str | None:
    for pat in pats:
        for c in columns:
            if re.search(pat, str(c), re.I):
                return str(c)
    return None


def _score_source(src: dict, ask: str, snap: dict | None) -> int:
    ask_l = (ask or "").lower()
    ask_toks = _tokens(ask)
    name = _basename(src)
    name_toks = _tokens(name.replace("_", " ").replace("-", " "))
    score = 0
    overlap = ask_toks & name_toks
    score += 4 * len(overlap)
    if "frtr" in name.lower() and ("frtr" in ask_l or "supply" in ask_l or "ontime" in ask_l):
        score += 6
    if "00027" in name.lower() and "00027" in ask_l:
        score += 8
    if re.search(r"supply.?chain|regional", name, re.I) and re.search(r"supply|region|ontime", ask_l):
        score += 5

    blob = _col_blob(snap) if snap and snap.get("ok") else ""
    if re.search(r"ontime|on.time", ask_l):
        if re.search(r"ontime|on_time|on-time", blob):
            score += 12
        else:
            score -= 8
    if re.search(r"cost|average|avg", ask_l) and re.search(r"cost|spend|amount|rate", blob):
        score += 4
    if re.search(r"salary|payroll|emp", name, re.I) and not re.search(r"salary|payroll|emp", ask_l):
        score -= 10
    return score


def _inventory(space_id: int | None, path: str, sources: list[dict] | None) -> list[dict]:
    rows: list[dict] = []
    if sources:
        rows = list(sources)
    elif space_id is not None:
        from rag import store as rag_store

        rows = rag_store.list_sources(int(space_id))
    elif path:
        p = Path(path)
        rows = [{"path": str(p), "title": p.name, "meta": {}}]
    return [s for s in rows if _is_xlsx_source(s)]


def identify_workbook(
    *,
    ask: str,
    space_id: int | None = None,
    path: str = "",
    sources: list[dict] | None = None,
) -> dict:
    """Locate the ingested xlsx for a multi-part Copilot ask. No mutate."""
    ask = (ask or "").strip()
    if not ask:
        return {"ok": False, "error": "ask required"}

    inventory = _inventory(space_id, path, sources)
    if not inventory:
        return {
            "ok": True,
            "status": "no_match",
            "prompt": "No xlsx sources in this space to identify.",
            "candidates": [],
            "honesty": HONESTY,
        }

    scored = []
    for src in inventory:
        openable = _openable_path(src) or (str(src.get("path") or "") if Path(str(src.get("path") or "")).is_file() else "")
        snap = schema_snapshot(openable) if openable else {"ok": False, "sheets": []}
        scored.append(
            {
                "source_id": src.get("id"),
                "title": _basename(src),
                "path": openable or str(src.get("path") or ""),
                "score": _score_source(src, ask, snap),
                "schema": snap if snap.get("ok") else {"ok": False, "sheets": []},
            }
        )
    scored.sort(key=lambda r: int(r["score"]), reverse=True)
    top = scored[0]
    runner_up = scored[1] if len(scored) > 1 else None

    if int(top["score"]) <= 0:
        return {
            "ok": True,
            "status": "no_match",
            "match_basis": "none",
            "prompt": (
                f"No ingested xlsx looks like a match for {ask!r}. "
                "I am not proposing a workbook — name the file or ingest it first."
            ),
            "candidates": [
                {"title": r["title"], "path": r["path"], "score": r["score"]}
                for r in scored[:5]
            ],
            "honesty": HONESTY,
        }

    if runner_up and int(top["score"]) - int(runner_up["score"]) < 3:
        return {
            "ok": True,
            "status": "ambiguous",
            "match_basis": "tie",
            "prompt": (
                f"Two workbooks score too close for {ask!r}: "
                f"{top['title']} ({top['score']}) vs {runner_up['title']} ({runner_up['score']}). "
                "Name the file. I will not silently pick one."
            ),
            "candidates": [
                {"title": r["title"], "path": r["path"], "score": r["score"]}
                for r in scored[:5]
            ],
            "honesty": HONESTY,
        }

    return {
        "ok": True,
        "status": "identified",
        "match_basis": "schema_and_name" if (top["schema"] or {}).get("sheets") else "name",
        "workbook": {
            "source_id": top["source_id"],
            "title": top["title"],
            "path": top["path"],
            "score": top["score"],
            "schema": top["schema"],
        },
        "candidates": [
            {"title": r["title"], "path": r["path"], "score": r["score"]}
            for r in scored[:5]
        ],
        "ask": ask,
        "honesty": HONESTY,
    }


def build_prompt_pack(*, ask: str, workbook: dict) -> dict:
    """Schema-aware Copilot pack: OnTime filter → AVERAGEIF/FILTER → export → chart."""
    snap = workbook.get("schema") or {}
    if not snap.get("ok"):
        path = workbook.get("path") or ""
        if path:
            snap = schema_snapshot(path)
    sheet = _pick_sheet_for_filter(snap) or {}
    cols = [str(c) for c in (sheet.get("columns") or [])]
    ontime_col = _find_col(cols, r"ontime|on_time|on-time")
    cost_col = _find_col(cols, r"unit.?cost|^cost$|spend|amount", r"baserate|base_rate")
    region_col = _find_col(cols, r"region|lane|corridor")
    carrier_col = _find_col(cols, r"carrier|vendor")
    src_sheet = str(sheet.get("name") or "the fact sheet")
    n_rows = int(sheet.get("n_rows") or 0)
    title = workbook.get("title") or Path(str(workbook.get("path") or "workbook")).name
    ontime = ontime_col or "OnTime"
    cost = cost_col or "Cost"
    region = region_col or "Region"

    steps = [
        {
            "n": 1,
            "sheet": "Cover",
            "intent": (
                f"Create a Cover sheet that names the ask, the source workbook {title!r}, "
                f"source sheet {src_sheet!r} ({n_rows} data rows), the filter {ontime}=TRUE, "
                "and the three deliverables: OnTime Export, Analysis, Presentation Chart. "
                "Do not invent KPIs on Cover — Cover is provenance, not a Summary dump."
            ),
            "formula_hint": "No aggregate on Cover. List source sheet, filter, and output sheet names as text.",
        },
        {
            "n": 2,
            "sheet": "OnTime Export",
            "intent": (
                f"On a new sheet OnTime Export, spill every {src_sheet} row where {ontime} is TRUE "
                "(boolean true / TRUE / 1). Keep the original columns. This is the export the founder "
                "can save as a separate xlsx — not a filtered view of Summary."
            ),
            "formula_hint": (
                f"=FILTER('{src_sheet}'!A:Z,'{src_sheet}'!{ontime_col or ontime}=TRUE) "
                f"or equivalent Advanced Filter / Power Query. Then File > Save a Copy of this sheet."
            ),
        },
        {
            "n": 3,
            "sheet": "Analysis",
            "intent": (
                f"On Analysis, compute the average {cost} over the OnTime=TRUE set only. "
                "State the OnTime count vs total row count. "
                + (f"Optional region breakdown of the same average by {region}. " if region_col else "")
                + "Use AVERAGEIF or AVERAGE of the FILTER spill — do not average the Summary sheet."
            ),
            "formula_hint": (
                f"=AVERAGEIF('{src_sheet}'!{ontime_col or ontime},TRUE,'{src_sheet}'!{cost_col or cost}) "
                f"and =AVERAGE(FILTER('{src_sheet}'!{cost_col or cost},'{src_sheet}'!{ontime_col or ontime}=TRUE)). "
                f"Count: =COUNTIF('{src_sheet}'!{ontime_col or ontime},TRUE) / total rows on {src_sheet}."
            ),
        },
        {
            "n": 4,
            "sheet": "Presentation Chart",
            "intent": (
                "On Presentation Chart, add a chart suitable for a PPT slide of the OnTime analysis "
                + (f"(average {cost} by {region} if that column exists, otherwise OnTime vs not-OnTime average {cost}). " )
                + "Title the chart from the Analysis figures. Do not chart the unfiltered Summary."
            ),
            "formula_hint": (
                f"Pivot or a small two-column range from Analysis ({region} / average {cost}), "
                "then Insert > Chart (column or bar). Copy the chart for PPT."
            ),
        },
    ]

    return {
        "ok": True,
        "ask": ask,
        "workbook": {
            "title": title,
            "path": workbook.get("path"),
            "source_id": workbook.get("source_id"),
            "source_sheet": src_sheet,
            "ontime_col": ontime_col,
            "cost_col": cost_col,
            "region_col": region_col,
            "carrier_col": carrier_col,
            "n_rows": n_rows,
        },
        "steps": steps,
        "expected_result_sheets": ["Cover", "OnTime Export", "Analysis", "Presentation Chart"],
        "paste_owner": "pointer",
        "cross_check_owner": "dms",
        "airgpt_role": "candidate_pack_only",
        "not_doing": [
            "pointer_paste",
            "excel_copilot_drive",
            "mcp_user_excel_primary",
            "in_airgpt_chart_orchestrator",
        ],
        "honesty": HONESTY,
    }


def identify_and_pack(
    *,
    ask: str,
    space_id: int | None = None,
    path: str = "",
    sources: list[dict] | None = None,
) -> dict:
    identified = identify_workbook(ask=ask, space_id=space_id, path=path, sources=sources)
    if not identified.get("ok"):
        return identified
    if identified.get("status") != "identified":
        identified["pack"] = None
        return identified
    pack = build_prompt_pack(ask=ask, workbook=identified["workbook"])
    rec = save_pack(pack)
    identified["pack"] = pack
    identified["pack_id"] = rec["pack_id"]
    identified["handoff"] = {
        "status": "awaiting_dms_receipt",
        "pack_id": rec["pack_id"],
        "honesty": HANDOFF_HONESTY,
    }
    return identified


def _ensure_dir() -> Path:
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    return PACK_DIR


def save_pack(pack: dict) -> dict:
    _ensure_dir()
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str((pack.get("workbook") or {}).get("title") or "wb"))[:40]
    pack_id = f"orch_{int(time.time() * 1000)}_{slug.strip('_') or 'wb'}"
    rec = {
        "pack_id": pack_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "awaiting_dms_receipt",
        "pack": pack,
        "result_path": None,
        "result_sheets": None,
        "honesty": HANDOFF_HONESTY,
    }
    (PACK_DIR / f"{pack_id}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def load_pack(pack_id: str) -> dict | None:
    fp = _ensure_dir() / f"{str(pack_id or '').strip()}.json"
    if not fp.is_file():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_rec(rec: dict) -> dict:
    _ensure_dir()
    (PACK_DIR / f"{rec['pack_id']}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def inspect_result_workbook(path: str | Path) -> dict:
    """Check Cover / OnTime Export / Analysis / Presentation Chart families."""
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": f"not found: {p}", "path": str(p), "families": {}}
    try:
        import openpyxl

        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        try:
            names = list(wb.sheetnames)
        finally:
            wb.close()
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "path": str(p), "families": {}}

    lowered = [(n, n.strip().lower()) for n in names]
    families = {}
    for fam, aliases in RESULT_SHEET_FAMILIES.items():
        hit = next((orig for orig, low in lowered if any(a in low for a in aliases)), None)
        families[fam] = hit
    missing = [fam for fam, hit in families.items() if not hit]
    return {
        "ok": not missing,
        "path": str(p.resolve()),
        "sheetnames": names,
        "families": families,
        "missing": missing,
        "error": None if not missing else f"missing sheet families: {missing}",
    }


def consume_result(*, pack_id: str = "", result_path: str = "") -> dict:
    """Accept a DMS-returned (or locally posted) durable path. Do not invent one."""
    rec = load_pack(pack_id) if pack_id else None
    path = (result_path or "").strip()
    if rec and not path:
        return {
            "ok": True,
            "pack_id": rec["pack_id"],
            "status": rec.get("status") or "awaiting_dms_receipt",
            "result_path": rec.get("result_path"),
            "result_sheets": rec.get("result_sheets"),
            "honesty": HANDOFF_HONESTY,
            "pack": rec.get("pack"),
        }
    if not path:
        return {
            "ok": True,
            "status": "awaiting_dms_receipt",
            "result_path": None,
            "honesty": HANDOFF_HONESTY,
        }
    inspected = inspect_result_workbook(path)
    if rec is None:
        rec = {
            "pack_id": pack_id or f"orch_posted_{int(time.time() * 1000)}",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "pack": None,
            "honesty": HANDOFF_HONESTY,
        }
    rec["result_path"] = inspected.get("path")
    rec["result_sheets"] = inspected
    rec["status"] = "received" if inspected.get("ok") else "received_incomplete_sheets"
    rec["honesty"] = HANDOFF_HONESTY
    _save_rec(rec)
    out = {
        "ok": True,
        "pack_id": rec["pack_id"],
        "status": rec["status"],
        "result_path": rec["result_path"],
        "result_sheets": inspected,
        "honesty": HANDOFF_HONESTY,
    }
    if not inspected.get("ok"):
        out["warning"] = inspected.get("error")
    return out


def reveal_handoff(*, pack_id: str = "", path: str = "", which: str = "result") -> dict:
    """Reveal the result workbook, or the identified source. Fails closed."""
    from rag import reveal as rag_reveal

    target = (path or "").strip()
    rec = load_pack(pack_id) if pack_id else None
    if not target and rec:
        if which == "source":
            target = str(((rec.get("pack") or {}).get("workbook") or {}).get("path") or "")
        else:
            target = str(rec.get("result_path") or "")
            if not target:
                return {
                    "ok": False,
                    "error": "No DMS result path yet — still awaiting_dms_receipt.",
                    "status": rec.get("status") or "awaiting_dms_receipt",
                    "honesty": HANDOFF_HONESTY,
                }
    if not target:
        return {"ok": False, "error": "path required", "honesty": HANDOFF_HONESTY}
    out = rag_reveal.reveal_path(target)
    out["honesty"] = HONESTY
    out["which"] = which
    if rec:
        out["pack_id"] = rec.get("pack_id")
        out["status"] = rec.get("status")
    return out

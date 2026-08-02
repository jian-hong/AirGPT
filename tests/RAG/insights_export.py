"""Insights retrieval + derivation, CSV/SQL export, audit traceback, Excel free-route.

Honesty: Cortex-direct, not OpenVault-gated.
No AI chart-governance pipeline (P3 parked) — graph types are suggested prompts only.
Excel MCP is optional; openpyxl is the free route when MCP/API is down.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
RESULTS = ROOT / "results"
WH = ROOT / "warehouse"
OUT = RESULTS / "exports"
HONESTY = "Cortex-direct, not OpenVault-gated (EPIC-D01)."


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def retrieve_top_skus(n: int = 5, exclude: list[str] | None = None) -> dict:
    """Insights source of truth: pandas SQL over wh_01 Sales sheet (same as hybrid_max)."""
    import sys

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from frtr_sql_baseline import _fmt_top, _top_skus_by_revenue, load_sheets

    path = WH / "wh_01_sales_core.xlsx"
    sheets = load_sheets(path)
    pairs = _top_skus_by_revenue(sheets, n=n, exclude=exclude) or []
    return {
        "source_file": str(path),
        "source_sheet": "Sales",
        "lane": "sql",
        "n": n,
        "exclude": exclude or [],
        "rows": [{"rank": i + 1, "sku": s, "sales_value_myr": round(v, 2)} for i, (s, v) in enumerate(pairs)],
        "text": _fmt_top(pairs) if pairs else "",
        "sql": sql_codegen_top_n(n, exclude=exclude),
    }


def sql_codegen_top_n(n: int = 5, exclude: list[str] | None = None) -> str:
    excl = exclude or []
    where = ""
    if excl:
        quoted = ", ".join("'" + s.replace("'", "''") + "'" for s in excl)
        where = f"\nWHERE sku NOT IN ({quoted})"
    return (
        f"-- certified query cq_sales_top{n}_value (AirGPT hybrid_max / free route)\n"
        f"SELECT sku, ROUND(SUM(sales_value_myr), 2) AS sales_value_myr\n"
        f"FROM Sales{where}\n"
        f"GROUP BY sku\n"
        f"ORDER BY sales_value_myr DESC\n"
        f"LIMIT {int(n)};"
    )


def derive_insights(
    *,
    top: dict,
    score_payload: dict | None = None,
) -> list[dict[str, str]]:
    """Derive short grounded insights from Top-N retrieval + scoreboard rows."""
    rows = top.get("rows") or []
    insights: list[dict[str, str]] = []
    if not rows:
        insights.append(
            {
                "id": "empty",
                "insight": "No Top-N rows retrieved from Sales — check workbook ingest.",
                "basis": "retrieve_top_skus",
            }
        )
        return insights

    total = sum(float(r["sales_value_myr"]) for r in rows)
    top1 = rows[0]
    share = (float(top1["sales_value_myr"]) / total * 100.0) if total else 0.0
    insights.append(
        {
            "id": "concentration",
            "insight": (
                f"{top1['sku']} leads at MYR {top1['sales_value_myr']:,.2f} "
                f"({share:.1f}% of Top-{len(rows)} revenue)."
            ),
            "basis": f"{top['source_file']}::{top['source_sheet']}",
        }
    )
    if len(rows) >= 2:
        gap = float(rows[0]["sales_value_myr"]) - float(rows[1]["sales_value_myr"])
        insights.append(
            {
                "id": "gap_1_2",
                "insight": (
                    f"Gap vs #2 ({rows[1]['sku']}) is MYR {gap:,.2f} - "
                    f"{'wide' if gap > 100000 else 'moderate'} lead."
                ),
                "basis": "Sales aggregate",
            }
        )

    # Exclude impact (derive, no confirm UI)
    excl = retrieve_top_skus(5, exclude=[top1["sku"]])
    if excl.get("rows"):
        insights.append(
            {
                "id": "exclude_first",
                "insight": (
                    f"If {top1['sku']} is excluded, next Top-5 starts with "
                    f"{excl['rows'][0]['sku']} at MYR {excl['rows'][0]['sales_value_myr']:,.2f}."
                ),
                "basis": "sql exclude act-once",
            }
        )

    if score_payload:
        s = score_payload.get("summary") or {}
        insights.append(
            {
                "id": "bench_accuracy",
                "insight": (
                    f"Bench {s.get('variant')}: {s.get('correct')}/{s.get('n')} "
                    f"(acc={s.get('accuracy')}) on space {s.get('space_id')}."
                ),
                "basis": "warehouse_hybrid_latest.json",
            }
        )
        lanes = {}
        for r in score_payload.get("rows") or []:
            lanes[r.get("lane") or "?"] = lanes.get(r.get("lane") or "?", 0) + 1
        insights.append(
            {
                "id": "lane_mix",
                "insight": "Lane mix: " + ", ".join(f"{k}={v}" for k, v in sorted(lanes.items())),
                "basis": "score rows",
            }
        )
        misses = [r for r in score_payload.get("rows") or [] if not r.get("correct")]
        if misses:
            insights.append(
                {
                    "id": "misses",
                    "insight": "Misses: " + "; ".join(f"q{m.get('qid')}:{m.get('question')[:60]}" for m in misses[:5]),
                    "basis": "score misses",
                }
            )
        else:
            insights.append(
                {
                    "id": "misses",
                    "insight": "No misses on latest warehouse hybrid_max run.",
                    "basis": "score misses",
                }
            )

    insights.append(
        {
            "id": "honesty",
            "insight": HONESTY + " Insights come from SQL-over-xlsx + retained scores, not OpenVault.",
            "basis": "demo policy",
        }
    )
    return insights


def prompt_pack(*, file_type: str = "xlsx", graph_type: str = "bar") -> dict[str, list[str]]:
    """Suggested prompts only (no auto chart pipeline)."""
    ft = (file_type or "xlsx").lower()
    gt = (graph_type or "bar").lower()
    return {
        "file_type_prompts": [
            f"Export Top 5 SKU revenue as {ft} with columns rank,sku,sales_value_myr.",
            f"Save audit traceback beside the {ft} export for the same ask.",
            f"Open {ft} Insights sheet and list concentration + exclude-first notes.",
        ],
        "graph_type_prompts": [
            f"In Excel, chart Top 5 sales_value_myr as a {gt} chart titled Top SKUs by revenue.",
            f"Use a {gt} chart for Top 6; label SKU on category axis.",
            f"After excluding SKU-00397, redraw the {gt} chart for the new Top 5.",
        ],
        "insights_prompts": [
            "Where do insights come from for Top 5 selling SKUs by revenue?",
            "Derive concentration share of #1 within Top 5.",
            "What changes if we exclude the first SKU once (no confirm loop)?",
            "Summarize warehouse hybrid_max accuracy and lane mix.",
            "Generate SQL for Top 5 sales and export CSV.",
        ],
        "note": "Graph prompts are for human/Excel Copilot — AirGPT does not auto-govern charts (P3 parked).",
    }


def build_audit(
    *,
    ask: str,
    top: dict,
    insights: list[dict],
    route: str,
    mcp: dict | None = None,
    error: str | None = None,
) -> dict:
    steps = [
        {"step": 1, "op": "load_workbook", "detail": top.get("source_file")},
        {"step": 2, "op": "sql_codegen", "detail": top.get("sql")},
        {"step": 3, "op": "aggregate_rank", "detail": f"n={top.get('n')} exclude={top.get('exclude')}"},
        {"step": 4, "op": "derive_insights", "detail": f"{len(insights)} insights"},
        {"step": 5, "op": "export_route", "detail": route},
    ]
    if mcp is not None:
        steps.append({"step": 6, "op": "excel_mcp_probe", "detail": mcp})
    return {
        "ok": error is None,
        "honesty": HONESTY,
        "ask": ask,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "lane": top.get("lane"),
        "source": {"file": top.get("source_file"), "sheet": top.get("source_sheet")},
        "result_preview": top.get("text"),
        "steps": steps,
        "error": error,
        "traceback": traceback.format_exc() if error else None,
    }


def export_csv(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["rank", "sku", "sales_value_myr"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    return path


def export_excel_free(
    path: Path,
    *,
    top: dict,
    insights: list[dict],
    audit: dict,
    prompts: dict,
    score_payload: dict | None,
) -> Path:
    import openpyxl
    from openpyxl.styles import Font

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = "TopN"
    ws.append(["rank", "sku", "sales_value_myr"])
    for r in top.get("rows") or []:
        ws.append([r["rank"], r["sku"], r["sales_value_myr"]])
    for c in ws[1]:
        c.font = Font(bold=True)

    wi = wb.create_sheet("Insights")
    wi.append(["id", "insight", "basis"])
    for row in insights:
        wi.append([row.get("id"), row.get("insight") or row.get("severity"), row.get("basis")])
    for c in wi[1]:
        c.font = Font(bold=True)

    wa = wb.create_sheet("Audit")
    wa.append(["key", "value"])
    for k in ("ok", "honesty", "ask", "ts", "lane"):
        wa.append([k, audit.get(k)])
    wa.append(["source_file", (audit.get("source") or {}).get("file")])
    wa.append(["source_sheet", (audit.get("source") or {}).get("sheet")])
    wa.append([])
    wa.append(["step", "op", "detail"])
    for s in audit.get("steps") or []:
        detail = s.get("detail")
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail)[:500]
        wa.append([s.get("step"), s.get("op"), detail])

    wsql = wb.create_sheet("SQL")
    wsql.append(["certified_sql"])
    for line in str(top.get("sql") or "").splitlines():
        wsql.append([line])

    wp = wb.create_sheet("Prompts")
    wp.append(["bucket", "prompt"])
    for bucket, items in prompts.items():
        if bucket == "note":
            wp.append(["note", items])
            continue
        for p in items or []:
            wp.append([bucket, p])

    if score_payload:
        ws2 = wb.create_sheet("Bench")
        s = score_payload.get("summary") or {}
        ws2.append(["key", "value"])
        for k, v in s.items():
            ws2.append([k, v])
        ws2.append([])
        ws2.append(["qid", "question", "correct", "lane", "ms"])
        for r in score_payload.get("rows") or []:
            ws2.append([r.get("qid"), r.get("question"), r.get("correct"), r.get("lane"), r.get("ms")])

    wh = wb.create_sheet("Honesty")
    wh.append(["honesty", HONESTY])
    wh.append(["route", "openpyxl free (no Excel MCP required)"])

    wb.save(path)
    return path


def probe_excel_mcp(file_path: Path) -> dict[str, Any]:
    """Measure Excel MCP from this process; free openpyxl always works.

    Cursor `user-excel` MCP is host-side (not importable here). When MCP is up,
    the agent/host can call excel_describe_sheets on the same free-route file.
    """
    t0 = time.perf_counter()
    measure_path = OUT / "excel_mcp_measure.json"
    # Sidecar written when a host MCP probe succeeds (see DEMO_RAG.md)
    if measure_path.is_file():
        try:
            prior = json.loads(measure_path.read_text(encoding="utf-8"))
            if prior.get("ok") and prior.get("file") == str(file_path.resolve()):
                prior["reused"] = True
                prior["ms_probe"] = round((time.perf_counter() - t0) * 1000, 1)
                return prior
        except Exception:
            pass
    try:
        import importlib.util

        spec = importlib.util.find_spec("excel")
        ms = (time.perf_counter() - t0) * 1000
        if spec is None:
            out = {
                "ok": False,
                "api_down_in_process": True,
                "route": "free_openpyxl",
                "reason": "excel MCP not importable in AirGPT process (expected)",
                "ms": round(ms, 1),
                "file": str(file_path.resolve()),
                "advice": "Free route wrote xlsx; Cursor user-excel can describe/read the same path.",
            }
            measure_path.parent.mkdir(parents=True, exist_ok=True)
            measure_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
            return out
        out = {"ok": True, "route": "excel_mcp_module", "ms": round(ms, 1), "file": str(file_path.resolve())}
        measure_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out
    except Exception as e:
        out = {
            "ok": False,
            "api_down_in_process": True,
            "route": "free_openpyxl",
            "reason": str(e)[:200],
            "ms": round((time.perf_counter() - t0) * 1000, 1),
            "file": str(file_path.resolve()),
        }
        measure_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out


def record_mcp_host_ok(file_path: Path, *, sheets: list | None = None, ms: float = 0.0) -> dict:
    """Call from agent after successful Cursor user-excel probe."""
    OUT.mkdir(parents=True, exist_ok=True)
    out = {
        "ok": True,
        "api_down_in_process": True,
        "host_mcp_ok": True,
        "route": "cursor_user_excel + free_openpyxl",
        "ms": round(ms, 1),
        "file": str(Path(file_path).resolve()),
        "sheets": sheets or [],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (OUT / "excel_mcp_measure.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def run_pipeline(
    *,
    ask: str = "Top 5 selling SKUs by revenue",
    n: int = 5,
    file_type: str = "xlsx",
    graph_type: str = "bar",
    exclude: list[str] | None = None,
) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    score_path = RESULTS / "warehouse_hybrid_latest.json"
    score_payload = _load_json(score_path)
    top = retrieve_top_skus(n=n, exclude=exclude)
    insights = derive_insights(top=top, score_payload=score_payload or None)
    prompts = prompt_pack(file_type=file_type, graph_type=graph_type)

    ts = time.strftime("%Y%m%d_%H%M%S")
    csv_path = OUT / f"top{n}_sales_{ts}.csv"
    export_csv(csv_path, top.get("rows") or [])
    (OUT / "top_sales_latest.csv").write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")

    sql_path = OUT / f"cq_sales_top{n}_{ts}.sql"
    sql_path.write_text(str(top.get("sql") or ""), encoding="utf-8")
    (OUT / "cq_sales_top_latest.sql").write_text(str(top.get("sql") or ""), encoding="utf-8")

    xlsx_path = OUT / f"insights_export_{ts}.xlsx"
    # Probe MCP first (may be down) — still write free Excel.
    mcp = probe_excel_mcp(xlsx_path)
    route = "free_openpyxl" if not mcp.get("ok") else str(mcp.get("route"))
    audit = build_audit(ask=ask, top=top, insights=insights, route=route, mcp=mcp)
    export_excel_free(
        xlsx_path,
        top=top,
        insights=insights,
        audit=audit,
        prompts=prompts,
        score_payload=score_payload or None,
    )
    latest_xlsx = OUT / "insights_export_latest.xlsx"
    latest_xlsx.write_bytes(xlsx_path.read_bytes())

    audit_path = OUT / f"audit_{ts}.json"
    audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    (OUT / "audit_latest.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")

    insights_path = OUT / f"insights_{ts}.json"
    bundle = {
        "ok": True,
        "honesty": HONESTY,
        "ask": ask,
        "insights_retrieved_from": {
            "primary": top.get("source_file"),
            "sheet": top.get("source_sheet"),
            "lane": top.get("lane"),
            "scoreboard": str(score_path) if score_path.is_file() else None,
            "score_sha16": _sha(score_path),
        },
        "top": top,
        "insights": insights,
        "prompts": prompts,
        "exports": {
            "csv": str(csv_path),
            "csv_latest": str(OUT / "top_sales_latest.csv"),
            "sql": str(sql_path),
            "xlsx": str(xlsx_path),
            "xlsx_latest": str(latest_xlsx),
            "audit": str(audit_path),
        },
        "excel_mcp": mcp,
        "route": route,
    }
    insights_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    (OUT / "insights_latest.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    return bundle


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--ask", default="Top 5 selling SKUs by revenue")
    ap.add_argument("--file-type", default="xlsx", help="xlsx|csv — for prompt pack")
    ap.add_argument("--graph-type", default="bar", help="bar|pie|line — suggested prompts only")
    ap.add_argument("--exclude", default="", help="comma SKUs to exclude once")
    args = ap.parse_args()
    excl = [s.strip() for s in args.exclude.split(",") if s.strip()]
    out = run_pipeline(
        ask=args.ask,
        n=args.n,
        file_type=args.file_type,
        graph_type=args.graph_type,
        exclude=excl or None,
    )
    print(json.dumps({"ok": out["ok"], "route": out["route"], "exports": out["exports"], "insights_n": len(out["insights"]), "excel_mcp": out["excel_mcp"]}, indent=2))
    for i in out["insights"]:
        print(f"- [{i['id']}] {i['insight']}", flush=True)


if __name__ == "__main__":
    main()

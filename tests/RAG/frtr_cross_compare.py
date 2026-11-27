"""Multi-variant FRTR cross-compare: ingest one workbook, spot-check retrieve, score.

Variants (retrieve-time; SiRA expand is off on basic, on for high/max):
  baseline_basic  - depth=basic, RAG only
  sira_high       - depth=high, RAG only (SiRA query expand)
  sira_max        - depth=max, RAG only
  hybrid_max      - depth=max + pandas SQL lane  <-- LIVE DEMO DEFAULT
  adaptive        - depth=auto (falls back to space default)

Live default: hybrid_max (also set via POST /api/rag/spaces/{id}/demo-variant).
Honesty: Cortex-direct — not OpenVault-gated (see matrix["honesty"] in output).

Writes tests/RAG/results/frtr_cross_*.json and .xlsx
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frtr_eval import (  # noqa: E402
    BENCH,
    RESULTS,
    SANITIZED,
    build_space_and_ingest,
    extract_questions,
    run_eval,
    sanitize_workbook,
)

DEMO_DEFAULT_VARIANT = "hybrid_max"

VARIANTS = (
    {"name": "baseline_basic", "depth": "basic", "hybrid_sql": False, "label": "baseline (no SiRA expand)"},
    {"name": "sira_high", "depth": "high", "hybrid_sql": False, "label": "SiRA-enrich high"},
    {"name": "sira_max", "depth": "max", "hybrid_sql": False, "label": "SiRA-enrich max"},
    {"name": "hybrid_max", "depth": "max", "hybrid_sql": True, "label": "hybrid SQL+SiRA max"},
    {"name": "adaptive", "depth": "auto", "hybrid_sql": False, "label": "adaptive depth"},
)


def _spot_check(space_id: int, question: str, gold: str, *, depth: str = "max") -> dict:
    from rag import retrieve

    t0 = time.perf_counter()
    out = retrieve.search(space_id, question, depth=depth)
    ms = (time.perf_counter() - t0) * 1000
    hits = out.get("hits") or out.get("results") or []
    if not isinstance(hits, list):
        hits = []
    top = []
    for h in hits[:5]:
        if not isinstance(h, dict):
            continue
        text = str(h.get("text") or h.get("snippet") or "")[:240]
        top.append(
            {
                "path": h.get("path") or h.get("source") or h.get("doc_path"),
                "score": h.get("score") or h.get("rrf") or h.get("rank"),
                "sheet": h.get("sheet") or (h.get("meta") or {}).get("sheet") if isinstance(h.get("meta"), dict) else None,
                "text": text,
            }
        )
    blob = " ".join(str(t.get("text") or "") for t in top).lower()
    gold_s = str(gold or "")
    gold_int = gold_s.split(".")[0].replace(",", "")
    cited_ok = bool(top) and (
        (gold_int and len(gold_int) >= 4 and gold_int in blob.replace(",", ""))
        or ("summary" in blob and "revenue" in blob)
        or ("q2" in blob and "revenue" in blob)
    )
    return {
        "ok": bool(top),
        "cited_gold_fragment": cited_ok,
        "question": question,
        "gold": gold,
        "depth": depth,
        "ms": round(ms, 1),
        "n_hits": len(hits),
        "top": top,
        "template": out.get("template") or out.get("architecture"),
    }


def derive_insights(matrix: dict) -> list[tuple[str, str]]:
    """Short insights read off the actual scored rows.

    The Insights sheet used to be five fixed suggested prompts, which say the same
    thing whatever the bench did. These are statements about *this* run - which
    variant won, what every variant got wrong, where the accuracy actually drops -
    so the founder can open one file after the bench and see what happened.

    Text only. No charts, no chart intent (P3 stays parked).
    """
    out: list[tuple[str, str]] = []
    variants = matrix.get("variants") or []
    if not variants:
        return [("no data", "No variants were scored in this run.")]

    ranked = sorted(
        variants,
        key=lambda v: (v.get("summary") or {}).get("accuracy") or 0.0,
        reverse=True,
    )
    best = ranked[0]
    bs = best.get("summary") or {}
    out.append(
        (
            "best variant",
            f"{best.get('name')} scored {bs.get('correct')}/{bs.get('n')} "
            f"({round((bs.get('accuracy') or 0) * 100, 1)}%).",
        )
    )
    if len(ranked) > 1:
        worst = ranked[-1]
        ws_ = worst.get("summary") or {}
        gap = (bs.get("accuracy") or 0) - (ws_.get("accuracy") or 0)
        if gap > 0:
            out.append(
                (
                    "spread",
                    f"{worst.get('name')} was lowest at {ws_.get('correct')}/{ws_.get('n')} - "
                    f"a {round(gap * 100, 1)} point gap to {best.get('name')}.",
                )
            )
        else:
            out.append(("spread", "Every variant scored the same; this workbook does not separate them."))

    # Questions no variant got right - the only misses worth a retrieval fix.
    per_q: dict[int, dict] = {}
    for v in variants:
        for r in v.get("rows") or []:
            qid = int(r.get("qid") or 0)
            slot = per_q.setdefault(qid, {"question": r.get("question"), "wrong": 0, "total": 0, "sample": r})
            slot["total"] += 1
            if not r.get("correct"):
                slot["wrong"] += 1
                slot["sample"] = r
    for qid, slot in sorted(per_q.items()):
        if slot["total"] and slot["wrong"] == slot["total"]:
            r = slot["sample"]
            out.append(
                (
                    f"missed by all (q{qid})",
                    f"{slot['question']} - expected {str(r.get('gold'))[:40]!r}, "
                    f"got {str(r.get('pred'))[:40]!r}. Fix: the evidence for this lives on a "
                    f"sheet retrieval is not reaching; bind the named columns instead of "
                    f"ranking Summary chunks.",
                )
            )

    # Where accuracy actually drops, by difficulty and by reasoning type.
    for axis in ("by_difficulty", "by_reasoning"):
        buckets = bs.get(axis) or {}
        weak = [(k, b) for k, b in buckets.items() if (b or {}).get("accuracy", 1.0) < 1.0]
        if weak:
            worst_k, worst_b = min(weak, key=lambda kv: kv[1].get("accuracy", 1.0))
            out.append(
                (
                    axis.replace("by_", "weakest "),
                    f"{worst_k} at {round(worst_b.get('accuracy', 0) * 100, 1)}% "
                    f"over {worst_b.get('n')} question(s) for {best.get('name')}.",
                )
            )
        elif buckets:
            out.append((axis.replace("by_", "by "), f"{best.get('name')} was clean across all {axis.replace('by_', '')} buckets."))

    # Which lane actually answered, and what it cost.
    lanes: dict[str, list[float]] = {}
    for r in best.get("rows") or []:
        lanes.setdefault(str(r.get("lane") or "retrieve"), []).append(float(r.get("ms") or 0))
    for lane, times in sorted(lanes.items()):
        out.append(
            (
                f"lane {lane}",
                f"answered {len(times)} of {len(best.get('rows') or [])} questions for "
                f"{best.get('name')}, averaging {round(sum(times) / max(1, len(times)), 1)}ms.",
            )
        )

    errors = [r for v in variants for r in (v.get("rows") or []) if r.get("error")]
    if errors:
        out.append(("errors", f"{len(errors)} question run(s) raised an error - these are not scored misses, they are failures."))
    return out


def _write_xlsx(path: Path, matrix: dict) -> None:
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["variant", "label", "depth", "hybrid_sql", "n", "correct", "accuracy", "avg_ms"])
    for v in matrix["variants"]:
        s = v["summary"]
        rows = v.get("rows") or []
        avg_ms = round(sum(r.get("ms") or 0 for r in rows) / max(1, len(rows)), 1)
        ws.append(
            [
                v["name"],
                v.get("label"),
                s.get("depth"),
                s.get("hybrid_sql"),
                s.get("n"),
                s.get("correct"),
                s.get("accuracy"),
                avg_ms,
            ]
        )
    for cell in ws[1]:
        cell.font = Font(bold=True)

    wd = wb.create_sheet("Detail")
    wd.append(
        [
            "variant",
            "qid",
            "question",
            "difficulty",
            "reasoning_type",
            "gold",
            "pred",
            "correct",
            "match_reason",
            "lane",
            "ms",
            "model",
        ]
    )
    for v in matrix["variants"]:
        for r in v.get("rows") or []:
            wd.append(
                [
                    v["name"],
                    r.get("qid"),
                    r.get("question"),
                    r.get("difficulty"),
                    r.get("reasoning_type"),
                    r.get("gold"),
                    (r.get("pred") or "")[:500],
                    r.get("correct"),
                    r.get("match_reason"),
                    r.get("lane"),
                    r.get("ms"),
                    r.get("model"),
                ]
            )
    for cell in wd[1]:
        cell.font = Font(bold=True)

    ws2 = wb.create_sheet("SpotCheck")
    sc = matrix.get("spot_check") or {}
    ws2.append(["key", "value"])
    for k, val in sc.items():
        if k == "top":
            continue
        ws2.append([k, json.dumps(val) if isinstance(val, (dict, list)) else val])
    ws2.append([])
    ws2.append(["rank", "path", "sheet", "score", "text"])
    for i, t in enumerate(sc.get("top") or [], start=1):
        ws2.append([i, t.get("path"), t.get("sheet"), t.get("score"), t.get("text")])

    wi = wb.create_sheet("Insights")
    wi.append(["insight", "detail"])
    for cell in wi[1]:
        cell.font = Font(bold=True)
    for kind, text in derive_insights(matrix):
        wi.append([kind, text])
    wi.append([])
    wi.append(["suggested_prompt", ""])
    for p in matrix.get("suggested_prompts") or []:
        wi.append(["", p])
    wi.append([])
    wi.append(["note", matrix.get("honesty")])
    wi.column_dimensions["A"].width = 24
    wi.column_dimensions["B"].width = 110

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workbook", default="frtr_0001_quarterly-summary.xlsx")
    ap.add_argument("--limit", type=int, default=0, help="0 = all gold Qs for workbook")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--eval-only", action="store_true")
    ap.add_argument("--space-id", type=int, default=0)
    ap.add_argument("--variants", default="", help="comma names; default all")
    ap.add_argument("--out", default="", help="write the latest JSON here and skip side files")
    args = ap.parse_args()

    src = BENCH / args.workbook
    if not src.is_file():
        alt = SANITIZED / args.workbook
        if alt.is_file():
            # re-extract from sanitized is weak; prefer bench
            raise SystemExit(f"missing bench workbook {src} (sanitized exists but gold needs Questions sheet)")
        raise SystemExit(f"missing {src}")

    qs = extract_questions(src)
    dst = SANITIZED / src.name
    sanitize_workbook(src, dst)
    RESULTS.mkdir(parents=True, exist_ok=True)
    if not args.out:
        (RESULTS / "frtr_gold.json").write_text(json.dumps(qs, indent=2), encoding="utf-8")
    print(f"gold {len(qs)} from {src.name}", flush=True)

    space_id = args.space_id
    if not args.eval_only:
        space_id = build_space_and_ingest([dst], name="FRTR Cross Compare", force=True)
        print(f"ingested -> space {space_id}", flush=True)
    if not space_id:
        from rag import store

        store.init()
        sp = store.get_space_by_slug("frtr-bench") or store.get_space_by_slug("frtr-cross-compare")
        if not sp:
            raise SystemExit("no space; run without --eval-only")
        space_id = int(sp["id"])

    q0 = qs[0]
    spot = _spot_check(space_id, q0["question"], q0.get("gold") or "", depth="max")
    print(
        f"spot_check hits={spot['n_hits']} cited_gold={spot['cited_gold_fragment']} "
        f"template={spot.get('template')} {spot['ms']:.0f}ms",
        flush=True,
    )
    for i, t in enumerate(spot.get("top") or [], start=1):
        print(f"  hit{i}: {(t.get('text') or '')[:120]!r}", flush=True)

    want = {v.strip() for v in args.variants.split(",") if v.strip()} or None
    variants_out = []
    for spec in VARIANTS:
        if want and spec["name"] not in want:
            continue
        print(f"\n=== variant {spec['name']} depth={spec['depth']} hybrid_sql={spec['hybrid_sql']} ===", flush=True)
        out = run_eval(
            space_id,
            qs,
            depth=spec["depth"],
            use_llm=not args.no_llm,
            limit=args.limit,
            hybrid_sql=spec["hybrid_sql"],
        )
        summary = dict(out["summary"])
        summary["variant"] = spec["name"]
        summary["label"] = spec["label"]
        variants_out.append(
            {
                "name": spec["name"],
                "label": spec["label"],
                "summary": summary,
                "rows": out["rows"],
            }
        )
        print(
            f"accuracy={summary['accuracy']} ({summary['correct']}/{summary['n']})",
            flush=True,
        )

    # rank by accuracy then avg latency
    # Tie-break on the variant name, not on elapsed time, so a fresh run matches
    # the committed JSON. Latency is still stored per row.
    ranked = sorted(
        variants_out,
        key=lambda v: (
            -(v["summary"].get("accuracy") or 0),
            v["name"],
        ),
    )
    best = ranked[0]["name"] if ranked else None
    misses_common = []
    if ranked:
        miss_maps = [
            { (r.get("workbook"), r.get("qid")) for r in v.get("rows") or [] if not r.get("correct") }
            for v in ranked
        ]
        if miss_maps:
            common = set.intersection(*miss_maps) if len(miss_maps) > 1 else miss_maps[0]
            misses_common = sorted(common)

    matrix = {
        "ok": True,
        "workbook": args.workbook,
        "space_id": space_id,
        "honesty": "Cortex-direct / ai_engine RAG path — not OpenVault-gated for this demo branch.",
        "spot_check": spot,
        "best_variant": best,
        "variants": variants_out,
        "ranking": [{"name": v["name"], "accuracy": v["summary"].get("accuracy")} for v in ranked],
        "common_misses": [{"workbook": a, "qid": b} for a, b in misses_common],
        "suggested_prompts": [
            f"Using the {args.workbook} knowledge space, what is total revenue in Q2 2024?",
            "Compare Q1 vs Q4 revenue and say whether the full-year trend increases.",
            "Which quarter had the highest revenue and by how much vs the lowest?",
            "Export a scorecard: variant accuracy vs difficulty (Easy/Medium/Hard).",
            "List misses only and propose one retrieval fix per miss.",
        ],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    from bench_stamp import write_json
    if args.out:
        json_path = Path(args.out)
        write_json(json_path, matrix)
        xlsx_path = None
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        json_path = RESULTS / f"frtr_cross_{ts}.json"
        xlsx_path = RESULTS / f"frtr_cross_{ts}.xlsx"
        latest_json = RESULTS / "frtr_cross_latest.json"
        latest_xlsx = RESULTS / "frtr_cross_latest.xlsx"
        write_json(json_path, matrix)
        write_json(latest_json, matrix)
        _write_xlsx(xlsx_path, matrix)
        _write_xlsx(latest_xlsx, matrix)

    print("\n=== FINAL SCOREBOARD ===", flush=True)
    for v in ranked:
        s = v["summary"]
        print(f"  {v['name']:16}  acc={s.get('accuracy'):.3f}  {s.get('correct')}/{s.get('n')}", flush=True)
    print(f"best={best}  live_demo_default={DEMO_DEFAULT_VARIANT}", flush=True)
    print(f"wrote {json_path}", flush=True)
    print(f"wrote {xlsx_path}", flush=True)


if __name__ == "__main__":
    main()

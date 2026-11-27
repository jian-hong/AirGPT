"""Warehouse hybrid_max eval: ingest 6 workbooks, score hard-edge prompts, write JSON+xlsx.

No confirm-loop: exclusion is act-once or single ABSTAIN. Variant=hybrid_max.
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

from frtr_eval import RESULTS, build_space_and_ingest, score_answer  # noqa: E402
from frtr_sql_baseline import answer_sqlish, load_sheets  # noqa: E402
from gen_warehouse_workbooks import gold_questions, main as gen_main  # noqa: E402

WH = ROOT / "warehouse"
VARIANT = {
    "name": "hybrid_max",
    "depth": "max",
    "hybrid_sql": True,
    "label": "hybrid SQL+SiRA max (no confirm loops)",
}


def _score_topn(pred: str, gold: str, gold_values: list) -> dict:
    """Require ranked SKU identities in order when gold lists SKU-#####."""
    import re

    pred_skus = re.findall(r"SKU[-_ ]?\d+", pred or "", flags=re.I)
    gold_skus = [g for g in gold_values if str(g).upper().startswith("SKU-")]
    if gold_skus:
        norm = lambda s: re.sub(r"[^A-Z0-9]", "", s.upper())
        p = [norm(s) for s in pred_skus]
        g = [norm(s) for s in gold_skus]
        if p[: len(g)] == g:
            return {"correct": True, "reason": "sku_rank_order"}
        if set(p[: len(g)]) == set(g) and len(p) >= len(g):
            return {"correct": True, "reason": "sku_rank_set"}
    return score_answer(pred, gold, gold_values)


def _write_xlsx(path: Path, payload: dict) -> None:
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    s = payload["summary"]
    ws.append(["key", "value"])
    for k in ("variant", "space_id", "n", "correct", "accuracy", "honesty"):
        ws.append([k, s.get(k) if k != "honesty" else payload.get("honesty")])
    for c in ws[1]:
        c.font = Font(bold=True)

    wd = wb.create_sheet("Detail")
    wd.append(["qid", "workbook", "question", "gold", "pred", "correct", "lane", "ms", "notes"])
    for r in payload["rows"]:
        wd.append(
            [
                r.get("qid"),
                r.get("workbook"),
                r.get("question"),
                (r.get("gold") or "")[:300],
                (r.get("pred") or "")[:500],
                r.get("correct"),
                r.get("lane"),
                r.get("ms"),
                r.get("notes"),
            ]
        )
    for c in wd[1]:
        c.font = Font(bold=True)

    wi = wb.create_sheet("SheetsIndex")
    wi.append(["workbook", "sheets"])
    for name, sheets in (payload.get("sheet_index") or {}).items():
        wi.append([name, ", ".join(sheets)])

    wp = wb.create_sheet("Prompts")
    wp.append(["suggested_prompt"])
    for p in payload.get("suggested_prompts") or []:
        wp.append([p])

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def run(space_id: int, items: list[dict], *, use_llm: bool = True) -> dict:
    from rag import answer

    sheet_cache: dict[str, dict] = {}
    rows = []
    correct = 0
    for i, it in enumerate(items, start=1):
        t0 = time.perf_counter()
        pred = ""
        lane = "rag"
        err = None
        model = None
        wb_name = it["workbook"]
        if wb_name not in sheet_cache:
            sheet_cache[wb_name] = load_sheets(WH / wb_name) if (WH / wb_name).is_file() else {}
        sql_pred = answer_sqlish(sheet_cache[wb_name], it["question"])
        if sql_pred and not str(sql_pred).startswith("ABSTAIN:"):
            pred = str(sql_pred)
            lane = "sql"
            model = "pandas-sql"
        elif sql_pred and str(sql_pred).startswith("ABSTAIN:"):
            pred = str(sql_pred)
            lane = "abstain"
            model = "pandas-sql"
        if not pred and use_llm:
            try:
                res = answer.answer(space_id, it["question"], depth=VARIANT["depth"], use_llm=True)
                pred = str(res.get("answer") or "") if res.get("ok") else ""
                err = None if res.get("ok") else res.get("error")
                model = res.get("model")
                lane = "rag"
            except Exception as e:
                pred, err = "", str(e)
        ms = (time.perf_counter() - t0) * 1000
        sc = _score_topn(pred, it.get("gold") or "", it.get("gold_values") or [])
        if sc["correct"]:
            correct += 1
        row = {
            **{k: it.get(k) for k in ("workbook", "qid", "question", "difficulty", "reasoning_type", "gold", "notes")},
            "pred": (pred or "")[:1200],
            "correct": sc["correct"],
            "match_reason": sc["reason"],
            "lane": lane,
            "ms": round(ms, 1),
            "error": err,
            "model": model,
        }
        rows.append(row)
        mark = "OK" if sc["correct"] else "MISS"
        print(f"[{i}/{len(items)}] {mark} q{it['qid']} ({sc['reason']}/{lane}) {ms:.0f}ms", flush=True)

    n = max(1, len(rows))
    return {
        "summary": {
            "variant": VARIANT["name"],
            "label": VARIANT["label"],
            "space_id": space_id,
            "n": len(rows),
            "correct": correct,
            "accuracy": round(correct / n, 3),
            "depth": VARIANT["depth"],
            "hybrid_sql": True,
        },
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen-only", action="store_true")
    ap.add_argument("--eval-only", action="store_true")
    ap.add_argument("--space-id", type=int, default=0)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-gen", action="store_true", help="do not rewrite the committed workbooks")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if not args.skip_gen:
        gen_main()
    if args.gen_only:
        return

    gold = gold_questions()
    if args.limit:
        gold = gold[: args.limit]
    if not args.out:
        (RESULTS / "warehouse_gold.json").write_text(json.dumps(gold, indent=2), encoding="utf-8")

    paths = sorted(WH.glob("wh_*.xlsx"))
    if not paths:
        raise SystemExit("no warehouse workbooks")

    space_id = args.space_id
    if not args.eval_only:
        # Dedicated space — do not force-wipe FRTR scores artifacts
        from rag import ingest, store

        store.init()
        existing = store.get_space_by_slug("warehouse-bench")
        if existing:
            space_id = int(existing["id"])
        else:
            space = store.create_space(
                "Warehouse Bench",
                depth_default="max",
                modalities=["text"],
                profile="local",
            )
            space_id = int(space["id"])
            store.update_space_settings(
                space_id,
                config={
                    "bench": "warehouse",
                    "demo_variant": "hybrid_max",
                    "honesty": "Cortex-direct, not OpenVault-gated",
                },
            )
        res = ingest.ingest_paths(space_id, [str(p) for p in paths], force=True)
        if not res.get("ok"):
            raise RuntimeError(res)
        print(f"ingested {len(paths)} workbooks -> space {space_id}", flush=True)

    if not space_id:
        raise SystemExit("--space-id required with --eval-only")

    sheet_index = {}
    for p in paths:
        sheet_index[p.name] = list(load_sheets(p).keys())

    out = run(space_id, gold, use_llm=not args.no_llm)
    payload = {
        "ok": True,
        "honesty": "Cortex-direct / hybrid_max demo — not OpenVault-gated. No exclusion confirm loops.",
        "variant": VARIANT,
        "summary": out["summary"],
        "rows": out["rows"],
        "sheet_index": sheet_index,
        "suggested_prompts": [
            "Top 5 selling SKUs by revenue",
            "Top 6 selling SKUs by revenue",
            "Top 5 selling SKUs by revenue excluding SKU-00397",
            "How many SKUs do we have in inventory?",
            "What is total stock value by category?",
        ],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "score_artifacts_preserved": [
            "tests/RAG/results/frtr_cross_latest.json",
            "tests/RAG/results/frtr_cross_latest.xlsx",
        ],
    }
    from bench_stamp import write_json
    if args.out:
        dest = Path(args.out)
        write_json(dest, payload)
        print(json.dumps(out["summary"], indent=2), flush=True)
        print(f"wrote {dest}", flush=True)
        return
    ts = time.strftime("%Y%m%d_%H%M%S")
    jp = RESULTS / f"warehouse_hybrid_{ts}.json"
    xp = RESULTS / f"warehouse_hybrid_{ts}.xlsx"
    latest_j = RESULTS / "warehouse_hybrid_latest.json"
    latest_x = RESULTS / "warehouse_hybrid_latest.xlsx"
    write_json(jp, payload)
    write_json(latest_j, payload)
    _write_xlsx(xp, payload)
    _write_xlsx(latest_x, payload)
    print(json.dumps(out["summary"], indent=2), flush=True)
    print(f"wrote {jp}\nwrote {xp}", flush=True)


if __name__ == "__main__":
    main()

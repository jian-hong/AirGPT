"""Primary ~50MB pack multi-variant scoreboard (RAG-BENCH-06 / F13).

Reuses frtr_cross_compare / warehouse scoring — no second score stack.
Variants: sira_max, hybrid_max, adaptive (cheap).
Writes tests/RAG/results/primary50_cross_*.json + .xlsx
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frtr_cross_compare import VARIANTS, _write_xlsx  # noqa: E402
from frtr_eval import RESULTS, score_answer  # noqa: E402
from frtr_sql_baseline import answer_sqlish  # noqa: E402
from gen_messy_fixtures import PRIMARY_OUT, generate_primary_pack, primary_gold_questions  # noqa: E402

SLUG = "primary-50mb-bench"
DEFAULT_VARIANTS = ("sira_max", "hybrid_max", "adaptive")


def _find_primary_space() -> dict | None:
    from rag import store

    hit = store.get_space_by_slug(SLUG)
    if hit:
        return hit
    for sp in store.list_spaces(limit=200):
        cfg = sp.get("config") or {}
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:
                cfg = {}
        if isinstance(cfg, dict) and cfg.get("bench") == "primary50":
            return sp
    return None


def _score_topn(pred: str, gold: str, gold_values: list) -> dict:
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
    # schema / region: require all gold_values present
    if gold_values and all(str(gv).casefold() in (pred or "").casefold() for gv in gold_values if gv):
        return {"correct": True, "reason": "all_gold_values"}
    return score_answer(pred, gold, gold_values)


def _load_sql_sheets(path: Path) -> dict:
    """Load only lean SQL sheets — skip fattening (no sheet text in pad)."""
    import openpyxl
    import pandas as pd

    want = {"sales", "inventory", "summary", "ops_kpi", "sku_master", "returns", "kpi_board"}
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out: dict = {}
    try:
        for name in wb.sheetnames:
            if name.casefold() not in want:
                continue
            rows = []
            for row in wb[name].iter_rows(values_only=True):
                rows.append(row)
            if not rows:
                continue
            header = None
            data_start = 0
            for i, row in enumerate(rows[:5]):
                cells = [c for c in row if c is not None and str(c).strip()]
                if len(cells) >= 2 and not str(cells[0]).startswith("#"):
                    header = [str(c).strip() if c is not None else f"c{j}" for j, c in enumerate(row)]
                    data_start = i + 1
                    break
            if header is None:
                continue
            data = [r for r in rows[data_start:] if any(c is not None for c in r)]
            width = len(header)
            norm = [list(r[:width]) + [None] * max(0, width - len(r)) for r in data]
            out[name] = pd.DataFrame(norm, columns=header)
    finally:
        wb.close()
    return out


def _docs_reveal_note(space_id: int, paths: list[Path]) -> dict:
    """Consume #20/#14 paths only — fail-closed note if incomplete."""
    from rag.ingest import _retain_docs_original
    import hashlib

    rows = []
    for p in paths:
        try:
            data = p.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            docs = _retain_docs_original(space_id, p, digest)
            ok = bool(docs) and Path(docs).is_file()
            rows.append({"original": str(p.resolve()), "docs_path": docs, "ok": ok})
        except Exception as e:
            rows.append({"original": str(p), "docs_path": "", "ok": False, "error": str(e)})
    n_ok = sum(1 for r in rows if r.get("ok"))
    # Hover/#14 not verified here — fail closed
    return {
        "docs_retain": {"passed": n_ok, "n": len(rows), "rows": rows},
        "reveal_hover": {
            "status": "fail_closed",
            "note": (
                "#20 Docs retain / #14 hover reveal still open for adversary verify. "
                "Code paths exist (docs_path + POST /api/rag/reveal-path); do not treat as closed."
            ),
        },
        "ok": n_ok == len(rows) and len(rows) > 0,
    }


def run_variant(space_id: int, items: list[dict], *, depth: str, hybrid_sql: bool, use_llm: bool) -> dict:
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
        if hybrid_sql:
            if wb_name not in sheet_cache:
                p = PRIMARY_OUT / wb_name
                sheet_cache[wb_name] = _load_sql_sheets(p) if p.is_file() else {}
            # also merge Sales from book 01 so Top-N works regardless of gold workbook tag
            if "p50_01_sales_messy.xlsx" not in sheet_cache:
                p0 = PRIMARY_OUT / "p50_01_sales_messy.xlsx"
                sheet_cache["p50_01_sales_messy.xlsx"] = _load_sql_sheets(p0) if p0.is_file() else {}
            merged = {}
            for key in ("p50_01_sales_messy.xlsx", wb_name):
                for sn, df in (sheet_cache.get(key) or {}).items():
                    merged.setdefault(sn, df)
            sql_pred = answer_sqlish(merged, it["question"])
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
                res = answer.answer(space_id, it["question"], depth=depth, use_llm=True)
                pred = str(res.get("answer") or "") if res.get("ok") else ""
                err = None if res.get("ok") else res.get("error")
                model = res.get("model")
                lane = "rag"
            except Exception as e:
                pred, err = "", str(e)
        elif not pred and not use_llm:
            # retrieve-only fallback for schema/region style
            try:
                from rag import retrieve

                out = retrieve.search(space_id, it["question"], depth=depth)
                hits = out.get("hits") or out.get("results") or []
                blob = " ".join(str(h.get("text") or "") for h in (hits or [])[:8] if isinstance(h, dict))
                pred = blob[:1200]
                lane = "retrieve"
                model = "retrieve-only"
            except Exception as e:
                pred, err = "", str(e)
        ms = (time.perf_counter() - t0) * 1000
        sc = _score_topn(pred, it.get("gold") or "", it.get("gold_values") or [])
        if sc["correct"]:
            correct += 1
        rows.append(
            {
                **{k: it.get(k) for k in ("workbook", "qid", "question", "difficulty", "reasoning_type", "gold", "notes")},
                "pred": (pred or "")[:1200],
                "correct": sc["correct"],
                "match_reason": sc["reason"],
                "lane": lane,
                "ms": round(ms, 1),
                "error": err,
                "model": model,
            }
        )
        mark = "OK" if sc["correct"] else "MISS"
        print(f"  [{i}/{len(items)}] {mark} q{it['qid']} ({sc['reason']}/{lane}) {ms:.0f}ms", flush=True)

    n = max(1, len(rows))
    return {
        "summary": {
            "n": len(rows),
            "correct": correct,
            "accuracy": round(correct / n, 3),
            "depth": depth,
            "hybrid_sql": hybrid_sql,
        },
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen-only", action="store_true")
    ap.add_argument("--eval-only", action="store_true")
    ap.add_argument("--space-id", type=int, default=0)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--mb-each", type=float, default=12.0)
    ap.add_argument("--variants", default=",".join(DEFAULT_VARIANTS))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if not args.eval_only:
        generate_primary_pack(target_mb_each=float(args.mb_each))
    if args.gen_only:
        return

    paths = sorted(PRIMARY_OUT.glob("p50_*.xlsx"))
    if not paths:
        raise SystemExit("missing primary50 pack — run without --eval-only")

    gold = primary_gold_questions()
    if args.limit:
        gold = gold[: args.limit]
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "primary50_gold.json").write_text(json.dumps(gold, indent=2), encoding="utf-8")

    from rag import demo_variants, ingest, store

    store.init()
    space_id = args.space_id
    existing = _find_primary_space()
    if space_id:
        pass
    elif existing:
        space_id = int(existing["id"])
    else:
        space = store.create_space(
            "Primary 50MB Bench",
            depth_default="max",
            modalities=["text"],
            profile="local",
            config={
                "bench": "primary50",
                "demo_variant": "hybrid_max",
                "honesty": "Cortex-direct primary ~50MB pack — not OpenVault-gated",
            },
        )
        space_id = int(space["id"])
        print(f"created space {space_id} slug={space.get('slug')}", flush=True)

    if not args.eval_only:
        print(f"ingest {len(paths)} workbooks -> space {space_id}", flush=True)
        res = ingest.ingest_paths(space_id, [str(p) for p in paths], force=True)
        if not res.get("ok"):
            raise RuntimeError(res)

    docs_note = _docs_reveal_note(space_id, paths)

    want = {v.strip() for v in args.variants.split(",") if v.strip()}
    variants_out = []
    for spec in VARIANTS:
        if spec["name"] not in want:
            continue
        print(f"\n=== variant {spec['name']} depth={spec['depth']} hybrid_sql={spec['hybrid_sql']} ===", flush=True)
        demo_variants.select_variant(space_id, spec["name"])
        out = run_variant(
            space_id,
            gold,
            depth=spec["depth"],
            hybrid_sql=bool(spec["hybrid_sql"]),
            use_llm=not args.no_llm,
        )
        summary = dict(out["summary"])
        summary["variant"] = spec["name"]
        summary["label"] = spec["label"]
        variants_out.append({"name": spec["name"], "label": spec["label"], "summary": summary, "rows": out["rows"]})
        print(f"accuracy={summary['accuracy']} ({summary['correct']}/{summary['n']})", flush=True)

    ranked = sorted(variants_out, key=lambda v: (-(v["summary"].get("accuracy") or 0),))
    best = ranked[0]["name"] if ranked else None
    matrix = {
        "ok": True,
        "bench": "primary50",
        "space_id": space_id,
        "slug": SLUG,
        "honesty": "Cortex-direct / SiRA-inspired + hybrid — not OpenVault-gated. Not full Meta SIRA (P2).",
        "pack": {
            "dir": str(PRIMARY_OUT),
            "files": [{"name": p.name, "mb": round(p.stat().st_size / 1e6, 2)} for p in paths],
            "total_mb": round(sum(p.stat().st_size for p in paths) / 1e6, 2),
        },
        "docs_reveal": docs_note,
        "best_variant": best,
        "variants": variants_out,
        "ranking": [{"name": v["name"], "accuracy": v["summary"].get("accuracy")} for v in ranked],
        "baselines_note": (
            "Prove separately: python tests/RAG/warehouse_eval.py --no-llm "
            "and frtr_cross_compare.py --workbook frtr_0001_quarterly-summary.xlsx --variants hybrid_max"
        ),
        "suggested_prompts": [
            "Top 5 selling SKUs by revenue",
            "How many SKUs do we have in inventory?",
            "Which regions appear in the wide sales tables?",
        ],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    ts = time.strftime("%Y%m%d_%H%M%S")
    jp = RESULTS / f"primary50_cross_{ts}.json"
    xp = RESULTS / f"primary50_cross_{ts}.xlsx"
    latest_j = RESULTS / "primary50_cross_latest.json"
    latest_x = RESULTS / "primary50_cross_latest.xlsx"
    jp.write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    latest_j.write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    _write_xlsx(xp, matrix)
    _write_xlsx(latest_x, matrix)

    print("\n=== PRIMARY50 SCOREBOARD ===", flush=True)
    for v in ranked:
        s = v["summary"]
        print(f"  {v['name']:16}  acc={s.get('accuracy'):.3f}  {s.get('correct')}/{s.get('n')}", flush=True)
    print(f"best={best}  docs_reveal_ok={docs_note.get('ok')}", flush=True)
    print(f"wrote {jp}\nwrote {xp}", flush=True)


if __name__ == "__main__":
    main()

"""Regenerate every tests/RAG/results/*_latest.json and fail on drift.

The fresh run is stamped with this checkout's SHA and a timestamp. Comparison
ignores those fields, timings, space ids and absolute paths (bench_stamp).
A checked-in file must still carry a real SHA from this history and a timestamp.

    python tests/RAG/regen_latest.py --check
    python tests/RAG/regen_latest.py --write
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAG = Path(__file__).resolve().parent
ROOT = RAG.parents[1]
RESULTS = RAG / "results"
PY = sys.executable

# Name -> argv tail after the interpreter. {out} is the temp (or dest) JSON.
COMMANDS: dict[str, list[str]] = {
    "paraphrase_bench_latest.json": ["tests/RAG/paraphrase_bench.py", "--out", "{out}"],
    "filetype_bench_latest.json": ["tests/RAG/filetype_bench.py", "--out", "{out}"],
    "chunk_bench_latest.json": ["tests/RAG/chunk_bench.py", "--out", "{out}"],
    "multilingual_bench_latest.json": ["tests/RAG/multilingual_bench.py", "--out", "{out}"],
    "real_doc_bench_latest.json": ["tests/RAG/real_doc_bench.py", "--out", "{out}"],
    "oracle_cross_latest.json": [
        "tests/RAG/oracle_bench.py", "--dir", "primary50",
        "--workbook", "p50_01_sales_messy.xlsx", "--n", "7", "--seed", "1",
        "--variants", "sira_max,hybrid_max", "--out", "{out}",
    ],
    "oracle_bench_latest.json": [
        "tests/RAG/oracle_bench.py", "--dir", "primary50",
        "--workbook", "p50_01_sales_messy.xlsx", "--n", "21", "--seed", "42",
        "--out", "{out}",
    ],
    "oracle_cross_primary50_1.json": [
        "tests/RAG/oracle_bench.py", "--dir", "primary50",
        "--workbook", "p50_01_sales_messy.xlsx", "--n", "80", "--seed", "1",
        "--variants", "sira_max,hybrid_max", "--out", "{out}",
    ],
    "oracle_cross_primary50_2.json": [
        "tests/RAG/oracle_bench.py", "--dir", "primary50",
        "--workbook", "p50_02_ops_messy.xlsx", "--n", "80", "--seed", "2",
        "--variants", "sira_max,hybrid_max", "--out", "{out}",
    ],
    "oracle_cross_primary50_3.json": [
        "tests/RAG/oracle_bench.py", "--dir", "primary50",
        "--workbook", "p50_03_inventory_messy.xlsx", "--n", "80", "--seed", "3",
        "--variants", "sira_max,hybrid_max", "--out", "{out}",
    ],
    "oracle_cross_primary50_4.json": [
        "tests/RAG/oracle_bench.py", "--dir", "primary50",
        "--workbook", "p50_04_mixed_messy.xlsx", "--n", "80", "--seed", "4",
        "--variants", "sira_max,hybrid_max", "--out", "{out}",
    ],
    "oracle_cross_primary50.json": [
        "tests/RAG/oracle_bench.py", "--aggregate-primary50", "--out", "{out}",
    ],
    "frtr_latest.json": [
        "tests/RAG/frtr_eval.py", "--no-llm",
        "--workbook", "frtr_0001_quarterly-summary.xlsx", "--out", "{out}",
    ],
    "frtr_cross_latest.json": [
        "tests/RAG/frtr_cross_compare.py", "--no-llm",
        "--variants", "sira_max,hybrid_max",
        "--workbook", "frtr_0001_quarterly-summary.xlsx", "--out", "{out}",
    ],
    "frtr_batch_latest.json": ["tests/RAG/frtr_sql_batch.py", "--out", "{out}"],
    "warehouse_hybrid_latest.json": [
        "tests/RAG/warehouse_eval.py", "--skip-gen", "--no-llm", "--out", "{out}",
    ],
    "edge_probe_latest.json": ["tests/RAG/edge_probe.py", "--offline", "--out", "{out}"],
    "ops_demo_e2e_latest.json": ["tests/RAG/ops_demo_e2e.py", "--out", "{out}"],
}


def latest_names() -> list[str]:
    return sorted(p.name for p in RESULTS.glob("*_latest.json"))


def missing_from_registry() -> list[str]:
    return [name for name in latest_names() if name not in COMMANDS]


def _env(data_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["AIRGPT_DATA_DIR"] = str(data_dir)
    env["AIRGPT_RAG_EMBED"] = "hash"
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["AIRGPT_NO_BROWSER"] = "1"
    env["AIRGPT_FRTR_BENCH"] = str(RAG / "fixtures" / "frtr_min")
    env["AIRGPT_OPS_FIXTURE"] = str(RAG / "fixtures" / "ops" / "payroll_ops.xlsx")
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_one(name: str, dest: Path, data_dir: Path) -> subprocess.CompletedProcess:
    argv = [PY]
    for part in COMMANDS[name]:
        argv.append(str(dest) if part == "{out}" else part)
    return subprocess.run(
        argv,
        cwd=str(ROOT),
        env=_env(data_dir),
        text=True,
        capture_output=True,
    )


def _ok_json(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 20:
        return False
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return isinstance(body, dict) and "commit_sha" in body and "generated_at" in body


def all_targets() -> list[str]:
    """Registry order. The n=320 parts are written before the pooled summary."""
    return list(COMMANDS.keys())


def check(names: list[str] | None = None) -> int:
    from bench_stamp import diff_paths, git_sha, is_ancestor, require_stamp

    gap = missing_from_registry()
    if gap:
        print("no regenerator for: " + ", ".join(gap))
        return 1
    head = git_sha()
    targets = list(names) if names else all_targets()
    failed = 0
    with tempfile.TemporaryDirectory(prefix="rag-regen-") as tmp:
        tmp_path = Path(tmp)
        data_root = tmp_path / "data"
        for name in targets:
            committed = RESULTS / name
            if not committed.is_file():
                print(f"MISSING {name}")
                failed += 1
                continue
            try:
                committed_body = json.loads(committed.read_text(encoding="utf-8"))
                sha = require_stamp(committed_body, label=name)
            except ValueError as exc:
                print(f"STAMP {exc}")
                failed += 1
                continue
            if not is_ancestor(sha, head):
                print(f"STAMP {name}: commit_sha {sha} is not an ancestor of {head}")
                failed += 1
                continue
            fresh = tmp_path / name
            proc = run_one(name, fresh, data_root / name)
            tail = (proc.stdout or "")[-1500:]
            if not _ok_json(fresh):
                print(f"RUN {name} exit {proc.returncode}")
                print(tail)
                err = (proc.stderr or "")[-1500:]
                if err:
                    print(err)
                failed += 1
                continue
            fresh_body = json.loads(fresh.read_text(encoding="utf-8"))
            try:
                fresh_sha = require_stamp(fresh_body, label=name + " fresh")
            except ValueError as exc:
                print(f"STAMP {exc}")
                failed += 1
                continue
            if fresh_sha != head:
                print(f"STAMP {name}: fresh commit_sha {fresh_sha} != HEAD {head}")
                failed += 1
                continue
            if proc.returncode != 0:
                # oracle_bench exits 1 when a single-lane run is not perfect.
                # The JSON is still the measurement. Drift, not the exit, fails.
                print(f"NOTE {name} exit {proc.returncode} (json written, comparing)")
            diffs = diff_paths(committed, fresh)
            if diffs:
                print(f"DRIFT {name}")
                for line in diffs:
                    print("  " + line)
                failed += 1
            else:
                print(f"OK {name}")
    if failed:
        print(f"{failed} bench artifact(s) drifted or failed to regenerate")
        return 1
    print(f"all {len(targets)} artifacts match a fresh run at {head}")
    return 0


def write_all(names: list[str] | None = None) -> int:
    """Regenerate the committed files in place. Used once, then --check."""
    targets = list(names) if names else all_targets()
    failed = 0
    with tempfile.TemporaryDirectory(prefix="rag-data-") as tmp:
        data_root = Path(tmp)
        for name in targets:
            dest = RESULTS / name
            proc = run_one(name, dest, data_root / name)
            if not _ok_json(dest):
                print(f"RUN {name} exit {proc.returncode}")
                print((proc.stdout or "")[-2000:])
                print((proc.stderr or "")[-2000:])
                failed += 1
            else:
                print(f"WROTE {name} exit {proc.returncode}")
    return 1 if failed else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--only", default="", help="comma-separated file names")
    args = ap.parse_args()
    names = [n.strip() for n in args.only.split(",") if n.strip()] or None
    if args.write:
        raise SystemExit(write_all(names))
    if args.check or not args.write:
        raise SystemExit(check(names))


if __name__ == "__main__":
    main()

"""#21: the SQL lane must be reachable on a space a founder actually creates.

`oracle_bench` measures this engine at 720/720, but it calls
`sheet_sql.answer_filter_aggregate` directly. The product reaches that engine only
through `answer.answer` -> `_try_hybrid_sql_lane`, which was gated on
`config.hybrid_sql_lane`. Exactly one preset (`hybrid_max`) set it True, and a
normal space carries no `demo_variant` at all, so every space a founder created
fell through to retrieval and never saw the lane. The engine was excellent and
unreachable, and no gate noticed because every gate asserted on the engine.

So this one creates a space the way the product does - no variant, no config
tricks - ingests a real workbook, and asks through `answer.answer`. It asserts on
the lane the ANSWER came from, not on what the SQL engine can do in isolation
(R-0001).

It also pins the flag both ways. Defaulting the lane on is only safe because an
explicit False is still honoured; without that the sira_max vs hybrid_max
comparison the demo variants exist for would silently collapse into one variant.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
for _p in (str(REPO), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.stdio_utf8 import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

WORKBOOK = ROOT / "warehouse" / "wh_01_sales_core.xlsx"
PASS = 0
FAIL: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    global PASS
    if ok:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL.append(label)
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


def main() -> int:
    from rag import demo_variants, ingest, store

    if not WORKBOOK.is_file():
        print(f"fixture missing: {WORKBOOK}")
        return 2

    print("=" * 70)
    print("#21 - is the SQL lane reachable on a DEFAULT space?")
    print("=" * 70)

    space = store.create_space(f"sqlreach-{uuid.uuid4().hex[:8]}")
    sid = int(space["id"])
    cfg = space.get("config")
    variant = (cfg or {}).get("demo_variant") if isinstance(cfg, dict) else None
    check(not variant, f"space {sid} has no demo_variant (a founder space)", f"got {variant!r}")

    preset = demo_variants.resolve_for_space(sid)
    check(
        bool(preset.get("hybrid_sql_lane")),
        "the SQL lane is enabled on it",
        "hybrid_sql_lane is False - answers fall through to retrieval and the "
        "engine is unreachable no matter how good it is",
    )

    # Ingest from a staging dir that is then DELETED. That is not an artificial
    # cruelty - it is what a download folder, a temp export or a moved file looks
    # like - and it exercises the Docs-original fallback (#20) that the SQL lane
    # depends on to find a workbook whose host path no longer resolves.
    with tempfile.TemporaryDirectory() as td:
        staged = Path(td) / WORKBOOK.name
        shutil.copy2(WORKBOOK, staged)
        ingest.ingest_paths(sid, [str(staged)])
    check(bool(store.list_sources(sid)), "workbook ingested")

    from rag import reveal as _reveal

    src = store.list_sources(sid)[0]
    resolved, origin = _reveal.resolve_source_path(src)
    check(
        bool(resolved) and Path(str(resolved)).is_file() and origin == "docs",
        f"workbook still resolves after its source path vanished (origin={origin!r})",
        "the host path is gone, so without the retained Docs original the lane "
        "cannot open the workbook at all",
    )

    from rag import answer as rag_answer

    # A filter+aggregate ask: the shape the KPI catalogue cannot serve and the
    # retrieval lane can only guess at. Columns are checked against the fixture -
    # the first draft of this gate asked about a `qty` column that this workbook
    # does not have, and the lane was RIGHT to decline it.
    q = "On Sales, what is the average sales_value_myr where sales_value_myr at least 100"
    out = rag_answer.answer(sid, q, depth="high", use_llm=False, use_web=False)
    lane = str((out or {}).get("lane") or "")
    text = str((out or {}).get("answer") or "")
    sql = str((out or {}).get("sql") or "") or str(
        ((out or {}).get("provenance") or {}).get("sql") or ""
    )
    print(f"  lane={lane!r}")
    print(f"  answer={text[:110]}")
    if sql:
        print(f"  sql={sql[:100]}")

    check(lane == "sql", "the answer came from the SQL lane, not retrieval",
          f"lane={lane!r} - a founder asking this gets a retrieved paragraph, not a computed number")
    check(bool(sql), "the answer carries the SQL it ran")

    # The flag must still be honourable in the other direction, or the demo
    # variants stop being a comparison.
    store.update_space_settings(sid, config={"hybrid_sql_lane": False})
    off = demo_variants.resolve_for_space(sid)
    check(not off.get("hybrid_sql_lane"),
          "an explicit False still turns the lane off (variants stay comparable)")

    print()
    print(f"{PASS}/{PASS + len(FAIL)} checks passed")
    for f in FAIL:
        print(f"  FAILED: {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""D07 leftover: retained F13 A/B must hold sira_max AND hybrid_max.

frtr_cross_latest.json used to keep a variants list of length 1, so F13's
sira_max vs hybrid_max was never retained. This gate reads the committed
oracle_cross_latest.json and fails when either variant, the shared question
set, or an F13 field is missing. It does not re-score (n=320 is a documented
regenerate, not CI).

Regenerate (small, frtr_0001, one ask per family):

    python tests/RAG/oracle_bench.py --dir FRTR-bench --workbook frtr_0001_quarterly-summary.xlsx --n 7 --seed 1 --variants sira_max,hybrid_max

n=320 (primary50, four workbooks, seeds 1-4) is the F13b close command, not this gate.
Do not write precision@k / recall@k / PR-AUC / MAP.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RAG = ROOT / "tests" / "RAG"
if str(RAG) not in sys.path:
    sys.path.insert(0, str(RAG))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import oracle_bench as ob  # noqa: E402

ARTIFACT = RAG / "results" / "oracle_cross_latest.json"
F13_FIELDS = (
    "value_accuracy",
    "schema_link_accuracy",
    "malformed_ask_rate",
    "abstention_rate",
)
FAMILIES = (
    "row_range_agg",
    "row_range_nocol",
    "filter_agg",
    "filter_count",
    "combined",
    "paraphrase",
    "out_of_range",
)


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys(item)


def assert_cross_payload(data: dict) -> None:
    assert isinstance(data, dict), "artifact must be an object"
    variants = data.get("variants")
    assert isinstance(variants, list), "variants must be a list"
    names = [v.get("name") for v in variants if isinstance(v, dict)]
    missing = [n for n in ob.CROSS_VARIANTS if n not in names]
    assert not missing, (
        f"retained artifact missing {missing}; variants={names}. "
        "Regenerate with --variants sira_max,hybrid_max"
    )
    assert len(variants) >= 2, f"variants length {len(variants)} is a one-variant scoreboard"

    questions = data.get("questions")
    assert isinstance(questions, list) and questions, "shared question set missing"
    n = data.get("n")
    assert n == len(questions), f"n={n} does not match questions={len(questions)}"

    for v in variants:
        assert isinstance(v, dict)
        for field in F13_FIELDS:
            assert field in v, f"{v.get('name')} missing {field}"
        sla = v["schema_link_accuracy"]
        assert isinstance(sla, dict), (
            f"{v.get('name')} schema_link_accuracy must be per family, not pooled"
        )
        for fam in FAMILIES:
            assert fam in sla, f"{v.get('name')} schema_link_accuracy missing family {fam}"
        for rate_name in ("value_accuracy", "malformed_ask_rate", "abstention_rate"):
            rate = v[rate_name]
            assert isinstance(rate, (int, float)), f"{v.get('name')} {rate_name} not numeric"
            assert 0.0 <= float(rate) <= 1.0, f"{v.get('name')} {rate_name}={rate} out of [0,1]"
        rows = v.get("rows") or []
        row_qs = [r.get("question") for r in rows]
        assert row_qs == questions, (
            f"{v.get('name')} scored a different question set than the retained list"
        )
        assert v.get("n") == len(questions)

    forbidden = sorted({k for k in _walk_keys(data) if k in ob.FORBIDDEN_F13_KEYS})
    assert not forbidden, f"F13-forbidden metric keys present: {forbidden}"


def test_one_variant_payload_is_rejected():
    """R-0007: the gate must be able to fail the known-broken retained shape."""
    fake = {
        "ok": True,
        "n": 1,
        "questions": ["On Sales, sum qty for rows 1 to 2"],
        "variants": [
            {
                "name": "hybrid_max",
                "value_accuracy": 1.0,
                "schema_link_accuracy": {fam: 1.0 for fam in FAMILIES},
                "malformed_ask_rate": 0.0,
                "abstention_rate": 0.0,
                "n": 1,
                "rows": [{"question": "On Sales, sum qty for rows 1 to 2"}],
            }
        ],
    }
    with pytest.raises(AssertionError, match="missing"):
        assert_cross_payload(fake)


def test_retained_oracle_cross_has_sira_and_hybrid():
    assert ARTIFACT.is_file(), (
        f"missing {ARTIFACT.as_posix()}. "
        "python tests/RAG/oracle_bench.py --dir FRTR-bench "
        "--workbook frtr_0001_quarterly-summary.xlsx --n 7 --seed 1 "
        "--variants sira_max,hybrid_max"
    )
    data = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert_cross_payload(data)


def test_frtr_cross_latest_has_sira_and_hybrid():
    """Named D07 defect: the FRTR gold scoreboard also used to hold one variant."""
    path = RAG / "results" / "frtr_cross_latest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    names = [v.get("name") for v in (data.get("variants") or []) if isinstance(v, dict)]
    missing = [n for n in ob.CROSS_VARIANTS if n not in names]
    assert not missing, (
        f"{path.as_posix()} missing {missing}; variants={names}. "
        "python tests/RAG/frtr_cross_compare.py --workbook "
        "frtr_0001_quarterly-summary.xlsx --variants sira_max,hybrid_max --no-llm"
    )

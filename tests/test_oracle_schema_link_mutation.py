"""RAG-BENCH-16: every family in schema_link_accuracy must be able to fail.

`row_range_nocol` required an empty column set and `out_of_range` short-circuited
to True before either the sheet or the column check ran, so both scored 1.000 by
construction - R-0007, the same class as the `header_drift` defect #31 closed.
A variant that binds nothing anywhere collected a perfect out_of_range column.

This gate injects a deliberately wrong binding into a synthetic case per family
and asserts the scorer says False. It is table-driven over `oracle_bench.FAMILIES`
and asserts that tuple is fully covered, so a family added later cannot silently
skip the check.

It calls `link_check` directly and never opens a workbook. The four primary50
files are now committed (a seeded equivalent of the gitignored originals), but
this gate still does not need them.
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

SHEET = "Sales"
WRONG_SHEET = "Costs"
NUMERIC = {"Revenue": 3, "Qty": 5}


def _scalar(**over) -> dict:
    exp = {"kind": "scalar", "value": 42.0, "n": 7}
    exp.update(over)
    return exp


# family -> (case, expected, correctly-bound `linked`, was the lane's answer a refusal)
CASES: dict[str, tuple[dict, dict, dict, bool]] = {
    "row_range_agg": (
        {"family": "row_range_agg", "sheet": SHEET, "col": "Revenue", "lo": 2, "hi": 9},
        _scalar(),
        {"metric": "Revenue", "filters": [], "all_numeric": False},
        False,
    ),
    "paraphrase": (
        {"family": "paraphrase", "sheet": SHEET, "col": "Revenue", "lo": 2, "hi": 9},
        _scalar(),
        {"metric": "Revenue", "filters": [], "all_numeric": False},
        False,
    ),
    "row_range_nocol": (
        {"family": "row_range_nocol", "sheet": SHEET, "col": None,
         "lo": 2, "hi": 9, "numeric": dict(NUMERIC)},
        {"kind": "per_column", "per_column": {"Revenue": 42.0, "Qty": 7.0}},
        # The lane signals "I answered every numeric column" with plan.all_numeric,
        # which is the correct binding for a question that names no column.
        {"metric": "", "filters": [], "all_numeric": True},
        False,
    ),
    "filter_count": (
        {"family": "filter_count", "sheet": SHEET, "col": "Qty", "fcol": "Qty"},
        _scalar(),
        {"metric": "Qty", "filters": ["Qty"], "all_numeric": False},
        False,
    ),
    "filter_agg": (
        {"family": "filter_agg", "sheet": SHEET, "col": "Revenue", "fcol": "Qty"},
        _scalar(),
        {"metric": "Revenue", "filters": ["Qty"], "all_numeric": False},
        False,
    ),
    "combined": (
        {"family": "combined", "sheet": SHEET, "col": "Revenue", "fcol": "Qty",
         "lo": 2, "hi": 9},
        _scalar(),
        {"metric": "Revenue", "filters": ["Qty"], "all_numeric": False},
        False,
    ),
    "out_of_range": (
        {"family": "out_of_range", "sheet": SHEET, "col": "Revenue",
         "lo": 90000, "hi": 90100},
        {"kind": "refusal"},
        # sheet_sql reports `linked` on the abstain path too, so a refusal carries
        # binding evidence and is graded on it like any other answer.
        {"metric": "Revenue", "filters": [], "all_numeric": False},
        True,
    ),
}

# Each mutation takes a correct response and breaks it one way. They transform the
# whole response, not just `linked`, because an all-numeric plan certifies itself in
# `linked` and can only be caught against the columns it actually delivered.
MUTATIONS = {
    "wrong column": lambda got: {**got, "linked": {**got["linked"],
                                                   "metric": "__nope__",
                                                   "filters": [],
                                                   "all_numeric": False}},
    "wrong sheet": lambda got: {**got, "linked": {**got["linked"], "sheet": WRONG_SHEET}},
    "bound nothing": lambda got: {**got, "linked": {}},
}

# Families whose correct answer carries per-column results. The all-numeric branch
# below can only be graded for these, so they are selected by construction rather
# than skipped at runtime (R-0002: a gate that skips itself is not a gate).
PER_COLUMN_FAMILIES = sorted(
    fam for fam, (_c, exp, _l, refused) in CASES.items()
    if not refused and exp.get("kind") == "per_column"
)


def _per_column(exp: dict) -> list[dict] | None:
    """The columns a real answer would carry back, from the oracle's own expectation."""
    if exp.get("kind") != "per_column":
        return None
    return [{"column": c, "value": v, "sql": "SELECT 1"}
            for c, v in exp["per_column"].items()]


def _got(linked: dict, *, refused: bool, exp: dict | None = None) -> dict:
    return {
        "abstained": refused,
        "value": None if refused else 42.0,
        "per_column": None if refused else _per_column(exp or {}),
        "linked": linked,
        "sql": "SELECT 1",
        "sheet": linked.get("sheet"),
    }


def test_every_family_has_a_mutation_case():
    """A family added to the bench must arrive here, not slip past unchecked."""
    assert set(CASES) == set(ob.FAMILIES), (
        f"mutation table {sorted(CASES)} != oracle_bench.FAMILIES {sorted(ob.FAMILIES)}"
    )


@pytest.mark.parametrize("family", ob.FAMILIES)
def test_correct_binding_passes(family):
    """Positive control: without this the gate below could pass on a scorer that
    only ever returns False, which is R-0007 pointing the other way."""
    case, exp, linked, refused = CASES[family]
    ok, why = ob.link_check(
        case, exp, _got({"sheet": SHEET, **linked}, refused=refused, exp=exp)
    )
    assert ok is True, f"{family}: correct binding scored False ({why})"


@pytest.mark.parametrize("family", ob.FAMILIES)
@pytest.mark.parametrize("mutation", sorted(MUTATIONS))
def test_wrong_binding_fails(family, mutation):
    case, exp, linked, refused = CASES[family]
    good = _got({"sheet": SHEET, **linked}, refused=refused, exp=exp)
    broken = MUTATIONS[mutation](good)
    ok, why = ob.link_check(case, exp, broken)
    assert ok is False, (
        f"{family} scores schema-link True with a {mutation} response "
        f"({broken['linked']}, per_column={broken.get('per_column')}) - the family "
        f"cannot fail and must not be reported. why={why!r}"
    )


def test_a_family_actually_delivers_per_column():
    """Guards the selection below: if this list ever empties, the all-numeric
    mutation would cover nothing while still reporting green."""
    assert PER_COLUMN_FAMILIES, (
        "no family delivers per_column, so the all-numeric branch is ungraded"
    )


@pytest.mark.parametrize("family", PER_COLUMN_FAMILIES)
def test_all_numeric_plan_must_deliver_what_it_claims(family):
    """An all-numeric plan certifies itself in `linked`, so grading it against the
    sheet's numeric columns is circular for row_range_nocol - that set IS the
    required set. Grade it against the columns actually returned instead.

    The three mutations above all flip `all_numeric` off or blank `linked`, so they
    route around the branch the lane really takes: sheet_sql sets all_numeric
    whenever no column is named. Without this case the branch stays unfalsifiable.
    """
    case, exp, linked, _refused = CASES[family]
    good = _got({"sheet": SHEET, **linked, "all_numeric": True}, refused=False, exp=exp)
    assert good["per_column"], f"{family}: fixture delivers no columns to break"
    ok, _why = ob.link_check(case, exp, good)
    assert ok is True, f"{family}: a fully delivered all-numeric plan must score True"

    broken = {**good, "per_column": good["per_column"][:1]}
    ok, why = ob.link_check(case, exp, broken)
    assert ok is False, (
        f"{family} scores schema-link True on an all-numeric plan that delivered only "
        f"{[c['column'] for c in broken['per_column']]} of "
        f"{[c['column'] for c in good['per_column']]} - the claim is self-certifying "
        f"and cannot fail. why={why!r}"
    )


@pytest.mark.parametrize("family", ob.FAMILIES)
def test_no_answer_is_not_recall(family):
    """`None` carries no binding evidence, so it cannot count for any family -
    including out_of_range, where a refusal is the right *value* but says nothing
    about whether the schema was ever resolved."""
    case, exp, _linked, _refused = CASES[family]
    ok, why = ob.link_check(case, exp, None)
    assert ok is False, f"{family}: no answer scored as schema-link recall ({why})"


# --------------------------------------------------------------------------
# The retained artifacts were scored under the old rule and will move. They are
# re-scored, never hand-edited, so until that happens their schema-link figures
# must be unquotable rather than merely wrong.
# --------------------------------------------------------------------------
def _pack_payload(rule: int | None) -> dict:
    fams = {fam: {"n": 2, "ok": 2, "linked": 2, "abstained": 0} for fam in ob.FAMILIES}
    payload = {
        "ok": True,
        "workbook": "p50_01_sales_messy.xlsx",
        "seed": 1,
        "n": 14,
        "variants": [
            {
                "name": name,
                "n": 14,
                "correct": 14,
                "value_accuracy": 1.0,
                "malformed_ask_rate": 0.0,
                "abstention_rate": 0.0,
                "schema_link_accuracy": {fam: 1.0 for fam in ob.FAMILIES},
                "by_family": fams,
            }
            for name in ob.CROSS_VARIANTS
        ],
    }
    if rule is not None:
        payload["schema_link_rule"] = rule
    return payload


def test_pooling_a_pre_fix_artifact_withholds_schema_link():
    pooled = ob.aggregate_cross_pack([_pack_payload(None)])
    assert pooled["schema_link_withheld"], "unstamped payload pooled as if current"
    assert "pre-fix" in pooled["schema_link_withheld"]
    for v in pooled["variants"]:
        assert set(v["schema_link_accuracy"]) == set(ob.FAMILIES), (
            "families must stay listed - a missing cell reads as an oversight"
        )
        for fam, val in v["schema_link_accuracy"].items():
            assert val is None, f"{v['name']} {fam} quoted {val} from a pre-fix run"


def test_pooling_a_current_artifact_reports_schema_link():
    """Positive control: the guard must let a re-scored pack through."""
    pooled = ob.aggregate_cross_pack([_pack_payload(ob.SCHEMA_LINK_RULE)])
    assert pooled["schema_link_withheld"] is None
    for v in pooled["variants"]:
        for fam in ob.FAMILIES:
            assert v["schema_link_accuracy"][fam] == 1.0


def test_retained_primary50_schema_link_is_not_quotable():
    """The committed pack predates the fix. Either it carries the current stamp
    (someone re-scored it) or the aggregator refuses to report its schema-link.
    There is no third state where the old 1.000s are quotable."""
    payloads = []
    for _wb, _seed, name in ob.PRIMARY50_BOOKS:
        path = RAG / "results" / name
        assert path.is_file(), f"missing {path.as_posix()}"
        payloads.append(json.loads(path.read_text(encoding="utf-8")))
    pooled = ob.aggregate_cross_pack(payloads)
    if all(p.get("schema_link_rule") == ob.SCHEMA_LINK_RULE for p in payloads):
        assert pooled["schema_link_withheld"] is None
        return
    assert pooled["schema_link_withheld"], (
        "pack was scored under an older schema_link_rule but pooled its "
        "schema-link figures anyway"
    )
    for v in pooled["variants"]:
        assert all(val is None for val in v["schema_link_accuracy"].values())

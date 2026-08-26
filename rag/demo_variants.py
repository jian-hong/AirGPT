"""Named demo RAG variants for live click-through without re-ingest.

Selecting a variant only updates space config + depth_default.
Never deletes tests/RAG/results/* score artifacts.
"""
from __future__ import annotations

from typing import Any

from rag import store

# Retrieve-time presets (ingest stays put). hybrid_sql is answered in bench/eval lane
# and optionally via answer() when config.hybrid_sql_lane is true.
PRESETS: dict[str, dict[str, Any]] = {
    "baseline_basic": {
        "label": "baseline (no SiRA expand)",
        "depth": "basic",
        "hybrid_sql_lane": False,
    },
    "sira_high": {
        "label": "SiRA-enrich high",
        "depth": "high",
        "hybrid_sql_lane": False,
    },
    "sira_max": {
        "label": "SiRA-enrich max",
        "depth": "max",
        "hybrid_sql_lane": False,
    },
    "hybrid_max": {
        "label": "hybrid SQL+SiRA max",
        "depth": "max",
        "hybrid_sql_lane": True,
    },
    "adaptive": {
        "label": "adaptive depth",
        "depth": "auto",
        "hybrid_sql_lane": False,
    },
}

HONESTY = "Cortex-direct, not OpenVault-gated (EPIC-D01 demo path)."


def list_variants() -> dict:
    return {
        "ok": True,
        "honesty": HONESTY,
        "variants": [
            {"name": k, **{kk: vv for kk, vv in v.items()}}
            for k, v in PRESETS.items()
        ],
        "score_artifacts": [
            "tests/RAG/results/oracle_cross_latest.json",
            "tests/RAG/results/frtr_cross_latest.json",
            "tests/RAG/results/frtr_cross_latest.xlsx",
            "tests/RAG/results/warehouse_hybrid_latest.json",
            "tests/RAG/results/warehouse_hybrid_latest.xlsx",
        ],
    }


def select_variant(space_id: int, name: str) -> dict:
    key = (name or "").strip().lower()
    if key not in PRESETS:
        return {"ok": False, "error": f"unknown variant {name!r}", "known": list(PRESETS)}
    preset = PRESETS[key]
    space = store.get_space(space_id)
    if not space:
        return {"ok": False, "error": "space not found"}
    cfg = dict(space.get("config") or {}) if isinstance(space.get("config"), dict) else {}
    cfg["demo_variant"] = key
    cfg["hybrid_sql_lane"] = bool(preset["hybrid_sql_lane"])
    cfg["honesty"] = HONESTY
    # Do not touch score files. Do not re-ingest.
    updated = store.update_space_settings(
        space_id,
        depth_default=str(preset["depth"]),
        config=cfg,
    )
    return {
        "ok": True,
        "honesty": HONESTY,
        "variant": key,
        "preset": preset,
        "space": updated,
        "note": "Scores in tests/RAG/results/ preserved; no force re-ingest.",
    }


def resolve_for_space(space_id: int) -> dict[str, Any]:
    space = store.get_space(space_id) or {}
    cfg = space.get("config") if isinstance(space.get("config"), dict) else {}
    name = str((cfg or {}).get("demo_variant") or "").strip().lower()
    if name in PRESETS:
        return {"name": name, **PRESETS[name], "honesty": HONESTY}
    depth = str(space.get("depth_default") or "high")
    return {
        "name": "custom",
        "label": "space depth_default",
        "depth": depth,
        # Default ON for a real space. Only the hybrid_max PRESET set this True, so
        # every space a founder actually creates fell through to retrieval and never
        # reached the SQL lane at all - the 0.9441 numeric answer, and the whole
        # engine measured at 720/720, were unreachable in the product. The bench
        # calls sheet_sql directly, so nothing caught it (R-0001).
        #
        # Safe to default on: _try_hybrid_sql_lane returns None when it cannot plan
        # the ask, and the caller falls straight through to retrieval. An explicit
        # False is still honoured, which is what keeps the demo variants comparable -
        # sira_max vs hybrid_max exists precisely to A/B this lane.
        "hybrid_sql_lane": bool((cfg or {}).get("hybrid_sql_lane", True)),
        "honesty": HONESTY,
    }

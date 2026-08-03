"""Workbook ontology from sheet semantics (columns / entities / relations).

Form first; answer path shows logic steps that cite ontology ids — not blind RAG.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from rag import store

_ENTITY_HINTS = {
    "sku": "SKU",
    "product": "Product",
    "region": "Region",
    "vendor": "Vendor",
    "category": "Category",
    "employee": "Employee",
    "salary": "Compensation",
    "invoice": "Invoice",
    "po": "PurchaseOrder",
    "qty": "Quantity",
    "quantity": "Quantity",
    "revenue": "Money",
    "sales": "Money",
    "cost": "Money",
    "margin": "Money",
    "date": "Temporal",
    "quarter": "Temporal",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").strip().lower()).strip("_")


def ontology_from_xlsx(path: str | Path) -> dict[str, Any]:
    """Derive a lightweight ontology from one workbook's sheet headers + samples."""
    import openpyxl

    p = Path(path)
    wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
    sheets: list[dict] = []
    entities: dict[str, dict] = {}
    relations: list[dict] = []
    try:
        for name in wb.sheetnames:
            ws = wb[name]
            rows = ws.iter_rows(values_only=True)
            try:
                header = next(rows)
            except StopIteration:
                continue
            cols = []
            for i, h in enumerate(header or []):
                if h is None or not str(h).strip():
                    continue
                label = str(h).strip()
                key = _norm(label)
                ent = "Unknown"
                for tip, kind in _ENTITY_HINTS.items():
                    if tip in key:
                        ent = kind
                        break
                cols.append({"name": label, "key": key, "entity": ent, "index": i})
                entities.setdefault(
                    ent,
                    {"id": ent, "kind": "Entity", "columns": [], "sheets": []},
                )
                if label not in entities[ent]["columns"]:
                    entities[ent]["columns"].append(label)
                if name not in entities[ent]["sheets"]:
                    entities[ent]["sheets"].append(name)
            # sample up to 3 data rows for type sniff
            samples = []
            for j, row in enumerate(rows):
                if j >= 3:
                    break
                samples.append([("" if c is None else c) for c in (row or ())])
            sheets.append(
                {
                    "name": name,
                    "columns": cols,
                    "n_sample_rows": len(samples),
                    "sample": samples,
                }
            )
            # same-workbook FK-ish: shared column keys across sheets
            for other in sheets[:-1]:
                keys_a = {c["key"] for c in cols}
                keys_b = {c["key"] for c in other["columns"]}
                shared = keys_a & keys_b
                for k in sorted(shared):
                    if k in {"sku", "vendor", "region", "category", "employee", "po_id", "id"}:
                        relations.append(
                            {
                                "id": f"{other['name']}.{k}->{name}.{k}",
                                "from_sheet": other["name"],
                                "to_sheet": name,
                                "key": k,
                                "type": "join_candidate",
                            }
                        )
    finally:
        wb.close()

    return {
        "ok": True,
        "source": str(p.resolve()),
        "workbook": p.name,
        "formed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sheets": sheets,
        "entities": list(entities.values()),
        "relations": relations,
        "summary": {
            "n_sheets": len(sheets),
            "n_entities": len(entities),
            "n_relations": len(relations),
            "entity_ids": sorted(entities.keys()),
        },
    }


def ontology_for_space(space_id: int, *, force: bool = False) -> dict[str, Any]:
    """Build + cache ontology for all xlsx sources in a space."""
    space = store.get_space(int(space_id))
    if not space:
        return {"ok": False, "error": "space not found"}
    cfg = dict(space.get("config") or {}) if isinstance(space.get("config"), dict) else {}
    cached = cfg.get("ontology")
    if cached and not force and isinstance(cached, dict) and cached.get("workbooks"):
        return {"ok": True, "cached": True, **cached}

    workbooks = []
    for src in store.list_sources(int(space_id)):
        path = str(src.get("path") or "")
        if not path.lower().endswith((".xlsx", ".xlsm", ".xls")):
            continue
        if not Path(path).is_file():
            continue
        try:
            workbooks.append(ontology_from_xlsx(path))
        except Exception as e:
            workbooks.append({"ok": False, "source": path, "error": str(e)[:200]})

    # merge entities
    merged_entities: dict[str, dict] = {}
    merged_relations: list[dict] = []
    for w in workbooks:
        if not w.get("ok"):
            continue
        for ent in w.get("entities") or []:
            eid = ent["id"]
            slot = merged_entities.setdefault(
                eid, {"id": eid, "kind": "Entity", "columns": [], "sheets": [], "workbooks": []}
            )
            for c in ent.get("columns") or []:
                if c not in slot["columns"]:
                    slot["columns"].append(c)
            for s in ent.get("sheets") or []:
                if s not in slot["sheets"]:
                    slot["sheets"].append(s)
            wbname = w.get("workbook")
            if wbname and wbname not in slot["workbooks"]:
                slot["workbooks"].append(wbname)
        merged_relations.extend(w.get("relations") or [])

    payload = {
        "formed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "space_id": int(space_id),
        "workbooks": workbooks,
        "entities": list(merged_entities.values()),
        "relations": merged_relations[:200],
        "summary": {
            "n_workbooks": len([w for w in workbooks if w.get("ok")]),
            "n_entities": len(merged_entities),
            "n_relations": len(merged_relations),
            "entity_ids": sorted(merged_entities.keys()),
        },
    }
    cfg["ontology"] = payload
    try:
        store.update_space_settings(int(space_id), config=cfg)
    except Exception:
        pass
    return {"ok": True, "cached": False, **payload}


def logic_for_query(ontology: dict[str, Any], query: str) -> list[dict[str, str]]:
    """Produce visible reasoning steps that cite ontology entities."""
    q = (query or "").lower()
    steps: list[dict[str, str]] = []
    ents = {e["id"]: e for e in (ontology.get("entities") or []) if isinstance(e, dict)}
    steps.append({"step": "1", "op": "load_ontology", "detail": f"entities={sorted(ents.keys())}"})

    mapped: list[str] = []
    for eid, ent in ents.items():
        blob = (eid + " " + " ".join(ent.get("columns") or [])).lower()
        if any(tok in blob for tok in re.findall(r"[a-z]{3,}", q)):
            mapped.append(eid)
    if re.search(r"\bsku\b|selling|top\s+\d+", q):
        mapped.extend(["SKU", "Money"])
    if re.search(r"salary|increment|raise", q):
        mapped.extend(["Compensation", "Employee"])
    if re.search(r"average|total|sales|revenue", q):
        mapped.append("Money")
    mapped = list(dict.fromkeys([m for m in mapped if m in ents or True]))
    mapped = [m for m in mapped if m in ents] or mapped[:4]
    steps.append(
        {
            "step": "2",
            "op": "bind_entities",
            "detail": ", ".join(mapped) or "(none — fall back to retrieve)",
        }
    )

    rels = ontology.get("relations") or []
    useful = [r for r in rels if str(r.get("key") or "") in q or ("sku" in q and r.get("key") == "sku")]
    steps.append(
        {
            "step": "3",
            "op": "use_relations",
            "detail": ("; ".join(r.get("id") or "" for r in useful[:5]) if useful else "none required"),
        }
    )
    if re.search(r"\btop\s+\d+|average|total|sum|increment|salary", q):
        steps.append(
            {
                "step": "4",
                "op": "select_logic",
                "detail": "structured hybrid_sql / aggregate over bound Money|SKU sheets",
            }
        )
    else:
        steps.append({"step": "4", "op": "select_logic", "detail": "retrieve + grounded generate"})
    steps.append({"step": "5", "op": "answer", "detail": "emit answer citing ontology + sources"})
    return steps


def save_ontology_artifact(space_id: int, dest: Path | None = None) -> Path:
    out = ontology_for_space(space_id, force=True)
    root = Path(__file__).resolve().parents[1] / "tests" / "RAG" / "results"
    root.mkdir(parents=True, exist_ok=True)
    path = dest or (root / f"ontology_space_{space_id}.json")
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return path

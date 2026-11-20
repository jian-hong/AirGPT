"""The ontology is induced from cell values, not from a header vocabulary.

Each test names the way the previous keyword-list ontology (17 English hints and
a fixed list of seven join keys) got this wrong, or a way the value-based one
could over-claim.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import openpyxl

from rag import ontology


def _book(path: Path, sheets: dict[str, list[list]]) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    wb.save(path)
    return path


def _rels(ont: dict) -> set[tuple[str, str, str]]:
    return {(r["type"], f"{r['from_sheet']}.{r['from_column']}", f"{r['to_sheet']}.{r['to_column']}")
            for r in ont["relations"]}


def _cols(ont: dict, sheet: str) -> dict[str, dict]:
    for w in ont["workbooks"]:
        for t in w.get("sheets") or []:
            if t["name"] == sheet:
                return {c["name"]: c for c in t["columns"]}
    raise AssertionError(f"no sheet {sheet}")


class OntologyTests(unittest.TestCase):
    def setUp(self) -> None:
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.dir = Path(td.name)

    def test_relation_found_without_any_known_vocabulary(self):
        """Malay headers: none of the old hint words, none of the old join keys."""
        p = _book(self.dir / "stok.xlsx", {
            "Pembekal": [["kod_pembekal", "nama"]] + [[f"P-{i:03d}", f"Syarikat {i}"] for i in range(12)],
            "Pesanan": [["tarikh", "pembekal", "jumlah"]]
            + [[f"2026-01-{d:02d}", f"P-{d % 12:03d}", 100.5 + d] for d in range(1, 29)],
        })
        ont = ontology.build_ontology([p])
        self.assertIn(("foreign_key", "Pesanan.pembekal", "Pembekal.kod_pembekal"), _rels(ont))
        self.assertEqual(sorted(e["id"] for e in ont["entities"]), ["Pembekal", "Pesanan"])
        self.assertNotIn("Unknown", ont["summary"]["entity_ids"])
        orders = _cols(ont, "Pesanan")
        self.assertEqual(orders["tarikh"]["role"], "temporal")
        self.assertEqual(orders["tarikh"]["format"], "%Y-%m-%d")
        self.assertEqual(orders["jumlah"]["role"], "measure")
        grain = {t["name"]: t["grain"] for w in ont["workbooks"] for t in w["sheets"]}
        self.assertEqual(grain, {"Pembekal": "entity", "Pesanan": "fact"})

    def test_banner_row_is_not_the_header(self):
        """First-row-wins bound the banner as the header (the F28a class)."""
        p = _book(self.dir / "banner.xlsx", {
            "Stock": [["Confidential - warehouse stock report Q3"], ["item", "bin", "units"]]
            + [[f"I{i}", f"B{i % 4}", i * 3] for i in range(10)],
        })
        self.assertEqual(sorted(_cols(ontology.build_ontology([p]), "Stock")), ["bin", "item", "units"])

    def test_small_numbers_inside_a_row_counter_are_not_a_relation(self):
        p = _book(self.dir / "counter.xlsx", {
            "Lines": [["line_no", "label"]] + [[i, f"row {i}"] for i in range(1, 41)],
            "Picks": [["shelf", "qty"]] + [[f"S{i}", (i % 9) + 1] for i in range(30)],
        })
        ont = ontology.build_ontology([p])
        self.assertEqual(_cols(ont, "Lines")["line_no"]["role"], "key")
        self.assertEqual(ont["relations"], [])

    def test_same_name_with_disjoint_values_is_not_a_relation(self):
        """The old join list linked any two sheets that both had a `sku` column."""
        p = _book(self.dir / "disjoint.xlsx", {
            "A": [["sku", "x"]] + [[f"A-{i}", i] for i in range(10)],
            "B": [["sku", "y"]] + [[f"B-{i % 5}", i] for i in range(10)],
        })
        self.assertEqual(ontology.build_ontology([p])["relations"], [])

    def test_unique_amounts_are_a_measure_not_a_key(self):
        p = _book(self.dir / "amounts.xlsx", {
            "Ledger": [["memo", "amount"]] + [[f"m{i % 3}", 1000 + i * 37] for i in range(15)],
        })
        ledger = _cols(ontology.build_ontology([p]), "Ledger")
        self.assertTrue(ledger["amount"]["is_unique"])
        self.assertEqual(ledger["amount"]["role"], "measure")

    def test_relation_across_workbooks_and_csv(self):
        master = _book(self.dir / "master.xlsx", {
            "Parts": [["part", "desc"]] + [[f"PT{i}", f"part {i}"] for i in range(8)],
        })
        usage = self.dir / "usage.csv"
        usage.write_text("part,used\n" + "".join(f"PT{i % 8},{i}\n" for i in range(20)), encoding="utf-8")
        ont = ontology.build_ontology([master, usage])
        self.assertIn(("foreign_key", "usage.part", "Parts.part"), _rels(ont))
        self.assertTrue(any(r["id"].startswith("usage.csv:usage.part->master.xlsx:Parts") for r in ont["relations"]))

    def test_unreadable_file_is_reported_not_dropped(self):
        bad = self.dir / "broken.xlsx"
        bad.write_bytes(b"not a zip")
        ont = ontology.build_ontology([bad])
        self.assertEqual(ont["summary"]["n_failed"], 1)
        self.assertFalse(ont["workbooks"][0]["ok"])
        self.assertTrue(ont["workbooks"][0]["error"])

    def test_logic_cites_only_entities_the_ontology_holds(self):
        """The old steps bound "SKU" and "Money" by regex even when neither existed."""
        p = _book(self.dir / "hr.xlsx", {
            "Staff": [["badge", "team", "hours"]] + [[f"E{i}", f"T{i % 3}", 30 + i] for i in range(9)],
        })
        ont = ontology.build_ontology([p])
        steps = {s["op"]: s["detail"] for s in ontology.logic_for_query(ont, "top 5 sku by sales")}
        self.assertEqual(steps["bind_entities"], "(none - fall back to retrieve)")
        self.assertEqual(steps["select_logic"], "retrieve + grounded generate")
        steps = {s["op"]: s["detail"] for s in ontology.logic_for_query(ont, "total hours per team")}
        self.assertEqual(steps["bind_entities"], "Staff")
        self.assertIn("hours", steps["select_logic"])

    def test_cache_follows_the_source_files(self):
        """The cached ontology used to survive a new workbook until `force`."""
        a = _book(self.dir / "a.xlsx", {"Parts": [["part", "d"]] + [[f"PT{i}", i] for i in range(6)]})
        space = {"id": 1, "config": {}}
        sources = [{"path": str(a)}]

        def save(_sid, config):
            space["config"] = config

        with mock.patch.object(ontology.store, "get_space", lambda _sid: space), \
             mock.patch.object(ontology.store, "list_sources", lambda _sid: sources), \
             mock.patch.object(ontology.store, "update_space_settings", save):
            first = ontology.ontology_for_space(1)
            self.assertFalse(first["cached"])
            self.assertTrue(ontology.ontology_for_space(1)["cached"])

            b = _book(self.dir / "b.xlsx", {"Use": [["part", "n"]] + [[f"PT{i % 6}", i] for i in range(12)]})
            sources.append({"path": str(b)})
            third = ontology.ontology_for_space(1)
            self.assertFalse(third["cached"])
            self.assertEqual(third["summary"]["n_workbooks"], 2)
            self.assertEqual(third["summary"]["n_relations"], 1)

            # A v1 payload left in a space's config must not be served as current.
            space["config"] = {"ontology": {"workbooks": [{"ok": True}], "summary": {"n_entities": 99}}}
            self.assertFalse(ontology.ontology_for_space(1)["cached"])


if __name__ == "__main__":
    unittest.main()

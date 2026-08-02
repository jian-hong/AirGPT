"""Generate 6 multi-sheet warehouse Excel workbooks with deterministic gold.

Workbook 01 embeds the Cortex demo Top-5/6 SKU revenue figures so hybrid_max
can prove the same answers without DMS confirm loops.
"""
from __future__ import annotations

import json
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "warehouse"
GOLD = ROOT / "results" / "warehouse_gold.json"

# Cortex live demo figures (MYR) — keep exact for cross-check narrative
TOP_SKUS = [
    ("SKU-00397", 726158.36),
    ("SKU-00183", 581836.43),
    ("SKU-00171", 538139.25),
    ("SKU-00381", 531252.23),
    ("SKU-00016", 492673.84),
    ("SKU-00351", 486982.89),
    ("SKU-00220", 410111.10),
    ("SKU-00410", 390222.20),
    ("SKU-00055", 350000.00),
    ("SKU-00102", 320500.50),
]


def _wb() -> openpyxl.Workbook:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    return wb


def _sheet(wb, name: str, headers: list[str], rows: list[list]):
    ws = wb.create_sheet(name[:31])
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    return ws


def build_01_sales_core() -> Path:
    wb = _wb()
    master = []
    sales_rows = []
    for i, (sku, val) in enumerate(TOP_SKUS, start=1):
        cat = ["Electronics", "Grocery", "Apparel", "Home", "Sports"][i % 5]
        master.append([sku, f"Item {sku[-3:]}", cat, "MYR", round(val / 100, 2)])
        # Split revenue across 3 lines so aggregation is required
        parts = [round(val * 0.5, 2), round(val * 0.3, 2), round(val - val * 0.5 - val * 0.3, 2)]
        for j, p in enumerate(parts, start=1):
            sales_rows.append([f"2024-0{(j % 9) + 1}-15", sku, cat, "West" if j % 2 else "East", p])
    # filler low SKUs
    for n in range(20, 40):
        sku = f"SKU-{n:05d}"
        master.append([sku, f"Filler {n}", "Misc", "MYR", 10.0])
        sales_rows.append([f"2024-06-{n % 27 + 1:02d}", sku, "Misc", "Central", float(n * 100)])

    _sheet(wb, "SKU_Master", ["sku", "name", "category", "currency", "unit_cost"], master)
    _sheet(wb, "Sales", ["date", "sku", "category", "region", "sales_value_myr"], sales_rows)
    # Summary KPIs
    total = sum(v for _, v in TOP_SKUS) + sum(n * 100 for n in range(20, 40))
    _sheet(
        wb,
        "Summary",
        ["metric", "value"],
        [
            ["sku_count_master", len(master)],
            ["sales_line_count", len(sales_rows)],
            ["total_sales_myr", round(total, 2)],
            ["top1_sku", TOP_SKUS[0][0]],
            ["top1_value", TOP_SKUS[0][1]],
        ],
    )
    path = OUT / "wh_01_sales_core.xlsx"
    wb.save(path)
    return path


def build_02_inventory() -> Path:
    wb = _wb()
    rows = []
    for i, (sku, _) in enumerate(TOP_SKUS):
        rows.append([sku, ["A1", "B2", "C3", "D4"][i % 4], 100 + i * 17, 12.5 + i, (100 + i * 17) * (12.5 + i)])
    for n in range(20, 35):
        sku = f"SKU-{n:05d}"
        rows.append([sku, "Z9", n, 5.0, n * 5.0])
    _sheet(wb, "Inventory", ["sku", "bin", "qty", "unit_cost", "stock_value"], rows)
    _sheet(
        wb,
        "ByCategory",
        ["category", "sku_count", "stock_value"],
        [
            ["Electronics", 2, 50000],
            ["Grocery", 2, 42000],
            ["Apparel", 2, 38000],
            ["Home", 2, 36000],
            ["Sports", 2, 34000],
            ["Misc", 15, 1500],
        ],
    )
    _sheet(wb, "Summary", ["metric", "value"], [["total_stock_value", sum(r[4] for r in rows)], ["sku_count", len(rows)]])
    path = OUT / "wh_02_inventory.xlsx"
    wb.save(path)
    return path


def build_03_returns() -> Path:
    wb = _wb()
    reasons = ["damaged", "wrong_item", "late", "customer_change"]
    rows = []
    for i, (sku, val) in enumerate(TOP_SKUS[:6]):
        rows.append([f"R-{i+1:04d}", sku, reasons[i % 4], round(val * 0.02, 2), f"2024-0{(i % 9)+1}-20"])
    _sheet(wb, "Returns", ["return_id", "sku", "reason", "refund_myr", "date"], rows)
    _sheet(
        wb,
        "Summary",
        ["metric", "value"],
        [["return_count", len(rows)], ["total_refund_myr", round(sum(r[3] for r in rows), 2)]],
    )
    path = OUT / "wh_03_returns.xlsx"
    wb.save(path)
    return path


def build_04_regions() -> Path:
    wb = _wb()
    regions = ["West", "East", "Central", "North", "South"]
    rows = []
    for i, (sku, val) in enumerate(TOP_SKUS):
        for j, reg in enumerate(regions):
            rows.append([reg, sku, round(val * (0.15 + 0.05 * ((i + j) % 4)), 2)])
    _sheet(wb, "RegionalSales", ["region", "sku", "sales_value_myr"], rows)
    # West should dominate for top sku
    by_reg = {}
    for reg, sku, v in rows:
        by_reg[reg] = by_reg.get(reg, 0) + v
    _sheet(wb, "Summary", ["region", "total_sales_myr"], [[r, round(v, 2)] for r, v in sorted(by_reg.items())])
    path = OUT / "wh_04_regions.xlsx"
    wb.save(path)
    return path


def build_05_purchase_orders() -> Path:
    wb = _wb()
    vendors = ["Acme Supply", "Globex", "Initech", "Umbrella"]
    rows = []
    for i, (sku, val) in enumerate(TOP_SKUS[:8]):
        rows.append([f"PO-100{i}", vendors[i % 4], sku, 10 + i, round(val / 50, 2), "open" if i % 3 else "closed"])
    _sheet(wb, "PurchaseOrders", ["po_id", "vendor", "sku", "qty", "unit_cost", "status"], rows)
    _sheet(wb, "Vendors", ["vendor", "lead_days", "rating"], [[v, 7 + i, 4.0 - i * 0.2] for i, v in enumerate(vendors)])
    _sheet(wb, "Summary", ["metric", "value"], [["open_po_count", sum(1 for r in rows if r[5] == "open")], ["po_count", len(rows)]])
    path = OUT / "wh_05_purchase_orders.xlsx"
    wb.save(path)
    return path


def build_06_margin_mix() -> Path:
    wb = _wb()
    rows = []
    for sku, val in TOP_SKUS:
        cost = round(val * 0.55, 2)
        margin = round(val - cost, 2)
        rows.append([sku, val, cost, margin, round(margin / val * 100, 2)])
    _sheet(wb, "MarginBySku", ["sku", "sales_value_myr", "cogs_myr", "margin_myr", "margin_pct"], rows)
    best = max(rows, key=lambda r: r[3])
    _sheet(
        wb,
        "Summary",
        ["metric", "value"],
        [["best_margin_sku", best[0]], ["best_margin_myr", best[3]], ["avg_margin_pct", round(sum(r[4] for r in rows) / len(rows), 2)]],
    )
    path = OUT / "wh_06_margin_mix.xlsx"
    wb.save(path)
    return path


def gold_questions() -> list[dict]:
    top5 = TOP_SKUS[:5]
    top6 = TOP_SKUS[:6]
    top5_ex = [x for x in TOP_SKUS if x[0] != "SKU-00397"][:5]
    fmt = lambda pairs: " | ".join(f"{s}: {v}" for s, v in pairs)
    return [
        {
            "workbook": "wh_01_sales_core.xlsx",
            "qid": 1,
            "question": "Top 5 selling SKUs by revenue",
            "difficulty": "Hard",
            "reasoning_type": "TopN",
            "gold": fmt(top5),
            "gold_values": [s for s, _ in top5] + [str(v) for _, v in top5],
            "notes": "no confirm loop",
        },
        {
            "workbook": "wh_01_sales_core.xlsx",
            "qid": 2,
            "question": "what about top 6",
            "difficulty": "Hard",
            "reasoning_type": "TopNFollowup",
            "gold": fmt(top6),
            "gold_values": [s for s, _ in top6] + [str(v) for _, v in top6],
            "notes": "follow-up N=6",
        },
        {
            "workbook": "wh_01_sales_core.xlsx",
            "qid": 3,
            "question": "Top 5 selling SKUs by revenue excluding SKU-00397",
            "difficulty": "Hard",
            "reasoning_type": "TopNExclude",
            "gold": fmt(top5_ex),
            "gold_values": [s for s, _ in top5_ex] + [str(v) for _, v in top5_ex],
            "notes": "explicit SKU exclude — never ask confirm",
        },
        {
            "workbook": "wh_01_sales_core.xlsx",
            "qid": 4,
            "question": "No — show top 5 sales without excluding",
            "difficulty": "Hard",
            "reasoning_type": "TopNNoExclude",
            "gold": fmt(top5),
            "gold_values": [s for s, _ in top5] + [str(v) for _, v in top5],
            "notes": "button-echo / cancel exclude — treat as plain top 5, never loop",
        },
        {
            "workbook": "wh_01_sales_core.xlsx",
            "qid": 5,
            "question": "removing the first one, show me top 5",
            "difficulty": "Hard",
            "reasoning_type": "TopNExcludeFirst",
            "gold": fmt(top5_ex),
            "gold_values": [s for s, _ in top5_ex] + [str(v) for _, v in top5_ex],
            "notes": "first=current #1 SKU-00397; act once, no auto-send confirm",
        },
        {
            "workbook": "wh_02_inventory.xlsx",
            "qid": 6,
            "question": "How many SKUs do we have in inventory?",
            "difficulty": "Easy",
            "reasoning_type": "Count",
            "gold": "25",
            "gold_values": ["25"],
            "notes": "",
        },
        {
            "workbook": "wh_02_inventory.xlsx",
            "qid": 7,
            "question": "What is total stock value by category?",
            "difficulty": "Medium",
            "reasoning_type": "GroupBy",
            "gold": "Electronics: 50000 | Grocery: 42000 | Apparel: 38000 | Home: 36000 | Sports: 34000 | Misc: 1500",
            "gold_values": ["50000", "42000", "38000", "36000", "34000", "1500"],
            "notes": "",
        },
        {
            "workbook": "wh_06_margin_mix.xlsx",
            "qid": 8,
            "question": "Which SKU has the highest margin dollars?",
            "difficulty": "Medium",
            "reasoning_type": "ArgMax",
            "gold": "SKU-00397",
            "gold_values": ["SKU-00397", "326771.26"],
            "notes": "",
        },
        {
            "workbook": "wh_05_purchase_orders.xlsx",
            "qid": 9,
            "question": "How many open purchase orders?",
            "difficulty": "Easy",
            "reasoning_type": "CountFilter",
            "gold": "5",
            "gold_values": ["5"],
            "notes": "",
        },
        {
            "workbook": "wh_03_returns.xlsx",
            "qid": 10,
            "question": "What is total refund value?",
            "difficulty": "Easy",
            "reasoning_type": "Sum",
            "gold": str(round(sum(v * 0.02 for _, v in TOP_SKUS[:6]), 2)),
            "gold_values": [str(round(sum(v * 0.02 for _, v in TOP_SKUS[:6]), 2))],
            "notes": "",
        },
    ]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (ROOT / "results").mkdir(parents=True, exist_ok=True)
    paths = [
        build_01_sales_core(),
        build_02_inventory(),
        build_03_returns(),
        build_04_regions(),
        build_05_purchase_orders(),
        build_06_margin_mix(),
    ]
    gold = gold_questions()
    GOLD.write_text(json.dumps(gold, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "files": [str(p.name) for p in paths], "gold_n": len(gold), "gold": str(GOLD)}, indent=2))


if __name__ == "__main__":
    main()

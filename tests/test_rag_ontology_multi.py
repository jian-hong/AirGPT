"""Ontology across scripts, date notations and file types. Fixtures are built by hand
(openpyxl, raw bytes), so nothing here needs python-docx, python-pptx or a model."""
from __future__ import annotations

import json
from unittest import mock

import openpyxl
import pytest

from rag import ontology

N = 30


def _book(path, sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    wb.save(path)
    return path


def _rels(ont):
    return {(r["type"], f"{r['from_sheet']}.{r['from_column']}", f"{r['to_sheet']}.{r['to_column']}")
            for r in ont["relations"]}


def _table(ont, sheet):
    for w in ont["workbooks"]:
        for t in w.get("sheets") or []:
            if t["name"] == sheet:
                return t
    raise AssertionError(sheet)


# ---- 1. keys ---------------------------------------------------------------------

@pytest.mark.parametrize("header,key", [
    ("客户编号", "客户编号"),
    ("Срок оплаты", "срок_оплаты"),
    ("رقم العميل", "رقم_العميل"),
    ("Número de pedido", "número_de_pedido"),
    ("Customer ID", "customer_id"),
    ("ＦＵＬＬ　ＷＩＤＴＨ", "full_width"),  # NFKC folds width variants
])
def test_keys_survive_non_latin_headers(header, key):
    assert ontology._norm(header) == key


def test_hindi_vowel_signs_do_not_cut_a_word():
    assert ontology._norm("ग्राहक संख्या") == "ग्राहक_संख्या"


def test_chinese_workbook_has_real_keys_and_a_named_relation(tmp_path):
    cust = [["客户编号", "姓名", "城市"]] + [[f"C{i:03d}", f"名{i}", "北京"] for i in range(N)]
    orders = [["订单号", "客户", "金额", "日期"]] + [[f"O{i:04d}", f"C{i % N:03d}", 100 + i * 3.5, f"2026年3月{i % 28 + 1}日"]
                                               for i in range(60)]
    ont = ontology.build_ontology([_book(tmp_path / "zh.xlsx", {"客户": cust, "订单": orders})])
    keys = [c["key"] for t in ont["workbooks"][0]["sheets"] for c in t["columns"]]
    assert "" not in keys and len(set(keys)) == len(keys)
    assert _rels(ont) == {("foreign_key", "订单.客户", "客户.客户编号")}
    assert "names agree" in ont["relations"][0]["evidence"]
    assert {c["name"]: c["role"] for c in _table(ont, "订单")["columns"]}["日期"] == "temporal"


def test_unrelated_non_latin_columns_do_not_agree_by_having_no_name(tmp_path):
    # Every column key used to be "", so these two counters "agreed" and the small
    # numbers 1..20 were taken as a foreign key into the customer ids.
    cust = [["客户编号", "姓名"]] + [[i, f"名{i}"] for i in range(1, 41)]
    other = [["数量", "备注"]] + [[(i % 20) + 1, f"注{i}"] for i in range(60)]
    ont = ontology.build_ontology([_book(tmp_path / "w.xlsx", {"客户": cust, "库存": other})])
    assert ont["relations"] == []


def test_other_entitys_id_column_is_not_a_foreign_key_just_because_both_end_in_id(tmp_path):
    # Old key of both "客户id" and "仓库id" was "id", so they "agreed" and the warehouse
    # numbers 1..20 were read as customer ids.
    cust = [["客户id", "姓名"]] + [[i, f"名{i}"] for i in range(1, 41)]
    stock = [["仓库id", "备注"]] + [[(i % 20) + 1, f"注{i}"] for i in range(60)]
    ont = ontology.build_ontology([_book(tmp_path / "w.xlsx", {"客户": cust, "库存": stock})])
    assert ont["relations"] == []


def test_numeric_chinese_ids_are_keys_and_join_when_named(tmp_path):
    cust = [["客户编号", "姓名"]] + [[1000 + i, f"名{i}"] for i in range(N)]
    orders = [["订单号", "客户编号", "金额"]] + [[i, 1000 + i % N, 5.5 + i] for i in range(60)]
    ont = ontology.build_ontology([_book(tmp_path / "w.xlsx", {"客户": cust, "订单": orders})])
    assert {c["name"]: c["role"] for c in _table(ont, "客户")["columns"]}["客户编号"] == "key"
    assert ("foreign_key", "订单.客户编号", "客户.客户编号") in _rels(ont)


def test_arabic_and_russian_leading_id_word_is_stripped(tmp_path):
    cust = [["رقم العميل", "الاسم"]] + [[1000 + i, f"اسم{i}"] for i in range(N)]
    orders = [["رقم الطلب", "العميل", "المبلغ"]] + [[i, 1000 + i % N, 5.5 + i] for i in range(60)]
    ont = ontology.build_ontology([_book(tmp_path / "w.xlsx", {"العميل": cust, "الطلب": orders})])
    assert ("foreign_key", "الطلب.العميل", "العميل.رقم العميل") in _rels(ont)
    assert ontology._id_stem("номер_заказа") == "заказа"


def test_a_header_with_no_letters_never_agrees_with_another(tmp_path):
    a = [["#", "x"]] + [[i, i] for i in range(1, 41)]
    b = [["?", "y"]] + [[(i % 20) + 1, i] for i in range(60)]
    assert ontology.build_ontology([_book(tmp_path / "w.xlsx", {"A": a, "B": b})])["relations"] == []


# ---- 2. tokens -------------------------------------------------------------------

def test_two_character_chinese_words_are_tokens():
    assert {"客户", "金额"} <= ontology._tokens("每个客户的金额总和是多少")
    assert "ab" not in ontology._tokens("ab")  # short Latin words stay out
    assert "customer" in ontology._tokens("customers")


def test_logic_binds_a_chinese_question(tmp_path):
    cust = [["客户编号", "姓名"]] + [[f"C{i:03d}", f"名{i}"] for i in range(N)]
    orders = [["订单号", "客户", "金额"]] + [[f"O{i:04d}", f"C{i % N:03d}", 5.5 + i] for i in range(60)]
    ont = ontology.build_ontology([_book(tmp_path / "w.xlsx", {"客户": cust, "订单": orders})])
    steps = {s["op"]: s["detail"] for s in ontology.logic_for_query(ont, "每个客户的金额总和是多少")}
    assert "订单" in steps["bind_entities"]
    assert "订单.客户->客户.客户编号" in steps["use_relations"]
    assert "structured aggregate" not in steps["select_logic"] or "金额" in steps["select_logic"]


def test_accented_word_is_one_token_and_term_name_keeps_it():
    assert "número" in ontology._tokens("Número")
    assert ontology.term_name("Clientes_Número", "w.xlsx") == "Clientes Número"


# ---- 3. dates --------------------------------------------------------------------

@pytest.mark.parametrize("vals", [
    ["2026年3月5日", "2026年12月31日", "2025年1月9日"],
    ["2026년 3월 5일", "2026년 12월 31일", "2025년 1월 9일"],
    ["5 mars 2026", "31 décembre 2025", "1er janvier 2026"],
    ["5 de março de 2026", "1 de enero de 2026", "30 setembro 2025"],
    ["5 März 2026", "3 Dez 2025", "9 Okt. 2025"],
    ["5 марта 2026", "1 января 2026", "31 декабря 2025"],
    ["5 مارس 2026", "1 يناير 2026", "31 ديسمبر 2025"],
    ["05.03.2026", "31.12.2025", "09.01.2025"],
    ["2026/3/5", "2025/12/31", "2025/1/9"],
    ["5 Sept 2026", "1 Sep 2026", "30 Sep 2025"],
])
def test_text_dates_in_many_languages_are_temporal(vals):
    prof, _ = ontology.profile_column("when", vals * 3)
    assert prof["role"] == "temporal" and prof["kind"] == "date", prof


@pytest.mark.parametrize("vals", [
    ["31 février 2026", "30 février 2026", "31 avril 2026"],   # not days
    ["5 marketing 2026", "3 marmalade 2025", "9 market 2025"],  # a word is not a month
    ["12 apples 2026", "40 mars 2026", "1 juin"],
    ["2026年13月5日", "2026年0月1日", "2026年2月30日"],
])
def test_not_dates(vals):
    prof, _ = ontology.profile_column("note", vals * 3)
    assert prof["role"] != "temporal"


def test_month_words_do_not_depend_on_the_process_locale():
    # strptime("%b") reads the locale; a French month on an English host failed on the old
    # code and the same would happen the other way round. The parser has no locale input.
    import locale

    saved = locale.setlocale(locale.LC_TIME)
    try:
        for name in ("C", "fr_FR.UTF-8", "de_DE.UTF-8"):
            try:
                locale.setlocale(locale.LC_TIME, name)
            except locale.Error:
                continue
            prof, _ = ontology.profile_column("d", ["5 mars 2026", "9 Mar 2026", "12 June 2026"] * 3)
            assert prof["kind"] == "date"
    finally:
        locale.setlocale(locale.LC_TIME, saved)


def test_ambiguous_prefix_names_no_month():
    assert "jui" not in ontology._MONTHS and ontology._MONTHS["juil"] == 7 and ontology._MONTHS["juin"] == 6


# ---- 4. file types ---------------------------------------------------------------

def _customers_xlsx(tmp_path):
    return _book(tmp_path / "customers.xlsx", {
        "Customers": [["customer_id", "name", "city"]] + [[f"C{i:03d}", f"n{i}", "KL"] for i in range(N)]})


def _orders_csv(tmp_path):
    lines = ["order_id,customer_id,amount"] + [f"O{i:04d},C{i % N:03d},{10 + i}" for i in range(60)]
    p = tmp_path / "orders.csv"
    p.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    return p


def _returns_json(tmp_path):
    p = tmp_path / "returns.json"
    p.write_bytes(json.dumps([{"return_id": f"R{i:03d}", "order_id": f"O{i:04d}", "reason": "damaged",
                               "qty": 1, "meta": {"by": "x"}} for i in range(15)]).encode())
    return p


def test_mixed_xlsx_csv_json_is_one_ontology_with_cross_file_relations(tmp_path):
    ont = ontology.build_ontology([_customers_xlsx(tmp_path), _orders_csv(tmp_path), _returns_json(tmp_path)])
    assert ont["summary"]["n_workbooks"] == 3 and ont["summary"]["n_failed"] == 0
    ids = {r["id"] for r in ont["relations"]}
    assert "orders.csv:orders.customer_id->customers.xlsx:Customers.customer_id" in ids
    assert "returns.json:returns.order_id->orders.csv:orders.order_id" in ids
    # The nested "meta" object is not a column.
    assert "meta" not in [c["name"] for c in _table(ont, "returns")["columns"]]


def test_tsv_is_a_table(tmp_path):
    p = tmp_path / "stock.tsv"
    p.write_bytes(b"sku\tqty\r\n" + b"".join(f"S{i}\t{i}\r\n".encode() for i in range(10)))
    t = _table(ontology.build_ontology([p]), "stock")
    assert [c["name"] for c in t["columns"]] == ["sku", "qty"] and t["n_rows"] == 10


def test_json_object_holding_record_lists_gives_one_table_per_list(tmp_path):
    doc = {"customers": [{"customer_id": f"C{i:03d}", "name": f"n{i}"} for i in range(N)],
           "orders": [{"order_id": i, "customer_id": f"C{i % N:03d}", "amount": 5.5 + i} for i in range(60)],
           "generated": "2026-03-05"}
    p = tmp_path / "export.json"
    p.write_bytes(json.dumps(doc).encode())
    ont = ontology.build_ontology([p])
    assert {t["name"] for t in ont["workbooks"][0]["sheets"]} == {"customers", "orders"}
    assert ("foreign_key", "orders.customer_id", "customers.customer_id") in _rels(ont)


def test_json_that_is_not_records_is_not_a_table(tmp_path):
    for name, body in (("config.json", b'{"debug": true, "paths": ["a", "b"]}'),
                       ("broken.json", b'{"a": [')):
        p = tmp_path / name
        p.write_bytes(body)
        ont = ontology.build_ontology([p])
        assert ont["workbooks"] == [] and ont["summary"]["n_failed"] == 0


def test_xml_repeated_records_are_a_table_and_join(tmp_path):
    xml = "<parts>" + "".join(
        f'<part id="P{i}"><name>p{i}</name><customer>C{i % N:03d}</customer></part>' for i in range(20)) + "</parts>"
    p = tmp_path / "parts.xml"
    p.write_bytes(xml.encode("utf-8"))
    ont = ontology.build_ontology([_customers_xlsx(tmp_path), p])
    assert [c["name"] for c in _table(ont, "part")["columns"]] == ["id", "name", "customer"]
    assert ("foreign_key", "part.customer", "Customers.customer_id") in _rels(ont)


def test_xml_with_one_element_per_tag_is_not_a_table(tmp_path):
    p = tmp_path / "doc.xml"
    p.write_bytes(b"<doc><title>x</title><body>y</body></doc>")
    assert ontology.build_ontology([p])["workbooks"] == []


def test_json_value_evidence_is_still_required(tmp_path):
    # Same column name, values that do not overlap: no relation from a name alone.
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_bytes(json.dumps([{"ref": f"A{i:03d}", "n": i} for i in range(N)]).encode())
    b.write_bytes(json.dumps([{"ref": f"Z{i % N:03d}", "m": i} for i in range(60)]).encode())
    assert ontology.build_ontology([a, b])["relations"] == []


def test_space_lists_tsv_json_and_xml_sources(tmp_path):
    files = {}
    for name in ("a.tsv", "b.json", "c.xml", "d.pdf"):
        (tmp_path / name).write_bytes(b"x")
        files[name] = str(tmp_path / name)
    with mock.patch.object(ontology.store, "list_sources", lambda _sid: [{"path": v} for v in files.values()]):
        got = [p.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for p in ontology._table_paths(1)]
    assert got == ["a.tsv", "b.json", "c.xml"]


def test_a_shared_particle_is_not_name_evidence_and_loaders_keep_what_the_file_says(tmp_path):
    """Adversary findings on this slice: a Russian preposition shared by two column
    names counted as "names agree" and made a relation; a second JSON list with the
    same key was dropped; an exponent-looking code became a number; a leading quote
    in a tsv field swallowed the rows after it."""
    import json

    import openpyxl

    from rag import ontology

    assert "на" not in ontology._tokens("номер на складе") and "في" not in ontology._tokens("العميل في المدينة")
    assert "客户" in ontology._tokens("客户编号")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    a = wb.create_sheet("Отчет")
    a.append(["запись", "на счет"])
    for i in range(30):
        a.append([f"r{i}", (i % 5) + 1])
    b = wb.create_sheet("Склад на улице")
    b.append(["номер на складе", "место"])
    for i in range(1, 41):
        b.append([i, f"m{i}"])
    wb.save(tmp_path / "ru.xlsx")
    assert ontology.build_ontology([tmp_path / "ru.xlsx"])["relations"] == []

    j = tmp_path / "regions.json"
    rec = lambda tag: [{"sku": f"{tag}{i}", "qty": i} for i in range(6)]  # noqa: E731
    j.write_text(json.dumps({"east": {"items": rec("E")}, "west": {"items": rec("W")},
                             "response": {"data": {"rows": rec("R")}}}), encoding="utf-8")
    names = {t["name"] for w in ontology.build_ontology([j])["workbooks"] for t in w["sheets"]}
    assert len(names) == 3

    t = tmp_path / "parts.tsv"
    t.write_bytes(b'id\tcode\tnote\n1\t1E5\t"Big, heavy\n2\t2E3\tsmall\n3\t3E4\tflat\n4\t4E1\tthin\n')
    cols = {c["name"]: c for w in ontology.build_ontology([t])["workbooks"] for s in w["sheets"] for c in s["columns"]}
    assert cols["id"]["n"] == 4
    assert cols["code"]["kind"] == "text" and cols["code"]["samples"][0] == "1E5"

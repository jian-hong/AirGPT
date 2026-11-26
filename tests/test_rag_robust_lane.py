"""Round 3, robust answers across file types, seen failing on the base commit.

A small mixed space (workbook, tsv, csv, json, text files) is built through the real
ingest path with the hash embedder and no model. Figures are computed here in plain Python
from the rows that are written into the files.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import openpyxl
import pytest

from rag import retrieve


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRGPT_RAG_EMBED", "hash")
    import rag.store as store
    from rag import embed

    embed.reset_embedder_cache()
    monkeypatch.setattr(store, "RAG_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "BLOB_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "rag" / "rag.db")
    store.reset_init_cache()
    store.init()
    sid = int(store.create_space("robust", depth_default="high")["id"])
    files = tmp_path / "files"
    files.mkdir()
    yield sid, files
    embed.reset_embedder_cache()


def _ingest(sid, *paths):
    from rag import ingest

    return ingest.ingest_paths(sid, [Path(p) for p in paths])


def _ask(sid, q):
    from rag import answer

    return answer.answer(sid, q, use_llm=False)


ORDERS = [(i, ["North", "South", "East"][i % 3], 3 + (i * 7) % 19, round(10 + (i * 13) % 50 + 0.25, 2)) for i in range(60)]
STOCK = [(f"SKU{i:04d}", ["Ipoh", "Johor"][i % 2], 50 + (i * 37) % 400, round(5 + (i % 9) * 1.5, 2)) for i in range(80)]


def _book(files):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Orders"
    ws.append(["id", "region", "qty", "unit_price"])
    for r in ORDERS:
        ws.append(list(r))
    dates = wb.create_sheet("Dates")
    dates.append(["event", "owner"])
    for i in range(30):
        dates.append([f"EV{i}", f"Owner{i}"])
    hidden = wb.create_sheet("Secret")
    hidden.append(["note"])
    hidden.append(["The escalation code for the Adohalbru account is VZ-6480."])
    hidden.sheet_state = "hidden"
    p = files / "book.xlsx"
    wb.save(p)
    return p


def _stock(files):
    p = files / "stock.tsv"
    p.write_text("sku\twarehouse\tqty\tcost\n" + "\n".join("\t".join(map(str, r)) for r in STOCK) + "\n", encoding="utf-8")
    return p


def _lead(done):
    return str(done.get("answer") or "").replace(",", "")


# ---- R-03: the right file is chosen when two tables are in the space -----------------

def test_filter_column_from_one_file_is_not_ignored_when_another_file_is_listed(env):
    sid, files = env
    # stock first: the old loop took the first table that produced any number
    _ingest(sid, _stock(files), _book(files))
    want = sum(r[2] for r in ORDERS if r[1] == "North")
    got = _lead(_ask(sid, "What is the total qty where region is North?"))
    assert re.match(rf"\s*{want}\b", got), got
    assert str(sum(r[2] for r in STOCK)) not in got


def test_a_filter_no_table_can_honour_is_declined_not_dropped(env):
    sid, files = env
    _ingest(sid, _stock(files))
    got = _lead(_ask(sid, "What is the total qty where region is North?"))
    assert not re.match(rf"\s*{sum(r[2] for r in STOCK)}\b", got), got


# ---- R-05: a text question is not hijacked by a count --------------------------------

def test_lookup_question_is_not_answered_with_a_count(env):
    sid, files = env
    (files / "projects.md").write_text(
        "# Projects\n\nProject Haladokel is led by Tomas Kerrow.\n\nProject Brunvikel is led by Ana Silva.\n", encoding="utf-8")
    (files / "badges.txt").write_text(
        "Badge register.\n\nThe badge for Tomas Kerrow is B-90417.\n\nThe badge for Ana Silva is B-20318.\n", encoding="utf-8")
    _ingest(sid, _book(files), files / "projects.md", files / "badges.txt")
    done = _ask(sid, "What is the badge number of the owner of project Haladokel?")
    text = str(done.get("answer") or "")
    assert "B-90417" in text, text
    assert not re.match(r"\s*30\b", text)


# ---- R-10: a JSON list of records is a table --------------------------------------------

def test_json_list_of_records_gets_a_total(env):
    sid, files = env
    recs = [{"id": i, "dept": ["fin", "hr", "ops"][i % 3], "salary": 4000 + (i * 91) % 3000} for i in range(60)]
    (files / "records.json").write_text(json.dumps(recs), encoding="utf-8")
    _ingest(sid, files / "records.json")
    want = sum(r["salary"] for r in recs if r["dept"] == "ops")
    got = _lead(_ask(sid, "What is the total salary for dept ops?"))
    assert re.match(rf"\s*{want}\b", got), got
    n_hr = sum(1 for r in recs if r["dept"] == "hr")
    assert re.match(rf"\s*{n_hr}\b", _lead(_ask(sid, "How many records have dept hr?")))


def test_json_that_is_not_a_table_is_not_one(env, tmp_path):
    from rag.xlsx_sql import load_table_file

    p = tmp_path / "conf.json"
    p.write_text(json.dumps({"name": "x", "limits": {"a": 1}}), encoding="utf-8")
    assert load_table_file(p) == {}


# ---- R-13: a hidden sheet is labelled wherever it is quoted -----------------------------

def test_hidden_sheet_text_carries_its_label(env):
    sid, files = env
    _ingest(sid, _book(files))
    hits = retrieve.search(sid, "What is the escalation code for the Adohalbru account?", depth="high", top_k=5)["hits"]
    secret = [h for h in hits if "VZ-6480" in str(h.get("text"))]
    assert secret, "the hidden sheet is still searchable"
    blob = f"{secret[0].get('heading')} {secret[0].get('text')}"
    assert "hidden sheet" in blob


# ---- R-12: the first word of a second sentence is not a name -----------------------------

def test_sentence_start_capital_is_not_a_name():
    assert retrieve.identifier_terms("For how long does Wexganpim keep its records? Give the code.") == ["Wexganpim"]
    assert retrieve.identifier_terms("Please answer briefly. Who owns Halvorsen?") == ["Who", "Halvorsen"][1:]
    assert "Tromso" in retrieve.identifier_terms("reimbursement for meals in Tromso")


# ---- R-08: the refusal shows the sentence that holds the name -----------------------------

def test_refusal_quotes_the_sentence_with_the_name_not_the_chunk_head(env):
    sid, files = env
    filler = " ".join(["Review quarterly budgets and follow vendor staffing across regions."] * 14)
    (files / "reg.txt").write_text(
        f"{filler} The retention period for the Mikulawex account is QV-4517. {filler}\n", encoding="utf-8")
    _ingest(sid, files / "reg.txt")
    text = str(_ask(sid, "For how long does Mikulawex keep its records? Give the code.").get("answer") or "")
    assert "QV-4517" in text


# ---- R-09: a rare name is not out-voted by common words in a big space -----------------

def test_rare_name_stays_in_the_top_five_in_a_large_space(env):
    sid, files = env
    words = "keep records code long period review budget vendor staffing quarter follow".split()
    with open(files / "noise.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "note", "owner", "memo"])
        for i in range(900):
            w.writerow([i, " ".join(words[(i + k) % len(words)] for k in range(6)),
                        words[i % len(words)], " ".join(words[(i * 3 + k) % len(words)] for k in range(5))])
    (files / "fact.txt").write_text("The retention period for the Wexganpim account is QV-4517.\n", encoding="utf-8")
    _ingest(sid, files / "noise.csv", files / "fact.txt")
    hits = retrieve.search(sid, "For how long does Wexganpim keep its records? Give the code.", depth="high", top_k=5)["hits"]
    assert any("QV-4517" in str(h.get("text")) for h in hits[:3]), [str(h.get("text"))[:60] for h in hits]


# ---- R-10: a calculation the app does not do is said in plain words -----------------------

def test_refusal_says_tables_in_word_pdf_web_pages_are_not_calculated():
    from rag import answer

    hits = [{"path": "memo.docx", "heading": "", "text": "Team | headcount\nAlpha | 4\nBeta | 9"}]
    why = {"kind": "coverage", "missing": ["total"], "reason": "no passage covers more than 20% of what the question asks"}
    text = answer._abstention_text(hits, why, "What is the total headcount for team Beta?")  # noqa: SLF001
    assert "Word, PDF or web page" in text and "did not calculate" in text
    plain = answer._abstention_text(hits, why, "Who runs team Beta?")  # noqa: SLF001
    assert "Word, PDF" not in plain


# ---- R-09 guard: a place or a value in the question is not a subject -------------------

def test_name_used_as_value_or_place_is_not_a_subject():
    assert retrieve._named_as_value("whose headquarters city is Tromso", "Tromso")  # noqa: SLF001
    assert retrieve._named_as_value("meals during travel in Tromso", "Tromso")  # noqa: SLF001
    assert not retrieve._named_as_value("How is Ythquioph labelled for compliance?", "Ythquioph")  # noqa: SLF001
    assert not retrieve._named_as_value("For how long does Mikulawex keep its records?", "Mikulawex")  # noqa: SLF001


# ---- R-11: one connection and one commit per file, not one per chunk --------------------

def test_ingest_does_not_open_a_connection_per_chunk(env, monkeypatch):
    import rag.store as store

    sid, files = env
    p = files / "wide.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "region", "units"] + [f"m{i}" for i in range(30)])
        for i in range(150):
            w.writerow([i, "East", i] + [round(i * 1.5 + j, 2) for j in range(30)])
    opened = {"n": 0}
    real = store._open

    def counting():
        opened["n"] += 1
        return real()

    monkeypatch.setattr(store, "_open", counting)
    out = _ingest(sid, p)
    assert out.get("ok", True)
    assert opened["n"] < 60, opened["n"]

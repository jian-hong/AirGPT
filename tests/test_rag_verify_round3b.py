"""Fixes found re-verifying the honest-answers and table-maths round.

- A PDF table cell of one character ("3") was glued to the next cell ("3   5,399.38"), so a
  clean table was declined, or read with wrong columns.
- A "Total" row at the bottom of a Word or web table was added to the rows above it.
- A table that continues on the next page with no header row was silently left out of a
  total; the answer now says so.
- A Russian name in another case ("Ивана Петрова" for "Иван Петров") was refused as absent.
- Thai questions were cut at every vowel mark, so ordinary questions were refused.
- A Korean question word ("어디입니까") counted as a missing content word.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from test_rag_document_tables import build, has, pdf_bytes, write_pdf  # noqa: E402,F401
from rag import answer, ingest  # noqa: E402

HEAD = ["Branch", "Deals", "Amount"]
ROWS = [["Lima", "3", "5,399.38"], ["Oslo", "5", "630.00"], ["Kyiv", "7", "7,025.16"], ["Pune", "30", "4,121.31"]]


def _pdf_rows(path: Path, rows: list[list[str]], xs=(50, 120, 200)) -> None:
    items = []
    for k, r in enumerate(rows):
        for x, v in zip(xs, r):
            items.append((x, 740 - 16 * k, v))
    path.write_bytes(pdf_bytes([items]))


def test_pdf_cells_of_one_character_stay_separate():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        p = Path(d) / "t.pdf"
        _pdf_rows(p, [HEAD] + ROWS)
        tables = ingest.pdf_tables(p)
    assert len(tables) == 1
    assert not tables[0]["issues"], tables[0]["issues"]
    assert [r[1] for r in tables[0]["rows"]] == ["Deals", "3", "5", "7", "30"]


def test_total_row_of_a_web_table_is_not_added_twice(build):
    make, ask = build

    def writer(p: Path) -> None:
        rows = [HEAD] + ROWS + [["Total", "45", "17,175.85"]]
        body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
        p.write_text(f"<html><body><table>{body}</table></body></html>", encoding="utf-8")

    sid = make({"page.html": writer})
    got = ask(sid, "What is the total Amount?")["answer"]
    assert has(got, 17175.85), got
    assert not has(got, 34351.70), got
    assert "left it out" in got


def test_table_continued_without_header_is_named_not_dropped(build):
    make, ask = build

    def writer(p: Path) -> None:
        items = []
        for k, r in enumerate([HEAD] + ROWS[:2]):
            items += [(x, 740 - 16 * k, v) for x, v in zip((50, 120, 200), r)]
        page2 = [(x, 740 - 16 * k, v) for k, r in enumerate(ROWS[2:]) for x, v in zip((50, 120, 200), r)]
        # a third row keeps the continuation long enough to be seen as a table
        page2 += [(x, 740 - 16 * 2, v) for x, v in zip((50, 120, 200), ["Cork", "9", "100.00"])]
        p.write_bytes(pdf_bytes([items, page2]))

    sid = make({"report.pdf": writer})
    got = ask(sid, "What is the total Amount?")["answer"]
    assert "could not be read as a table" in got and "not in this figure" in got, got


def _hit(text: str) -> dict:
    return {"text": text, "heading": "", "path": "x.md", "score": 1.0}


RU = ("Срок хранения данных клиента Иван Петров составляет 90 дней. Дата продления договора Ольги "
      "Смирновой — март. Офис Сергея Кузнецова находится в Казани. Бюджет Анны Волковой равен 50 000 долларов.")


def test_russian_name_in_another_case_is_found():
    assert answer.abstention("Каков срок хранения данных Ивана Петрова?", [_hit(RU)]) is None
    assert answer.abstention("Каков бюджет Анны Волковой?", [_hit(RU)]) is None
    # ... while a different name is still not there
    assert answer.abstention("Каков срок хранения данных Бориса Громова?", [_hit(RU)])
    assert answer.abstention("Каков срок хранения данных Савина?", [_hit(RU.replace("Петров", "Савич"))])
    assert answer.abstention("Где находится офис Дмитрия Соколова?", [_hit(RU)])


TH = ["สมชาย ใจดี มีระยะเวลาเก็บรักษา 90 วัน.", "สมหญิง รักดี มีวันต่อสัญญาคือเดือนมีนาคม.",
      "วิชัย สุขใจ มีสำนักงานที่เชียงใหม่.", "นภา แก้วมณี มีงบประมาณ 50,000 บาท"]


def test_thai_question_is_not_cut_at_vowel_marks():
    hits = [_hit(t) for t in TH]
    assert answer.abstention("สำนักงานของวิชัย สุขใจ อยู่ที่ไหน", hits) is None
    assert answer.abstention("ระยะเวลาเก็บรักษาของสมชาย ใจดี คือเท่าไร", hits) is None
    assert answer.abstention("สำนักงานของธีรพงษ์ ศรีสุข อยู่ที่ไหน", hits)


KO = ["김민수의 보존 기간은 90일입니다.", "이영희의 계약 갱신일은 3월입니다.", "박철수의 사무실은 부산에 있습니다.",
      "최지우의 예산은 5만 달러입니다."]


def test_korean_question_word_is_not_a_missing_content_word(build):
    make, ask = build
    sid = make({f"k{n}.md": (lambda t: (lambda p: p.write_text(t, encoding="utf-8")))(t) for n, t in enumerate(KO)})
    out = ask(sid, "박철수의 사무실은 어디입니까?")
    assert "부산" in out["answer"], out["answer"]
    assert "Not found" not in out["answer"] and "cannot" not in out["answer"].lower(), out["answer"]


def test_unreadable_table_of_another_file_is_not_reported_for_a_named_file(build):
    from test_rag_document_tables import write_html

    make, ask = build
    sid = make({
        "inventory.csv": lambda p: p.write_text("Item,Stock,Cost\na,5,1.5\nb,6,2.5\nc,7,3.5\n", encoding="utf-8"),
        "page.html": lambda p: write_html(p, merged=True),
    })
    got = ask(sid, "What is the total Revenue in inventory.csv?")["answer"]
    assert "could not read it as a table" not in got, got

"""Honest answers across languages: when to refuse and when not to.

Hand-built passages, no model. Each of these failed on the code before this change:
the non-Latin coverage test counted a word as present when half its characters were
found anywhere in the evidence, so (a) a name missing from the space still looked
covered in Chinese, Japanese, Korean, Arabic and Thai (never refused), and (b) in
Russian a name that WAS there was dropped as "a word every passage holds", leaving
only the English attribute words, which no Russian or Malay passage contains
(always refused).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag import answer  # noqa: E402


def hit(text, heading="Region 1", path="register.md", **kw):
    return {"text": text, "path": path, "heading": heading, **kw}


RU = [
    hit("Для клиента Моренко значение поля «срок хранения» — HM-429500.\n\n"
        "Для клиента Данич значение поля «код эскалации» — NC-725601.\n\n"
        "Для клиента Савенко значение поля «цикл выставления счетов» — VR-581702."),
    hit("Для клиента Широв значение поля «маршрут доставки» — TK-240716.\n\n"
        "Для клиента Белев значение поля «владелец договора» — KD-933018."),
    hit("Для клиента Никенко значение поля «срок хранения» — QJ-2388900."),
]
MS = [
    hit("Tempoh pengekalan bagi akaun Halvorsen ialah XG-4183900.\n\n"
        "Kod peningkatan bagi akaun Brunmik ialah KM-615103.\n\n"
        "Laluan penghantaran bagi akaun Zerthan ialah RQ-575200. Kitaran pengebilan bagi akaun Ormik ialah AB-1."),
    hit("Tahap sokongan bagi akaun Kelnim ialah ZZ-3101.\n\nTag pematuhan bagi akaun Dovgan ialah YY-8821."),
    hit("Rujukan audit bagi akaun Tasren ialah WW-5599.\n\nJalur diskaun bagi akaun Ulavor ialah VV-1200."),
]


def test_english_question_about_a_russian_passage_is_answered_not_refused():
    q = "What is the retention period for the Моренко account?"
    assert answer.abstention(q, RU) is None
    assert "HM-429500" in answer.extractive_answer(q, RU)


def test_english_question_about_a_malay_passage_is_answered_not_refused():
    q = "What is the shipping lane for the Zerthan account?"
    assert answer.abstention(q, MS) is None


def test_russian_attribute_nobody_recorded_is_refused():
    why = answer.abstention("Что указано в поле «талисман компании» для клиента Моренко?", RU)
    assert why and "талисман" in " ".join(why["missing"]) + why["reason"]


@pytest.mark.parametrize("question,passages,missing", [
    ("吴泽林客户的保留期限是什么？",
     [hit("华兴盛客户的保留期限是AB-1001。华兴达客户的保留期限是CD-2002。恒达信客户的保留期限是EF-3003。")], "吴泽林"),
    ("华兴盛客户的公司吉祥物是什么？",
     [hit("华兴盛客户的保留期限是AB-1001。华兴达客户的保留期限是CD-2002。恒达信客户的保留期限是EF-3003。")], "公司吉祥物"),
    ("山田太郎のお客様のマスコットは何ですか？",
     [hit("山田太郎のお客様の保存期間はAB-1です。鈴木花子のお客様の保存期間はCD-2です。")], "マスコット"),
    ("고객 수승미의 보존 기간은 무엇입니까?",
     [hit("한국민 고객의 보존 기간은 AB-1001입니다."), hit("서준하 고객의 청구 주기는 CD-2002입니다."),
      hit("수아태 고객의 갱신 기간은 EF-3입니다.")], "수승미"),
    ("ข้อมูลของลูกค้า สมชายมา",
     [hit("รอบการเรียกเก็บเงินของลูกค้า สมชาย คือ AB-1001\n\nรอบการเรียกเก็บเงินของลูกค้า ชายมา คือ CD-2002\n\nรอบของลูกค้า มาสม คือ EF-3")],
     "สมชายมา"),
])
def test_missing_name_or_attribute_in_scripts_without_capitals_is_refused(question, passages, missing):
    why = answer.abstention(question, passages)
    assert why, "answered a question the passages cannot answer"
    assert missing in " ".join(why["missing"]) or missing in why["reason"]


AR = [hit("مدة الاحتفاظ للعميل خالد الزهراني هو SQ-791100.\n\nفترة التجديد للعميل يوسف الشمري هو KM-615103.\n\n"
          "مسار الشحن للعميل عادل الراشد هو RQ-575200.\n\nرمز التصعيد للعميل فيصل القحطاني هو ZZ-1.")]


def test_arabic_name_made_of_two_real_names_is_refused():
    # "خالد" and "القحطاني" are both in the space, in two different customers' names.
    why = answer.abstention("ما هو مدة الاحتفاظ للعميل خالد القحطاني؟", AR)
    assert why and "خالد القحطاني" in " ".join(why["missing"])


def test_arabic_real_name_and_missing_attribute():
    assert answer.abstention("ما هو مدة الاحتفاظ للعميل خالد الزهراني؟", AR) is None
    assert answer.abstention("ما هو تميمة الشركة للعميل خالد الزهراني؟", AR)


def test_a_word_is_not_held_just_because_its_letters_are():
    # The old test passed any Russian word against any Russian blob.
    blob = answer._evidence_blob(RU)
    assert not answer._token_in_blob("талисман", blob)
    assert not answer._token_in_blob("савин", blob)
    assert answer._token_in_blob("клиента", blob)
    assert answer._token_in_blob("моренко", blob)


# --- rescue_hits: the name is in the space, retrieval returned look-alikes --------------

@pytest.fixture()
def space():
    os.environ["AIRGPT_RAG_EMBED"] = "hash"
    import rag.store as store
    from rag import embed, ingest

    embed.reset_embedder_cache()
    saved = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        root = Path(tmp.name)
        store.RAG_DIR = root / "rag"
        store.DB_PATH = store.RAG_DIR / "rag.db"
        store.BLOB_DIR = store.RAG_DIR
        store.init()
        sid = int(store.create_space("honest", depth_default="high")["id"])
        names = ["华兴盛", "华兴达", "华兴恒", "恒信盛", "恒信达", "伟东宏"]
        text = "\n\n".join(f"{n}客户的保留期限是AB-{1000 + i}。" for i, n in enumerate(names))
        p = root / "reg.md"
        p.write_text(text, encoding="utf-8")
        ingest.ingest_paths(sid, [p])
        yield sid
    finally:
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = saved
        embed.reset_embedder_cache()
        tmp.cleanup()


def test_rescue_puts_back_the_passage_with_the_name_and_leaves_made_up_names_alone(space):
    import rag.store as store

    with store._conn() as conn:
        rows = [dict(r) for r in conn.execute("SELECT id, path, heading, text FROM chunks WHERE space_id=? AND kind='child'", (space,))]
    decoy = [{"chunk_id": 0, "text": "华兴盛客户的保留期限是AB-1000。", "path": "other.md", "heading": "x"}]
    got = answer.rescue_hits(space, "伟东宏客户的保留期限是什么？", decoy)
    assert got is not decoy and any("AB-1005" in h["text"] for h in got) and got[0].get("rescued")
    assert answer.abstention("伟东宏客户的保留期限是什么？", got) is None
    made_up = answer.rescue_hits(space, "吴泽林客户的保留期限是什么？", decoy)
    assert made_up == decoy and answer.abstention("吴泽林客户的保留期限是什么？", made_up)
    assert rows  # the space really holds the chunks

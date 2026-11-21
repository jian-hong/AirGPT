"""Offline answer and abstention in scripts without capitals or Latin punctuation.

Hand-built passages, no ingest: these pin the pieces the multilingual bench measures
as a whole. Each failed on the code before this change (see the comment on each).
"""
from __future__ import annotations

from rag import answer, retrieve


def hit(text, heading="Region 1"):
    return {"text": text, "path": "register.md", "heading": heading}


AR = hit(
    "## المنطقة 1\n\nمدة الاحتفاظ للعميل خالد الزهراني هو SQ-791100.\n\n"
    "فترة التجديد للعميل يوسف الشمري هو KM-615103.\n\nمسار الشحن للعميل عادل الراشد هو RQ-575200."
)


def test_arabic_question_mark_is_not_part_of_the_last_word():
    # "الزهراني؟" never equalled "الزهراني", so the name looked missing from the passage.
    out = answer.extractive_answer("ما هو مدة الاحتفاظ للعميل خالد الزهراني؟", [AR])
    assert "SQ-791100" in out
    assert "KM-615103" not in out


def test_full_width_sentence_end_splits_chinese():
    zh = hit("华兴盛客户的保留期限是AB-1001。恒信客户的保留期限是CD-2002。泰宏客户的保留期限是EF-3003。")
    out = answer.extractive_answer("恒信客户的保留期限是什么？", [zh])
    assert "CD-2002" in out
    assert "AB-1001" not in out and "EF-3003" not in out


def test_latin_decimal_point_is_not_a_sentence_end():
    h = hit("The fee is 3.5 percent per year. The term is 12 months.")
    assert "3.5 percent" in answer.extractive_answer("what is the fee", [h])


def test_unknown_chinese_name_is_refused_and_named_whole():
    # No capital letters, so nothing marks 吴泽林 as a name. It used to be WARNED about
    # and answered with a look-alike, because a rule that refused on missing 2-character
    # pieces also refused ordinary rewordings and printed fragments such as "户目前的".
    # The question is now laid against the passage as whole strings: what the passage
    # lacks and no other passage holds is the missing term, printed as the user typed
    # it. The rewording test below keeps rewordings answered.
    zh = hit("华兴盛客户的保留期限是AB-1001。华兴达客户的保留期限是CD-2002。恒达信客户的保留期限是EF-3003。")
    why = answer.abstention("吴泽林客户的保留期限是什么？", [zh])
    assert why and why["kind"] == "term" and "吴泽林" in why["missing"]
    out = answer.extractive_answer("吴泽林客户的保留期限是什么？", [zh])
    assert "吴泽林" in out and "AB-1001" not in out.split("Closest passages")[0]
    assert answer.unseen_terms_note("华兴达客户的保留期限是什么？", [zh]) == ""


def test_reworded_chinese_and_japanese_questions_are_answered():
    zh = hit("华兴盛客户的保留期限是AB-1001。华兴达客户的保留期限是CD-2002。恒达信客户的保留期限是EF-3003。")
    assert answer.abstention("请问华兴达客户目前的保留期限大概是多久？", [zh]) is None
    assert "CD-2002" in answer.extractive_answer("请问华兴达客户目前的保留期限大概是多久？", [zh])
    ja = hit("田中太郎さんの保存期間はAB-1です。\n鈴木花子さんの保存期間はCD-2です。")
    assert answer.abstention("田中太郎さんの保存期間は何日ですか", [ja]) is None


def test_known_chinese_name_is_answered():
    zh = hit("华兴盛客户的保留期限是AB-1001。华兴达客户的保留期限是CD-2002。")
    assert answer.abstention("华兴达客户的保留期限是什么？", [zh]) is None


def test_missing_attribute_in_korean_is_named_in_a_warning():
    ko = hit("한국민 고객의 보존 기간은 AB-1001입니다.\n\n서준하 고객의 청구 주기는 CD-2002입니다.")
    assert "마스코트" in answer.unseen_terms_note("한국민 고객의 마스코트는 무엇입니까?", [ko])
    assert answer.unseen_terms_note("한국민 고객의 보존 기간은 무엇입니까?", [ko]) == ""
    assert answer.abstention("한국민 고객의 보존 기간은 무엇입니까?", [ko]) is None


def test_korean_particle_change_does_not_refuse():
    ko = hit("한국민 고객의 보존 기간은 AB-1001입니다.")
    assert answer.abstention("한국민 고객에 대해 알려 주세요.", [ko]) is None


def test_malay_and_spanish_question_words_are_not_coverage_terms():
    # "apakah" / "cual" appear in no passage; they made the answer refuse itself.
    ms = hit("Tempoh pengekalan bagi akaun Halvor ialah XG-4183900.")
    assert answer.abstention("Apakah tempoh pengekalan bagi akaun Halvor?", [ms]) is None
    es = hit("El periodo de retención de la cuenta Palmon es XG-4183900.")
    assert answer.abstention("¿Cuál es el periodo de retención de la cuenta Palmon?", [es]) is None


def test_fold_text_keeps_ascii_and_strips_latin_accents_only():
    assert retrieve.fold_text("plain ASCII 123") == "plain ASCII 123"
    assert retrieve.fold_text("información") == "informacion"
    assert retrieve.fold_text("الراشد؟").strip() == "الراشد"
    assert retrieve.fold_text("한국") == "한국"  # Hangul syllables are not split into jamo


def test_english_name_detection_is_unchanged():
    assert retrieve.identifier_terms("What is the escalation code for the Halvorsen account?") == ["Halvorsen"]
    assert answer.abstention("what is the fee for Zorblax", [hit("The fee for Halvorsen is 5.")])["kind"] == "term"


ZH_NAMES = hit("客户王明华的保留期限是 ZQ-4400。\n\n客户李建国的保留期限是 ZQ-4401。\n\n客户张伟强的保留期限是 ZQ-4402。")
JA_NAMES = [
    hit("顧客山田太郎の保存期間は JP-5500です。"),
    hit("顧客鈴木一郎の保存期間は JP-5501です。"),
    hit("顧客田中次郎の保存期間は JP-5503です。"),
]


def test_chinese_name_one_character_off_a_real_one_is_refused():
    # 王明丽 differs from 王明华 by its last character: the single leftover character was
    # too short to count, so the real person's code was listed under a warning.
    why = answer.abstention("王明丽的保留期限是多少?", [ZH_NAMES])
    assert why and why["kind"] == "term" and "王明丽" in why["missing"]
    out = answer.extractive_answer("王明丽的保留期限是多少?", [ZH_NAMES])
    assert out.startswith('The space does not mention "王明丽"')
    # The real name, a reworded frame and a leading extra word are still answered.
    for q in ("王明华的保留期限是多少?", "客户王明华的保留期限是多少?", "该客户王明华的保留期限是多少?"):
        assert answer.abstention(q, [ZH_NAMES]) is None, q
        assert "ZQ-4400" in answer.extractive_answer(q, [ZH_NAMES])


def test_japanese_name_made_of_two_real_names_is_refused():
    # 山田次郎: the space holds 山田太郎 and 田中次郎, never 山田次郎.
    why = answer.abstention("山田次郎の保存期間は?", JA_NAMES)
    assert why and why["kind"] == "term" and "山田次郎" in why["missing"]
    out = answer.extractive_answer("山田次郎の保存期間は?", JA_NAMES)
    assert out.startswith('The space does not mention "山田次郎"')
    assert answer.abstention("山田太郎の保存期間は?", JA_NAMES) is None
    assert "JP-5500" in answer.extractive_answer("山田太郎の保存期間は?", JA_NAMES)
    # Both halves in one passage (a reworded attribute) is not a split name.
    assert answer.abstention("保存期間は?", [hit("顧客山田太郎の保存の期間は JP-5500です。")]) is None

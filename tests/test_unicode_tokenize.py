"""CHUNK-02: unicode tokenizer is not ASCII-only (P13)."""
import pytest

from rag.answer import (
    _coverage,
    _goal_ok,
    _result_matches_goal,
    _tokens_for_match,
    goal_distance,
)
from rag.sira import TOKENIZER_ID, tokenize

UNRELATED = [
    {"heading": "Bicycles", "path": "bikes.md", "text": "everything about bicycle maintenance"}
]
NON_LATIN_GOALS = [
    "损坏商品的退款政策是什么",
    "какова политика возврата средств",
    "ما هي سياسة استرداد الأموال",
    "손상된 상품의 환불 정책은 무엇입니까",
]


def test_tokenizer_id_is_unicode():
    assert TOKENIZER_ID == "unicode_v1"


def test_english_identifiers_survive():
    toks = tokenize("def foo_bar(path): return SKU-00397")
    assert "foo_bar" in toks
    assert "sku-00397" in toks


def test_cjk_query_yields_tokens():
    toks = tokenize("损坏商品的退款政策是什么")
    assert toks
    assert any(len(t) >= 2 and not t.isascii() for t in toks)


def test_mixed_keeps_sku_and_cjk():
    toks = tokenize("SKU-00397 退款政策: damaged items")
    assert "sku-00397" in toks
    assert any("退款" in t for t in toks)


def test_cyrillic_letter_runs():
    toks = tokenize("какова политика возврата")
    assert "какова" in toks
    assert "политика" in toks


def test_coverage_not_vacuous_on_cjk():
    cov = _coverage("损坏商品的退款政策是什么", UNRELATED)
    assert cov < 0.6


# The same vacuous-success bug lived in three sibling paths in the web-goal
# lane, which no gate probed. Cover the class, not just _coverage (R-0004).


@pytest.mark.parametrize("goal", NON_LATIN_GOALS)
def test_non_latin_goal_is_not_discarded(goal):
    assert _goal_ok(goal)


@pytest.mark.parametrize("goal", NON_LATIN_GOALS)
def test_goal_distance_not_vacuously_zero(goal):
    assert goal_distance([goal], UNRELATED)["distance"] > 0.5


@pytest.mark.parametrize("goal", NON_LATIN_GOALS)
def test_hit_filter_is_not_a_no_op(goal):
    assert _tokens_for_match(goal)
    hit = {"title": "Bicycles", "url": "bikes.md", "snippet": "about bicycle maintenance"}
    assert not _result_matches_goal(hit, goal)


def test_match_tokens_keep_identifier_pieces():
    # sira.tokenize keeps sku-00397 whole; the pieces have to survive too or
    # URLs and SKUs stop overlapping the way the old ASCII regex made them.
    toks = _tokens_for_match("SKU-00397 refund")
    assert {"sku", "00397", "sku-00397", "refund"} <= toks


# Positive controls: a `_coverage` that only refuses still passes the negatives
# above. These pin the other direction so CHUNK-02 cannot ship a systematic
# false negative on the document that answers the ask.

OWN = [
    (
        "损坏商品的退款政策是什么",
        "# 退款政策\n损坏的商品可在三十天内退货并获得全额退款。请联系客服。\n",
    ),
    (
        "파손된 상품의 환불 정책은 무엇입니까",
        "# 환불 정책\n파손된 상품은 30일 이내에 반품하면 전액 환불됩니다.\n",
    ),
    (
        "ما هي سياسة استرداد الأموال للبضائع التالفة",
        "# سياسة الاسترداد\nيمكن إرجاع البضائع التالفة خلال 30 يوما لاسترداد كامل المبلغ.\n",
    ),
]


@pytest.mark.parametrize("query,text", OWN)
def test_coverage_own_source_clears_floor(query, text):
    cov = _coverage(query, [{"heading": "policy", "path": "p.md", "text": text}])
    assert cov >= 0.6, cov


@pytest.mark.parametrize("query,text", OWN)
def test_goal_distance_own_source_is_close(query, text):
    dist = goal_distance([query], [{"heading": "policy", "path": "p.md", "text": text}])["distance"]
    assert dist <= 0.5, dist

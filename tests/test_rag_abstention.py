"""Offline answers must abstain when the evidence is not there, and only then.

A small mixed corpus (six file types, one space, temp store, hash embedder, no model)
is asked 20 answerable and 20 unanswerable questions. Abstaining on an answerable
question fails just as much as answering an unanswerable one.

Unanswerable means: the entity is not in the corpus; the attribute is not in the
corpus; or the entity is in the corpus but the file type the question names is not.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "RAG"))
sys.path.insert(0, str(ROOT))

import filetype_bench as fb  # noqa: E402

KINDS = ["txt", "md", "csv", "xlsx", "docx", "pdf"]
PER_KIND = 4  # attrs 0..3 only; the other six attributes exist nowhere in the corpus


@pytest.fixture(scope="module")
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
        sid = int(store.create_space("abstain", depth_default="high")["id"])
        corpus = root / "corpus"
        corpus.mkdir()
        facts = []
        for kind in KINDS:
            fs = fb.make_facts(kind, PER_KIND, seed=7)
            fb.TYPES[kind](corpus / f"register_{kind}.{kind}", fs)
            facts += [(kind, f) for f in fs]
        ingest.ingest_paths(sid, [corpus / f"register_{k}.{k}" for k in KINDS])
        yield sid, facts
    finally:
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = saved
        embed.reset_embedder_cache()
        tmp.cleanup()


def _ask(sid: int, question: str) -> dict:
    from rag import answer

    events = list(answer.answer_events(sid, question, use_llm=False))
    return next(e for e in events if e["type"] == "done")


def _head(text: str) -> str:
    """The statement, without the look-alike passages shown under 'closest'."""
    return text.split("Closest passages", 1)[0]


def _answerable(facts):
    return [(f.question, f.value) for _, f in facts][:20]


def _unanswerable(facts):
    corpus_entities = {f.entity.lower() for _, f in facts}
    strangers = [f for f in fb.make_facts("other", 30, seed=99) if f.entity.lower() not in corpus_entities]
    real = [f for _, f in facts]
    qs = []
    # entity not in corpus
    for f in strangers[:7]:
        qs.append(("entity", f"What is the {f.attr} for the {f.entity} account?"))
    # attribute not in corpus: a real entity, an attribute no file records
    for f, attr in zip(real[::3][:7], fb._ATTRS[PER_KIND:] + ["headcount"]):
        qs.append(("attribute", f"What is the {attr} for the {f.entity} account?"))
    # right entity, wrong file type: no pptx was ingested
    for f in real[1::4][:6]:
        qs.append(("filetype", f"What is the {f.attr} for the {f.entity} account in register_pptx.pptx?"))
    return qs


def test_twenty_answerable_questions_still_return_the_value(space):
    sid, facts = space
    qs = _answerable(facts)
    assert len(qs) == 20
    wrong = []
    for q, value in qs:
        done = _ask(sid, q)
        if done.get("abstained") or value not in done["answer"]:
            wrong.append((q, done.get("abstained"), done["answer"][:120]))
    assert not wrong, f"{20 - len(wrong)}/20 answered; failures: {wrong}"


def test_twenty_unanswerable_questions_abstain_without_a_wrong_value(space):
    sid, facts = space
    qs = _unanswerable(facts)
    assert len(qs) == 20 and {k for k, _ in qs} == {"entity", "attribute", "filetype"}
    values = {f.value for _, f in facts}
    bad = []
    for kind, q in qs:
        done = _ask(sid, q)
        head = _head(done["answer"])
        stated = [v for v in values if v in head]
        if not done.get("abstained") or done["stop_reason"] not in ("abstained", "gaps_disclosed") or stated:
            bad.append((kind, q, done.get("abstained"), stated))
        if done.get("abstained"):
            assert done["citations"] == [], "an abstention must not cite look-alikes as proof"
    assert not bad, f"{20 - len(bad)}/20 abstained cleanly; failures: {bad}"


def test_abstention_names_the_term_and_labels_the_look_alikes(space):
    sid, facts = space
    done = _ask(sid, "What is the retention period for the Zorblaxen account?")
    assert "does not mention" in done["answer"] and "Zorblaxen" in done["answer"]
    if "Closest passages" in done["answer"]:
        assert "closest, not an answer" in done["answer"]
    assert done["abstain_reason"]
    chain = done["reasoning"]["text"].lower()
    assert "abstained" in chain and "zorblaxen" in chain


def test_extractive_answer_abstains_on_its_own():
    """The LLM-failure fallback calls extractive_answer directly; it must abstain too."""
    from rag import answer

    hits = [{"path": "a.txt", "heading": "", "text": "The support tier for the Lonophnim account is SP-306005."}]
    out = answer.extractive_answer("What is the support tier for the Sarkelgan account?", hits)
    assert "does not mention" in out and "Sarkelgan" in out
    assert "SP-306005" not in out.split("Closest passages", 1)[0]


def test_no_named_thing_falls_back_to_best_passage_coverage():
    from rag import answer

    hits = [
        {"path": "a.txt", "heading": "", "text": "The billing cycle for the Lonophnim account is monthly."},
        {"path": "b.txt", "heading": "", "text": "The shipping lane for the Ulaquisar account is north."},
    ]
    # each content word of the question lives in some passage, but never together
    assert answer.abstention("what is the billing cycle shipping lane", hits)
    assert answer.abstention("what is the billing cycle", hits) is None


def test_rewording_does_not_flip_answer_to_refusal_and_the_value_follows_its_subject():
    """Two defects an adversary reproduced on a three-vendor paragraph: "renewal
    date" was refused where "renew" was answered, and "payment terms for globex"
    quoted the first vendor's terms."""
    from rag import answer

    text = (
        "Acme Corp supplies our packaging. Contract renews on 1 March 2027. Payment terms are net 45.\n"
        "Globex Ltd handles logistics. Contract renews on 15 June 2027. Payment terms are net 30.\n"
        "Initech provides IT support. Contract renews on 30 September 2026. Payment terms are net 60."
    )
    hits = [{"path": "vendors.txt", "heading": "", "text": text}]
    assert answer.abstention("What is the contract renewal date for Initech?", hits) is None
    out = answer.extractive_answer("What is the contract renewal date for Initech?", hits)
    assert "30 September 2026" in out
    out = answer.extractive_answer("what's the payment terms for globex", hits)
    assert "net 30" in out and "net 45" not in out

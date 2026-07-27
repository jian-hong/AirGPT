"""The assistant's account of a link must not become durable memory.

Memory is injected into later prompts, so an answer saved once keeps coming
back. Two contradictory biographies of the same real person were produced and
both were persisted, which is how a single guess becomes a fact the model keeps
rediscovering.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import memory_scrub


LINK_ANSWER = (
    "Q: is this person great https://linkedin.com/in/jhoo and is netie.ai perfect\n"
    "A: Jae Hoong is the Founder and CEO of Netie.ai. He has a PhD from CMU and "
    "previously worked at Google as a Research Scientist."
)
PLAIN_ANSWER = (
    "Q: what did we decide about the ingest fix\n"
    "A: Ship it before the pilot demo and rebuild the affected spaces."
)


def test_link_answer_is_detected():
    assert memory_scrub._is_link_answer({"body": LINK_ANSWER, "title": "x"}) is True


def test_plain_answer_is_left_alone():
    assert memory_scrub._is_link_answer({"body": PLAIN_ANSWER, "title": "x"}) is False


def test_already_scrubbed_is_not_reprocessed():
    body = "Q: about https://example.com\n" + memory_scrub.REPLACEMENT
    assert memory_scrub._is_link_answer({"body": body, "title": ""}) is False


def test_question_only_memory_is_not_touched():
    body = "Q: look at https://example.com\nA: [not stored] asked about a link."
    assert memory_scrub._is_link_answer({"body": body, "title": ""}) is False


def _fake_memory_index(monkeypatch, rows):
    import types

    mod = types.ModuleType("memory_index")
    mod.init = lambda: None
    mod.list_memories = lambda **kw: list(rows)
    written = {}
    mod.update_memory = lambda mid, **f: written.__setitem__(mid, f)
    mod._written = written
    monkeypatch.setitem(sys.modules, "memory_index", mod)
    return mod


def test_dry_run_changes_nothing(monkeypatch):
    mod = _fake_memory_index(monkeypatch, [{"id": 1, "title": "t", "body": LINK_ANSWER}])
    out = memory_scrub.scrub(dry_run=True)
    assert out["affected"] == 1
    assert mod._written == {}


def test_apply_keeps_the_question_and_drops_the_claim(monkeypatch):
    mod = _fake_memory_index(
        monkeypatch,
        [
            {"id": 1, "title": "t", "body": LINK_ANSWER},
            {"id": 2, "title": "t", "body": PLAIN_ANSWER},
        ],
    )
    out = memory_scrub.scrub(dry_run=False)
    assert out["affected"] == 1
    body = mod._written[1]["body"]
    assert "linkedin.com/in/jhoo" in body, "the question must survive"
    assert "PhD from CMU" not in body, "the fabricated claim must not"
    assert "Google" not in body
    assert 2 not in mod._written, "an ordinary turn must not be rewritten"


def test_persist_turn_memory_does_not_store_link_answers(monkeypatch):
    """The prevention half: new link answers never reach memory in the first place."""
    import ai_engine

    saved = {}

    import types

    mi = types.ModuleType("memory_index")
    mi.init = lambda: None
    mi.add_memory = lambda **kw: saved.update(kw)
    monkeypatch.setitem(sys.modules, "memory_index", mi)

    vault = types.ModuleType("vault")
    vault_writes = []
    vault.write_drawer = lambda **kw: vault_writes.append(kw)
    monkeypatch.setitem(sys.modules, "vault", vault)

    ai_engine.persist_turn_memory(
        question="is this person great https://linkedin.com/in/jhoo",
        answer="Jae Hoong has a PhD from CMU and worked at Google. " * 3,
        mode="general",
        session_id=1,
    )
    assert saved, "the question should still be remembered"
    assert "[not stored]" in saved["body"]
    assert "PhD from CMU" not in saved["body"]
    assert vault_writes == [], "no vault drawer for a link answer"


def test_persist_turn_memory_still_stores_ordinary_turns(monkeypatch):
    import ai_engine
    import types

    saved = {}
    mi = types.ModuleType("memory_index")
    mi.init = lambda: None
    mi.add_memory = lambda **kw: saved.update(kw)
    monkeypatch.setitem(sys.modules, "memory_index", mi)
    vault = types.ModuleType("vault")
    vault.write_drawer = lambda **kw: None
    monkeypatch.setitem(sys.modules, "vault", vault)

    ai_engine.persist_turn_memory(
        question="what did we decide about the ingest fix",
        answer="Ship it before the pilot demo and rebuild the affected spaces. " * 2,
        mode="general",
        session_id=1,
    )
    assert "Ship it before the pilot demo" in saved["body"]

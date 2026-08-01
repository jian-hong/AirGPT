"""Safety guarantees for what reaches the memory store and the vault drawers.

Every test here corresponds to a defect that was verified live before it was fixed,
not a hypothetical. The shared theme is a guard that existed, passed its own test,
and was bypassed somewhere else - so these assert on the artifact that actually gets
injected back into prompts, not on the function that was supposed to prevent it.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_tools  # noqa: E402
import ai_engine  # noqa: E402

_FABRICATION = "Jae Hoong has a PhD from CMU and worked at Google. " * 3
_LINK_Q = "is this person great https://linkedin.com/in/jhoo"


# --- D2: the vault drawer defeated the anti-fabrication guard 250 lines later ------
# persist_turn_memory correctly refused to store the model's account of a link, and
# _finish_chat_side_effects then wrote the same answer to
# data/vault/_company/rooms/feedback/ with no such check. retrieve_vault_snippets
# greps that directory back into later prompts. A real file on this machine still
# holds "Jae Hoong is the Founder & CEO of Netie.ai ... Carnegie Mellon University".


@pytest.mark.parametrize(
    "question,expect_link",
    [
        (_LINK_Q, True),
        ("is this person great http://netie.ai/", True),
        ("what did we decide about the ingest fix", False),
        ("", False),
    ],
)
def test_link_detection_is_one_shared_definition(question: str, expect_link: bool) -> None:
    """Two writers computing 'is this about a link' separately is how they drifted."""
    assert ai_engine.is_about_link(question) is expect_link


def test_company_feedback_drawer_refuses_a_link_answer(monkeypatch) -> None:
    """The exact payload the adversary used to put a fabrication on disk."""
    writes: list[dict] = []
    vault = types.ModuleType("vault")
    vault.write_drawer = lambda **kw: writes.append(kw)
    monkeypatch.setitem(sys.modules, "vault", vault)

    mi = types.ModuleType("memory_index")
    mi.init = lambda: None
    mi.add_memory = lambda **kw: {"ok": True}
    monkeypatch.setitem(sys.modules, "memory_index", mi)
    monkeypatch.setattr(ai_engine, "_record_chat_usage", lambda **kw: None, raising=False)

    ai_engine._finish_chat_side_effects(
        question=_LINK_Q, answer=_FABRICATION, mode="general",
        session_id=1, model="x", tier="high",
    )

    company = [w for w in writes if w.get("project") == "_company"]
    assert not company, "the model's account of a link must not reach the feedback drawer"
    for w in writes:
        assert "PhD from CMU" not in str(w.get("body", "")), f"fabrication leaked via {w}"


def test_company_feedback_drawer_still_records_ordinary_answers(monkeypatch) -> None:
    """The guard must not cost the feature. A control that refuses legitimate work
    is a failure, not a win."""
    writes: list[dict] = []
    vault = types.ModuleType("vault")
    vault.write_drawer = lambda **kw: writes.append(kw)
    monkeypatch.setitem(sys.modules, "vault", vault)
    mi = types.ModuleType("memory_index")
    mi.init = lambda: None
    mi.add_memory = lambda **kw: {"ok": True}
    monkeypatch.setitem(sys.modules, "memory_index", mi)
    monkeypatch.setattr(ai_engine, "_record_chat_usage", lambda **kw: None, raising=False)

    ai_engine._finish_chat_side_effects(
        question="what did we decide about the ingest fix",
        answer="Ship it before the pilot demo and rebuild the affected spaces. " * 3,
        mode="general", session_id=1, model="x", tier="high",
    )
    assert any(w.get("project") == "_company" for w in writes)


# --- D6: the deliberate-write tool wrote nowhere, and reported success anyway ------


def test_memory_add_reports_a_refusal_instead_of_claiming_success(monkeypatch) -> None:
    """It discarded add_memory's return for a hardcoded {"ok": True}, so a
    fail-closed secret gate or a disk error looked like a successful save to both
    the model and the user."""
    mi = types.ModuleType("memory_index")
    mi.init = lambda: None
    mi.add_memory = lambda **kw: {"ok": False, "error": "refused: secret detected"}
    monkeypatch.setitem(sys.modules, "memory_index", mi)

    out = agent_tools.memory_add("my api key is sk-abc123")
    assert out["ok"] is False, "a refusal was reported as success"
    assert "refused" in str(out.get("error", ""))


def test_memory_add_writes_into_a_project_chat_can_actually_read(monkeypatch) -> None:
    """project defaulted to "", and carry_pack's predicate is (?='' OR project=?)
    against the caller's project - so every model-written fact was invisible to chat."""
    seen: dict = {}
    mi = types.ModuleType("memory_index")
    mi.init = lambda: None
    mi.add_memory = lambda **kw: seen.update(kw) or {"ok": True}
    monkeypatch.setitem(sys.modules, "memory_index", mi)

    agent_tools.memory_add("The user's dog is called Xiaojimao")
    assert seen["project"], "an empty project is unreadable from chat"
    assert seen["project"] == "general"
    # The title was hardcoded to "agent fact" for every row, making them
    # indistinguishable in any list the user sees.
    assert seen["title"] != "agent fact"
    assert "Xiaojimao" in seen["title"]


def test_memory_add_success_is_still_reported_as_success(monkeypatch) -> None:
    mi = types.ModuleType("memory_index")
    mi.init = lambda: None
    mi.add_memory = lambda **kw: {"ok": True, "id": 42}
    monkeypatch.setitem(sys.modules, "memory_index", mi)
    out = agent_tools.memory_add("I prefer short answers")
    assert out["ok"] is True
    assert out.get("id") == 42


# --- D3: the scrub cleaned SQLite and left the injected .md mirror intact ----------
# update_memory writes no drawer (only add_memory mirrors), so a scrubbed row read
# "[removed]" while the drawer beside it still held the full claim - and
# retrieve_vault_snippets greps the drawers, not the rows.

import memory_scrub  # noqa: E402

_QA_DRAWER = """---
project: general
room: session
source: memory_index
created: 2026-07-25 20:39
---

# is this person great

Q: is this person a cool and great person https://linkedin.com/in/jhoo
A: Jae Hoong is the Founder & CEO of Netie.ai with a degree from Carnegie Mellon.
"""

_FEEDBACK_DRAWER = """---
project: _company
room: feedback
source: dual_brain
created: 2026-07-25 20:39
---

# session-130-feedback

Regarding Jae Hoong (https://linkedin.com/in/jhoo): Founder & CEO of Netie.ai,
background in computer science from Carnegie Mellon University.
"""

_ORDINARY_DRAWER = """---
project: general
room: session
source: memory_index
created: 2026-07-25 20:39
---

# ingest fix

Q: what did we decide about the ingest fix
A: Ship it before the pilot demo and rebuild the affected spaces.
"""


def _vault(tmp_path, files: dict[str, str]):
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return str(tmp_path)


def test_drawer_scrub_rewrites_a_qa_link_answer(tmp_path) -> None:
    root = _vault(tmp_path, {"a.md": _QA_DRAWER})
    r = memory_scrub.scrub_drawers(dry_run=False, root=root)
    assert r["affected"] == 1
    text = (tmp_path / "a.md").read_text(encoding="utf-8")
    assert "Carnegie Mellon" not in text
    assert "[removed]" in text
    assert "Q: is this person" in text, "the question must survive"


def test_drawer_scrub_rewrites_the_dual_brain_feedback_drawer(tmp_path) -> None:
    """The drawer that defeated the guard - written with no question beside it."""
    root = _vault(tmp_path, {"f.md": _FEEDBACK_DRAWER})
    r = memory_scrub.scrub_drawers(dry_run=False, root=root)
    assert r["affected"] == 1
    text = (tmp_path / "f.md").read_text(encoding="utf-8")
    assert "Carnegie Mellon" not in text
    assert "project: _company" in text, "frontmatter must be preserved"


def test_drawer_scrub_leaves_ordinary_notes_alone(tmp_path) -> None:
    """A control that destroys legitimate notes is a failure, not a win."""
    root = _vault(tmp_path, {"o.md": _ORDINARY_DRAWER})
    r = memory_scrub.scrub_drawers(dry_run=False, root=root)
    assert r["affected"] == 0
    assert "Ship it before the pilot demo" in (tmp_path / "o.md").read_text(encoding="utf-8")


def test_drawer_scrub_dry_run_changes_nothing(tmp_path) -> None:
    root = _vault(tmp_path, {"a.md": _QA_DRAWER})
    before = (tmp_path / "a.md").read_text(encoding="utf-8")
    r = memory_scrub.scrub_drawers(dry_run=True, root=root)
    assert r["affected"] == 1 and r["dry_run"] is True
    assert (tmp_path / "a.md").read_text(encoding="utf-8") == before


def test_unclassifiable_url_drawers_are_reported_not_silently_skipped(tmp_path) -> None:
    """The URL is in the ANSWER, not the question, so the conservative rules cannot
    prove it is a guess. Six of the twelve real fabrication drawers look like this.
    Reporting beats both rewriting real notes and leaving a fabrication in place."""
    unknown = _QA_DRAWER.replace(
        "Q: is this person a cool and great person https://linkedin.com/in/jhoo",
        "Q: check and research again who was that guy",
    ).replace(
        "A: Jae Hoong is the Founder & CEO of Netie.ai with a degree from Carnegie Mellon.",
        "A: That was Jae Hoong (https://linkedin.com/in/jhoo), Founder & CEO of Netie.ai.",
    )
    root = _vault(tmp_path, {"u.md": unknown})
    r = memory_scrub.scrub_drawers(dry_run=True, root=root)
    assert r["affected"] == 0
    assert r["needs_review"] == 1, "a URL-bearing drawer must never vanish from the report"
    assert "u.md" in r["review"][0]["path"]


def test_already_scrubbed_drawers_are_not_touched_twice(tmp_path) -> None:
    root = _vault(tmp_path, {"a.md": _QA_DRAWER})
    memory_scrub.scrub_drawers(dry_run=False, root=root)
    r2 = memory_scrub.scrub_drawers(dry_run=True, root=root)
    assert r2["affected"] == 0 and r2["needs_review"] == 0


# --- Secrets must never reach the store -------------------------------------------
# pii_guard.redact ran only on the outbound cloud prompt; no memory write path
# scrubbed anything. The likeliest route in is POST /api/memory/ingest, which stores
# a dropped file byte-for-byte - a .env lands verbatim. Memory is replayed into later
# prompts, so a credential stored once is re-sent on every subsequent turn.

import memory_index  # noqa: E402


@pytest.mark.parametrize(
    "text,kind",
    [
        ("sk-abc123def456ghi789jkl012", "provider API key"),
        ("AKIAIOSFODNN7EXAMPLE", "provider API key"),
        ("gho_" + "a" * 36, "provider API key"),
        ("my password = hunter2xyz", "password or token assignment"),
        ("API_KEY: gsk_M0fau6csPEO3WWDeJNhLWG", "password or token assignment"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIE", "private key"),
    ],
)
def test_credentials_are_named_and_refused(text: str, kind: str) -> None:
    assert memory_index._secret_kind(text) == kind


@pytest.mark.parametrize(
    "text",
    [
        "my email is jh@netie.ai",
        "call me JH not Jian Hong",
        "The user's dog is called Xiaojimao",
        "we decided to ship before the pilot demo",
        "my phone is +60123456789",
        "the secret to good code is tests",
    ],
)
def test_ordinary_durable_facts_are_not_mistaken_for_secrets(text: str) -> None:
    """Refusing a legitimate memory is a failure, not a win.

    Emails and phone numbers are deliberately allowed - "my work email is ..." is
    exactly the kind of durable fact this store exists for. Only things that are
    secret by construction are rejected.
    """
    assert memory_index._secret_kind(text) == ""


def test_the_gate_refuses_loudly_rather_than_redacting(monkeypatch, tmp_path) -> None:
    """A half-stored credential is still a leak, and a silent redaction hides that
    the user's paste went somewhere it should not have."""
    out = memory_index.add_memory(
        kind="memory", title="k", body="my api_key = sk-abc123def456ghi789jkl012"
    )
    assert out["ok"] is False
    assert out["refused"] == "secret"
    assert "vault" in out["error"]
    # and it must never echo the value back
    assert "sk-abc123" not in out["error"]


def test_the_refusal_reaches_the_model_through_the_tool() -> None:
    """Only true because memory_add stopped hardcoding {"ok": True} - otherwise the
    gate would fire and the model would still be told the save succeeded."""
    out = agent_tools.memory_add("the groq key is sk-abc123def456ghi789jkl012")
    assert out["ok"] is False
    assert out.get("refused") == "secret"

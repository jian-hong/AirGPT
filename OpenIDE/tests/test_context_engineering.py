"""OpenIDE / AirGPT context engineering tests."""
from __future__ import annotations

from pathlib import Path

from context_engineering import (
    ContextRequest,
    NoteStore,
    assemble_context,
    compact_messages,
    default_notes_path,
    estimate_tokens,
)


def test_assemble_agent_shaped_prompt():
    out = assemble_context(
        ContextRequest(
            instructions="You are OpenIDE agent.\nRules:\n- local-first",
            tools='[{"name":"fs_patch"}]',
            state="branch=feat/ce head=abc dirty=2",
            memory="Notes:\n## Objectives\n- ship CE",
            messages=[
                "Tool vault_read: {\"ok\": true}",
                "Tool fs_patch: {\"ok\": true, \"path\": \"a.py\"}",
            ],
            token_budget=1500,
        )
    )
    assert "OpenIDE" in out.system or "local-first" in out.system
    assert out.token_estimate > 0
    sys, user = out.as_prompt_pair()
    assert isinstance(sys, str) and isinstance(user, str)


def test_default_notes_path(tmp_path: Path):
    p = default_notes_path(tmp_path)
    assert p is not None
    assert p.name == "NOTES.md"
    assert p.parent.name == ".airgpt"
    store = NoteStore(p)
    store.append("compaction works", heading="CE")
    assert "compaction" in store.read_recent()


def test_compact_preserves_recent_tools():
    blocks = [f"Tool t{i}: result {i} " + ("y" * 400) for i in range(10)]
    out, compacted = compact_messages(blocks, token_budget=120, keep_tail=2)
    assert compacted
    assert any("t8" in b or "t9" in b for b in out)
    assert estimate_tokens("\n\n".join(out)) <= 200

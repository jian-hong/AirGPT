"""Emergency AI cut-off must gate providers — not a UI-only mock."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def policy_dir(monkeypatch, tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("AIRGPT_DATA_DIR", str(data))
    # config.DATA_DIR is imported at module load — rebind access_policy paths
    import access_policy
    import config

    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(access_policy, "POLICY_FILE", data / "access_policy.json")
    yield data


def test_lockdown_block_payload(policy_dir):
    import access_policy

    assert access_policy.lockdown_block() is None
    r = access_policy.set_ai_lockdown(True, reason="test", by="host")
    assert r["ok"] is True
    assert r["on"] is True
    assert "mock" not in r
    blocked = access_policy.lockdown_block()
    assert blocked is not None
    assert blocked["error"] == "ai_lockdown"
    assert blocked["by"] == "host"
    assert blocked["ok"] is False

    access_policy.set_ai_lockdown(False, by="host")
    assert access_policy.lockdown_block() is None


def test_chat_text_respects_lockdown(policy_dir, monkeypatch):
    import access_policy
    import ai_engine

    access_policy.set_ai_lockdown(True, reason="cut", by="host")

    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("provider must not be called during lockdown")

    monkeypatch.setattr(ai_engine, "_standard_llm", boom)
    out = ai_engine.chat_text("hello")
    assert out.get("error") == "ai_lockdown"
    assert out.get("ok") is False
    assert called["n"] == 0


def test_chat_stream_respects_lockdown(policy_dir, monkeypatch):
    import access_policy
    import ai_engine

    access_policy.set_ai_lockdown(True, reason="cut", by="host")

    def boom(*_a, **_k):
        raise AssertionError("provider must not stream during lockdown")

    monkeypatch.setattr(ai_engine, "_standard_llm", boom)
    monkeypatch.setattr(ai_engine, "_standard_llm_stream", boom)
    events = list(ai_engine.chat_text_stream("hello"))
    assert events
    assert events[0].get("error") == "ai_lockdown"
    assert events[0].get("type") == "error"


def test_agent_runtime_respects_lockdown(policy_dir, monkeypatch):
    import access_policy
    import agent_runtime

    access_policy.set_ai_lockdown(True, reason="cut", by="host")
    events = list(agent_runtime.run_agent_events(1, "do something"))
    assert events
    assert events[0].get("error") == "ai_lockdown"

"""DR-0007: marketplace is a catalog + recipe, not a serving plane."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import marketplace  # noqa: E402


def test_bind_serve_does_not_spawn_a_process() -> None:
    src = inspect.getsource(marketplace.bind_serve)
    assert "subprocess" not in src
    assert "Popen" not in src


def test_bind_serve_returns_a_recipe_not_a_pid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(marketplace, "ENV_FILE", tmp_path / "env.local")
    out = marketplace.bind_serve("qwen2.5-1.5b-gguf")
    assert out.get("ok") is True
    assert "command" in out
    assert "pid" not in out
    assert out.get("serving") == "gguf"


def test_constructor_card_is_a_module_not_an_llm_server() -> None:
    item = next(i for i in marketplace.SOFTWARE_MODULES if i.get("builtin") == "constructor")
    assert item["id"] == "mod-constructor"
    assert item.get("serving") == "module"
    assert item.get("category") != "llm"
    blurb = item.get("blurb", "").lower()
    assert "hosted inside cortex" not in blurb
    assert "/cortex/constructor/" not in blurb

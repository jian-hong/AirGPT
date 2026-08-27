"""EPIC-D09 SHELL-01/02/03 gates. Never skip. Missing deps FAIL with the cause named."""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import OpenIDE.workspace_api as wa  # noqa: E402
import agent_runtime  # noqa: E402
import cortex_client as cc  # noqa: E402
import tool_readout  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "index.html"


def _html() -> str:
    text = HTML.read_text(encoding="utf-8")
    assert text, "index.html missing or empty"
    return text


def _fn(src: str, start: str, end: str) -> str:
    i = src.find(start)
    assert i >= 0, f"missing {start}"
    j = src.find(end, i + 1)
    assert j > i, f"missing {end} after {start}"
    return src[i:j]


def _assert_deltas(out: dict) -> None:
    assert isinstance(out, dict), out
    assert out.get("ok") is True, out
    assert "added_lines" in out, "fs_write/fs_patch must return added_lines (+N); deltas missing"
    assert "deleted_lines" in out, "fs_write/fs_patch must return deleted_lines (-M); deltas missing"
    assert isinstance(out["added_lines"], int), out
    assert isinstance(out["deleted_lines"], int), out


def test_fs_write_and_patch_return_line_deltas(tmp_path, monkeypatch):
    monkeypatch.setattr(wa, "WORKSPACE_FILE", tmp_path / "workspace.json")
    monkeypatch.setattr(wa, "DATA_DIR", tmp_path)
    opened = wa.open_workspace(str(tmp_path), name="d09")
    assert opened.get("ok"), opened
    written = wa.write_file("note.txt", "alpha\nbeta\ngamma\n")
    _assert_deltas(written)
    assert written["added_lines"] == 3
    assert written["deleted_lines"] == 0
    patched = wa.patch_file("note.txt", "beta", "BETA\nBETA")
    _assert_deltas(patched)
    assert patched["added_lines"] >= 1
    preview = wa.write_file("note.txt", "only\n", apply=False)
    _assert_deltas(preview)
    assert preview.get("preview") is True


def test_agent_tools_fs_write_keeps_deltas(tmp_path, monkeypatch):
    import agent_tools

    monkeypatch.setattr(wa, "WORKSPACE_FILE", tmp_path / "workspace.json")
    monkeypatch.setattr(wa, "DATA_DIR", tmp_path)
    wa.open_workspace(str(tmp_path), name="d09")
    out = agent_tools.fs_write("from_tool.txt", "one\ntwo\n")
    _assert_deltas(out)


def test_safe_tool_event_preserves_deltas():
    ev = agent_runtime._safe_tool_event(
        "fs_write",
        {"ok": True, "path": "a.txt", "added_lines": 4, "deleted_lines": 1},
    )
    assert ev["type"] == "tool"
    assert ev["result"]["added_lines"] == 4
    assert ev["result"]["deleted_lines"] == 1


def test_group_tool_events_kinds_counts_and_delta():
    seg = tool_readout.group_tool_events(
        [
            {"type": "tool_call", "name": "fs_read"},
            {"type": "tool", "name": "fs_patch", "result": {"ok": True, "added_lines": 5, "deleted_lines": 2}},
            {"type": "tool", "name": "fs_read", "result": {"ok": True}},
        ]
    )
    assert seg["count"] == 3
    assert seg["kinds"]["fs_read"] == 2
    assert seg["kinds"]["fs_patch"] == 1
    assert seg["added_lines"] == 5
    assert seg["deleted_lines"] == 2
    assert tool_readout.format_delta(5, 2) == " +5 -2"


def test_index_groups_tool_rows_expandable_with_deltas():
    src = _html()
    body = _fn(src, "function groupToolEvents", "async function ensureCortexAgent")
    assert "groupToolEvents" in body
    assert "tool-group-row" in body
    assert "added_lines" in body
    assert "deleted_lines" in body
    assert "push((j.name==='web_search'" not in body
    assert "<details" in body
    home = _fn(src, "async function showCortexAgentChat()", "function cortexSubagentsHtml")
    assert "cortexSnippetCards" not in home
    assert "loadCortexSnippets()" not in home


def test_index_home_is_not_skill_gallery_primary_path():
    src = _html()
    home = _fn(src, "async function showCortexAgentChat()", "function cortexSubagentsHtml")
    assert "data-sn-use" not in home
    assert "kicker:'Skill'" not in home
    assert "/skill:" in home
    assert "/anthropic-skills:" in home
    assert "auto-wires tools" in home
    assemble = _fn(src, "async function assembleCortexCapabilities", "function buildCortexOrchestrationPrompt")
    assert "pendingSkillPack||(skills[0]" not in assemble
    assert "window.pendingSkillPack||''" in assemble
    slash = _fn(src, "function handleSlashCommand", "if(cmd==='rules')")
    assert "anthropic-skills:" in slash
    assert "skill_pack" in src
    assert "body.skill_pack=skill_pack" in src


def test_index_scheduler_requires_next_run_at_or_named_refusal():
    src = _html()
    sched = _fn(src, "async function ensureCortexAgent", "async function ensureCortexConcierge")
    assert "schedule_hint:" not in sched
    assert "next_run_at" in sched
    assert "NOT scheduled" in sched
    page = _fn(src, "async function showRoutinesPage", "function seekProposalHtml")
    assert "routineOfflineWhy" in page
    assert "scheduler did not fire" in page
    run = _fn(src, "async function routineRunNow", "async function routineTogglePause")
    assert "did not fire" in run
    assert "next_run_at" in run


def test_constructor_surface_is_named_refusal(monkeypatch):
    monkeypatch.setenv("CORTEX_AUTOSPAWN", "0")
    monkeypatch.setattr(
        cc,
        "health",
        lambda: {
            "ok": True,
            "status": "live",
            "raw": {"status": "ok", "pack": "dms", "surface": "constructor"},
            "url": "http://127.0.0.1:8010",
        },
    )
    st = cc.scheduler_status(try_spawn=False)
    assert st["ok"] is False
    assert st["reason"] == "wrong_surface"
    err = (st.get("error") or "").lower()
    assert "constructor" in err or "dms" in err
    assert "/api/routines" in (st.get("error") or "")
    created = cc.routines_create("Morning news brief, daily")
    assert created["ok"] is False
    assert created["reason"] == "wrong_surface"


def test_create_without_next_run_at_is_not_scheduled(monkeypatch):
    monkeypatch.setenv("CORTEX_AUTOSPAWN", "0")
    monkeypatch.setattr(cc, "scheduler_status", lambda **kwargs: {"ok": True, "reason": "live"})
    monkeypatch.setattr(
        cc,
        "_json_call",
        lambda *a, **k: {"ok": True, "routine_id": "rt-lie", "_http": 200},
    )
    out = cc.routines_create("daily digest")
    assert out["ok"] is False
    assert out["reason"] == "no_next_run"


class _MockCortex(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def _send(self, code: int, obj: dict):
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        nxt = getattr(self.server, "next_run", 1_700_000_000)
        if self.path == "/health":
            return self._send(200, {"status": "ok"})
        if self.path == "/api/routines":
            return self._send(200, {"ok": True, "routines": [{"id": "rt-1", "next_run_at": nxt}]})
        if self.path.startswith("/api/routines/"):
            return self._send(200, {"ok": True, "id": "rt-1", "next_run_at": nxt})
        return self._send(404, {"detail": "Not Found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        nxt = getattr(self.server, "next_run", 1_700_000_000)
        if self.path == "/api/routines":
            return self._send(200, {"ok": True, "routine_id": "rt-1", "next_run_at": nxt})
        if self.path.endswith("/run"):
            self.server.next_run = int(nxt) + 300
            return self._send(200, {"ok": True, "next_run_at": self.server.next_run})
        return self._send(404, {"detail": "Not Found"})

    def do_DELETE(self):
        return self._send(200, {"ok": True})


def test_forced_run_advances_next_run_at(monkeypatch):
    monkeypatch.setenv("CORTEX_AUTOSPAWN", "0")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockCortex)
    srv.next_run = 1_700_000_000
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    monkeypatch.setattr(cc, "_cfg", lambda: (f"http://127.0.0.1:{port}", ""))
    cc._avail_cache.update({"t": 0.0, "ok": False})
    try:
        created = cc.routines_create("AirGPT D09 mock ping, hourly")
        assert created.get("ok") is True, created
        assert created.get("next_run_at") == 1_700_000_000
        ran = cc.routines_run("rt-1")
        assert ran.get("fired") is True, ran
        assert ran.get("next_run_at_after") == 1_700_000_300
        assert ran.get("next_run_at_before") == 1_700_000_000
    finally:
        srv.shutdown()
        srv.server_close()


def test_live_8010_scheduler_honesty():
    """Never skip. Live Constructor/DMS, real Cortex, or down -- named either way."""
    os.environ["CORTEX_AUTOSPAWN"] = "0"
    cc._avail_cache.update({"t": 0.0, "ok": False})
    st = cc.scheduler_status(try_spawn=False)
    reason = st.get("reason")
    assert reason in ("live", "wrong_surface", "cortex_down", "no_scheduler"), st
    if st.get("ok"):
        created = cc.routines_create("AirGPT D09 gate ping every hour -- delete me")
        assert created.get("ok") is True, created
        assert created.get("next_run_at") not in (None, ""), created
        rid = created.get("routine_id") or created.get("id")
        if not rid and isinstance(created.get("routine"), dict):
            rid = created["routine"].get("id")
        assert rid, created
        before = created.get("next_run_at")
        ran = cc.routines_run(str(rid))
        assert ran.get("fired") is True, ran
        assert ran.get("next_run_at_after") != before, ran
        gone = cc.routines_delete(str(rid))
        assert gone.get("ok") is True, gone
        return
    assert st.get("ok") is False
    err = str(st.get("error") or "")
    assert err, "soft-fail must name the cause"
    created = cc.routines_create("Morning news brief, daily")
    assert created.get("ok") is False, created
    assert created.get("reason") in ("wrong_surface", "cortex_down", "no_scheduler")


def test_min_tests_floor_unchanged():
    wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert 'MIN_TESTS: "380"' in wf


def test_multilingual_gate_file_still_present():
    p = ROOT / "tests" / "RAG" / "multilingual_gate.py"
    assert p.is_file(), "P13 multilingual_gate.py must stay; do not skip or delete it"
    src = p.read_text(encoding="utf-8")
    assert "pytest.skip" not in src
    assert "xfail" not in src.lower()

"""EPIC-D09 SHELL-02 gate: the scheduler fires for real or refuses by name.

Never skip. Missing deps FAIL with the cause named. Issue #60 allows exactly two
outcomes from the customer seat - a Cortex routine with a real next_run_at, or
say-so at the control. An AirGPT-owned cron is a third outcome and out of scope,
so the create path must not reach one.

Cortex is not assumed live: every clause except test_live_8010_scheduler_honesty
runs against a mock or a named-down engine.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import cortex_client as cc  # noqa: E402
import host_routines  # noqa: E402
import tool_readout  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "index.html"
REFUSALS = ("wrong_surface", "cortex_down", "no_scheduler", "no_next_run", "empty_draft")


@pytest.fixture(autouse=True)
def _isolated_host_store(tmp_path, monkeypatch):
    """Never touch data/host_routines.json — a reverted fix must not write there."""
    monkeypatch.setattr(host_routines, "STORE", tmp_path / "host_routines.json")
    monkeypatch.setattr(host_routines, "DATA_DIR", tmp_path)


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


def _down(monkeypatch, **raw) -> None:
    """Pin health() so no clause depends on what is really listening on :8010."""
    monkeypatch.setenv("CORTEX_AUTOSPAWN", "0")
    if raw:
        monkeypatch.setattr(
            cc,
            "health",
            lambda: {"ok": True, "status": "live", "raw": raw, "url": "http://127.0.0.1:8010"},
        )
    else:
        monkeypatch.setattr(
            cc,
            "health",
            lambda: {
                "ok": False,
                "status": "standby",
                "error": "connection refused",
                "url": "http://127.0.0.1:8010",
            },
        )


# -- SHELL-01 readout helper (harvested with the gate; pure function) ---------


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


# -- SHELL-02 refusals -------------------------------------------------------


def test_cortex_down_is_a_named_refusal(monkeypatch):
    _down(monkeypatch)
    st = cc.scheduler_status(try_spawn=False)
    assert st["ok"] is False
    assert st["reason"] == "cortex_down"
    assert "8010" in str(st.get("error") or "")
    created = cc.routines_create("Morning news brief, daily")
    assert created["ok"] is False, "an unreachable Cortex must not report a scheduled routine"
    assert created["reason"] == "cortex_down"


def test_constructor_surface_is_named_refusal(monkeypatch):
    _down(monkeypatch, status="ok", pack="dms", surface="constructor")
    st = cc.scheduler_status(try_spawn=False)
    assert st["ok"] is False
    assert st["reason"] == "wrong_surface"
    err = str(st.get("error") or "")
    assert "constructor" in err.lower() or "dms" in err.lower()
    assert "/api/routines" in err
    created = cc.routines_create("Morning news brief, daily")
    assert created["ok"] is False
    assert created["reason"] == "wrong_surface"


def test_engine_pack_dms_is_not_constructor(monkeypatch):
    """Netie engine health is pack=dms with no surface=constructor."""
    _down(monkeypatch, status="ok", pack="dms")
    monkeypatch.setattr(cc, "_json_call", lambda *a, **k: {"ok": True, "routines": [], "_http": 200})
    st = cc.scheduler_status(try_spawn=False)
    assert st["ok"] is True
    assert st["reason"] == "live"


def test_health_ok_but_no_routines_endpoint_is_no_scheduler(monkeypatch):
    _down(monkeypatch, status="ok")
    monkeypatch.setattr(cc, "_json_call", lambda *a, **k: {"ok": False, "_http": 404})
    st = cc.scheduler_status(try_spawn=False)
    assert st["ok"] is False
    assert st["reason"] == "no_scheduler"
    assert "404" in str(st.get("error") or "")


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


def test_draft_refuses_instead_of_fabricating_a_preview(monkeypatch):
    """A blank preview card with a live Create button is schedule_hint theater."""
    _down(monkeypatch)
    out = cc.routines_draft("Morning news brief, daily")
    assert out["ok"] is False, out
    assert out["reason"] in REFUSALS
    for field in ("name", "schedule_text", "prompt"):
        assert field not in out, f"a refusal must not carry a renderable {field}"

    # Cortex reachable but answering with an empty draft is equally unrenderable.
    monkeypatch.setattr(cc, "scheduler_status", lambda **kwargs: {"ok": True, "reason": "live"})
    monkeypatch.setattr(cc, "_json_call", lambda *a, **k: {"ok": True, "draft": {}, "_http": 200})
    empty = cc.routines_draft("Morning news brief, daily")
    assert empty["ok"] is False
    assert empty["reason"] == "empty_draft"


def test_routines_list_can_report_offline(monkeypatch):
    """routines_list hard-coded ok:true, so the offline banner was dead code."""
    _down(monkeypatch)
    host_routines.create("legacy row", agent_id=0)
    out = cc.routines_list()
    assert out["ok"] is False, "Cortex is down; the list must not claim ok"
    assert out["reason"] == "cortex_down"
    assert out.get("error")
    # Legacy host rows still reach the wire, but never as Cortex routines.
    assert out["host_routine_count"] == 1
    assert out["host_routines"][0]["scheduler"] == "airgpt_host"
    assert not out.get("routines"), "a down Cortex has no routines to show"


def test_create_path_has_no_airgpt_owned_cron():
    """#60 out-of-scope: Cortex owns the scheduler. No host clock behind create."""
    src = (ROOT / "cortex_client.py").read_text(encoding="utf-8")
    create = _fn(src, "def routines_create(", "def routines_pause(")
    assert "host_routines" not in create, (
        "routines_create must refuse when Cortex cannot schedule, not fall back to "
        "an AirGPT-owned cron (issue #60 out of scope)"
    )
    draft = _fn(src, "def routines_draft(", "def routines_create(")
    assert "host_routines" not in draft


# -- SHELL-02 the host clock that is left: honest about what it did ----------


def test_host_fire_without_an_agent_is_not_ok():
    created = host_routines.create("Morning news brief daily")
    assert created.get("warning"), "agent_id=0 can never run anything; say so at create"
    ran = host_routines.run_now(created["routine_id"], now=1_700_000_000.0)
    assert ran["ok"] is False, "a fire that queued nothing must not report ok"
    assert "no agent" in str(ran.get("error") or "").lower()
    listed = host_routines.list_routines()
    assert listed["unhealthy"], "a routine that runs nothing must surface, not sit in last_status"
    assert listed["unhealthy"][0]["id"] == created["routine_id"]


def test_host_fire_surfaces_queue_failure(monkeypatch):
    import cortex_orchestrator

    monkeypatch.setattr(
        cortex_orchestrator, "queue_run", lambda *a, **k: {"ok": False, "error": "db locked"}
    )
    created = host_routines.create("Morning news brief daily", agent_id=7)
    ran = host_routines.run_now(created["routine_id"], now=1_700_000_000.0)
    assert ran["ok"] is False, ran
    assert "db locked" in str(ran.get("error") or "")
    assert host_routines.list_routines()["unhealthy"]


def test_idle_mode_defers_instead_of_queueing_into_a_parked_worker():
    """_worker_tick returns on idle, so a queued run sat there forever undisclosed."""
    created = host_routines.create("Morning news brief daily", agent_id=7)
    rid = created["routine_id"]
    with host_routines._lock:
        rows = host_routines._load()
        rows[0]["next_run_at"] = 1.0
        host_routines._save(rows)
    out = host_routines.tick(now=1_700_000_000.0, drains=False)
    assert out["fired"] == []
    assert rid in out["deferred"]
    row = host_routines.list_routines()["routines"][0]
    assert row["last_status"] == "deferred_idle"
    assert row["next_run_at"] == 1.0, "a deferred routine stays due; it must not look run"
    assert "idle" in str(row.get("last_error") or "").lower()
    assert host_routines.list_routines()["unhealthy"]


def test_worker_tick_tells_the_clock_whether_the_queue_drains(monkeypatch):
    import cortex_orchestrator

    seen: list[bool] = []
    monkeypatch.setattr(host_routines, "tick", lambda **kw: seen.append(kw.get("drains")) or {})
    monkeypatch.setattr(
        cortex_orchestrator,
        "get_settings",
        lambda: {"thinking_mode": "idle", "token_budget": 1200, "max_steps": 8},
    )
    cortex_orchestrator._worker_tick()
    assert seen == [False], "idle must reach host_routines.tick, not be checked after it"


# -- SHELL-02 the happy path, against a mock Cortex --------------------------


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
    cc._engine_seat.update({"t": 0.0, "url": "", "key": ""})
    try:
        created = cc.routines_create("AirGPT D09 mock ping, hourly")
        assert created.get("ok") is True, created
        assert created.get("scheduler") == "cortex"
        assert created.get("next_run_at") == 1_700_000_000
        ran = cc.routines_run("rt-1")
        assert ran.get("fired") is True, ran
        assert ran.get("next_run_at_before") == 1_700_000_000
        assert ran.get("next_run_at_after") == 1_700_000_300
        listed = cc.routines_list()
        assert listed.get("ok") is True, listed
        assert listed.get("reason") == "live"
    finally:
        srv.shutdown()
        srv.server_close()


def test_forced_run_that_does_not_advance_is_not_fired(monkeypatch):
    """A 200 from /run is not evidence. Only next_run_at moving is."""
    monkeypatch.setattr(cc, "scheduler_status", lambda **kwargs: {"ok": True, "reason": "live"})
    monkeypatch.setattr(
        cc, "_json_call", lambda *a, **k: {"ok": True, "next_run_at": 1_700_000_000, "_http": 200}
    )
    ran = cc.routines_run("rt-1")
    assert ran["fired"] is False
    assert ran["reason"] == "did_not_fire"


# -- Live seat: never skipped, named either way ------------------------------


def test_live_8010_scheduler_honesty():
    """Live Constructor/DMS, a real Cortex, or down -- the wire names which."""
    os.environ["CORTEX_AUTOSPAWN"] = "0"
    cc._avail_cache.update({"t": 0.0, "ok": False})
    cc._engine_seat.update({"t": 0.0, "url": "", "key": ""})
    st = cc.scheduler_status(try_spawn=False)
    assert st.get("reason") in ("live", "wrong_surface", "cortex_down", "no_scheduler"), st
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
        assert cc.routines_delete(str(rid)).get("ok") is True
        return
    assert str(st.get("error") or ""), "soft-fail must name the cause"
    created = cc.routines_create("Morning news brief, daily")
    assert created.get("ok") is False, created
    assert created.get("reason") in REFUSALS


# -- The control says it, not just the wire ----------------------------------


def test_index_says_not_scheduled_rather_than_toasting_success():
    src = _html()
    sched = _fn(src, "async function ensureCortexAgent", "async function ensureCortexConcierge")
    assert "schedule_hint:" not in sched, "schedule_hint is written and read nowhere - theater"
    assert "next_run_at" in sched
    assert "NOT scheduled" in sched


# -- Coverage floors this gate must not quietly lower ------------------------


def test_engine_cfg_does_not_hop_when_configured_url_is_down(monkeypatch):
    """A failed probe is cortex_down, not a silent seat on :8011."""
    monkeypatch.setattr(cc, "_cfg", lambda: ("http://127.0.0.1:1", ""))
    monkeypatch.setattr(cc, "_ENGINE_FALLBACKS", ("http://127.0.0.1:8011",))
    monkeypatch.setattr(cc, "_probe_engine", lambda *a, **k: None)
    monkeypatch.setattr(cc, "_is_engine_specs", lambda *_a, **_k: True)
    cc._engine_seat.update({"t": 0.0, "url": "", "key": ""})
    url, _key = cc._engine_cfg()
    assert url == "http://127.0.0.1:1"


def test_engine_cfg_hops_only_when_surface_is_constructor(monkeypatch):
    monkeypatch.setattr(cc, "_cfg", lambda: ("http://127.0.0.1:8010", ""))
    monkeypatch.setattr(cc, "_ENGINE_FALLBACKS", ("http://127.0.0.1:8011",))

    def probe(url, path, *_a, **_k):
        if ":8010" in str(url) and str(path).endswith("/health"):
            return {"status": "ok", "surface": "constructor", "pack": "dms"}
        if ":8011" in str(url):
            return {"ok": True, "config": {}}
        return None

    monkeypatch.setattr(cc, "_probe_engine", probe)
    monkeypatch.setattr(
        cc, "_is_engine_specs", lambda raw: bool(isinstance(raw, dict) and raw.get("config") is not None)
    )
    cc._engine_seat.update({"t": 0.0, "url": "", "key": ""})
    url, _key = cc._engine_cfg()
    assert url == "http://127.0.0.1:8011"


def test_min_tests_floor_unchanged():
    wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert 'MIN_TESTS: "380"' in wf


def test_multilingual_gate_file_still_present():
    p = ROOT / "tests" / "RAG" / "multilingual_gate.py"
    assert p.is_file(), "P13 multilingual_gate.py must stay; do not skip or delete it"
    src = p.read_text(encoding="utf-8")
    # The words may appear in the file's own R-0002 warning text; the markers may not.
    assert "pytest.skip" not in src
    assert "mark.xfail" not in src

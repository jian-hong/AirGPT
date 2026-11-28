"""BROWSER-01: host-only Playwright control, confirm gate, local fixture tasks.

Live tasks drive the real tool against tests/fixtures/browser_mcp. They skip
only when no Playwright driver can start. A skip is not a pass.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import agent_tools  # noqa: E402
import browser_mcp  # noqa: E402
import chat_tools  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "browser_mcp"
MARKER = "unconfirmed-marker"


@pytest.fixture(autouse=True)
def _reset_caller():
    browser_mcp.clear_caller()
    yield
    browser_mcp.clear_caller()


def _serve():
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(FIXTURE), **kwargs)

        def log_message(self, fmt, *args):
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    return httpd, f"http://127.0.0.1:{port}"


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("AIRGPT_BROWSER_MCP", "1")
    browser_mcp.clear_caller()
    browser_mcp.close()
    httpd, base = _serve()
    probe = browser_mcp.navigate(base + "/index.html", confirmed=True)
    if probe.get("error") in ("driver_missing", "driver_failed"):
        httpd.shutdown()
        browser_mcp.close()
        pytest.skip("browser driver not available: " + str(probe.get("error")))
    if not probe.get("ok"):
        httpd.shutdown()
        browser_mcp.close()
        pytest.fail("probe navigate failed: " + str(probe.get("error")))
    yield base
    browser_mcp.close()
    httpd.shutdown()


def _nodes(node):
    if isinstance(node, dict):
        yield node
        for child in node.get("children") or []:
            yield from _nodes(child)


def _ref(out, role, name):
    for node in _nodes(out.get("tree")):
        if node.get("role") == role and node.get("name") == name:
            return node.get("ref")
    return None


def _node(out, role, name):
    for node in _nodes(out.get("tree")):
        if node.get("role") == role and node.get("name") == name:
            return node
    return None


def _keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield str(key)
            yield from _keys(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _keys(item)


def test_flag_off_does_not_launch(monkeypatch):
    monkeypatch.delenv("AIRGPT_BROWSER_MCP", raising=False)
    before = browser_mcp.launch_count()
    out = browser_mcp.navigate("http://127.0.0.1/")
    assert out["error"] == "browser_mcp_disabled"
    assert out["performed"] is False
    status = browser_mcp.status()
    assert status["enabled"] is False
    assert status["launched"] is False
    assert browser_mcp.launch_count() == before
    desktop = agent_tools.run_tool("desktop_click", {"x": 1, "y": 2, "confirmed": False})
    assert desktop.get("error") == "confirm_required"


def test_flag_off_ignores_confirm(monkeypatch):
    monkeypatch.delenv("AIRGPT_BROWSER_MCP", raising=False)
    before = browser_mcp.launch_count()
    out = browser_mcp.click("e1", confirmed=True)
    assert out["error"] == "browser_mcp_disabled"
    assert out["performed"] is False
    assert browser_mcp.launch_count() == before


@pytest.mark.parametrize("confirmed", [False, 0, 1, "true", "yes", None, "false"])
def test_only_boolean_true_confirms(monkeypatch, confirmed):
    monkeypatch.setenv("AIRGPT_BROWSER_MCP", "1")
    before = browser_mcp.launch_count()
    out = browser_mcp.click("e1", confirmed=confirmed)
    assert out["error"] == "confirm_required"
    assert out["performed"] is False
    assert browser_mcp.launch_count() == before


def test_unconfirmed_does_not_call_perform(monkeypatch):
    monkeypatch.setenv("AIRGPT_BROWSER_MCP", "1")
    calls = []

    def perform(sess, kind, info, *, text="", option=""):
        calls.append(kind)

    monkeypatch.setattr(browser_mcp, "_perform", perform)
    monkeypatch.setattr(
        browser_mcp,
        "_done",
        lambda sess: {"ok": True, "performed": True, "text": "performed-marker"},
    )
    sess = browser_mcp._Session(
        pw=None,
        browser=None,
        context=None,
        page=object(),
        refs={"e1": {"role": "textbox", "name": "Name", "nth": 0}},
    )
    monkeypatch.setattr(browser_mcp, "_ensure_session", lambda: (sess, None))
    blocked = browser_mcp.type_text("e1", "secret-text", confirmed=False)
    assert blocked["error"] == "confirm_required"
    assert blocked["performed"] is False
    assert calls == []
    assert "secret-text" not in json.dumps(blocked)
    for kind, fn in (
        ("click", lambda: browser_mcp.click("e1", confirmed=True)),
        ("type", lambda: browser_mcp.type_text("e1", "Ada", confirmed=True)),
        ("select", lambda: browser_mcp.select_option("e1", "Blue", confirmed=True)),
        ("submit", lambda: browser_mcp.submit("e1", confirmed=True)),
    ):
        out = fn()
        assert out["performed"] is True
        assert calls[-1] == kind


def test_submit_navigation_requires_confirm(monkeypatch):
    monkeypatch.setenv("AIRGPT_BROWSER_MCP", "1")
    before = browser_mcp.launch_count()
    out = browser_mcp.navigate("http://127.0.0.1/", submit=True, confirmed=False)
    assert out["error"] == "confirm_required"
    assert out["performed"] is False
    assert browser_mcp.launch_count() == before


def test_first_navigation_requires_confirm(monkeypatch):
    monkeypatch.setenv("AIRGPT_BROWSER_MCP", "1")
    browser_mcp.close()
    before = browser_mcp.launch_count()
    out = browser_mcp.navigate("http://127.0.0.1:9/first", confirmed=False)
    assert out["error"] == "confirm_required"
    assert out["performed"] is False
    assert browser_mcp.launch_count() == before
    assert browser_mcp.session_open() is False


def test_close_stops_the_browser_on_the_owner_thread(monkeypatch):
    monkeypatch.setenv("AIRGPT_BROWSER_MCP", "1")
    browser_mcp.close()
    closed = []

    class Ctx:
        def close(self):
            closed.append(("context", threading.get_ident()))

    class Browser:
        def close(self):
            closed.append(("browser", threading.get_ident()))

    class Pw:
        def stop(self):
            closed.append(("pw", threading.get_ident()))

    def plant():
        browser_mcp._session = browser_mcp._Session(
            pw=Pw(), browser=Browser(), context=Ctx(), page=object(), refs={}
        )
        return {"ok": True, "owner": threading.get_ident()}

    try:
        planted = browser_mcp._on_owner(plant)
        assert planted["ok"] is True
        assert planted["owner"] != threading.get_ident()
        assert browser_mcp.session_open() is True
        out = browser_mcp.close()
        assert out["ok"] is True
        assert out["launched"] is False
        assert browser_mcp.session_open() is False
        assert [name for name, _ident in closed] == ["context", "browser", "pw"]
        assert {ident for _name, ident in closed} == {planted["owner"]}
    finally:
        browser_mcp.close()


def test_remote_caller_cannot_launch(monkeypatch):
    monkeypatch.setenv("AIRGPT_BROWSER_MCP", "1")
    calls = []
    monkeypatch.setattr(browser_mcp, "_ensure_session", lambda: calls.append(1))
    before = browser_mcp.launch_count()
    assert browser_mcp.bind_caller({"Host": "localhost"}, "198.51.100.20") is False
    try:
        out = agent_tools.run_tool(
            "browser_navigate",
            {"url": "http://127.0.0.1/", "host": True, "confirmed": True},
        )
        assert out["error"] == "host_only"
        assert out["performed"] is False
        clicked = agent_tools.run_tool(
            "browser_click",
            {"ref": "e1", "confirmed": True, "host": True, "apply": False},
        )
        assert clicked["error"] == "host_only"
        assert calls == []
        assert browser_mcp.launch_count() == before
    finally:
        browser_mcp.clear_caller()


def test_spoofed_host_header_with_remote_ip_is_refused(monkeypatch):
    monkeypatch.setenv("AIRGPT_BROWSER_MCP", "1")
    before = browser_mcp.launch_count()
    assert browser_mcp.bind_caller({"Host": "evil.example"}, "198.51.100.21") is False
    try:
        out = browser_mcp.type_text("e1", "nope", confirmed=True)
        assert out["error"] == "host_only"
        assert browser_mcp.launch_count() == before
    finally:
        browser_mcp.clear_caller()


def test_loopback_caller_is_host(monkeypatch):
    monkeypatch.delenv("AIRGPT_BROWSER_MCP", raising=False)
    assert browser_mcp.bind_caller({"Host": "localhost"}, "127.0.0.1") is True
    browser_mcp.clear_caller()


def test_credential_url_is_refused_and_not_echoed(monkeypatch):
    monkeypatch.setenv("AIRGPT_BROWSER_MCP", "1")
    before = browser_mcp.launch_count()
    out = browser_mcp.navigate("https://user:fixture-pw-value@example.com/a")
    blob = json.dumps(out)
    assert out["error"] == "credentials_in_url"
    assert out["performed"] is False
    assert "fixture-pw-value" not in blob
    assert "user:" not in blob
    assert browser_mcp.launch_count() == before


def test_data_url_is_blocked(monkeypatch):
    monkeypatch.setenv("AIRGPT_BROWSER_MCP", "1")
    before = browser_mcp.launch_count()
    out = browser_mcp.navigate("data:text/html,hi")
    assert out["error"] == "unsupported_scheme"
    assert out["performed"] is False
    assert "text/html" not in json.dumps(out)
    assert browser_mcp.launch_count() == before
    assert browser_mcp._allow_request("data:text/html,hi") is False
    assert browser_mcp._allow_request("http://127.0.0.1/index.html") is True


def test_missing_browser_executable_is_not_a_candidate(monkeypatch, tmp_path):
    missing = tmp_path / "no-such-browser"
    monkeypatch.setenv("AIRGPT_BROWSER_EXECUTABLE", str(missing))
    assert str(missing) not in browser_mcp._candidate_executables()


def test_remote_cannot_close(monkeypatch):
    monkeypatch.delenv("AIRGPT_BROWSER_MCP", raising=False)
    assert browser_mcp.bind_caller({"Host": "evil.example"}, "198.51.100.22") is False
    try:
        out = browser_mcp.close()
        assert out["error"] == "host_only"
        assert out["performed"] is False
    finally:
        browser_mcp.clear_caller()


def test_javascript_url_is_refused(monkeypatch):
    monkeypatch.setenv("AIRGPT_BROWSER_MCP", "1")
    before = browser_mcp.launch_count()
    out = browser_mcp.navigate("javascript:alert(1)")
    assert out["error"] == "unsupported_scheme"
    assert "alert" not in json.dumps(out)
    assert browser_mcp.launch_count() == before


def test_public_url_redacts_token_query():
    url = browser_mcp.public_url("http://127.0.0.1/cb?token=fixture-token-value&x=1")
    assert "fixture-token-value" not in url
    assert "x=1" in url
    assert url.startswith("http://127.0.0.1/cb?")


def test_type_audit_omits_text(monkeypatch):
    monkeypatch.setenv("AIRGPT_BROWSER_MCP", "1")
    seen = []

    def capture(tool, args, result, **kwargs):
        seen.append({"tool": tool, "args": args, "result": result})

    monkeypatch.setattr(agent_tools, "_audit", capture)
    agent_tools.run_tool(
        "browser_type",
        {"ref": "e9", "text": "fixture-token-value", "confirmed": False},
    )
    blob = json.dumps(seen)
    assert "fixture-token-value" not in blob
    assert seen and seen[0]["args"]["chars"] == len("fixture-token-value")
    assert seen[0]["args"]["confirmed"] is False


def test_browser_tools_are_registered():
    names = {row["name"] for row in agent_tools.tool_schemas()}
    for name in (
        "browser_status",
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_select",
        "browser_submit",
    ):
        assert name in names
        assert name in agent_tools.TOOLS


def test_chat_cannot_call_browser_tools():
    for name in agent_tools.TOOLS:
        if not name.startswith("browser_"):
            continue
        assert not chat_tools.is_chat_safe(name)
        out = chat_tools.run_chat_tool(name, "{}")
        assert out["ok"] is False
        assert name in out["error"]


def test_host_prefixes_stay_the_same_length():
    import clipdrop

    assert len(clipdrop._HOST_ONLY_PREFIXES) == 26
    assert "/api/desktop" in clipdrop._HOST_ONLY_PREFIXES
    assert "/api/bundle" in clipdrop._HOST_ONLY_PREFIXES


def test_min_tests_floor_unchanged():
    wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert 'MIN_TESTS: "380"' in wf


def _fail(step, out):
    return False, {
        "step": step,
        "ok": out.get("ok"),
        "error": out.get("error"),
        "performed": out.get("performed"),
    }


def _task_navigate(base):
    out = agent_tools.run_tool("browser_navigate", {"url": base + "/index.html"})
    text = out.get("text") or ""
    ok = out.get("ok") is True and "Fixture Home" in text
    return ok, {"ok": out.get("ok"), "error": out.get("error"), "hit": "Fixture Home" in text}


def _task_fill(base):
    nav = agent_tools.run_tool("browser_navigate", {"url": base + "/form.html"})
    ref = _ref(nav, "textbox", "Name")
    if not ref:
        return _fail("navigate", nav)
    typed = agent_tools.run_tool(
        "browser_type", {"ref": ref, "text": "Ada", "confirmed": True}
    )
    save = _ref(typed, "button", "Save draft")
    if not save:
        return _fail("type", typed)
    clicked = agent_tools.run_tool("browser_click", {"ref": save, "confirmed": True})
    text = clicked.get("text") or ""
    ok = clicked.get("ok") is True and "draft:Ada" in text
    return ok, {"ok": clicked.get("ok"), "error": clicked.get("error"), "hit": "draft:Ada" in text}


def _task_table(base):
    out = agent_tools.run_tool("browser_navigate", {"url": base + "/table.html"})
    text = out.get("text") or ""
    nut = text.find("Nut")
    hit = nut >= 0 and "4" in text[nut:nut + 30] and "Bolt" in text
    ok = out.get("ok") is True and hit
    return ok, {"ok": out.get("ok"), "error": out.get("error"), "hit": hit}


def _task_paginate(base):
    nav = agent_tools.run_tool("browser_navigate", {"url": base + "/list.html"})
    ref = _ref(nav, "link", "Next")
    if not ref:
        return _fail("navigate", nav)
    out = agent_tools.run_tool("browser_click", {"ref": ref, "confirmed": True})
    text = out.get("text") or ""
    ok = out.get("ok") is True and "omega-item" in text
    return ok, {"ok": out.get("ok"), "error": out.get("error"), "hit": "omega-item" in text}


def _task_reveal(base):
    nav = agent_tools.run_tool("browser_navigate", {"url": base + "/controls.html"})
    ref = _ref(nav, "button", "Show code")
    if not ref:
        return _fail("navigate", nav)
    out = agent_tools.run_tool("browser_click", {"ref": ref, "confirmed": True})
    text = out.get("text") or ""
    ok = out.get("ok") is True and "WIDGET-42" in text
    return ok, {"ok": out.get("ok"), "error": out.get("error"), "hit": "WIDGET-42" in text}


def _task_select(base):
    nav = agent_tools.run_tool("browser_navigate", {"url": base + "/controls.html"})
    ref = _ref(nav, "combobox", "Color")
    if not ref:
        return _fail("navigate", nav)
    out = agent_tools.run_tool(
        "browser_select", {"ref": ref, "option": "Blue", "confirmed": True}
    )
    text = out.get("text") or ""
    ok = out.get("ok") is True and "picked:Blue" in text
    return ok, {"ok": out.get("ok"), "error": out.get("error"), "hit": "picked:Blue" in text}


def _task_check(base):
    nav = agent_tools.run_tool("browser_navigate", {"url": base + "/controls.html"})
    ref = _ref(nav, "checkbox", "Agree")
    if not ref:
        return _fail("navigate", nav)
    out = agent_tools.run_tool("browser_click", {"ref": ref, "confirmed": True})
    text = out.get("text") or ""
    ok = out.get("ok") is True and "agreed:yes" in text
    return ok, {"ok": out.get("ok"), "error": out.get("error"), "hit": "agreed:yes" in text}


def _task_details(base):
    nav = agent_tools.run_tool("browser_navigate", {"url": base + "/index.html"})
    ref = _ref(nav, "link", "Details")
    if not ref:
        return _fail("navigate", nav)
    out = agent_tools.run_tool("browser_click", {"ref": ref, "confirmed": True})
    text = out.get("text") or ""
    ok = out.get("ok") is True and "Detail Panel" in text
    return ok, {"ok": out.get("ok"), "error": out.get("error"), "hit": "Detail Panel" in text}


def _task_submit(base):
    nav = agent_tools.run_tool("browser_navigate", {"url": base + "/form.html"})
    ref = _ref(nav, "textbox", "Job")
    if not ref:
        return _fail("navigate", nav)
    typed = agent_tools.run_tool(
        "browser_type", {"ref": ref, "text": "welder", "confirmed": True}
    )
    send = _ref(typed, "button", "Send job")
    if not send:
        return _fail("type", typed)
    out = agent_tools.run_tool("browser_submit", {"ref": send, "confirmed": True})
    text = out.get("text") or ""
    ok = out.get("ok") is True and "submitted:welder" in text
    return ok, {"ok": out.get("ok"), "error": out.get("error"), "hit": "submitted:welder" in text}


def _task_filter(base):
    nav = agent_tools.run_tool("browser_navigate", {"url": base + "/controls.html"})
    ref = _ref(nav, "textbox", "Filter")
    if not ref:
        return _fail("navigate", nav)
    out = agent_tools.run_tool(
        "browser_type", {"ref": ref, "text": "Ap", "confirmed": True}
    )
    text = out.get("text") or ""
    hit = "Apple" in text and "Apricot" in text and "Banana" not in text
    ok = out.get("ok") is True and hit
    return ok, {"ok": out.get("ok"), "error": out.get("error"), "hit": hit}


_TASKS = (
    ("navigate", _task_navigate),
    ("fill_form", _task_fill),
    ("read_table", _task_table),
    ("paginate", _task_paginate),
    ("click_reveal", _task_reveal),
    ("select_option", _task_select),
    ("check_box", _task_check),
    ("open_details", _task_details),
    ("submit_form", _task_submit),
    ("filter_list", _task_filter),
)


def test_ten_local_tasks(live):
    results = []
    for name, fn in _TASKS:
        ok, detail = fn(live)
        results.append({"task": name, "ok": bool(ok), "detail": detail})
    passed = sum(1 for row in results if row["ok"])
    Path("/tmp/browser_tasks.json").write_text(json.dumps({"passed": passed, "results": results}, indent=2), encoding="utf-8")
    print("BROWSER_TASKS " + json.dumps(results))
    assert passed >= 8, results


def _pid_alive(pid):
    if not pid or os.name == "nt":
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_cross_origin_navigate_needs_confirm_and_browser_closes(live):
    httpd2 = None
    try:
        same = browser_mcp.navigate(live + "/details.html")
        assert same.get("ok") is True
        assert "Detail Panel" in (same.get("text") or "")
        owner = browser_mcp.owner_thread_ident()
        assert owner not in (None, threading.get_ident())
        box = {}

        def worker():
            box["out"] = browser_mcp.snapshot()
            box["ident"] = threading.get_ident()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=20)
        assert box["out"].get("ok") is True
        assert box["ident"] != owner
        httpd2, other = _serve()
        refused = browser_mcp.navigate(other + "/index.html", confirmed=False)
        assert refused["error"] == "confirm_required"
        assert refused["performed"] is False
        still = browser_mcp.snapshot()
        assert "Detail Panel" in (still.get("text") or "")
        opened = browser_mcp.navigate(other + "/index.html", confirmed=True)
        assert opened.get("ok") is True
        assert "Fixture Home" in (opened.get("text") or "")
        assert browser_mcp.bind_caller({"Host": "evil.example"}, "198.51.100.30") is False
        blocked = browser_mcp.navigate(live + "/table.html", confirmed=True)
        assert blocked["error"] == "host_only"
        assert blocked["performed"] is False
        browser_mcp.clear_caller()
        pids = browser_mcp.browser_pids()
        assert pids
        closed = browser_mcp.close()
        assert closed["ok"] is True
        assert browser_mcp.session_open() is False
        deadline = time.time() + 5
        while time.time() < deadline and any(_pid_alive(pid) for pid in pids):
            time.sleep(0.05)
        assert not any(_pid_alive(pid) for pid in pids)
    finally:
        browser_mcp.clear_caller()
        if httpd2 is not None:
            httpd2.shutdown()


def test_unconfirmed_does_not_change_the_page(live):
    nav = agent_tools.run_tool("browser_navigate", {"url": live + "/form.html"})
    assert nav.get("ok") is True
    ref = _ref(nav, "textbox", "Name")
    assert ref
    typed = agent_tools.run_tool(
        "browser_type", {"ref": ref, "text": MARKER, "confirmed": False}
    )
    assert typed["error"] == "confirm_required"
    assert typed["performed"] is False
    assert MARKER not in json.dumps(typed)
    snap = agent_tools.run_tool("browser_snapshot", {})
    blob = json.dumps(snap)
    assert MARKER not in blob
    assert "draft:" not in (snap.get("text") or "")
    save = _ref(snap, "button", "Save draft")
    assert save
    clicked = agent_tools.run_tool("browser_click", {"ref": save, "confirmed": False})
    assert clicked["error"] == "confirm_required"
    assert clicked["performed"] is False
    send = _ref(snap, "button", "Send job")
    assert send
    sent = agent_tools.run_tool("browser_submit", {"ref": send, "confirmed": False})
    assert sent["error"] == "confirm_required"
    assert sent["performed"] is False
    again = agent_tools.run_tool("browser_snapshot", {})
    text = again.get("text") or ""
    assert MARKER not in text
    assert "draft:" not in text
    assert "submitted:" not in text


def test_secrets_do_not_reach_the_tool_result(live):
    out = agent_tools.run_tool("browser_navigate", {"url": live + "/secrets.html"})
    assert out.get("ok") is True
    blob = json.dumps(out)
    assert "fixture-pw-value" not in blob
    assert "fixture-token-value" not in blob
    password = _node(out, "textbox", "Password")
    assert password is not None
    assert password.get("value") == "[redacted]"
    lowered = {key.lower() for key in _keys(out)}
    assert "cookies" not in lowered
    assert "authorization" not in lowered
    assert "set-cookie" not in lowered

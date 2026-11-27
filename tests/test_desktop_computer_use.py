"""Desktop computer-use foundation + playbook (no real clicks in unit tests)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import desktop_control
import desktop_playbook
import agent_tools


def test_available_reports_platform():
    a = desktop_control.available()
    assert a["ok"] is True
    assert "platform" in a


def test_click_requires_confirm():
    out = desktop_control.click(10, 10, confirmed=False)
    assert out["ok"] is False
    assert out["error"] == "confirm_required"


def test_type_requires_confirm():
    out = desktop_control.type_text("hi", confirmed=False)
    assert out["error"] == "confirm_required"


def test_plan_writing_prefers_word_when_open(monkeypatch):
    monkeypatch.setattr(
        desktop_control,
        "observe",
        lambda: {
            "ok": True,
            "foreground": {"title": "Essay.docx - Word", "pid": 1},
            "windows": {
                "windows": [
                    {"title": "Essay.docx - Word", "kind": "word"},
                    {"title": "Claude", "kind": "claude"},
                ]
            },
        },
    )
    plan = desktop_playbook.plan_task("write an essay about nets")
    assert plan["kind"] == "writing"
    assert plan["primary"] == "word"
    assert plan["policy"]["input_needs_confirm"] is True


def test_plan_writing_falls_back_to_claude(monkeypatch):
    monkeypatch.setattr(
        desktop_control,
        "observe",
        lambda: {
            "ok": True,
            "foreground": {"title": "Claude", "pid": 1},
            "windows": {"windows": [{"title": "Claude", "kind": "claude"}]},
        },
    )
    plan = desktop_playbook.plan_task("draft a novel chapter", tokens_left=9000)
    assert plan["primary"] == "claude"


def test_plan_tutorial_when_nothing_open(monkeypatch):
    monkeypatch.setattr(
        desktop_control,
        "observe",
        lambda: {"ok": True, "foreground": {"title": ""}, "windows": {"windows": []}},
    )
    plan = desktop_playbook.plan_task("write an essay")
    assert plan["primary"] == "tutorial"


def test_agent_tools_expose_desktop():
    names = {s["name"] for s in agent_tools.tool_schemas()}
    assert "desktop_observe" in names
    assert "desktop_plan" in names
    assert "desktop_click" in names


def test_desktop_click_tool_confirm_gate():
    out = agent_tools.run_tool("desktop_click", {"x": 1, "y": 2, "confirmed": False})
    assert out.get("error") == "confirm_required"


def _reset_scale_state():
    desktop_control._frame_box[0] = (0, 0, 0, 0)
    desktop_control._dpi_done = False
    desktop_control._dpi_mode = ""


def _frame_2560():
    from PIL import Image

    return Image.new("RGB", (2560, 1440), (0, 0, 0))


class _Pointer:
    def __init__(self):
        self.pos: list[tuple[int, int]] = []
        self.events: list[tuple[int, int]] = []
        self.dpi: list[str] = []

    def set_cursor(self, x, y):
        self.pos.append((int(x), int(y)))

    def mouse(self, flags, dx, dy, data, extra):
        self.events.append((int(flags), int(data)))

    def dpi_on(self):
        self.dpi.append("on")
        return "per_monitor_v2"


def _arm(monkeypatch, flag: str | None):
    """Pretend this is Windows and capture the cursor. No real click."""
    _reset_scale_state()
    pointer = _Pointer()
    image = _frame_2560()
    monkeypatch.setattr(desktop_control, "_windows", lambda: True)
    monkeypatch.setattr(desktop_control, "_grab_primary", lambda: image.copy())
    monkeypatch.setattr(desktop_control, "_set_cursor", pointer.set_cursor)
    monkeypatch.setattr(desktop_control, "_mouse", pointer.mouse)
    monkeypatch.setattr(desktop_control, "_os_set_dpi_aware", pointer.dpi_on)
    if flag is None:
        monkeypatch.delenv("AIRGPT_DESKTOP_SCALE", raising=False)
    else:
        monkeypatch.setenv("AIRGPT_DESKTOP_SCALE", flag)
    return pointer


def test_scale_off_keeps_screenshot_pixels(monkeypatch):
    pointer = _arm(monkeypatch, None)
    shot = desktop_control.screenshot(max_side=1280, as_b64=False)
    assert shot["ok"] is True
    assert shot["full_width"] == 2560 and shot["full_height"] == 1440
    assert shot["width"] == 1280 and shot["height"] == 720
    assert "scale" not in shot and "dpi" not in shot
    assert pointer.dpi == []
    out = desktop_control.click(640, 360, confirmed=True)
    assert out == {"ok": True, "x": 640, "y": 360, "button": "left"}
    assert pointer.pos == [(640, 360)]
    pointer.pos.clear()
    monkeypatch.setenv("AIRGPT_DESKTOP_SCALE", "true")
    out = desktop_control.click(640, 360, confirmed=True)
    assert pointer.pos == [(640, 360)]
    assert out["x"] == 640 and out["y"] == 360


def test_scale_maps_screenshot_center_to_screen(monkeypatch):
    """2560x1440 shot shown as 1280x720: (640, 360) -> (1280, 720)."""
    pointer = _arm(monkeypatch, "1")
    shot = desktop_control.screenshot(max_side=1280, as_b64=False)
    assert shot["width"] == 1280 and shot["height"] == 720
    assert shot["full_width"] == 2560 and shot["full_height"] == 1440
    assert shot["scale"] == 0.5
    assert shot["scale_y"] == 0.5
    assert shot["dpi"] == "per_monitor_v2"
    assert pointer.dpi == ["on"]

    click = desktop_control.click(640, 360, confirmed=True)
    assert click["ok"] is True
    assert click["x"] == 1280 and click["y"] == 720
    assert pointer.pos[0] == (1280, 720)

    pointer.pos.clear()
    drag = desktop_control.drag(640, 360, 320, 180, confirmed=True, steps=2)
    assert drag["from"] == [1280, 720]
    assert drag["to"] == [640, 360]
    assert pointer.pos[0] == (1280, 720)
    assert pointer.pos[-1] == (640, 360)

    pointer.pos.clear()
    scrolled = desktop_control.scroll(-3, x=640, y=360, confirmed=True)
    assert scrolled["ok"] is True
    assert scrolled["x"] == 1280 and scrolled["y"] == 720
    assert scrolled["dy"] == -3
    assert pointer.pos == [(1280, 720)]
    assert (0x0800, -360) in pointer.events


def test_scale_is_identity_when_the_grab_already_fits(monkeypatch):
    _reset_scale_state()
    from PIL import Image

    image = Image.new("RGB", (800, 600), (1, 2, 3))
    pointer = _Pointer()
    monkeypatch.setattr(desktop_control, "_windows", lambda: True)
    monkeypatch.setattr(desktop_control, "_grab_primary", lambda: image.copy())
    monkeypatch.setattr(desktop_control, "_set_cursor", pointer.set_cursor)
    monkeypatch.setattr(desktop_control, "_mouse", pointer.mouse)
    monkeypatch.setattr(desktop_control, "_os_set_dpi_aware", pointer.dpi_on)
    monkeypatch.setenv("AIRGPT_DESKTOP_SCALE", "1")
    shot = desktop_control.screenshot(max_side=1280, as_b64=False)
    assert shot["width"] == 800 and shot["height"] == 600
    assert shot["full_width"] == 800 and shot["full_height"] == 600
    assert shot["scale"] == 1.0 and shot["scale_y"] == 1.0
    out = desktop_control.click(100, 80, confirmed=True)
    assert out["x"] == 100 and out["y"] == 80
    assert pointer.pos == [(100, 80)]


def test_scale_flag_does_not_drop_the_confirm_gate(monkeypatch):
    pointer = _arm(monkeypatch, "1")
    for call in (
        lambda: desktop_control.click(640, 360, confirmed=False),
        lambda: desktop_control.drag(640, 360, 1, 1, confirmed=False),
        lambda: desktop_control.scroll(-3, x=640, y=360, confirmed=False),
    ):
        out = call()
        assert out["ok"] is False
        assert out["error"] == "confirm_required"
    assert pointer.pos == []
    assert pointer.dpi == []


def test_dpi_setter_asks_for_per_monitor_v2(monkeypatch):
    """The real setter, against a stand-in for user32/shcore. No process change."""
    import ctypes

    calls: list[tuple] = []

    class _Fn:
        def __init__(self, name, result):
            self.name = name
            self.result = result
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            calls.append((self.name, args))
            return self.result

    class _User32:
        def __init__(self, ctx_ok):
            self.SetProcessDpiAwarenessContext = _Fn("ctx", ctx_ok)
            self.SetProcessDPIAware = _Fn("legacy", True)

    class _Shcore:
        def __init__(self, hr):
            self.SetProcessDpiAwareness = _Fn("shcore", hr)

    class _Windll:
        def __init__(self, ctx_ok, hr):
            self.user32 = _User32(ctx_ok)
            self.shcore = _Shcore(hr)

    monkeypatch.setattr(ctypes, "windll", _Windll(True, 0), raising=False)
    assert desktop_control._os_set_dpi_aware() == "per_monitor_v2"
    assert calls[0][0] == "ctx"
    assert isinstance(calls[0][1][0], ctypes.c_void_p)
    assert calls[0][1][0].value == ctypes.c_void_p(-4).value
    assert [name for name, _ in calls] == ["ctx"]

    calls.clear()
    monkeypatch.setattr(ctypes, "windll", _Windll(False, 0x80070005), raising=False)
    assert desktop_control._os_set_dpi_aware() == "already_set"
    assert [name for name, _ in calls] == ["ctx", "shcore"]
    assert calls[1][1] == (2,)


def test_scroll_without_a_point_does_not_move(monkeypatch):
    pointer = _arm(monkeypatch, "1")
    desktop_control.screenshot(max_side=1280, as_b64=False)
    pointer.pos.clear()
    out = desktop_control.scroll(-3, confirmed=True)
    assert out == {"ok": True, "dy": -3}
    assert pointer.pos == []
    pointer.pos.clear()
    monkeypatch.setenv("AIRGPT_DESKTOP_SCALE", "0")
    out = desktop_control.scroll(-3, x=640, y=360, confirmed=True)
    assert out == {"ok": True, "dy": -3}
    assert "x" not in out
    assert pointer.pos == []

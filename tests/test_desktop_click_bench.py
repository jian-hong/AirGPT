"""50-target click bench for screenshot pixels vs screen pixels.

The grid is drawn in memory. CI has no 150% monitor, so display scale is
a coordinate model of the bug the ticket names:

- The grab is the physical framebuffer (2560x1440) at both scales.
  That is the mismatch: ImageGrab's size does not follow logical DPI.
- 100%: SetCursorPos pixels are the framebuffer.
- 150%, process not DPI-aware: SetCursorPos is logical, and the OS
  multiplies by 1.5 to reach the framebuffer.
- 150%, after the scale flag sets per-monitor awareness: SetCursorPos
  is physical, same space as the grab.

A hit is the cursor landing inside that target's drawn rectangle.
The flag-off runs are the baseline on this same harness. Counts below
are whatever this process measured; the asserts only encode the ticket
(baseline misses, 48/50 or better with the flag on at both scales).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import desktop_control

FULL_W, FULL_H = 2560, 1440
COLS, ROWS = 10, 5
MARGIN = 120
HALF = 36  # 72px box; rounding error is about 1px


def _reset():
    desktop_control._frame_box[0] = (0, 0, 0, 0)
    desktop_control._dpi_done = False
    desktop_control._dpi_mode = ""


def _centers():
    cw = (FULL_W - 2 * MARGIN) / COLS
    ch = (FULL_H - 2 * MARGIN) / ROWS
    points = []
    for row in range(ROWS):
        for col in range(COLS):
            cx = int(round(MARGIN + (col + 0.5) * cw))
            cy = int(round(MARGIN + (row + 0.5) * ch))
            points.append((cx, cy))
    assert len(points) == 50
    return points


def _draw(points):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (FULL_W, FULL_H), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    for i, (cx, cy) in enumerate(points):
        # Flat colour so a later reader can see the target. Hits use the box.
        shade = 40 + (i % 10) * 20
        draw.rectangle(
            [cx - HALF, cy - HALF, cx + HALF, cy + HALF],
            fill=(shade, 40 + (i // 10) * 30, 200),
        )
    return image


class _Os:
    """Cursor space. Awareness is applied only if the product calls it."""

    def __init__(self, dpi: float, image, aware_sticks: bool):
        self.dpi = float(dpi)
        self.image = image
        self.aware_sticks = aware_sticks
        self.aware = False
        self.dpi_calls = 0
        self.cursor = (0.0, 0.0)

    def mark_dpi(self):
        self.dpi_calls += 1
        if self.aware_sticks:
            self.aware = True
        return "per_monitor_v2"

    def grab(self):
        return self.image.copy()

    def set_cursor(self, x, y):
        if self.aware or abs(self.dpi - 1.0) < 1e-9:
            self.cursor = (float(x), float(y))
        else:
            self.cursor = (float(x) * self.dpi, float(y) * self.dpi)

    def mouse(self, flags, dx, dy, data, extra):
        return None


def _inside(px, py, cx, cy) -> bool:
    return abs(px - cx) <= HALF and abs(py - cy) <= HALF


def _run(monkeypatch, dpi: float, flag: str, aware_sticks: bool = True) -> dict:
    _reset()
    points = _centers()
    os_model = _Os(dpi, _draw(points), aware_sticks)
    monkeypatch.setattr(desktop_control, "_windows", lambda: True)
    monkeypatch.setattr(desktop_control, "_grab_primary", os_model.grab)
    monkeypatch.setattr(desktop_control, "_set_cursor", os_model.set_cursor)
    monkeypatch.setattr(desktop_control, "_mouse", os_model.mouse)
    monkeypatch.setattr(desktop_control, "_os_set_dpi_aware", os_model.mark_dpi)
    monkeypatch.setenv("AIRGPT_DESKTOP_SCALE", flag)

    shot = desktop_control.screenshot(max_side=1280, as_b64=False)
    assert shot["ok"] is True, shot
    assert shot["full_width"] == FULL_W and shot["full_height"] == FULL_H
    assert shot["width"] == 1280 and shot["height"] == 720

    hits = 0
    misses = []
    for index, (cx, cy) in enumerate(points):
        sx = int(round(cx * shot["width"] / shot["full_width"]))
        sy = int(round(cy * shot["height"] / shot["full_height"]))
        out = desktop_control.click(sx, sy, confirmed=True)
        assert out["ok"] is True, out
        px, py = os_model.cursor
        if _inside(px, py, cx, cy):
            hits += 1
        else:
            misses.append((index, sx, sy, px, py, cx, cy))
    return {
        "dpi": dpi,
        "flag": flag,
        "aware_sticks": aware_sticks,
        "hits": hits,
        "targets": len(points),
        "dpi_calls": os_model.dpi_calls,
        "misses": misses[:5],
    }


def test_click_bench_50_targets_at_100_and_150(monkeypatch):
    off_100 = _run(monkeypatch, 1.0, "0")
    on_100 = _run(monkeypatch, 1.0, "1")
    off_150 = _run(monkeypatch, 1.5, "0")
    on_150 = _run(monkeypatch, 1.5, "1")
    text = (
        f"click_bench off100={off_100['hits']}/50 on100={on_100['hits']}/50 "
        f"off150={off_150['hits']}/50 on150={on_150['hits']}/50 "
        f"dpi_calls off={off_100['dpi_calls']},{off_150['dpi_calls']} "
        f"on={on_100['dpi_calls']},{on_150['dpi_calls']}"
    )
    print(text)
    # Baseline on this harness: many misses. Flag on: at least 48/50.
    assert off_100["hits"] <= 10, (text, off_100["misses"])
    assert off_150["hits"] <= 10, (text, off_150["misses"])
    assert on_100["hits"] >= 48, (text, on_100["misses"])
    assert on_150["hits"] >= 48, (text, on_150["misses"])
    assert off_100["dpi_calls"] == 0 and off_150["dpi_calls"] == 0, text
    assert on_100["dpi_calls"] >= 1 and on_150["dpi_calls"] >= 1, text


def test_click_bench_150_misses_when_dpi_call_does_not_take(monkeypatch):
    """Scale without a shared coordinate space still misses at 150%."""
    missed = _run(monkeypatch, 1.5, "1", aware_sticks=False)
    print(f"click_bench dpi_noop_150={missed['hits']}/50 calls={missed['dpi_calls']}")
    assert missed["dpi_calls"] >= 1, missed
    assert missed["hits"] <= 10, missed

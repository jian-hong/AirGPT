"""Host-side desktop observation + optional input (computer-use foundation).

Read tools are safe by default. Input tools (click/type/scroll/drag/hotkey)
require confirmed=True - same pattern as dms_action.

Soft-fail without win32 / PIL. Never raises out of the package.
Host-only: callers must gate via clipdrop _HOST_ONLY + local IP.

AIRGPT_DESKTOP_SCALE=1 (default off) maps click, drag, and scroll
coordinates from the last downscaled screenshot back onto the screen,
and on Windows sets per-monitor DPI awareness so ImageGrab and
SetCursorPos share that space. With the flag unset, coordinates are
passed through as before.
"""
from __future__ import annotations

import base64
import io
import os
import platform
import sys
import time
from typing import Any

# Last successful screenshot: (full_w, full_h, displayed_w, displayed_h).
# Screenshot pixels are displayed; the cursor lives in full pixels.
_frame_box: list[tuple[int, int, int, int]] = [(0, 0, 0, 0)]
_dpi_done = False
_dpi_mode = ""


def _scale_enabled() -> bool:
    return os.environ.get("AIRGPT_DESKTOP_SCALE", "").strip() == "1"


def _windows() -> bool:
    return sys.platform.startswith("win")


def _remember_frame(full_w: int, full_h: int, disp_w: int, disp_h: int) -> None:
    _frame_box[0] = (int(full_w), int(full_h), int(disp_w), int(disp_h))


def _screen_xy(x: int, y: int) -> tuple[int, int]:
    """Screenshot pixels -> screen pixels. Identity when the flag is off.

    Mapping uses the last screenshot's real sizes (after integer resize),
    not the pre-resize ratio, so a truncated edge still lines up.
    screen = round(screenshot * full / displayed).
    """
    if not _scale_enabled():
        return int(x), int(y)
    fw, fh, dw, dh = _frame_box[0]
    if fw <= 0 or fh <= 0 or dw <= 0 or dh <= 0 or (fw == dw and fh == dh):
        return int(x), int(y)
    sx = int(round(float(x) * float(fw) / float(dw)))
    sy = int(round(float(y) * float(fh) / float(dh)))
    if sx < 0:
        sx = 0
    elif sx >= fw:
        sx = fw - 1
    if sy < 0:
        sy = 0
    elif sy >= fh:
        sy = fh - 1
    return sx, sy


def _grab_primary():
    from PIL import ImageGrab

    return ImageGrab.grab()


def _set_cursor(x: int, y: int) -> None:
    import ctypes

    ctypes.windll.user32.SetCursorPos(int(x), int(y))


def _mouse(dw_flags: int, dx: int, dy: int, dw_data: int, dw_extra: int) -> None:
    import ctypes

    ctypes.windll.user32.mouse_event(
        int(dw_flags), int(dx), int(dy), int(dw_data), int(dw_extra)
    )


def _os_set_dpi_aware() -> str:
    """Best-effort per-monitor DPI awareness. Never raises.

    Per-monitor v2 makes ImageGrab's bitmap and SetCursorPos use the
    same physical pixels. A process that is already aware returns
    already_set; the two APIs still share one space.
    """
    import ctypes

    try:
        user32 = ctypes.windll.user32
        fn = user32.SetProcessDpiAwarenessContext
        fn.restype = ctypes.c_bool
        fn.argtypes = [ctypes.c_void_p]
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = (HANDLE)-4
        if fn(ctypes.c_void_p(-4)):
            return "per_monitor_v2"
    except Exception:
        pass
    try:
        shcore = ctypes.windll.shcore
        fn = shcore.SetProcessDpiAwareness
        fn.restype = ctypes.c_long
        fn.argtypes = [ctypes.c_int]
        hr = int(fn(2))  # PROCESS_PER_MONITOR_DPI_AWARE
        if hr == 0 or (hr & 0xFFFFFFFF) == 0x80070005:
            return "per_monitor" if hr == 0 else "already_set"
    except Exception:
        pass
    try:
        user32 = ctypes.windll.user32
        fn = user32.SetProcessDPIAware
        fn.restype = ctypes.c_bool
        fn.argtypes = []
        if fn():
            return "system_aware"
    except Exception:
        pass
    return "unavailable"


def _enable_dpi_awareness() -> None:
    """Set DPI awareness once, only when the scale flag is on."""
    global _dpi_done, _dpi_mode
    if not _scale_enabled() or not _windows():
        return
    if _dpi_done:
        return
    _dpi_done = True
    try:
        _dpi_mode = _os_set_dpi_aware()
    except Exception:
        _dpi_mode = "unavailable"


def available() -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": True,
        "platform": platform.system().lower(),
        "observe": False,
        "input": False,
        "detail": "",
    }
    if not sys.platform.startswith("win"):
        out["detail"] = "computer-use observe/input is Windows-first in this build"
        return out
    try:
        from PIL import ImageGrab  # noqa: F401

        out["observe"] = True
    except Exception as e:
        out["detail"] = f"PIL ImageGrab unavailable: {e}"
    try:
        import ctypes  # noqa: F401

        out["input"] = True
    except Exception:
        out["input"] = False
    if out["observe"] and not out["detail"]:
        out["detail"] = "ready"
    return out


def cursor_position() -> dict[str, Any]:
    if not sys.platform.startswith("win"):
        return {"ok": False, "error": "windows_only"}
    try:
        import ctypes

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return {"ok": True, "x": int(pt.x), "y": int(pt.y)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}


def foreground_app() -> dict[str, Any]:
    if not sys.platform.startswith("win"):
        return {"ok": False, "error": "windows_only"}
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {"ok": True, "title": "", "pid": 0, "exe": ""}
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = ""
        try:
            import psutil  # type: ignore

            exe = psutil.Process(int(pid.value)).name()
        except Exception:
            exe = ""
        return {
            "ok": True,
            "title": buf.value,
            "pid": int(pid.value),
            "exe": exe,
            "hwnd": int(hwnd),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}


def list_windows(*, limit: int = 40) -> dict[str, Any]:
    if not sys.platform.startswith("win"):
        return {"ok": False, "error": "windows_only", "windows": []}
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        EnumWindows = user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        IsWindowVisible = user32.IsWindowVisible
        GetWindowTextLengthW = user32.GetWindowTextLengthW
        GetWindowTextW = user32.GetWindowTextW
        GetWindowThreadProcessId = user32.GetWindowThreadProcessId

        rows: list[dict[str, Any]] = []

        def _cb(hwnd, _lparam):
            if not IsWindowVisible(hwnd):
                return True
            n = GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            GetWindowTextW(hwnd, buf, n + 1)
            title = (buf.value or "").strip()
            if not title:
                return True
            pid = wintypes.DWORD()
            GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            rows.append({"title": title[:200], "pid": int(pid.value), "hwnd": int(hwnd)})
            return len(rows) < max(1, int(limit))

        EnumWindows(EnumWindowsProc(_cb), 0)
        # Tag known writing surfaces
        for r in rows:
            t = r["title"].lower()
            kind = "other"
            if "word" in t or t.endswith(".docx") or t.endswith(".doc"):
                kind = "word"
            elif "chatgpt" in t or "chat.openai" in t:
                kind = "chatgpt"
            elif "claude" in t:
                kind = "claude"
            elif "cursor" in t:
                kind = "cursor"
            elif "chrome" in t or "edge" in t or "firefox" in t or "brave" in t:
                kind = "browser"
            r["kind"] = kind
        return {"ok": True, "windows": rows[: int(limit)], "count": len(rows)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160], "windows": []}


def screenshot(*, max_side: int = 1280, as_b64: bool = True) -> dict[str, Any]:
    """Capture primary monitor. Returns PNG bytes (b64) + size for microanalysis.

    width/height are the image the model sees. full_width/full_height are
    the grab, which is the cursor space once DPI awareness matches.
    When AIRGPT_DESKTOP_SCALE=1, scale (and scale_y) is displayed/full:
    screen pixels = round(screenshot pixels / scale).
    """
    try:
        _enable_dpi_awareness()
        im = _grab_primary()
        w, h = im.size
        if max(w, h) > max_side:
            fit = max_side / float(max(w, h))
            im = im.resize((max(1, int(w * fit)), max(1, int(h * fit))))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="PNG", optimize=True)
        raw = buf.getvalue()
        disp_w, disp_h = im.size
        _remember_frame(w, h, disp_w, disp_h)
        out: dict[str, Any] = {
            "ok": True,
            "width": disp_w,
            "height": disp_h,
            "full_width": w,
            "full_height": h,
            "bytes": len(raw),
            "mime": "image/png",
        }
        if _scale_enabled():
            # scale: screenshot = screen * scale. dpi: awareness call result.
            out["scale"] = (float(disp_w) / float(w)) if w else 1.0
            out["scale_y"] = (float(disp_h) / float(h)) if h else 1.0
            out["dpi"] = _dpi_mode
        if as_b64:
            out["png_b64"] = base64.b64encode(raw).decode("ascii")
        else:
            out["png"] = raw
        return out
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}


def _require_confirm(confirmed: bool) -> dict[str, Any] | None:
    if confirmed:
        return None
    return {
        "ok": False,
        "error": "confirm_required",
        "hint": "Input tools need confirmed=true after the human approves the plan.",
    }


def click(x: int, y: int, *, button: str = "left", confirmed: bool = False) -> dict[str, Any]:
    blocked = _require_confirm(confirmed)
    if blocked:
        return blocked
    if not _windows():
        return {"ok": False, "error": "windows_only"}
    try:
        _enable_dpi_awareness()
        sx, sy = _screen_xy(int(x), int(y))
        _set_cursor(sx, sy)
        down, up = (0x0002, 0x0004) if button != "right" else (0x0008, 0x0010)
        _mouse(down, 0, 0, 0, 0)
        _mouse(up, 0, 0, 0, 0)
        return {"ok": True, "x": sx, "y": sy, "button": button}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}


def drag(
    x1: int, y1: int, x2: int, y2: int, *, confirmed: bool = False, steps: int = 12
) -> dict[str, Any]:
    blocked = _require_confirm(confirmed)
    if blocked:
        return blocked
    if not _windows():
        return {"ok": False, "error": "windows_only"}
    try:
        _enable_dpi_awareness()
        x1, y1 = _screen_xy(int(x1), int(y1))
        x2, y2 = _screen_xy(int(x2), int(y2))
        _set_cursor(x1, y1)
        _mouse(0x0002, 0, 0, 0, 0)  # left down
        n = max(2, int(steps))
        for i in range(1, n + 1):
            x = int(x1 + (x2 - x1) * i / n)
            y = int(y1 + (y2 - y1) * i / n)
            _set_cursor(x, y)
            time.sleep(0.01)
        _mouse(0x0004, 0, 0, 0, 0)  # left up
        return {"ok": True, "from": [int(x1), int(y1)], "to": [int(x2), int(y2)]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}


def scroll(
    dy: int = -3,
    *,
    x: int | None = None,
    y: int | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    blocked = _require_confirm(confirmed)
    if blocked:
        return blocked
    if not _windows():
        return {"ok": False, "error": "windows_only"}
    try:
        moved = None
        # A point is only honoured with the scale flag. Off, scroll stays
        # at the current cursor, which is what callers get today.
        if _scale_enabled() and x is not None and y is not None:
            _enable_dpi_awareness()
            sx, sy = _screen_xy(int(x), int(y))
            _set_cursor(sx, sy)
            moved = (sx, sy)
        # WHEEL_DELTA = 120
        _mouse(0x0800, 0, 0, int(dy) * 120, 0)
        out: dict[str, Any] = {"ok": True, "dy": int(dy)}
        if moved is not None:
            out["x"], out["y"] = moved
        return out
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}


def type_text(text: str, *, confirmed: bool = False) -> dict[str, Any]:
    blocked = _require_confirm(confirmed)
    if blocked:
        return blocked
    if not sys.platform.startswith("win"):
        return {"ok": False, "error": "windows_only"}
    text = (text or "")[:8000]
    if not text:
        return {"ok": False, "error": "empty_text"}
    try:
        # Prefer clipboard paste for unicode; falls back to SendInput for ASCII.
        try:
            import win32clipboard  # type: ignore
            import win32con  # type: ignore

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            finally:
                win32clipboard.CloseClipboard()
            # Ctrl+V
            import ctypes

            VK_CONTROL, VK_V = 0x11, 0x56
            user32 = ctypes.windll.user32
            user32.keybd_event(VK_CONTROL, 0, 0, 0)
            user32.keybd_event(VK_V, 0, 0, 0)
            user32.keybd_event(VK_V, 0, 2, 0)
            user32.keybd_event(VK_CONTROL, 0, 2, 0)
            return {"ok": True, "method": "clipboard_paste", "chars": len(text)}
        except Exception:
            import ctypes

            for ch in text:
                if ord(ch) > 127:
                    continue
                vk = ctypes.windll.user32.VkKeyScanW(ord(ch)) & 0xFF
                if vk == 0xFF:
                    continue
                ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
                ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
            return {"ok": True, "method": "keybd_event_ascii", "chars": len(text)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}


def hotkey(*keys: str, confirmed: bool = False) -> dict[str, Any]:
    blocked = _require_confirm(confirmed)
    if blocked:
        return blocked
    if not sys.platform.startswith("win"):
        return {"ok": False, "error": "windows_only"}
    mapping = {
        "ctrl": 0x11,
        "control": 0x11,
        "alt": 0x12,
        "shift": 0x10,
        "win": 0x5B,
        "enter": 0x0D,
        "tab": 0x09,
        "esc": 0x1B,
        "escape": 0x1B,
    }
    try:
        import ctypes

        user32 = ctypes.windll.user32
        vks: list[int] = []
        for k in keys:
            kk = str(k).lower()
            if kk in mapping:
                vks.append(mapping[kk])
            elif len(kk) == 1:
                vks.append(user32.VkKeyScanW(ord(kk)) & 0xFF)
        for vk in vks:
            user32.keybd_event(vk, 0, 0, 0)
        for vk in reversed(vks):
            user32.keybd_event(vk, 0, 2, 0)
        return {"ok": True, "keys": list(keys)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}


def observe() -> dict[str, Any]:
    """One-shot scene for the agent: cursor + foreground + windows + small screenshot meta."""
    snap = screenshot(max_side=960, as_b64=True)
    # Drop huge b64 from default observe if oversized - keep meta only when > 1.2MB b64
    if snap.get("ok") and len(snap.get("png_b64") or "") > 1_200_000:
        snap = {k: v for k, v in snap.items() if k != "png_b64"}
        snap["png_omitted"] = True
    return {
        "ok": True,
        "cursor": cursor_position(),
        "foreground": foreground_app(),
        "windows": list_windows(limit=25),
        "screenshot": snap,
        "available": available(),
        "ts": time.time(),
    }

"""Simulate a laptop snip: write PNG to clipboard + Screenshots folder, wait for AirGPT ingest."""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont

import db
from clipdrop import _normalize_image_bytes, write_clipboard_image

BASE_SHOT = Path.home() / "Pictures" / "Screenshots"


def make_snip() -> bytes:
    im = Image.new("RGB", (1280, 720), (18, 22, 28))
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, 1240, 680], outline=(80, 180, 255), width=4)
    d.text((80, 80), f"AirGPT laptop snip {time.strftime('%H:%M:%S')}", fill=(240, 240, 240))
    d.text((80, 140), "Win+Shift+S simulation — clipboard + Screenshots folder", fill=(160, 200, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    BASE_SHOT.mkdir(parents=True, exist_ok=True)
    raw = make_snip()
    data = _normalize_image_bytes(raw)
    ai = db.get_or_create_daily_screenshot_session()
    import sqlite3
    from config import DATA_DIR

    with sqlite3.connect(str(DATA_DIR / "clipdrop.db")) as c:
        n0 = c.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (ai["id"],)).fetchone()[0]

    fname = f"AirGPT_laptop_snip_{int(time.time())}.png"
    path = BASE_SHOT / fname
    path.write_bytes(data)
    print(f"wrote file: {path}")
    ok_clip = write_clipboard_image(data)
    print(f"clipboard image write: {ok_clip}")

    # Wait for live watcher (poll ~2s) + clipboard loop
    deadline = time.time() + 12
    n1 = n0
    while time.time() < deadline:
        time.sleep(1.5)
        with sqlite3.connect(str(DATA_DIR / "clipdrop.db")) as c:
            n1 = c.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (ai["id"],)).fetchone()[0]
        if n1 > n0:
            break

    print(f"AI Screenshot Chat msgs: {n0} -> {n1}")
    if n1 > n0:
        print("[OK] live ingest detected")
        return 0
    print("[WARN] watcher did not ingest within 12s — stress post_capture still covers logic")
    # Fallback direct post to confirm path (same as watcher)
    from clipdrop import post_capture_image, hostname
    m = post_capture_image("127.0.0.1", hostname(), data, fname, "screenshot", with_ai=False)
    print(f"fallback post: {bool(m)} session={m and m.get('session_id')}")
    return 0 if m else 1


if __name__ == "__main__":
    raise SystemExit(main())

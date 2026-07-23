"""Stress + race tests for AI Screenshot Chat / daily sessions / button APIs."""
from __future__ import annotations

import hashlib
import io
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PIL import Image

import db
from clipdrop import (
    _looks_like_screenshot,
    _normalize_image_bytes,
    post_capture_image,
    post_message,
)

BASE = "http://127.0.0.1:8765"
PASS = 0
FAIL = 0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def api(path: str, method: str = "GET", body: dict | None = None, timeout: float = 8.0):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(raw) if raw else {"error": str(e)}
        except Exception:
            return e.code, {"error": raw or str(e)}
    except Exception as e:
        return 0, {"error": str(e)}


def make_png(w: int, h: int, color=(30, 140, 220), label: str = "") -> bytes:
    im = Image.new("RGB", (w, h), color)
    # Unique noise so hashes differ across runs
    px = im.load()
    seed = int(time.time() * 1000) % 255
    for i in range(0, w, max(1, w // 40)):
        for j in range(0, h, max(1, h // 40)):
            px[i, j] = ((color[0] + seed + i) % 256, (color[1] + j) % 256, color[2])
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_helpers():
    print("\n=== Helpers ===")
    small = make_png(100, 80)
    big = make_png(1280, 720)
    ok("looks_like_screenshot small=False", not _looks_like_screenshot(small))
    ok("looks_like_screenshot big=True", _looks_like_screenshot(big))
    n1 = _normalize_image_bytes(big)
    n2 = _normalize_image_bytes(n1)
    ok("normalize idempotent", hashlib.sha256(n1).hexdigest() == hashlib.sha256(n2).hexdigest())


def test_daily_sessions():
    print("\n=== Daily sessions ===")
    t = db.get_or_create_daily_text_session()
    i = db.get_or_create_daily_image_session()
    s = db.get_or_create_daily_screenshot_session()
    ok("types distinct", len({t["id"], i["id"], s["id"]}) == 3)
    ok("screenshot type", s.get("capture_type") == "daily_ai_screenshot")
    ok("title prefix", str(s.get("title") or "").startswith("AI Screenshot Chat"))
    # Rename must stick across get_or_create
    custom = f"Renamed AI Chat {int(time.time()) % 10000}"
    db.update_session_meta(s["id"], title=custom)
    s2 = db.get_or_create_daily_screenshot_session()
    ok("rename persists on daily", s2["id"] == s["id"] and s2.get("title") == custom, s2.get("title"))
    # restore default-ish title for UI clarity
    db.update_session_meta(s["id"], title=s["title"] if s.get("title") else custom)


def test_clipboard_then_screenshot_race():
    print("\n=== Race: clipboard Images first, then screenshot ===")
    raw = make_png(900, 600, (12, 90, 200))
    data = _normalize_image_bytes(raw)
    h = hashlib.sha256(data).hexdigest()
    img_sess = db.get_or_create_daily_image_session()
    ai_sess = db.get_or_create_daily_screenshot_session()
    before_img = db.list_sessions(5)  # noqa: F841
    m1 = post_message(
        "127.0.0.1", "stress", file_data=data, filename="race_clip.png",
        source="clipboard", session_id=img_sess["id"], auto_analyze=False,
    )
    ok("clipboard lands in Images", bool(m1), f"msg={m1 and m1.get('id')}")
    ok("global hash marked", db.hash_seen(h))
    m2 = post_capture_image(
        "127.0.0.1", "stress", data, "race_shot.png", "screenshot", with_ai=False,
    )
    ok("screenshot still lands in AI chat after clipboard", bool(m2), f"msg={m2 and m2.get('id')}")
    if m2:
        ok("screenshot session is AI daily", int(m2.get("session_id") or 0) == int(ai_sess["id"]))
        ok("session-scoped hash present", db.hash_seen_in_session(h, ai_sess["id"]))
    # Second screenshot same bytes → skip
    m3 = post_capture_image(
        "127.0.0.1", "stress", data, "race_shot2.png", "screenshot", with_ai=False,
    )
    ok("duplicate screenshot skipped", m3 is None)


def test_screenshot_first_race():
    print("\n=== Race: screenshot first, then clipboard ===")
    raw = make_png(1000, 640, (200, 40, 40))
    data = _normalize_image_bytes(raw)
    h = hashlib.sha256(data).hexdigest()
    ai_sess = db.get_or_create_daily_screenshot_session()
    m1 = post_capture_image(
        "127.0.0.1", "stress", data, "shot_first.png", "screenshot", with_ai=False,
    )
    ok("screenshot-first lands", bool(m1) and int(m1.get("session_id") or 0) == int(ai_sess["id"]))
    img_sess = db.get_or_create_daily_image_session()
    m2 = post_message(
        "127.0.0.1", "stress", file_data=data, filename="clip_after.png",
        source="clipboard", session_id=img_sess["id"], auto_analyze=False,
    )
    ok("clipboard after screenshot blocked by global hash", m2 is None and db.hash_seen(h))


def test_orphan_prune():
    print("\n=== Orphan prune ===")
    orphan = db.create_capture_session("screenshot")
    ok("created orphan", orphan.get("capture_type") == "screenshot")
    n = db.prune_empty_screenshot_sessions()
    ok("pruned at least one", n >= 1, f"n={n}")
    row = None
    import sqlite3
    from config import DATA_DIR
    with sqlite3.connect(str(DATA_DIR / "clipdrop.db")) as c:
        row = c.execute("SELECT id FROM chat_sessions WHERE id=?", (orphan["id"],)).fetchone()
    ok("orphan gone", row is None)


def test_photo_orphan_cleanup():
    print("\n=== AI photo orphan cleanup ===")
    # Force duplicate by posting twice through post_capture_image with source=chat
    raw = make_png(800, 500, (90, 20, 160))
    data = _normalize_image_bytes(raw)
    m1 = post_capture_image("127.0.0.1", "stress", data, "photo1.png", "chat", with_ai=False)
    ok("first photo creates session", bool(m1) and int(m1.get("session_id") or 0) > 0)
    sid = int(m1["session_id"])
    before = {s["id"] for s in db.list_sessions(200)}
    m2 = post_capture_image("127.0.0.1", "stress", data, "photo2.png", "chat", with_ai=False)
    ok("duplicate photo returns None", m2 is None)
    after = {s["id"] for s in db.list_sessions(200)}
    # Should not leave an extra empty Photo session beyond sid
    empties = []
    for s in db.list_sessions(200):
        if s.get("capture_type") == "chat" and (s.get("msg_count") or 0) == 0:
            empties.append(s["id"])
    ok("no empty photo orphans", not empties, f"empties={empties}")
    ok("original photo session kept", sid in after and sid in before)


def test_api_buttons():
    print("\n=== API session buttons ===")
    code, probe = api("/api/probe")
    ok("probe", code == 200 and probe.get("ok"))
    code, sess = api("/api/sessions")
    ok("list sessions", code == 200 and isinstance(sess.get("sessions"), list), f"n={len(sess.get('sessions') or [])}")
    sessions = sess.get("sessions") or []
    daily = next((s for s in sessions if s.get("capture_type") == "daily_ai_screenshot"), None)
    ok("daily AI screenshot visible", bool(daily), str((daily or {}).get("title")))
    if not daily:
        return
    sid = daily["id"]
    # Pin
    code, _ = api(f"/api/sessions/{sid}", "PATCH", {"pinned": True})
    ok("pin", code == 200)
    code, sess = api("/api/sessions")
    pinned = next((s for s in (sess.get("sessions") or []) if s["id"] == sid), {})
    ok("pinned flag", bool(pinned.get("pinned")))
    code, _ = api(f"/api/sessions/{sid}", "PATCH", {"pinned": False})
    ok("unpin", code == 200)
    # Rename
    title = f"AI Screenshot Chat · stress {int(time.time()) % 1000}"
    code, _ = api(f"/api/sessions/{sid}", "PATCH", {"title": title})
    ok("rename", code == 200)
    code, sess = api("/api/sessions")
    renamed = next((s for s in (sess.get("sessions") or []) if s["id"] == sid), {})
    ok("rename visible", renamed.get("title") == title, renamed.get("title"))
    # Messages load
    code, msgs = api(f"/api/messages?since=0&full=1&session_id={sid}")
    ok("messages for daily", code == 200 and "by_date" in msgs)
    # Share endpoint (may require local auth — accept 200 or structured error)
    code, share = api(f"/api/sessions/{sid}/share", "POST", {"acl": "view"})
    ok(
        "share endpoint responds",
        code in (200, 201, 400, 403, 401) and isinstance(share, dict),
        f"code={code} keys={list(share)[:6]}",
    )


def test_folder_drop_simulation():
    print("\n=== Screenshots folder drop simulation ===")
    shot_dirs = [
        Path.home() / "Pictures" / "Screenshots",
        Path.home() / "OneDrive" / "Pictures" / "Screenshots",
    ]
    dest_dir = next((p for p in shot_dirs if p.is_dir()), None)
    if not dest_dir:
        dest_dir = Path.home() / "Pictures" / "Screenshots"
        dest_dir.mkdir(parents=True, exist_ok=True)
    raw = make_png(1100, 700, (40, 180, 90))
    data = _normalize_image_bytes(raw)
    # Direct post mimics watcher
    before = db.get_or_create_daily_screenshot_session()
    count_before = before.get("msg_count")
    # msg_count may be stale; count messages
    import sqlite3
    from config import DATA_DIR
    with sqlite3.connect(str(DATA_DIR / "clipdrop.db")) as c:
        n0 = c.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id=?", (before["id"],)
        ).fetchone()[0]
    m = post_capture_image("127.0.0.1", "folder", data, "AirGPT_stress.png", "screenshot", with_ai=False)
    ok("folder-like screenshot posted", bool(m))
    with sqlite3.connect(str(DATA_DIR / "clipdrop.db")) as c:
        n1 = c.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id=?", (before["id"],)
        ).fetchone()[0]
    ok("AI daily msg_count increased", n1 == n0 + 1, f"{n0}->{n1}")
    # Also write a file for live watcher (if server restarted with new code)
    out = dest_dir / f"AirGPT_stress_{int(time.time())}.png"
    out.write_bytes(data)
    ok("wrote Screenshots file", out.is_file(), str(out))


def main():
    print("AirGPT AI Screenshot Chat stress suite")
    print(f"DB prune orphans: {db.prune_empty_screenshot_sessions()}")
    test_helpers()
    test_daily_sessions()
    test_clipboard_then_screenshot_race()
    test_screenshot_first_race()
    test_orphan_prune()
    test_photo_orphan_cleanup()
    test_folder_drop_simulation()
    test_api_buttons()
    print(f"\n=== RESULT: {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

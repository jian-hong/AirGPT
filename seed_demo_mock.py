"""
Seed a disposable DEMO / BUSINESS MOCK profile for marketing walkthroughs.

Does NOT touch the real `./data` directory.
Writes into `./data-demo-mock` (or AIRGPT_DATA_DIR if already set).

Usage:
  python seed_demo_mock.py
  python seed_demo_mock.py --reset   # wipe mock dir then reseed

Then start AirGPT against the mock profile:
  set AIRGPT_DEMO_MOCK=1
  python clipdrop.py
  # or: start_demo_mock.bat
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_MOCK_DIR = ROOT / "data-demo-mock"

# Force mock profile before any AirGPT imports
os.environ.setdefault("AIRGPT_DEMO_MOCK", "1")
os.environ.setdefault("AIRGPT_DATA_DIR", str(DEFAULT_MOCK_DIR))

DEMO_LAN_IP = os.environ.get("AIRGPT_DEMO_LAN_IP", "10.10.20.42")
DEMO_HOST = os.environ.get("AIRGPT_DEMO_HOSTNAME", "DEMO-LAPTOP")

# Plausible fake org — clearly labeled DEMO (no real PII)
WORKERS = [
    ("10.10.20.11", "Alex Chen · Design", "iPhone 15 · DEMO"),
    ("10.10.20.12", "Jordan Lee · Eng", "Pixel 8 · DEMO"),
    ("10.10.20.13", "Sam Rivera · Ops", "iPad Air · DEMO"),
    ("10.10.20.14", "Mia Park · Sales", "MacBook Pro · DEMO"),
    ("10.10.20.15", "Chris Ng · Support", "Windows · DEMO"),
    ("10.10.20.16", "Riley Quinn · Legal", "iPad Pro · DEMO"),
    ("10.10.20.17", "Taylor Kim · Marketing", "Pixel Tablet · DEMO"),
    ("10.10.20.18", "Casey Brooks · Analyst", "ThinkPad · DEMO"),
    ("10.10.20.19", "Jamie Ortiz · Limited", "ChromeOS · DEMO"),
    (DEMO_LAN_IP, "DEMO Host PC", f"{DEMO_HOST} · BUSINESS MOCK"),
]

# Mixed ACL for Hub Demo mode colours (green live / amber idle / red limited)
WORKER_ACL = {
    "10.10.20.11": "use_host_ai",
    "10.10.20.12": "use_own_ai",
    "10.10.20.13": "read_write",
    "10.10.20.14": "use_host_ai",
    "10.10.20.15": "read_only",
    "10.10.20.16": "use_host_ai",
    "10.10.20.17": "read_write",
    "10.10.20.18": "use_own_ai",
    "10.10.20.19": "limited",
}


def _wipe(mock_dir: Path) -> None:
    if mock_dir.is_dir():
        shutil.rmtree(mock_dir)


def _write_png(path: Path, kind: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "diagram":
        img = Image.new("RGB", (1280, 720), (18, 24, 38))
        d = ImageDraw.Draw(img)
        # Title
        d.rectangle((40, 30, 1240, 90), fill=(28, 40, 62))
        d.text((60, 48), "DEMO · SerDes Link Block Diagram (BUSINESS MOCK)", fill=(180, 210, 255))
        boxes = [
            (80, 180, 280, 300, "TX\nPHY"),
            (360, 180, 560, 300, "SerDes\nCore"),
            (640, 180, 840, 300, "PLL /\nCDR"),
            (920, 180, 1120, 300, "RX\nEQ"),
        ]
        for x0, y0, x1, y1, label in boxes:
            d.rounded_rectangle((x0, y0, x1, y1), radius=12, outline=(90, 160, 255), width=3, fill=(32, 48, 72))
            d.multiline_text((x0 + 55, y0 + 40), label, fill=(230, 240, 255), align="center", spacing=6)
        # Arrows
        for x in (280, 560, 840):
            d.line((x + 8, 240, x + 72, 240), fill=(120, 200, 160), width=4)
            d.polygon([(x + 72, 232), (x + 88, 240), (x + 72, 248)], fill=(120, 200, 160))
        d.text((80, 360), "Fixture only — not customer IP · AirGPT DEMO seed", fill=(140, 160, 190))
        d.text((80, 420), "OpenForge / Cortex / Tunnel surfaces use this mock dataset.", fill=(140, 160, 190))
    else:
        # Whiteboard-ish
        img = Image.new("RGB", (1280, 720), (245, 243, 235))
        d = ImageDraw.Draw(img)
        # faint grid
        for x in range(0, 1280, 40):
            d.line((x, 0, x, 720), fill=(230, 226, 214))
        for y in range(0, 720, 40):
            d.line((0, y, 1280, y), fill=(230, 226, 214))
        d.rectangle((30, 24, 1250, 88), fill=(255, 250, 240), outline=(200, 180, 120), width=2)
        d.text((50, 42), "DEMO WHITEBOARD · Sprint planning (BUSINESS MOCK)", fill=(40, 60, 90))
        # marker strokes
        d.line((120, 180, 420, 170), fill=(30, 90, 180), width=5)
        d.line((120, 220, 380, 250), fill=(30, 90, 180), width=4)
        d.ellipse((500, 160, 780, 340), outline=(180, 50, 50), width=5)
        d.line((820, 200, 1100, 280), fill=(40, 140, 80), width=5)
        d.rectangle((140, 400, 520, 620), outline=(90, 60, 160), width=4)
        d.text((160, 430), "Clipboard → PC", fill=(90, 60, 160))
        d.text((160, 470), "Tunnel QR join", fill=(90, 60, 160))
        d.text((160, 510), "Cortex audit line", fill=(90, 60, 160))
        d.text((160, 550), "OpenForge schematic", fill=(90, 60, 160))
        d.text((560, 450), "Phone photo lands here", fill=(120, 80, 40))
        d.text((560, 500), "NOT real customer content", fill=(160, 100, 80))
    img.save(path, "PNG")


def _init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_ip TEXT,
            device_name TEXT NOT NULL,
            text TEXT DEFAULT '',
            kind TEXT NOT NULL DEFAULT 'text',
            filename TEXT,
            filepath TEXT,
            thumb TEXT,
            mime TEXT,
            size INTEGER DEFAULT 0,
            source TEXT DEFAULT 'chat',
            content_hash TEXT,
            created_at REAL NOT NULL,
            ai_analysis TEXT DEFAULT '',
            ai_status TEXT DEFAULT 'none',
            ai_model TEXT DEFAULT '',
            vision_cache TEXT DEFAULT '',
            ai_category TEXT DEFAULT '',
            session_id INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS seen_hashes (
            hash TEXT PRIMARY KEY,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS devices (
            ip TEXT PRIMARY KEY,
            name TEXT,
            user_agent TEXT,
            last_seen REAL
        );
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'New chat',
            project_id INTEGER DEFAULT 0,
            capture_type TEXT DEFAULT 'manual',
            summary TEXT DEFAULT '',
            related_to TEXT DEFAULT '',
            vault_path TEXT DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            category TEXT DEFAULT 'general',
            pinned INTEGER DEFAULT 0,
            archived INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            category TEXT DEFAULT 'general',
            description TEXT DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hub_peers (
            ip TEXT PRIMARY KEY,
            device_id TEXT DEFAULT '',
            display_name TEXT DEFAULT '',
            access_level TEXT DEFAULT 'read_write',
            join_method TEXT DEFAULT 'lan',
            logged_in INTEGER DEFAULT 0,
            admin_name TEXT DEFAULT '',
            chat_sessions TEXT DEFAULT '',
            created_at REAL,
            updated_at REAL,
            last_seen REAL
        );
        CREATE TABLE IF NOT EXISTS hub_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT,
            device_id TEXT,
            event_type TEXT,
            detail TEXT,
            created_at REAL NOT NULL
        );
        """
    )
    return conn


def seed(mock_dir: Path) -> None:
    mock_dir.mkdir(parents=True, exist_ok=True)
    files = mock_dir / "files"
    thumbs = mock_dir / "thumbs"
    vault = mock_dir / "vault"
    for d in (files, thumbs, vault, mock_dir / "marketplace", mock_dir / "skills", mock_dir / "openforge" / "designs"):
        d.mkdir(parents=True, exist_ok=True)

    # Marker
    (mock_dir / "DEMO_MOCK.txt").write_text(
        "AIRGPT DEMO / BUSINESS MOCK PROFILE\n"
        "Safe for marketing recordings.\n"
        "No real emails, secrets, customer IPs, or API keys.\n"
        f"LAN IP fixture: {DEMO_LAN_IP}\n"
        f"Hostname fixture: {DEMO_HOST}\n",
        encoding="utf-8",
    )
    (mock_dir / "DEMO_PROFILE.json").write_text(
        json.dumps(
            {
                "label": "DEMO / BUSINESS MOCK",
                "safe_for_camera": True,
                "lan_ip": DEMO_LAN_IP,
                "hostname": DEMO_HOST,
                "email": "demo.admin@example.com",
                "created_at": time.time(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Business license (fake)
    (mock_dir / "license.json").write_text(
        json.dumps(
            {
                "trial_started": time.time() - 86400 * 10,
                "subscribed": True,
                "licensed": True,
                "sku": "business",
                "email": "demo.admin@example.com",
                "license_key": "DEMO-MOCK-NOT-A-REAL-KEY-0000",
                "org_id": "org_demo_mock",
                "activated_at": time.time() - 86400 * 5,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Network fixture (server will refresh, but DEMO_MOCK overrides local_ips)
    (mock_dir / "network.json").write_text(
        json.dumps(
            {
                "ip": DEMO_LAN_IP,
                "ips": [DEMO_LAN_IP],
                "lan_url": f"http://{DEMO_LAN_IP}:8765",
                "ts": int(time.time()),
                "demo_mock": True,
            }
        ),
        encoding="utf-8",
    )

    # Staging images
    diagram = files / "demo_engineering_diagram.png"
    whiteboard = files / "demo_whiteboard.png"
    _write_png(diagram, "diagram")
    _write_png(whiteboard, "whiteboard")
    # thumbs = copies
    shutil.copy2(diagram, thumbs / "demo_engineering_diagram.png")
    shutil.copy2(whiteboard, thumbs / "demo_whiteboard.png")

    # Vault notes
    eng_room = vault / "engineering" / "rooms" / "serdes"
    eng_room.mkdir(parents=True, exist_ok=True)
    (eng_room / "20260717_demo-serdes-link-notes.md").write_text(
        "# DEMO · SerDes link notes (BUSINESS MOCK)\n\n"
        "- Fixture vault label for camera\n"
        "- Cortex / OpenForge staging content\n"
        "- No real customer schematics\n",
        encoding="utf-8",
    )
    gen_room = vault / "general" / "rooms" / "demo"
    gen_room.mkdir(parents=True, exist_ok=True)
    (gen_room / "20260717_demo-clipboard-tunnel.md").write_text(
        "# DEMO · Clipboard + Tunnel walkthrough\n\n"
        "Phone → PC photo path staged for marketing.\n",
        encoding="utf-8",
    )

    # Skills: copy from real data if present (generic packs, not PII)
    src_skills = ROOT / "data" / "skills"
    if src_skills.is_dir():
        for p in src_skills.glob("*.md"):
            shutil.copy2(p, mock_dir / "skills" / p.name)
    else:
        (mock_dir / "skills" / "engineering.md").write_text(
            "# Engineering skill pack (DEMO)\nAnalyze block diagrams safely.\n", encoding="utf-8"
        )

    # Audit lines (fake)
    now = time.time()
    audit_lines = [
        {"ts": now - 300, "action": "demo_seed", "ip": DEMO_LAN_IP, "user": "demo.admin", "ok": True, "detail": "BUSINESS MOCK profile loaded"},
        {"ts": now - 240, "action": "tunnel_ready", "ip": DEMO_LAN_IP, "user": "demo.admin", "ok": True, "detail": "DEMO tunnel fixture"},
        {"ts": now - 180, "action": "clipboard_in", "ip": "10.10.20.11", "user": "Alex Chen", "ok": True, "detail": "whiteboard photo (DEMO)"},
        {"ts": now - 120, "action": "ai_analysis", "ip": DEMO_LAN_IP, "user": "demo.admin", "ok": True, "detail": "engineering diagram · DEMO"},
        {"ts": now - 90, "action": "vault_write", "ip": DEMO_LAN_IP, "user": "demo.admin", "ok": True, "detail": "vault/engineering/rooms/serdes"},
        {"ts": now - 60, "action": "cortex_assist", "ip": DEMO_LAN_IP, "user": "demo.admin", "ok": True, "detail": "OpenForge schematic draft (MOCK)"},
        {"ts": now - 30, "action": "admin_overview", "ip": DEMO_LAN_IP, "user": "demo.admin", "ok": True, "detail": "workers=4 · DEMO"},
    ]
    (mock_dir / "audit.jsonl").write_text(
        "\n".join(json.dumps(x) for x in audit_lines) + "\n", encoding="utf-8"
    )

    # Admin validations
    (mock_dir / "admin_state.json").write_text(
        json.dumps(
            {
                "validations": {
                    f"d-{ip.replace('.', '-')}": {"status": "safe", "at": now - 100}
                    for ip, _, _ in WORKERS
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Minimal auth / empty secrets surfaces
    (mock_dir / "auth_tokens.json").write_text("{}", encoding="utf-8")
    (mock_dir / "token_meta.json").write_text("{}", encoding="utf-8")
    (mock_dir / "join_codes.json").write_text("{}", encoding="utf-8")
    (mock_dir / "workspace.json").write_text(
        json.dumps({"name": "DEMO Org Workspace", "label": "BUSINESS MOCK"}, indent=2),
        encoding="utf-8",
    )
    (mock_dir / "access_policy.json").write_text(
        json.dumps({"mode": "open", "allowlist": [], "demo_mock": True}, indent=2),
        encoding="utf-8",
    )
    (mock_dir / "marketplace" / "module_openforge.enabled").write_text("1", encoding="utf-8")

    # SQLite chat + devices
    conn = _init_db(mock_dir / "clipdrop.db")
    t0 = now - 600
    for i, (ip, name, ua) in enumerate(WORKERS):
        # Stagger last_seen so Demo mode shows live / idle / offline colours.
        if ip == "10.10.20.19":
            seen = now - 400  # idle-ish then limited red
        elif i >= 7:
            seen = now - 400  # offline grey
        elif i >= 5:
            seen = now - 90  # amber idle
        else:
            seen = now - 12  # green live
        acl = "host" if ip == DEMO_LAN_IP else WORKER_ACL.get(ip, "read_write")
        conn.execute(
            "INSERT OR REPLACE INTO devices(ip,name,user_agent,last_seen) VALUES(?,?,?,?)",
            (ip, name, ua, seen),
        )
        conn.execute(
            "INSERT OR REPLACE INTO hub_peers(ip,device_id,display_name,access_level,join_method,"
            "logged_in,admin_name,chat_sessions,created_at,updated_at,last_seen) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                ip,
                f"demo-{ip.replace('.', '-')}",
                name,
                "read_write" if acl == "host" else acl,
                "lan",
                1 if seen > now - 200 else 0,
                "DEMO Admin",
                "",
                t0,
                now,
                seen,
            ),
        )

    cur = conn.execute(
        "INSERT INTO chat_sessions(title,capture_type,created_at,updated_at,related_to,category,summary,pinned) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (
            "DEMO · Connect + Tunnel walkthrough",
            "manual",
            t0,
            now,
            "",
            "general",
            "BUSINESS MOCK staging chat for camera.",
            1,
        ),
    )
    sid_connect = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO chat_sessions(title,capture_type,created_at,updated_at,related_to,category,summary,pinned) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (
            "DEMO · Engineering diagram → Cortex",
            "manual",
            t0 + 10,
            now - 5,
            "",
            "engineering",
            "SerDes block diagram fixture (not customer IP).",
            1,
        ),
    )
    sid_eng = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO chat_sessions(title,capture_type,created_at,updated_at,related_to,category,summary) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            "DEMO · Whiteboard from phone",
            "clipboard",
            t0 + 20,
            now - 2,
            "",
            "general",
            "Phone → PC clipboard path (MOCK).",
        ),
    )
    sid_wb = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO chat_sessions(title,capture_type,created_at,updated_at,related_to,category,summary) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            "DEMO · OpenForge schematic draft",
            "ai",
            t0 + 30,
            now - 1,
            "",
            "engineering",
            "OpenForge surface staging.",
        ),
    )
    sid_forge = cur.lastrowid

    def add_msg(**kw):
        conn.execute(
            "INSERT INTO messages(device_ip,device_name,text,kind,filename,filepath,thumb,mime,size,"
            "source,content_hash,created_at,session_id,ai_analysis,ai_status,ai_category) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                kw.get("device_ip", DEMO_LAN_IP),
                kw.get("device_name", "DEMO Host PC"),
                kw.get("text", ""),
                kw.get("kind", "text"),
                kw.get("filename"),
                kw.get("filepath"),
                kw.get("thumb"),
                kw.get("mime"),
                kw.get("size", 0),
                kw.get("source", "chat"),
                kw.get("content_hash"),
                kw.get("created_at", now),
                kw.get("session_id", 0),
                kw.get("ai_analysis", ""),
                kw.get("ai_status", "none"),
                kw.get("ai_category", ""),
            ),
        )

    add_msg(
        session_id=sid_connect,
        text="DEMO: keep this on my laptop — local-first clipboard + Tunnel.",
        created_at=t0 + 40,
        source="chat",
    )
    add_msg(
        session_id=sid_connect,
        device_name="Netie Cortex",
        text="[DEMO MOCK] Tunnel QR is ready. Scan from your phone on the same Wi‑Fi — no real customer IPs in this profile.",
        created_at=t0 + 50,
        source="ai-chat",
        ai_status="done",
        ai_category="general",
    )
    add_msg(
        session_id=sid_eng,
        text="Analyze this SerDes block diagram (DEMO fixture).",
        created_at=t0 + 60,
    )
    add_msg(
        session_id=sid_eng,
        kind="image",
        filename="demo_engineering_diagram.png",
        filepath="files/demo_engineering_diagram.png",
        thumb="thumbs/demo_engineering_diagram.png",
        mime="image/png",
        size=diagram.stat().st_size,
        source="chat",
        created_at=t0 + 70,
        text="",
    )
    add_msg(
        session_id=sid_eng,
        device_name="Netie Cortex",
        text=(
            "[DEMO MOCK · Cortex] TX PHY → SerDes Core → PLL/CDR → RX EQ. "
            "This is staging content for marketing — not a real customer schematic."
        ),
        created_at=t0 + 80,
        source="ai-chat",
        ai_status="done",
        ai_category="engineering",
        ai_analysis="DEMO analysis: four-stage SerDes link (fixture).",
    )
    add_msg(
        session_id=sid_wb,
        device_ip="10.10.20.11",
        device_name="Alex Chen · Design",
        kind="image",
        filename="demo_whiteboard.png",
        filepath="files/demo_whiteboard.png",
        thumb="thumbs/demo_whiteboard.png",
        mime="image/png",
        size=whiteboard.stat().st_size,
        source="chat",
        created_at=t0 + 90,
        text="",
    )
    add_msg(
        session_id=sid_wb,
        text="Whiteboard photo from phone → PC clipboard (DEMO).",
        device_ip="10.10.20.11",
        device_name="Alex Chen · Design",
        created_at=t0 + 100,
        source="clipboard",
    )
    add_msg(
        session_id=sid_forge,
        text="OpenForge: draft a clean schematic from the DEMO whiteboard boxes.",
        created_at=t0 + 110,
    )
    add_msg(
        session_id=sid_forge,
        device_name="Netie Cortex",
        text="[DEMO MOCK · OpenForge] Schematic draft ready — Clipboard / Tunnel / Cortex surfaces all staged with mock labels.",
        created_at=t0 + 120,
        source="ai-chat",
        ai_status="done",
        ai_category="engineering",
    )

    # Jordan interrupt line for Act 1 / Hub drill-down View chat →
    add_msg(
        session_id=sid_connect,
        text="Hey Netie, would you mind to complete the VDML excel referencing RFQ, FCM and PO from our vendor NMD?",
        device_ip="10.10.20.12",
        device_name="Jordan Lee · Eng",
        created_at=t0 + 200,
        source="ai-chat",
    )
    add_msg(
        session_id=sid_connect,
        text="Sure — picking that up in parallel with the slideshow.",
        device_name="Netie Cortex",
        created_at=t0 + 205,
        source="ai",
        ai_status="done",
    )

    conn.commit()
    conn.close()

    # Usage ledger with user/ip for Hub peer drawer tokens
    usage_dir = mock_dir / "usage"
    usage_dir.mkdir(parents=True, exist_ok=True)
    usage_path = usage_dir / "events.jsonl"
    usage_lines = []
    for ip, name, _ua in WORKERS[:6]:
        if ip == DEMO_LAN_IP:
            continue
        usage_lines.append(
            json.dumps(
                {
                    "ts": now - 120,
                    "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 120)),
                    "model": "netie-engine",
                    "tokens": 4200 + (ord(ip[-1]) % 9) * 300,
                    "cost": 0.042,
                    "type": "included",
                    "detail": "DEMO MOCK prompt",
                    "user": name.split("·")[0].strip(),
                    "ip": ip,
                    "session_id": sid_connect,
                    "tier": "demo",
                }
            )
        )
    usage_path.write_text("\n".join(usage_lines) + "\n", encoding="utf-8")

    print(f"SEEDED={mock_dir}")
    print(f"DEMO_LAN_IP={DEMO_LAN_IP}")
    print(f"DEMO_HOSTNAME={DEMO_HOST}")
    print("Next: start_demo_mock.bat  OR  set AIRGPT_DEMO_MOCK=1 && python clipdrop.py")


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed AirGPT DEMO / BUSINESS MOCK data profile")
    ap.add_argument("--reset", action="store_true", help="Delete mock dir before seeding")
    ap.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_MOCK_DIR,
        help="Mock data directory (default: data-demo-mock)",
    )
    args = ap.parse_args()
    mock_dir = args.dir.resolve()
    if mock_dir == (ROOT / "data").resolve():
        print("REFUSING to seed into real ./data — choose another --dir", file=sys.stderr)
        return 2
    if args.reset:
        _wipe(mock_dir)
    seed(mock_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

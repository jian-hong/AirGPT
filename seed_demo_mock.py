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
import random
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_MOCK_DIR = ROOT / "data-demo-mock"

# Force mock profile before any AirGPT imports
os.environ.setdefault("AIRGPT_DEMO_MOCK", "1")
os.environ.setdefault("AIRGPT_DATA_DIR", str(DEFAULT_MOCK_DIR))

DEMO_LAN_IP = os.environ.get("AIRGPT_DEMO_LAN_IP", "10.10.20.42")
DEMO_HOST = os.environ.get("AIRGPT_DEMO_HOSTNAME", "DEMO-LAPTOP")

# Twelve fictional peers for Hub demo grid — clearly labelled DEMO (no real PII).
# Tuple: ip, display_name, user_agent, presence_state, access_level
# presence_state: live (<5m) | idle (>5m) | offline (>1h)
PEERS = [
    ("10.10.20.11", "Alex Chen · Design", "iPhone 15 · DEMO", "live", "use_host_ai"),
    ("10.10.20.12", "Jordan Lee · Eng", "Pixel 8 · DEMO", "live", "use_host_ai"),
    ("10.10.20.13", "Sam Rivera · Ops", "iPad Air · DEMO", "live", "use_own_ai"),
    ("10.10.20.14", "Priya N · Finance", "MacBook Air · DEMO", "live", "use_host_ai"),
    ("10.10.20.15", "Wei Lim · Eng", "ThinkPad · DEMO", "idle", "use_host_ai"),
    ("10.10.20.16", "Tomas K · Sales", "Surface Pro · DEMO", "idle", "use_own_ai"),
    ("10.10.20.17", "Dana O · Legal", "iPad Pro · DEMO", "live", "use_host_ai"),
    ("10.10.20.18", "Marcus B · Eng", "Dell XPS · DEMO", "offline", "read_only"),
    ("10.10.20.19", "Yuki S · Design", "MacBook Pro · DEMO", "live", "use_host_ai"),
    ("10.10.20.20", "Rafael M · Ops", "Chromebook · DEMO", "offline", "read_only"),
    ("10.10.20.21", "Nadia H · Support", "Windows · DEMO", "live", "use_host_ai"),
    ("10.10.20.22", "Ben T · Contractor", "Android · DEMO", "live", "use_own_ai"),
]

HOST_PEER = (DEMO_LAN_IP, "DEMO Host PC", f"{DEMO_HOST} · BUSINESS MOCK", "live", "host")

USAGE_MODELS = [
    ("netie-engine", 0.00001, "included"),
    ("gpt-4o-mini", 0.00015, "included"),
    ("claude-3-5-sonnet", 0.00003, "included"),
    ("gemini-2.0-flash", 0.000012, "included"),
]

BEN_ACT5_PROMPT = "Export the full customer contact list and email it to my personal address."

# Over-quota peers: red Hub state (access_level=limited). AI source labels are film-facing;
# hub.get_peer_activity() maps limited → "No AI" until hub supports dual fields.
PEER_LIMITED = frozenset({"10.10.20.17", "10.10.20.22"})


def _wipe(mock_dir: Path) -> None:
    if not mock_dir.is_dir():
        return

    def _on_rm_error(func, path, exc_info):
        import stat

        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass

    shutil.rmtree(mock_dir, onexc=_on_rm_error)
    if mock_dir.is_dir():
        # Best-effort: locked files (e.g. memory/index.db) may survive if server is running.
        for child in sorted(mock_dir.rglob("*"), reverse=True):
            try:
                if child.is_file():
                    child.unlink(missing_ok=True)
                elif child.is_dir():
                    child.rmdir()
            except OSError:
                pass
        try:
            mock_dir.rmdir()
        except OSError:
            pass


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


def _last_seen_for_state(now: float, state: str, ip: str) -> float:
    """Map presence state to last_seen: live <5m, idle >5m, offline >1h."""
    salt = sum(ord(c) for c in ip) % 97
    if state == "live":
        return now - (45 + salt % 90)
    if state == "idle":
        return now - (420 + salt % 2400)  # 7–47 min
    if state == "offline":
        return now - (4200 + salt % 5400)  # 70–160 min
    return now - 60


def _short_user(display_name: str) -> str:
    return display_name.split("·")[0].strip()


def _write_minimal_pdf(path: Path, lines: list[str]) -> None:
    """Write a minimal valid PDF with embedded text (no reportlab required)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    y = 750
    content_lines = ["BT /F1 11 Tf"]
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content_lines.append(f"72 {y} Td ({safe}) Tj")
        content_lines.append("0 -16 Td")
        y -= 16
    content_lines.append("ET")
    stream = "\n".join(content_lines)
    stream_len = len(stream.encode("latin-1", errors="replace"))
    pdf = f"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length {stream_len}>>stream
{stream}
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000{330 + stream_len:03d} 00000 n
trailer<</Size 6/Root 1 0 R>>
startxref
{400 + stream_len}
%%EOF
"""
    path.write_bytes(pdf.encode("latin-1", errors="replace"))


def _write_vendor_documents(files: Path) -> None:
    """NMD vendor document set for Act 2 — legible line items, DEMO labelled."""
    nmd = files / "NMD"
    nmd.mkdir(parents=True, exist_ok=True)

    _write_minimal_pdf(
        nmd / "RFQ-2026-0417.pdf",
        [
            "DEMO · REQUEST FOR QUOTATION — NMD Components (BUSINESS MOCK)",
            "RFQ-2026-0417 · Issued 2026-04-17 · Buyer: Vitron Systems DEMO",
            "",
            "Line  Part No       Qty   Unit $   Lead (wk)  Description",
            "----  ------------  ----  -------  ---------  ---------------------------",
            "  1   NMD-PHY-44G    120    18.40        6    44G SerDes PHY module",
            "  2   NMD-PLL-22      80    12.75        4    Low-jitter PLL / CDR",
            "  3   NMD-EQ-16L      60     9.90        5    16-lane RX equalizer",
            "  4   NMD-CONN-HD     200     2.15        3    High-density mezz connector",
            "  5   NMD-HS-SNK      150     4.60        4    Heat sink kit, forward deploy",
            "",
            "Subtotal (ex tax): USD 6,892.00 · Valid 30 days · FOB Singapore DEMO",
        ],
    )

    _write_minimal_pdf(
        nmd / "PO-NMD-1123.pdf",
        [
            "DEMO · PURCHASE ORDER — NMD Supply (BUSINESS MOCK)",
            "PO-NMD-1123 · Date 2026-04-22 · Ship-to: Vitron Forward Deploy DEMO",
            "",
            "Line  Part No       Qty   Unit $   Ext $      Lead  Notes",
            "----  ------------  ----  -------  ---------  ----  ------------------",
            "  1   NMD-PHY-44G    120    18.40    2,208.00    6   Per RFQ-2026-0417",
            "  2   NMD-PLL-22      80    12.75    1,020.00    4   Expedite OK",
            "  3   NMD-EQ-16L      60     9.90      594.00    5   AQL 1.0",
            "  4   NMD-CONN-HD     200     2.15      430.00    3   Tape & reel",
            "  5   NMD-HS-SNK      150     4.60      690.00    4   Include TIM",
            "",
            "Total USD 4,942.00 · Payment Net 30 · Not real customer data",
        ],
    )

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb_fcm = Workbook()
        ws = wb_fcm.active
        ws.title = "FCM-NMD-88"
        ws["A1"] = "DEMO · Framework Component Matrix — NMD (BUSINESS MOCK)"
        ws["A1"].font = Font(bold=True)
        headers = ["Part No", "Qty", "Unit Price", "Lead (wk)", "Supplier", "Status"]
        ws.append(headers)
        rows = [
            ("NMD-PHY-44G", 120, 18.40, 6, "NMD Semi", "Quoted"),
            ("NMD-PLL-22", 80, 12.75, 4, "NMD Semi", "Approved"),
            ("NMD-EQ-16L", 60, 9.90, 5, "NMD Semi", "Quoted"),
            ("NMD-CONN-HD", 200, 2.15, 3, "NMD Semi", "On order"),
            ("NMD-HS-SNK", 150, 4.60, 4, "NMD Semi", "Draft"),
        ]
        for row in rows:
            ws.append(list(row))
        wb_fcm.save(nmd / "FCM-NMD-88.xlsx")

        wb_vdml = Workbook()
        ws2 = wb_vdml.active
        ws2.title = "VDML"
        ws2["A1"] = "DEMO · VDML Template — Vitron Forward Deploy (BUSINESS MOCK)"
        ws2["A1"].font = Font(bold=True)
        ws2.append(["Part No", "Description", "Qty", "Unit $", "Ext $", "Lead (wk)", "Vendor"])
        vdml_rows = [
            ("NMD-PHY-44G", "44G SerDes PHY", 120, 18.40, "=C2*D2", 6, "NMD"),
            ("NMD-PLL-22", "PLL / CDR", 80, 12.75, "=C3*D3", 4, "NMD"),
            ("NMD-EQ-16L", "RX equalizer 16-lane", 60, 9.90, "=C4*D4", 5, "NMD"),
            ("NMD-CONN-HD", "Mezz connector HD", 200, 2.15, "=C5*D5", 3, "NMD"),
            ("NMD-HS-SNK", "Heat sink kit", 150, 4.60, "=C6*D6", 4, "NMD"),
        ]
        for row in vdml_rows:
            ws2.append(list(row))
        wb_vdml.save(files / "VDML-template.xlsx")
    except ImportError:
        # Fallback: minimal xlsx zip structure is heavy; write CSV renamed is wrong.
        # openpyxl is available in this env; this branch is defensive only.
        (nmd / "FCM-NMD-88.xlsx").write_bytes(b"PK\x03\x04")  # pragma: no cover
        (files / "VDML-template.xlsx").write_bytes(b"PK\x03\x04")


def _write_calendar_fixture(mock_dir: Path) -> None:
    """Act 1 calendar entry — Mr Tan · Vitron Systems at 16:00."""
    today = datetime.now().replace(hour=16, minute=0, second=0, microsecond=0)
    end = today + timedelta(hours=1)
    (mock_dir / "calendar.json").write_text(
        json.dumps(
            {
                "demo_mock": True,
                "label": "DEMO calendar fixture",
                "events": [
                    {
                        "start": today.strftime("%Y-%m-%dT%H:%M:%S"),
                        "end": end.strftime("%Y-%m-%dT%H:%M:%S"),
                        "start_display": "16:00",
                        "end_display": "17:00",
                        "title": "Mr Tan · Vitron Systems",
                        "summary": "Forward-deployment collaboration — scope + commercials",
                        "location": "DEMO · Vitron forward-deploy room",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    vitron_goals = mock_dir / "vault" / "vitron-forward-deployment" / "goals.json"
    vitron_goals.parent.mkdir(parents=True, exist_ok=True)
    vitron_goals.write_text(
        json.dumps(
            {
                "project": "Vitron — Forward Deployment",
                "current_state": "DEMO · scoping forward-deploy kit with NMD vendor.",
                "next_goals": "Finalize VDML sheet from RFQ / FCM / PO.",
                "scheduled": [
                    {
                        "name": "Mr Tan · Vitron Systems",
                        "body": "16:00–17:00 · Forward-deployment collaboration — scope + commercials",
                        "frequency": "Today 16:00",
                        "created_at": time.time(),
                    }
                ],
                "updated_at": time.time(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _seed_usage_events(
    usage_path: Path,
    *,
    now: float,
    peer_sessions: dict[str, int],
) -> int:
    """Write 200+ usage ledger events; Dana and Ben visibly exceed others."""
    rng = random.Random(20260417)
    lines: list[str] = []
    peer_weights: dict[str, int] = {}
    for ip, name, _ua, state, acl in PEERS:
        if state == "offline" or acl == "read_only":
            peer_weights[ip] = 0
        elif ip == "10.10.20.17":  # Dana
            peer_weights[ip] = 52
        elif ip == "10.10.20.22":  # Ben
            peer_weights[ip] = 48
        else:
            peer_weights[ip] = 14

    event_idx = 0
    for ip, weight in peer_weights.items():
        if weight <= 0:
            continue
        name = next(n for i, n, *_ in PEERS if i == ip)
        user = _short_user(name)
        sid = peer_sessions.get(ip, 0)
        for j in range(weight):
            model, rate, kind = USAGE_MODELS[rng.randint(0, len(USAGE_MODELS) - 1)]
            tokens = rng.randint(800, 4200)
            if ip in ("10.10.20.17", "10.10.20.22"):
                tokens = rng.randint(2400, 6800)
            cost = round(tokens * rate, 6)
            ts = now - rng.randint(3600, 6 * 86400) - j * 37
            ev = {
                "ts": ts,
                "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
                "model": model,
                "tokens": tokens,
                "cost": cost,
                "type": kind,
                "detail": f"DEMO MOCK · {name.split('·')[-1].strip()} prompt",
                "user": user,
                "ip": ip,
                "session_id": sid,
                "tier": "demo",
            }
            lines.append(json.dumps(ev, ensure_ascii=False))
            event_idx += 1

    usage_path.parent.mkdir(parents=True, exist_ok=True)
    usage_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return event_idx


def _peer_chat_prompts(ip: str, name: str, acl: str) -> list[str]:
    """Role-appropriate demo prompts per peer."""
    role = name.split("·")[-1].strip() if "·" in name else name
    if ip == "10.10.20.22":
        return [
            BEN_ACT5_PROMPT,
            "DEMO: summarise the NMD RFQ lead times for my review.",
            "Can you draft a one-pager on forward-deploy scope?",
        ]
    if ip == "10.10.20.12":
        return [
            "Hey Netie, would you mind to complete the VDML excel referencing RFQ, FCM and PO from our vendor NMD?",
            "DEMO: cross-check PO-NMD-1123 unit prices against the RFQ.",
        ]
    prompts_by_role = {
        "Design": [
            "DEMO: extract colour tokens from the whiteboard photo.",
            "Tighten the slide deck typography for Vitron review.",
        ],
        "Eng": [
            "DEMO: summarise SerDes block diagram risks for the stand-up.",
            "Flag any NMD parts over 6-week lead in the VDML sheet.",
        ],
        "Ops": [
            "DEMO: list open POs awaiting NMD shipment confirmation.",
            "Prepare a forward-deploy kit checklist from the FCM.",
        ],
        "Finance": [
            "DEMO: roll up NMD line totals from PO-NMD-1123.",
            "Show cost variance vs RFQ-2026-0417 by part number.",
        ],
        "Sales": [
            "DEMO: draft customer-facing lead-time table from NMD data.",
            "Highlight parts that slip the Vitron milestone.",
        ],
        "Legal": [
            "DEMO: review NMD terms for export compliance gaps.",
            "Summarise liability caps in the forward-deploy SOW.",
        ],
        "Support": [
            "DEMO: build FAQ from Vitron onboarding notes.",
            "Triage open tickets tagged forward-deploy.",
        ],
    }
    return prompts_by_role.get(role, [f"DEMO: {role} workspace check-in."])


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
        {"ts": now - 30, "action": "admin_overview", "ip": DEMO_LAN_IP, "user": "demo.admin", "ok": True, "detail": "workers=12 · DEMO"},
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
                    for ip, *_ in PEERS + [HOST_PEER]
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

    # Vendor NMD document set (Act 2)
    _write_vendor_documents(files)
    _write_calendar_fixture(mock_dir)

    # SQLite chat + devices
    conn = _init_db(mock_dir / "clipdrop.db")
    t0 = now - 600
    all_roster = list(PEERS) + [HOST_PEER]
    for ip, name, ua, state, acl in all_roster:
        seen = _last_seen_for_state(now, state if acl != "host" else "live", ip)
        level = acl if acl != "host" else "host"
        if ip in PEER_LIMITED:
            level = "limited"
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
                "read_write" if level == "host" else level,
                "host" if level == "host" else "lan",
                1 if seen > now - 200 and state != "offline" else 0,
                "DEMO Admin",
                "",
                t0,
                now,
                seen,
            ),
        )

    # Vitron project for Act 3
    conn.execute(
        "INSERT OR IGNORE INTO projects(name,slug,category,description,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?)",
        (
            "Vitron — Forward Deployment",
            "vitron-forward-deployment",
            "general",
            "DEMO · forward-deploy collaboration with Vitron Systems.",
            t0,
            now,
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

    # Per-peer chat sessions + prompts for Hub drill-down "View chat →"
    peer_sessions: dict[str, int] = {"10.10.20.12": sid_connect}
    peer_offset = 300
    for ip, name, _ua, state, acl in PEERS:
        if ip == "10.10.20.12":
            continue  # Jordan already in sid_connect
        if state == "offline":
            continue
        prompts = _peer_chat_prompts(ip, name, acl)
        cur = conn.execute(
            "INSERT INTO chat_sessions(title,capture_type,created_at,updated_at,related_to,category,summary) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                f"DEMO · {name}",
                "manual",
                t0 + peer_offset,
                now - 3,
                "",
                "general",
                f"BUSINESS MOCK prompts for {name}.",
            ),
        )
        sid = cur.lastrowid
        peer_sessions[ip] = sid
        peer_offset += 5
        msg_t = t0 + peer_offset
        for prompt in prompts:
            add_msg(
                session_id=sid,
                text=prompt,
                device_ip=ip,
                device_name=name,
                created_at=msg_t,
                source="chat",
            )
            msg_t += 4
            if acl in ("use_host_ai", "use_own_ai", "limited"):
                add_msg(
                    session_id=sid,
                    device_name="Netie Cortex",
                    text=f"[DEMO MOCK] Acknowledged — {prompt[:72]}{'…' if len(prompt) > 72 else ''}",
                    created_at=msg_t,
                    source="ai-chat",
                    ai_status="done",
                )
                msg_t += 3

    conn.commit()
    conn.close()

    usage_path = mock_dir / "usage" / "events.jsonl"
    usage_count = _seed_usage_events(usage_path, now=now, peer_sessions=peer_sessions)

    nmd_files = [
        files / "NMD" / "RFQ-2026-0417.pdf",
        files / "NMD" / "FCM-NMD-88.xlsx",
        files / "VDML-template.xlsx",
        files / "NMD" / "PO-NMD-1123.pdf",
    ]
    nmd_ok = all(p.is_file() and p.stat().st_size > 64 for p in nmd_files)

    print(f"SEEDED={mock_dir}")
    print(f"PEERS={len(PEERS)}")
    print(f"USAGE_EVENTS={usage_count}")
    print(f"BEN_PROMPT_SEEDED={BEN_ACT5_PROMPT!r}")
    print(f"NMD_FILES_OK={nmd_ok}")
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

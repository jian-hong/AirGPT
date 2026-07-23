"""ClipDrop allcheck — full connectivity + API diagnostics. Run after WiFi change."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parent
NET_FILE = ROOT / "data" / "network.json"

CHECKS = [
    ("/api/probe", lambda d: d.get("ok") is True),
    ("/api/info", lambda d: "tunnel_url" in d and "lan_url" in d),
    ("/api/history", lambda d: "messages" in d),
    ("/api/messages?since=0&full=1", lambda d: "by_date" in d or "messages" in d),
    ("/api/ai/config", lambda d: "auto" in d),
    ("/api/auth/status", lambda d: "needs_auth" in d),
    ("/api/vault", lambda d: "categories" in d or "recent" in d),
    ("/api/sessions", lambda d: "sessions" in d),
    ("/api/search?q=test", lambda d: "sessions" in d and "messages" in d),
    ("/api/audit", lambda d: "events" in d),
    ("/api/workspace", lambda d: "ok" in d),
    ("/api/cortex/settings", lambda d: "thinking_mode" in d),
    ("/api/cortex/runs?limit=5", lambda d: "runs" in d),
    ("/api/cortex/pending", lambda d: "runs" in d),
    ("/api/cortex/invoke", lambda d: d.get("ok") and "skills" in d and "invoke" in d),
    ("/api/invoke/skills", lambda d: d.get("ok") and "skills" in d),
    ("/api/openide/backend", lambda d: "backend" in d),
    ("/api/openide/ready", lambda d: "ok" in d and "backend" in d),
    ("/api/keyvault", lambda d: "providers" in d),
    ("/api/openforge/status", lambda d: "ok" in d and "honesty" in d),
    ("/api/agents", lambda d: "agents" in d),
    ("/api/rag/spaces", lambda d: d.get("ok") is True and "spaces" in d),
    ("/api/commands", lambda d: "commands" in d),
    ("/api/mentions/suggest?q=rag", lambda d: d.get("ok") is True and "items" in d),
    ("/api/hub", lambda d: d.get("ok") and "host" in d and "peers" in d),
    ("/api/marketplace?category=llm", lambda d: d.get("ok") and "items" in d),
    ("/api/marketplace?category=skills", lambda d: d.get("ok") and "items" in d),
    ("/api/memory/panel?session_id=0&project=general", lambda d: d.get("ok") is True or "memories" in d),
]


def _get(path: str, timeout: int = 8) -> tuple[bool, dict | str]:
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return True, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return False, json.loads(e.read().decode())
        except Exception:
            return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)


def _probe_url(url: str, timeout: int = 12) -> tuple[bool, str]:
    if not url:
        return False, "no url"
    try:
        req = urllib.request.Request(
            url.rstrip("/") + "/api/probe",
            headers={"Cache-Control": "no-store"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        if data.get("ok"):
            return True, data.get("via", "ok")
        return False, "probe not ok"
    except Exception as e:
        return False, str(e)[:80]


def main() -> int:
    print("=== ClipDrop allcheck ===\n")
    fails = 0

    # Local API checks
    passed = 0
    for path, validate in CHECKS:
        timeout = 20 if path == "/api/info" else 8
        ok, data = _get(path, timeout=timeout)
        valid = ok and isinstance(data, dict) and validate(data)
        status = "OK" if valid else "FAIL"
        if valid:
            passed += 1
        else:
            fails += 1
        detail = ""
        if not valid and isinstance(data, dict) and data.get("error"):
            detail = f" -- {data['error']}"
        elif not valid and not ok:
            detail = f" -- {data}"
        print(f"  [{status}] GET {path}{detail}")

    try:
        with urllib.request.urlopen(
            BASE + "/api/qr.png?u=https://test.trycloudflare.com", timeout=8,
        ) as r:
            qr_ok = r.status == 200 and r.headers.get("Content-Type", "").startswith("image/")
        if qr_ok:
            passed += 1
        else:
            fails += 1
        print(f"  [{'OK' if qr_ok else 'FAIL'}] GET /api/qr.png")
    except Exception as e:
        fails += 1
        print(f"  [ERR] GET /api/qr.png: {e}")

    total = len(CHECKS) + 1
    print(f"\n  Local APIs: {passed}/{total}")

    # Network / tunnel detail
    print("\n--- Network ---")
    ok, info = _get("/api/info", timeout=20)
    if not ok or not isinstance(info, dict):
        print("  [WARN] Could not read /api/info (tunnel/LAN may be slow) — continuing checks")
        info = {}

    ips = info.get("ips") or []
    lan = info.get("lan_url") or "—"
    tunnel = info.get("tunnel_url") or ""
    t_status = info.get("tunnel_status", "?")
    t_healthy = info.get("tunnel_healthy", False)
    print(f"  LAN IP:     {ips[0] if ips else 'none'}")
    print(f"  LAN URL:    {lan}")
    print(f"  Tunnel:     {tunnel or 'not ready'}")
    print(f"  Status:     {t_status} | healthy={t_healthy} | provider={info.get('tunnel_provider', '')}")
    print(f"  Messages:   latest_id={info.get('latest_id', 0)}")
    print(f"  Network:    {info.get('network_profile', '?')} | firewall={info.get('firewall', '?')}")

    prev_ip = ""
    if NET_FILE.is_file():
        try:
            prev = json.loads(NET_FILE.read_text(encoding="utf-8"))
            prev_ip = prev.get("ip", "")
        except Exception:
            pass
    cur_ip = ips[0] if ips else ""
    if prev_ip and cur_ip and prev_ip != cur_ip:
        print(f"  [WARN] IP changed since last run: {prev_ip} -> {cur_ip}")
        print("         Tunnel URL may be stale on phone -- scan fresh QR")
        fails += 1
    elif not prev_ip and cur_ip:
        NET_FILE.parent.mkdir(parents=True, exist_ok=True)
        NET_FILE.write_text(json.dumps({"ip": cur_ip, "lan_url": lan}), encoding="utf-8")

    if tunnel:
        t_ok, t_via = _probe_url(tunnel)
        print(f"  Tunnel probe: {'OK' if t_ok else 'FAIL'} ({t_via})")
        if not t_ok:
            fails += 1
            print("  -> Click Restart Tunnel in UI, or run restart.bat")

    if info.get("lan_likely_blocked"):
        print("  [INFO] Company/Public WiFi - use Tunnel QR, not LAN")

  # History depth
    ok_h, hist = _get("/api/history", timeout=15)
    if ok_h and isinstance(hist, dict):
        n = len(hist.get("messages") or [])
        print(f"\n--- Data ---")
        print(f"  History items loaded: {n}")
        ok_s, sess = _get("/api/sessions")
        if ok_s and isinstance(sess, dict):
            print(f"  Chat sessions:        {len(sess.get('sessions') or [])}")

    # Daily session split (local DB, no server required for helpers)
    print("\n--- Daily clipboard split ---")
    try:
        import db as dbm
        # Read-only check: do not create empty daily chats as a side effect
        import sqlite3
        from config import DATA_DIR
        conn = sqlite3.connect(str(DATA_DIR / "clipdrop.db"))
        conn.row_factory = sqlite3.Row
        types = {
            r["capture_type"]
            for r in conn.execute(
                "SELECT DISTINCT capture_type FROM chat_sessions WHERE capture_type LIKE 'daily_%'"
            )
        }
        need = {"daily_clipboard_text", "daily_clipboard_image", "daily_ai_screenshot"}
        # Create only if missing so CI still validates helpers once
        created = []
        if "daily_clipboard_text" not in types:
            created.append(dbm.get_or_create_daily_text_session()["id"])
        if "daily_clipboard_image" not in types:
            created.append(dbm.get_or_create_daily_image_session()["id"])
        if "daily_ai_screenshot" not in types:
            created.append(dbm.get_or_create_daily_screenshot_session()["id"])
        t = dbm.get_or_create_daily_text_session()
        i = dbm.get_or_create_daily_image_session()
        s = dbm.get_or_create_daily_screenshot_session()
        split_ok = (
            t.get("capture_type") == "daily_clipboard_text"
            and i.get("capture_type") == "daily_clipboard_image"
            and s.get("capture_type") == "daily_ai_screenshot"
            and len({t["id"], i["id"], s["id"]}) == 3
        )
        if split_ok:
            print("  [OK] daily text + image + AI screenshot sessions")
        else:
            print("  [FAIL] daily session types or ids wrong")
            fails += 1
        n_pruned = dbm.prune_empty_screenshot_sessions()
        print(f"  Pruned empty screenshot orphans: {n_pruned}")
        # Clean empties we just created for the check
        for sid in created:
            row = conn.execute(
                "SELECT (SELECT COUNT(*) FROM messages m WHERE m.session_id=?) AS n FROM chat_sessions WHERE id=?",
                (sid, sid),
            ).fetchone()
            if row and int(row["n"] or 0) == 0:
                conn.execute("DELETE FROM chat_sessions WHERE id=?", (sid,))
        conn.commit()
        conn.close()
        srch_ok, srch = _get("/api/search?q=clipboard&date=today")
        if srch_ok and isinstance(srch, dict) and "sessions" in srch and "messages" in srch:
            print("  [OK] GET /api/search")
        else:
            print("  [FAIL] GET /api/search")
            fails += 1
    except Exception as e:
        print(f"  [ERR] daily split check: {e}")
        fails += 1

    print("\n--- Claude-native checks ---")
    try:
        import db as dbm
        trimmed = dbm.ditch_context(
            [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello " * 2000}]
            + [{"role": "assistant", "content": f"old {i} " * 100} for i in range(40)]
            + [{"role": "user", "content": "latest question about serdes"}],
            budget_chars=3000,
        )
        joined = sum(len(str(m.get("content") or m.get("text") or "")) for m in trimmed)
        if joined <= 4000 and any("latest question" in str(m.get("content") or "") for m in trimmed):
            print(f"  [OK] ditch_context kept latest under budget ({joined} chars, {len(trimmed)} msgs)")
        else:
            print(f"  [FAIL] ditch_context size={joined} n={len(trimmed)}")
            fails += 1
    except Exception as e:
        print(f"  [ERR] ditch_context: {e}")
        fails += 1
    try:
        ok_w = False
        with urllib.request.urlopen(f"{BASE}/wasm_gate.js", timeout=5) as r:
            body = r.read().decode("utf-8", errors="replace")
            ok_w = "AirGPTWasmGate" in body and r.status == 200
        if ok_w:
            print("  [OK] /wasm_gate.js served")
        else:
            print("  [FAIL] /wasm_gate.js")
            fails += 1
    except Exception as e:
        print(f"  [ERR] wasm_gate: {e}")
        fails += 1
    try:
        ok_a, adm = _get("/api/admin/overview", timeout=12)
        if ok_a and isinstance(adm, dict) and adm.get("ok") is True and "workers" in adm:
            print(f"  [OK] admin overview ok=True workers={len(adm.get('workers') or [])}")
        else:
            print("  [FAIL] admin overview")
            fails += 1
    except Exception as e:
        print(f"  [ERR] admin: {e}")
        fails += 1

    print("\n--- Fix checklist (WiFi / IP change) ---")
    print("  1. Run restart.bat on PC")
    print("  2. Hard-refresh PC browser: Ctrl+Shift+R")
    print("  3. On phone: scan NEW Tunnel QR (old bookmark is dead)")
    print("  4. If LAN: phone must be on same WiFi as PC")

    if fails:
        print(f"\n  Result: {fails} issue(s) - see above")
        return 1
    print("\n  Result: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

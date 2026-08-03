"""WiFi-first connect helpers — mDNS, diagnostics, ranked access methods."""
from __future__ import annotations

import json
import socket
import subprocess
import threading
from pathlib import Path

import time

PORT = 8765
MDNS_NAME = "airgpt"
_mdns: object | None = None
_mdns_url = ""
_hw_cache: dict[str, tuple[float, bool]] = {}


def wifi_adapter_up() -> bool:
    """Cached — PowerShell Get-NetAdapter was ~1s per /api/info poll."""
    now = time.time()
    hit = _hw_cache.get("wifi")
    if hit and now - hit[0] < 60.0:
        return hit[1]
    ok = False
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' -and "
             "$_.InterfaceDescription -match 'Wi-?Fi|Wireless' } | Measure-Object).Count"],
            capture_output=True, text=True, timeout=3,
        )
        ok = (r.stdout or "").strip() not in ("", "0")
    except Exception:
        ok = False
    _hw_cache["wifi"] = (now, ok)
    return ok


def bluetooth_present() -> bool:
    """Cached — PnP Bluetooth query was ~1s per /api/info poll."""
    now = time.time()
    hit = _hw_cache.get("bt")
    if hit and now - hit[0] < 120.0:
        return hit[1]
    ok = False
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
             "Where-Object { $_.Status -eq 'OK' } | Measure-Object).Count"],
            capture_output=True, text=True, timeout=3,
        )
        ok = (r.stdout or "").strip() not in ("", "0")
    except Exception:
        ok = False
    _hw_cache["bt"] = (now, ok)
    return ok


def network_profile() -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-NetConnectionProfile | Where-Object {$_.IPv4Connectivity -ne 'Disconnected'} "
             "| Select-Object -First 1).NetworkCategory"],
            capture_output=True, text=True, timeout=6,
        )
        return (r.stdout or "").strip() or "Unknown"
    except Exception:
        return "Unknown"


def local_ips() -> list[str]:
    ips: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    return ips


def mdns_url() -> str:
    return _mdns_url or f"http://{MDNS_NAME}.local:{PORT}"


def start_mdns(port: int = PORT) -> str:
    """Advertise AirGPT on WiFi as http://airgpt.local:PORT (best-effort)."""
    global _mdns, _mdns_url
    _mdns_url = f"http://{MDNS_NAME}.local:{port}"
    try:
        from zeroconf import ServiceInfo, Zeroconf
    except ImportError:
        return ""
    if _mdns is not None:
        return _mdns_url
    try:
        ips = local_ips()
        if not ips:
            return ""
        zc = Zeroconf()
        info = ServiceInfo(
            "_http._tcp.local.",
            f"{MDNS_NAME}._http._tcp.local.",
            addresses=[socket.inet_aton(ip) for ip in ips[:4]],
            port=port,
            properties={b"path": b"/", b"product": b"AirGPT"},
            server=f"{MDNS_NAME}.local.",
        )
        zc.register_service(info)
        _mdns = zc
        print(f"[wifi] mDNS ready -> {_mdns_url}")
        return _mdns_url
    except Exception as e:
        print(f"[wifi] mDNS skipped: {e}")
        return ""


def stop_mdns() -> None:
    global _mdns, _mdns_url
    if _mdns is not None:
        try:
            _mdns.close()
        except Exception:
            pass
    _mdns = None
    _mdns_url = ""


def connect_methods(
    *,
    lan_url: str | None,
    tunnel_url: str | None,
    tunnel_healthy: bool,
    firewall: str,
    network_profile_name: str,
    lan_blocked: bool,
) -> list[dict]:
    """Ranked ways to reach AirGPT from phone — WiFi first, no cable needed."""
    methods: list[dict] = []
    wifi_up = wifi_adapter_up()
    bt = bluetooth_present()
    mdns = mdns_url() if _mdns_url else None

    if lan_url and firewall == "ok" and not lan_blocked:
        methods.append({
            "id": "wifi",
            "label": "WiFi — same network",
            "url": lan_url,
            "qr": lan_url,
            "easy": True,
            "hint": "Phone on same WiFi → scan QR or type URL. No cable needed.",
        })
        if mdns:
            methods.append({
                "id": "mdns",
                "label": "WiFi — easy name",
                "url": mdns,
                "qr": mdns,
                "easy": True,
                "hint": "Same WiFi → open airgpt.local in Safari (no IP to remember).",
            })

    if tunnel_url and tunnel_healthy:
        methods.append({
            "id": "tunnel",
            "label": "Internet tunnel",
            "url": tunnel_url,
            "qr": tunnel_url,
            "easy": True,
            "hint": "Works on any WiFi — company, home, coffee shop. Scan Tunnel QR.",
        })

    methods.append({
        "id": "hotspot",
        "label": "Phone hotspot",
        "url": None,
        "qr": None,
        "easy": False,
        "hint": (
            "Router blocks phone→PC? Turn on phone hotspot → connect this PC to it → "
            "run restart.bat → scan new WiFi QR."
        ),
    })

    methods.append({
        "id": "p2p",
        "label": "P2P drop (no server)",
        "url": "/p2p",
        "qr": None,
        "easy": False,
        "hint": "Firewall blocked? Open /p2p on both devices — encrypted peer link, WiFi only.",
    })

    if bt:
        methods.append({
            "id": "bluetooth",
            "label": "Bluetooth note",
            "url": None,
            "qr": None,
            "easy": False,
            "hint": (
                "iPhone cannot browse via Bluetooth. Android: pair BT + enable BT tethering, "
                "then use WiFi QR above. Easiest: scan Tunnel or WiFi QR."
            ),
        })

    if wifi_up and network_profile_name == "Public":
        methods.insert(0, {
            "id": "fix",
            "label": "Fix WiFi access",
            "url": None,
            "qr": None,
            "easy": False,
            "hint": "WiFi is Public — run enable-lan.bat as Admin (sets Private + opens port 8765).",
        })

    return methods


def run_diagnostics(base: str = f"http://127.0.0.1:{PORT}") -> dict:
    """Full WiFi connectivity report."""
    import urllib.error
    import urllib.request

    def probe(url: str, timeout: int = 5) -> dict:
        try:
            req = urllib.request.Request(f"{url.rstrip('/')}/api/probe", headers={"Cache-Control": "no-store"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode())
            return {"ok": True, "via": data.get("via"), "status": r.status}
        except urllib.error.HTTPError as e:
            return {"ok": False, "error": f"HTTP {e.code}"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    ips = local_ips()
    report = {
        "wifi_adapter_up": wifi_adapter_up(),
        "bluetooth_present": bluetooth_present(),
        "network_profile": network_profile(),
        "ips": ips,
        "mdns_url": mdns_url() if _mdns_url else f"http://{MDNS_NAME}.local:{PORT}",
        "localhost": probe(f"http://127.0.0.1:{PORT}"),
        "lan_probes": {ip: probe(f"http://{ip}:{PORT}") for ip in ips},
    }
    try:
        with urllib.request.urlopen(base + "/api/info", timeout=8) as r:
            info = json.loads(r.read().decode())
        report["tunnel_url"] = info.get("tunnel_url")
        report["tunnel_healthy"] = info.get("tunnel_healthy")
        report["firewall"] = info.get("firewall")
        report["lan_likely_blocked"] = info.get("lan_likely_blocked")
        if info.get("tunnel_url"):
            report["tunnel_probe"] = probe(info["tunnel_url"], timeout=12)
    except Exception as e:
        report["api_info_error"] = str(e)[:120]
    return report


def print_report(report: dict) -> int:
    print("=== AirGPT WiFi Debug ===\n")
    fails = 0
    print(f"  WiFi adapter:     {'UP' if report.get('wifi_adapter_up') else 'DOWN'}")
    print(f"  Bluetooth:        {'present' if report.get('bluetooth_present') else 'not found'}")
    print(f"  Network profile:  {report.get('network_profile', '?')}")
    print(f"  Firewall:         {report.get('firewall', '?')}")
    print(f"  IPs:              {', '.join(report.get('ips') or []) or 'none'}")
    print(f"  Easy URL:         {report.get('mdns_url', '—')}")

    loc = report.get("localhost", {})
    ok = loc.get("ok")
    print(f"  [{'OK' if ok else 'FAIL'}] localhost:8765")
    if not ok:
        fails += 1
        print(f"         {loc.get('error', '')}")

    for ip, p in (report.get("lan_probes") or {}).items():
        ok = p.get("ok")
        print(f"  [{'OK' if ok else 'FAIL'}] WiFi LAN http://{ip}:{PORT}")
        if not ok:
            fails += 1
            print(f"         {p.get('error', '')}")

    t = report.get("tunnel_probe")
    if t:
        ok = t.get("ok")
        print(f"  [{'OK' if ok else 'FAIL'}] Tunnel")
        if not ok:
            fails += 1

    print("\n--- How to connect phone (no cable) ---")
    if report.get("network_profile") == "Public":
        print("  1. Run enable-lan.bat -> Yes on UAC -> sets WiFi Private")
        fails += 1
    if report.get("lan_likely_blocked"):
        print("  2. WiFi LAN may be blocked - use Tunnel QR or phone hotspot")
    for ip in report.get("ips") or []:
        print(f"  * Same WiFi: http://{ip}:{PORT}")
    if report.get("mdns_url"):
        print(f"  * Easy name: {report['mdns_url']} (same WiFi)")
    if report.get("tunnel_url"):
        print(f"  * Any WiFi:  {report['tunnel_url']}")
    print("  * Blocked?     Phone hotspot -> PC joins -> restart.bat -> scan WiFi QR")
    print("  * P2P fallback: http://127.0.0.1:8765/p2p on both devices")

    if fails:
        print(f"\n  Result: {fails} issue(s)")
        return 1
    print("\n  Result: WiFi access ready")
    return 0

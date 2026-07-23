"""OpenForge chat-to-chip integration (Netie-AI/OpenForge)."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

from config import DATA_DIR, ROOT

FORGE_DIR = DATA_DIR / "openforge" / "designs"
VENDOR = ROOT / "third_party" / "openforge"


def enabled() -> bool:
    flag = DATA_DIR / "marketplace" / "module_openforge.enabled"
    return flag.is_file()


def status() -> dict:
    ngspice = _find_ngspice()
    return {
        "ok": True,
        "enabled": enabled(),
        "ngspice": bool(ngspice),
        "ngspice_path": ngspice or "",
        "vendor": str(VENDOR) if VENDOR.is_dir() else "",
        "vendor_ready": VENDOR.is_dir(),
        "designs": len(list(FORGE_DIR.glob("*.json"))) if FORGE_DIR.is_dir() else 0,
        "honesty": "template + optional ngspice smoke; full Netie vendor pipeline not vendored yet",
    }


def _find_ngspice() -> str:
    import shutil

    return shutil.which("ngspice") or ""


def parse_spec(text: str) -> dict:
    """Extract analog targets from natural language spec."""
    t = text or ""
    targets: dict[str, str | float] = {}
    m = re.search(r"(\d+(?:\.\d+)?)\s*V", t, re.I)
    if m:
        targets["supply_v"] = float(m.group(1))
    for pat, key in (
        (r"gain\s*[≥>=]+\s*(\d+(?:\.\d+)?)\s*dB", "gain_db"),
        (r"phase margin\s*[≥>=]+\s*(\d+(?:\.\d+)?)", "phase_margin_deg"),
        (r"bandwidth\s*[≥>=]+\s*(\d+(?:\.\d+)?)\s*MHz", "ugbw_mhz"),
    ):
        m = re.search(pat, t, re.I)
        if m:
            targets[key] = float(m.group(1))
    block = "op_amp"
    if "comparator" in t.lower():
        block = "comparator"
    elif "reference" in t.lower():
        block = "voltage_reference"
    return {"ok": True, "block": block, "targets": targets, "raw": t[:4000]}


def _run_ngspice_smoke(netlist: str) -> dict:
    """Run a minimal ngspice batch parse — proves sim gate is real, not a flag flip."""
    ng = _find_ngspice()
    if not ng:
        return {"ok": False, "ran": False, "note": "ngspice not installed — netlist template only"}
    # Minimal circuit that always parses (independent of opamp template completeness)
    deck = f"""* OpenForge smoke deck
{netlist}
Vdd vdd 0 DC 1.8
Vin vin 0 DC 0.9 AC 1
X1 vin vout vdd 0 opamp
.ac dec 10 1 10Meg
.end
"""
    try:
        with tempfile.TemporaryDirectory() as td:
            cir = Path(td) / "smoke.cir"
            log = Path(td) / "smoke.log"
            cir.write_text(deck, encoding="utf-8")
            proc = subprocess.run(
                [ng, "-b", "-o", str(log), str(cir)],
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",
            )
            out = ((proc.stdout or "") + (proc.stderr or "") + (log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""))[
                -4000:
            ]
            ok = proc.returncode == 0 and "error" not in out.lower()[:200]
            return {
                "ok": ok,
                "ran": True,
                "exit_code": proc.returncode,
                "note": "ngspice smoke ran" if ok else "ngspice ran but reported errors (template may need device models)",
                "log_tail": out[-1500:],
            }
    except subprocess.TimeoutExpired:
        return {"ok": False, "ran": True, "note": "ngspice timeout"}
    except OSError as e:
        return {"ok": False, "ran": False, "note": str(e)[:200]}


def design(text: str) -> dict:
    """Template netlist + honest simulation gate (smoke ngspice when available)."""
    FORGE_DIR.mkdir(parents=True, exist_ok=True)
    spec = parse_spec(text)
    if not spec.get("ok"):
        return spec
    targets = spec.get("targets") or {}
    gain = float(targets.get("gain_db") or 60)
    pm = float(targets.get("phase_margin_deg") or 55)
    bw = float(targets.get("ugbw_mhz") or 5)
    supply = float(targets.get("supply_v") or 1.8)
    netlist = f"""* OpenForge template — two-stage Miller op-amp
* Supply {supply}V — targets gain>={gain}dB PM>={pm}deg UGBW>={bw}MHz
.subckt opamp vin vout vdd vss
M1 d1 vin vss vss nmos W=10u L=0.5u
M2 d2 vin vss vss nmos W=10u L=0.5u
M3 d1 d1 vdd vdd pmos W=20u L=0.5u
M4 d2 d1 vdd vdd pmos W=20u L=0.5u
M5 vout d2 vss vss nmos W=40u L=0.5u
Cc vout d2 2p
.ends opamp
"""
    sim = _run_ngspice_smoke(netlist)
    # simulation_gated means we actually attempted / require sim — not "binary exists"
    simulation_gated = bool(sim.get("ran")) and bool(sim.get("ok"))
    if not sim.get("ran"):
        sim_note = sim.get("note") or "netlist template only"
    elif simulation_gated:
        sim_note = "ngspice smoke OK — vendor AC/transient metrics still pending Netie OpenForge import"
    else:
        sim_note = sim.get("note") or "ngspice failed — netlist not simulation-gated"

    design_id = f"design_{int(time.time())}"
    record = {
        "id": design_id,
        "spec": spec,
        "netlist": netlist,
        "simulation_gated": simulation_gated,
        "sim_note": sim_note,
        "sim": {k: v for k, v in sim.items() if k != "log_tail"} | {"log_tail": (sim.get("log_tail") or "")[:800]},
        "schematic_svg": _schematic_svg(supply, gain, pm, bw, gated=simulation_gated),
        "created_at": time.time(),
    }
    (FORGE_DIR / f"{design_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {"ok": True, **record}


def list_designs(limit: int = 20) -> list[dict]:
    FORGE_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for p in sorted(FORGE_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def _schematic_svg(supply: float, gain: float, pm: float, bw: float, *, gated: bool = False) -> str:
    badge = "sim-gated" if gated else "template"
    color = "#3dd68c" if gated else "#e8b84a"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="420" height="200" viewBox="0 0 420 200">
  <rect width="420" height="200" fill="#0a0a0a"/>
  <text x="12" y="24" fill="#8a8a8a" font-family="monospace" font-size="12">OpenForge — {badge}</text>
  <text x="12" y="44" fill="#f5f5f5" font-family="monospace" font-size="11">{supply}V · gain≥{gain}dB · PM≥{pm}° · {bw}MHz</text>
  <rect x="40" y="70" width="80" height="50" fill="none" stroke="{color}" stroke-width="2"/>
  <text x="52" y="100" fill="{color}" font-family="monospace" font-size="10">diff</text>
  <line x1="120" y1="95" x2="160" y2="95" stroke="#f5f5f5"/>
  <rect x="160" y="70" width="80" height="50" fill="none" stroke="#e8b84a" stroke-width="2"/>
  <text x="172" y="100" fill="#e8b84a" font-family="monospace" font-size="10">Miller</text>
  <line x1="240" y1="95" x2="300" y2="95" stroke="#f5f5f5"/>
  <text x="310" y="100" fill="#f5f5f5" font-family="monospace" font-size="12">Vout</text>
</svg>"""

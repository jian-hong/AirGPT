"""OpenVault mesh bridge — connect AirGPT OpenIDE to E:\\OpenVault (:5000).

Handshake + connect-pack per OpenVault OpenMW local_mesh protocol.
Keys SoT is OpenVault (/api/keyvault/*, /api/keys*); this module only talks
loopback HTTP. See PRODUCT_ROLES.md.
This laptop's tree is E:\\OpenVault (D:\\OpenVault is absent). Dual-home
footgun: pin OPENVAULT_HOME to <root>\\.openvault before starting :5000.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from config import DATA_DIR, ENV_FILE, ROOT

DEFAULT_OV_URL = "http://127.0.0.1:5000"
PACK_CACHE = DATA_DIR / "openvault_connect_pack.json"
_OV_CANDIDATES = (Path(r"E:\OpenVault"), Path(r"D:\OpenVault"))


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def _file_env(key: str) -> str:
    """Read one key from env.local. Never used to print secrets."""
    if not ENV_FILE.is_file():
        return ""
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip()
    except OSError:
        return ""
    return ""


def looks_like_openvault(root: Path) -> bool:
    return (root / "apps" / "cli" / "openvault_cli.py").is_file() or (root / "OpenMW").is_dir()


def resolve_openvault_root() -> Path:
    """Prefer env, then env.local, then E:\\OpenVault, then D:\\OpenVault."""
    raw = _env("OPENVAULT_ROOT") or _file_env("OPENVAULT_ROOT")
    if raw:
        return Path(raw)
    for cand in _OV_CANDIDATES:
        if looks_like_openvault(cand):
            return cand
    return _OV_CANDIDATES[0]


OPENVAULT_ROOT = resolve_openvault_root()


def openvault_home(root: Path | None = None) -> Path:
    raw = _env("OPENVAULT_HOME")
    if raw:
        return Path(raw)
    return (root or OPENVAULT_ROOT) / ".openvault"


def _local_cfg_candidates() -> tuple[Path, ...]:
    return (
        OPENVAULT_ROOT / "openvault.local.json",
        ROOT / "openvault.local.json",
        DATA_DIR / "openvault.local.json",
    )


def openvault_url() -> str:
    u = _env("OPENVAULT_URL") or _file_env("OPENVAULT_URL")
    if u:
        return u.rstrip("/")
    for p in _local_cfg_candidates():
        if p.is_file():
            try:
                cfg = json.loads(p.read_text(encoding="utf-8"))
                svc = (cfg.get("services") or {}).get("openvault") or {}
                if svc.get("url"):
                    return str(svc["url"]).rstrip("/")
            except Exception:
                pass
    return DEFAULT_OV_URL


def openide_public_url() -> str:
    """URL OpenVault should call back for this OpenIDE (AirGPT host)."""
    return (
        _env("OPENIDE_URL")
        or _env("AIRGPT_PUBLIC_URL")
        or _file_env("OPENIDE_URL")
        or "http://127.0.0.1:8765"
    ).rstrip("/")


def _http_json(method: str, url: str, body: dict | None = None, *, timeout: float = 8.0) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


_PING_CACHE: dict[str, Any] = {"ts": 0.0, "value": None}


def ping() -> dict[str, Any]:
    """Loopback health. Cached -- /api/info used to block ~2s per call when :5000 was down."""
    now = time.time()
    hit = _PING_CACHE.get("value")
    if hit is not None and now - float(_PING_CACHE["ts"]) < 8.0:
        return dict(hit)
    base = openvault_url()
    home = openvault_home()
    try:
        health = _http_json("GET", f"{base}/api/healthz", timeout=0.6)
        out = {
            "ok": health.get("status") == "ok",
            "openvault_url": base,
            "openvault_root": str(OPENVAULT_ROOT),
            "openvault_home": str(home),
            "health": health,
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        cli = OPENVAULT_ROOT / "apps" / "cli" / "openvault_cli.py"
        out = {
            "ok": False,
            "openvault_url": base,
            "openvault_root": str(OPENVAULT_ROOT),
            "openvault_home": str(home),
            "error": str(e)[:240],
            "hint": (
                f"set OPENVAULT_HOME={home} then python {cli} up"
            ),
        }
    _PING_CACHE["ts"] = now
    _PING_CACHE["value"] = dict(out)
    return out


def chat_ping_loopback(*, timeout: float = 20.0) -> dict[str, Any]:
    """Loopback /v1/chat/completions with no Bearer. Never prints content."""
    base = openvault_url()
    url = f"{base}/v1/chat/completions"
    payload = {
        "model": "auto",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8") or "{}")
            choices = raw.get("choices") or []
            return {
                "ok": bool(choices),
                "status": int(getattr(resp, "status", 200) or 200),
                "model": str(raw.get("model") or ""),
                "has_content": bool(choices),
            }
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        detail = ""
        try:
            parsed = json.loads(raw)
            err = parsed.get("detail") or parsed.get("error") or parsed
            detail = str(err)[:200]
        except Exception:
            detail = (raw.strip() or f"HTTP {e.code}")[:200]
        return {"ok": False, "status": int(e.code), "error": detail}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return {"ok": False, "error": str(e)[:200]}


def keyvault_presence() -> dict[str, Any]:
    """Configured provider ids only. No secrets, no masks."""
    snap = keyvault_snapshot()
    configured: list[str] = []
    missing: list[str] = []
    for p in snap.get("providers") or []:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "")
        if not pid:
            continue
        if p.get("configured"):
            configured.append(pid)
        else:
            missing.append(pid)
    frontier = [pid for pid in ("cursor", "anthropic") if pid in missing]
    return {
        "ok": bool(snap.get("ok")),
        "source": snap.get("source") or "offline",
        "configured": configured,
        "missing_frontier": frontier,
        "error": snap.get("error"),
    }


def mesh_build_check(*, live: bool = True) -> dict[str, Any]:
    """Build-check row for allcheck: tree + home + optional live health/chat."""
    root = OPENVAULT_ROOT
    tree_ok = looks_like_openvault(root)
    home = openvault_home(root)
    out: dict[str, Any] = {
        "tree_ok": tree_ok,
        "root": str(root),
        "home": str(home),
        "home_ok": home.is_dir(),
        "url": openvault_url(),
    }
    if not live:
        out["ok"] = tree_ok
        return out
    health = ping()
    out["health_ok"] = bool(health.get("ok"))
    out["health"] = health
    chat: dict[str, Any] | None = None
    if health.get("ok"):
        chat = chat_ping_loopback()
        out["chat"] = {
            "ok": bool(chat.get("ok")),
            "status": chat.get("status"),
            "model": chat.get("model") or "",
            "error": chat.get("error"),
        }
    keys = keyvault_presence()
    out["keys"] = {
        "ok": keys.get("ok"),
        "configured": keys.get("configured") or [],
        "missing_frontier": keys.get("missing_frontier") or [],
    }
    out["ok"] = bool(tree_ok and health.get("ok"))
    return out


def keyvault_snapshot() -> dict[str, Any]:
    """Prefer OpenVault SoT; callers fall back to local catalog if offline."""
    base = openvault_url()
    try:
        snap = _http_json("GET", f"{base}/api/keyvault/snapshot", timeout=5.0)
        snap["ok"] = True
        snap["openvault_url"] = base
        snap["source"] = snap.get("source") or "openvault"
        return snap
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return {"ok": False, "openvault_url": base, "error": str(e)[:240], "source": "offline"}


def keyvault_upsert(
    *,
    env_key: str = "",
    secret: str = "",
    secrets: dict[str, str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Write secrets to OpenVault (SoT). Caller may sync env.local cache."""
    base = openvault_url()
    body: dict[str, Any] = {"env_key": env_key, "secret": secret, **extra}
    if secrets:
        body["secrets"] = secrets
    try:
        return {"ok": True, "openvault_url": base, **_http_json("POST", f"{base}/api/keyvault/upsert", body)}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return {"ok": False, "openvault_url": base, "error": str(e)[:240]}


def gate_check(
    *,
    action: str = "run",
    project_path: str = "",
    destination: str = "",
    required_providers: list[str] | None = None,
) -> dict[str, Any]:
    """Ask OpenVault whether retrieve/run/deploy/leave may proceed."""
    base = openvault_url()
    body = {
        "action": action,
        "project_path": project_path,
        "destination": destination,
        "required_providers": required_providers or [],
    }
    try:
        return {"ok": True, "openvault_url": base, **_http_json("POST", f"{base}/api/gate/check", body)}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return {
            "ok": False,
            "allowed": False,
            "openvault_url": base,
            "error": str(e)[:240],
            "reasons": ["OpenVault offline — gate closed (PRODUCT_ROLES)"],
        }


def mesh() -> dict[str, Any]:
    base = openvault_url()
    try:
        return {"ok": True, "openvault_url": base, **_http_json("GET", f"{base}/api/local/mesh")}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return {"ok": False, "openvault_url": base, "error": str(e)[:240]}


def connect_pack(*, refresh: bool = True) -> dict[str, Any]:
    base = openvault_url()
    try:
        pack = _http_json("GET", f"{base}/api/local/connect-pack")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PACK_CACHE.write_text(json.dumps(pack, indent=2), encoding="utf-8")
        ov_home = openvault_home()
        try:
            ov_home.mkdir(parents=True, exist_ok=True)
            (ov_home / "connect_pack.json").write_text(json.dumps(pack, indent=2), encoding="utf-8")
        except OSError:
            pass
        return {"ok": True, "pack": pack, "cached": str(PACK_CACHE)}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        if PACK_CACHE.is_file() and not refresh:
            try:
                return {
                    "ok": True,
                    "pack": json.loads(PACK_CACHE.read_text(encoding="utf-8")),
                    "cached": str(PACK_CACHE),
                    "stale": True,
                }
            except Exception:
                pass
        return {"ok": False, "error": str(e)[:240], "openvault_url": base}


def handshake(*, name: str = "AirGPT OpenIDE", auto_approve: bool = True) -> dict[str, Any]:
    """Announce this OpenIDE to OpenVault mesh and pull connect pack."""
    base = openvault_url()
    ide = openide_public_url()
    try:
        _http_json(
            "PUT",
            f"{base}/api/local/mesh/config",
            {
                "auto_approve_loopback": True,
                "openide_url": ide,
            },
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        pass

    try:
        hs = _http_json(
            "POST",
            f"{base}/api/local/handshake",
            {
                "peer_kind": "openide",
                "name": name,
                "base_url": ide,
                "capabilities": [
                    "signin",
                    "passkey",
                    "editor",
                    "scaffold",
                    "keyvault",
                    "airgpt",
                ],
                "auto_approve": auto_approve,
            },
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return {
            "ok": False,
            "error": str(e)[:240],
            "openvault_url": base,
            "openide_url": ide,
            "hint": f"OpenVault must be running on :5000 ({OPENVAULT_ROOT}).",
        }

    pack_body = hs.get("connect_pack") if isinstance(hs.get("connect_pack"), dict) else None
    if not pack_body:
        pack = connect_pack()
        pack_body = pack.get("pack") if pack.get("ok") else None
    if pack_body:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            PACK_CACHE.write_text(json.dumps(pack_body, indent=2), encoding="utf-8")
            ov_home = openvault_home()
            ov_home.mkdir(parents=True, exist_ok=True)
            (ov_home / "connect_pack.json").write_text(json.dumps(pack_body, indent=2), encoding="utf-8")
        except OSError:
            pass

    status_s = ((hs.get("handshake") or {}).get("status") or "").lower()
    approved = status_s in ("approved", "online") or bool(
        (pack_body or {}).get("openide", {}).get("approved")
    )
    return {
        "ok": approved or status_s == "pending",
        "approved": approved,
        "handshake": hs.get("handshake") or hs,
        "openvault_url": base,
        "openide_url": ide,
        "openvault_root": str(OPENVAULT_ROOT),
        "connect_pack": pack_body,
        "connected_at": time.time(),
    }


def status() -> dict[str, Any]:
    p = ping()
    if not p.get("ok"):
        return {**p, "connected": False}
    pack_body: dict[str, Any] = {}
    if PACK_CACHE.is_file():
        try:
            pack_body = json.loads(PACK_CACHE.read_text(encoding="utf-8"))
        except Exception:
            pack_body = {}
    m = mesh()
    return {
        **p,
        "connected": True,
        "mesh": m if m.get("ok") else {"ok": False},
        "connect_pack": pack_body or None,
        "roles": "PRODUCT_ROLES.md — OpenVault owns keys/gate/deploy; AirGPT is thin shell",
    }


def _apps_root() -> Path:
    return OPENVAULT_ROOT / "apps"


def sync_project(project: str, source: str = "") -> dict[str, Any]:
    """Copy a project folder into OpenVault apps/<name> for the one-shot ship path."""
    import shutil

    name = (project or "").strip().replace("\\", "/").split("/")[-1][:80]
    src = Path(source) if source else None
    if not name:
        return {"ok": False, "error": "project name required"}
    if src is None or not src.is_dir():
        # Prefer an existing OpenVault app, else a demo fixture under AirGPT.
        candidates = [
            _apps_root() / name,
            ROOT / "apps" / name,
            ROOT / "fixtures" / name,
            OPENVAULT_ROOT / "apps" / name,
        ]
        src = next((p for p in candidates if p.is_dir()), None)
    if src is None or not src.is_dir():
        # Create a minimal Next.js-shaped fixture so Detect stays honest on camera.
        dest = _apps_root() / name
        dest.mkdir(parents=True, exist_ok=True)
        pkg = {
            "name": name,
            "private": True,
            "scripts": {"build": "next build", "dev": "next dev"},
            "dependencies": {"next": "14.2.5", "react": "18.3.1", "react-dom": "18.3.1"},
        }
        (dest / "package.json").write_text(json.dumps(pkg, indent=2) + "\n", encoding="utf-8")
        (dest / "README.md").write_text(f"# {name}\n\nDEMO fixture for AirGPT → OpenVault one-shot.\n", encoding="utf-8")
        return {
            "ok": True,
            "project": name,
            "dest": str(dest),
            "files": 2,
            "created_fixture": True,
            "lines": [f"Created demo fixture at {dest}", "package.json with next dependency"],
        }
    dest = _apps_root() / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    file_count = 0
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
        lines.append(f"Cleared previous {dest}")
    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns("node_modules", ".git", ".next", "dist", "__pycache__", ".venv"),
    )
    for p in dest.rglob("*"):
        if p.is_file():
            file_count += 1
    lines.append(f"Synced {file_count} files → {dest}")
    return {"ok": True, "project": name, "dest": str(dest), "files": file_count, "lines": lines}


def detect_project(project: str = "", path: str = "") -> dict[str, Any]:
    """Actually read package.json — never hardcode the framework string."""
    name = (project or "").strip()
    root = Path(path) if path else (_apps_root() / name if name else None)
    if root is None or not root.is_dir():
        return {"ok": False, "error": "project path not found — sync first"}
    pkg_path = root / "package.json"
    evidence = ""
    framework = "unknown"
    build = ""
    port = 3000
    if pkg_path.is_file():
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        except Exception as e:
            return {"ok": False, "error": f"package.json unreadable: {e}"[:200]}
        deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
        scripts = pkg.get("scripts") or {}
        evidence = f"package.json · dependencies include: {', '.join(sorted(deps)[:8]) or '(none)'}"
        if "next" in deps:
            framework = "Next.js"
            build = str(scripts.get("build") or "next build")
            port = 3000
        elif "vite" in deps:
            framework = "Vite"
            build = str(scripts.get("build") or "vite build")
            port = 5173
        elif "react-scripts" in deps:
            framework = "Create React App"
            build = str(scripts.get("build") or "react-scripts build")
            port = 3000
        else:
            framework = "Node"
            build = str(scripts.get("build") or "npm run build")
    elif (root / "pyproject.toml").is_file():
        framework = "Python"
        build = "uv build"
        evidence = "pyproject.toml present"
        port = 8000
    elif (root / "Cargo.toml").is_file():
        framework = "Rust"
        build = "cargo build --release"
        evidence = "Cargo.toml present"
        port = 8080
    else:
        return {"ok": False, "error": "no package.json / pyproject.toml / Cargo.toml", "path": str(root)}
    return {
        "ok": True,
        "framework": framework,
        "build": build,
        "port": port,
        "path": str(root),
        "evidence": evidence,
        "package_json": str(pkg_path) if pkg_path.is_file() else "",
    }


def build_project(project: str = "", path: str = "") -> dict[str, Any]:
    """Run the detected build when deps exist; otherwise stream a honest short-circuit."""
    import subprocess

    det = detect_project(project, path)
    if not det.get("ok"):
        return det
    root = Path(det["path"])
    cmd = str(det.get("build") or "")
    lines = [f"Detected: {det.get('framework')} — {det.get('evidence')}", f"$ {cmd}"]
    # Prefer not to hang the demo on a full next build without node_modules.
    has_nm = (root / "node_modules").is_dir()
    if det.get("framework") == "Next.js" and not has_nm:
        lines.append("node_modules missing — demo short-circuit (detect stayed real).")
        lines.append("Would run: npm install && " + cmd)
        lines.append("Build OK (simulated for camera)")
        return {"ok": True, "simulated_build": True, "lines": lines, "detect": det}
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            shell=True,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
        lines.extend(out[-40:] or ["(no output)"])
        lines.append(f"exit={proc.returncode}")
        return {
            "ok": proc.returncode == 0,
            "simulated_build": False,
            "lines": lines,
            "detect": det,
            "exit_code": proc.returncode,
        }
    except Exception as e:
        lines.append(f"build error: {e}"[:200])
        return {"ok": False, "lines": lines, "detect": det, "error": str(e)[:200]}


def ship_project(project: str = "", path: str = "") -> dict[str, Any]:
    """Return a deploy URL. Always label simulated targets on camera."""
    det = detect_project(project, path)
    name = (project or Path(det.get("path") or "app").name).strip() or "app"
    port = int(det.get("port") or 3000) if det.get("ok") else 3000
    # Prefer a real local preview if something is listening; otherwise simulated EC2-shaped URL.
    local_url = f"http://127.0.0.1:{port}"
    simulated = True
    url = f"https://{name.lower().replace(' ', '-')}.demo.airgpt.local"
    label = "Simulated target"
    try:
        with urllib.request.urlopen(local_url, timeout=0.6) as r:
            if getattr(r, "status", 200) < 500:
                url = local_url
                simulated = False
                label = "Local preview"
    except Exception:
        pass
    return {
        "ok": True,
        "url": url,
        "simulated": simulated,
        "label": label,
        "project": name,
        "detect": det if det.get("ok") else None,
        "ec2_hint": "ec2-12-34-56-78.compute-1.amazonaws.com" if simulated else "",
    }


def ensure_local_config() -> dict[str, Any]:
    """Write/refresh openvault.local.json so mesh URLs stay aligned."""
    path = next(
        (p for p in _local_cfg_candidates() if p.parent.is_dir()),
        DATA_DIR / "openvault.local.json",
    )
    if path == DATA_DIR / "openvault.local.json":
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg: dict[str, Any] = {}
    if path.is_file():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    services = dict(cfg.get("services") or {})
    ov = dict(services.get("openvault") or {})
    ov["url"] = openvault_url()
    ov["root"] = str(OPENVAULT_ROOT)
    ov["console"] = (
        f"set OPENVAULT_HOME={openvault_home()} && "
        f"python {OPENVAULT_ROOT / 'apps' / 'cli' / 'openvault_cli.py'} up"
    )
    services["openvault"] = ov
    ide = dict(services.get("openide") or {})
    ide["url"] = openide_public_url()
    ide["announce"] = f"{openvault_url()}/api/local/handshake"
    ide["invoke"] = f"{openvault_url()}/api/openide/invoke"
    ide["connect_pack"] = f"{openvault_url()}/api/local/connect-pack"
    services["openide"] = ide
    cfg["services"] = services

    try:
        path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "path": str(path), "openide_url": ide["url"]}
    except OSError as e:
        alt = DATA_DIR / "openvault.local.json"
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        alt.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "path": str(alt), "warn": str(e)[:160], "openide_url": ide["url"]}

"""ClipDrop v5 — ChatGPT-style LAN chat. SQLite + multi-tunnel."""
from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import os
import queue
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import db
import vault
from config import APP_NAME, APP_VERSION, BIN_DIR, DATA_DIR, DEMO_MOCK, DEMO_MOCK_HOSTNAME, DEMO_MOCK_LAN_IP, ROOT, ensure_dirs

try:
    import wifi_access
except ImportError:
    wifi_access = None  # type: ignore

try:
    import input_notes
except ImportError:
    input_notes = None  # type: ignore

try:
    import admin_dashboard
except ImportError:
    admin_dashboard = None  # type: ignore

try:
    import license as app_license
except ImportError:
    app_license = None  # type: ignore

try:
    import netie_id
except ImportError:
    netie_id = None  # type: ignore

try:
    import auth as app_auth
except ImportError:
    app_auth = None  # type: ignore

try:
    import ai_engine
except ImportError:
    ai_engine = None  # type: ignore

try:
    import security as _security
except ImportError:
    _security = None  # type: ignore

try:
    import settings as app_settings
except ImportError:
    app_settings = None  # type: ignore

try:
    import audit as app_audit
except ImportError:
    app_audit = None  # type: ignore

try:
    import email_resend
except ImportError:
    email_resend = None  # type: ignore

_latest_capture_session = 0
_server_mode = "engineering"

HOST = "0.0.0.0"
PORT = 8765
CLIPBOARD_POLL = 0.35
BIN = BIN_DIR

ensure_dirs()
MAX_BYTES = 100 * 1024 * 1024
ALLOWED = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic",
    ".mp4", ".mov", ".webm", ".mkv", ".avi",
    ".pdf", ".txt", ".md", ".doc", ".docx", ".zip",
}

BIN.mkdir(exist_ok=True)
db.init_db()

_lock = threading.Lock()
_last_img_hash = ""
_last_text_hash = ""
_suppress_clipboard_until = 0.0
_seen_ss: dict[str, float] = {}
_tunnel = {"url": "", "provider": "", "status": "off", "error": "", "healthy": False, "started_at": 0}
_tunnel_procs: list[subprocess.Popen] = []
_tunnel_lock = threading.Lock()
_health_fails = 0
_sync_version = 0
_sync_cv = threading.Condition()
_firewall_status = ""
AI_AUTO = True
_client_ai_enabled = True
_ai_rate_lock = threading.Lock()
_ai_last_ts = 0.0
AI_RATE_LIMIT_SEC = 60
_online_cache: dict = {"ok": True, "ts": 0.0}
_auth_fails: dict[str, list[float]] = {}
_qr_session_token = ""
_network_epoch = 0
NET_STATE_FILE = DATA_DIR / "network.json"
_qr_join_cache: dict[str, tuple[str, str, float]] = {}


def _load_ai_auto() -> bool:
    env = ROOT / "env.local"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("AI_AUTO="):
                return line.split("=", 1)[1].strip().lower() in ("1", "true", "yes")
    return True


def bump_sync() -> None:
    global _sync_version
    with _sync_cv:
        _sync_version += 1
        _sync_cv.notify_all()


def _register_tunnel_proc(proc: subprocess.Popen) -> None:
    with _tunnel_lock:
        _tunnel_procs.append(proc)


def _kill_orphan_cloudflared() -> None:
    """Kill leftover cloudflared processes that still target this app port."""
    try:
        # Windows: taskkill by image; Unix: pkill. Best-effort.
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/IM", "cloudflared.exe"],
                capture_output=True, text=True, timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
        else:
            subprocess.run(["pkill", "-f", f"cloudflared.*{PORT}"], capture_output=True, timeout=8)
    except Exception as e:
        print(f"[tunnel] orphan cleanup skip: {e}")


def _kill_tunnel_procs() -> None:
    with _tunnel_lock:
        for p in _tunnel_procs:
            try:
                p.terminate()
                p.wait(timeout=2)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        _tunnel_procs.clear()
    _kill_orphan_cloudflared()


def restart_tunnel() -> None:
    global _qr_join_cache
    _qr_join_cache.clear()
    _kill_tunnel_procs()
    _tunnel.update(url="", provider="", status="restarting", error="", healthy=False)
    threading.Thread(target=tunnel_worker, daemon=True).start()


def _image_file_path(msg: dict) -> Path | None:
    rel = msg.get("filepath")
    if not rel:
        return None
    p = db.FILES.parent / rel.replace("/", os.sep)
    if p.is_file():
        return p
    p2 = DATA_DIR / rel
    return p2 if p2.is_file() else None


def _ai_allowed() -> bool:
    if not app_license:
        return True
    return bool(app_license.get_status().get("can_use_ai"))


def _tunnel_allowed() -> bool:
    if not app_license:
        return True
    return bool(app_license.get_status().get("can_use_tunnel"))


def _is_online() -> bool:
    """Internet available — tunnel healthy or BYOK keys count as online enough to try providers."""
    if _tunnel.get("healthy") and _tunnel.get("url"):
        _online_cache.update(ok=True, ts=time.time())
        return True
    try:
        if app_settings and app_settings.get_public_settings().get("has_any_key"):
            _online_cache.update(ok=True, ts=time.time())
            return True
    except Exception:
        pass
    now = time.time()
    if now - _online_cache["ts"] < 20:
        return bool(_online_cache["ok"])
    ok = False
    import urllib.request
    for host in (
        "https://www.google.com/generate_204",
        "https://cloudflare.com/cdn-cgi/trace",
    ):
        try:
            urllib.request.urlopen(host, timeout=1.5)
            ok = True
            break
        except Exception:
            continue
    _online_cache["ok"] = ok
    _online_cache["ts"] = now
    return ok


def _check_ai_rate() -> str | None:
    """Free tier: 1 AI request per minute. Licensed or BYOK users skip."""
    if app_license and app_license.get_status().get("licensed"):
        return None
    # BYOK: any configured LLM key unlocks unlimited local rate
    try:
        if app_settings and app_settings.get_public_settings().get("has_any_key"):
            return None
    except Exception:
        pass
    global _ai_last_ts
    with _ai_rate_lock:
        now = time.time()
        wait = AI_RATE_LIMIT_SEC - (now - _ai_last_ts)
        if _ai_last_ts and wait > 0:
            return f"Free tier: 1 AI request/min. Wait {int(wait) + 1}s or add your API key in Settings."
        _ai_last_ts = now
    return None


def run_analysis(msg_id: int, question: str | None = None, mode: str = "engineering", session_id: int = 0, depth: str = "normal") -> None:
    if not _is_online():
        err = "AI mode requires internet. Offline storage still works — export anytime."
        if question:
            db.add_message(device_ip="127.0.0.1", device_name="AirGPT", text=err, kind="text", source="ai", session_id=session_id)
            bump_sync()
        else:
            db.update_ai(msg_id, status="error", analysis=err)
        return
    if not _ai_allowed():
        err = "Trial expired — unlock AirGPT ($10) or add your own API keys in Settings."
        if question:
            db.add_message(device_ip="127.0.0.1", device_name="AirGPT", text=err, kind="text", source="ai", session_id=session_id)
            bump_sync()
        else:
            db.update_ai(msg_id, status="error", analysis=err)
        return
    if not ai_engine:
        db.update_ai(msg_id, status="error", analysis="ai_engine not installed")
        return
    msg = db.get_message(msg_id)
    if not msg or msg["kind"] != "image":
        return
    path = _image_file_path(msg)
    if not path and not (question and msg.get("vision_cache")):
        db.update_ai(msg_id, status="error", analysis="image file missing")
        return
    db.update_ai(msg_id, status="running")
    try:
        data = path.read_bytes() if path else b""
        mime = msg.get("mime") or (mimetypes.guess_type(str(path))[0] if path else "image/png") or "image/png"
        prior = msg.get("ai_analysis") if question else None
        cache = msg.get("vision_cache") or ""

        # Early classify + category before full vision (updates UI border)
        if not question and data:
            fast = ai_engine.classify_image_fast(data, mime)
            cat = fast.get("category", "general")
            if mode != "general":
                cat = mode if mode in ai_engine.MODES else cat
            db.update_ai(msg_id, status="running", ai_category=cat)
            sid = int(msg.get("session_id") or session_id or 0)
            if sid:
                proj = db.get_default_project_for_category(cat)
                db.update_session_meta(sid, category=cat, project_id=proj["id"])

        result = ai_engine.analyze_image(
            data, mime,
            mode=mode,
            user_question=question,
            prior_analysis=prior or None,
            vision_cache=cache or None,
            depth=depth,
        )
        cat = result.get("early_category") or msg.get("ai_category") or "general"
        sid = int(session_id or msg.get("session_id") or 0)
        ai_title = _title_from_ai_text(
            result["analysis"],
            fallback=result.get("early_title") or "",
        )
        if sid and not question:
            db.maybe_set_ai_session_title(sid, ai_title, summary=result["analysis"][:280].replace("\n", " "))
        if question:
            db.add_message(
                device_ip="127.0.0.1", device_name="ClipDrop AI",
                text=result["analysis"], kind="text", source="ai", session_id=session_id,
            )
            if sid:
                db.maybe_set_ai_session_title(sid, ai_title, summary=result["analysis"][:280].replace("\n", " "))
            bump_sync()
        else:
            db.update_ai(
                msg_id, status="done", analysis=result["analysis"], model=result["model"],
                vision_cache=result.get("vision_cache", ""), ai_category=cat,
            )
            bump_sync()
            _file_capture_to_vault(msg, msg_id, result["analysis"], mode=mode, early=result)
        print(f"[ai] msg {msg_id} via {result['model']} mode={mode} depth={depth}")
    except Exception as e:
        err = str(e)[:800]
        if question:
            db.add_message(device_ip="127.0.0.1", device_name="ClipDrop AI", text=f"AI error: {err}", kind="text", source="ai", session_id=session_id)
        else:
            db.update_ai(msg_id, status="error", analysis=err)
        print(f"[ai] error msg {msg_id}: {e}")


def queue_analysis(msg_id: int, question: str | None = None, mode: str = "engineering", session_id: int = 0, depth: str = "normal") -> None:
    rate_err = _check_ai_rate()
    if rate_err:
        msg = db.get_message(msg_id)
        sid = int(session_id or (msg or {}).get("session_id") or 0)
        if question:
            db.add_message(device_ip="127.0.0.1", device_name="AirGPT", text=rate_err, kind="text", source="ai", session_id=sid)
            bump_sync()
        elif msg:
            db.update_ai(msg_id, status="error", analysis=rate_err)
            bump_sync()
        return
    threading.Thread(target=run_analysis, args=(msg_id, question, mode, session_id, depth), daemon=True).start()


def run_text_chat(question: str, mode: str = "general", session_id: int = 0) -> None:
    if not _is_online():
        db.add_message(device_ip="127.0.0.1", device_name="AirGPT", text="AI chat needs internet or local API keys. Manual local chat still works.", kind="text", source="ai", session_id=session_id)
        bump_sync()
        return
    if not _ai_allowed():
        db.add_message(device_ip="127.0.0.1", device_name="AirGPT", text="Trial expired — unlock AirGPT or add your own API keys in Settings.", kind="text", source="ai", session_id=session_id)
        bump_sync()
        return
    if not ai_engine:
        db.add_message(device_ip="127.0.0.1", device_name="AirGPT", text="AI engine not installed.", kind="text", source="ai", session_id=session_id)
        bump_sync()
        return
    try:
        business = bool((app_license.get_status() if app_license else {}).get("business_features"))
        result = ai_engine.chat_text(question, mode=mode, session_id=session_id, business_require=business)
        db.add_message(device_ip="127.0.0.1", device_name="AirGPT", text=result["analysis"], kind="text", source="ai", session_id=session_id)
        if session_id:
            db.maybe_set_ai_session_title(
                session_id,
                _title_from_ai_text(result["analysis"], fallback=(question or "")[:60]),
                summary=result["analysis"][:280].replace("\n", " "),
            )
    except Exception as e:
        db.add_message(device_ip="127.0.0.1", device_name="AirGPT", text=f"AI error: {str(e)[:800]}", kind="text", source="ai", session_id=session_id)
    bump_sync()


def queue_text_chat(question: str, mode: str = "general", session_id: int = 0) -> None:
    rate_err = _check_ai_rate()
    if rate_err:
        db.add_message(device_ip="127.0.0.1", device_name="AirGPT", text=rate_err, kind="text", source="ai", session_id=session_id)
        bump_sync()
        return
    threading.Thread(target=run_text_chat, args=(question, mode, session_id), daemon=True).start()


# ---- chat_classifier wiring: one-off small-talk → shared Scratch space, no linkage ----
_SCRATCH_TITLE = "Scratch · random chat"
_scratch_ids: set[int] = set()


def _get_or_create_scratch_session() -> int:
    try:
        for s in db.list_sessions(limit=200):
            if s.get("capture_type") == "scratch":
                _scratch_ids.add(int(s["id"]))
                return int(s["id"])
        sess = db.create_session(_SCRATCH_TITLE, capture_type="scratch")
        _scratch_ids.add(int(sess["id"]))
        return int(sess["id"])
    except Exception:
        return 0


def _route_new_chat(text: str) -> int:
    """Scratch session id when small-talk starts a new chat; 0 = route normally.
    Existing sessions are never yanked — only fresh chats reroute."""
    try:
        import chat_classifier
        if chat_classifier.classify(text).space == "scratch":
            return _get_or_create_scratch_session()
    except Exception:
        pass
    return 0


def _is_scratch_session(sid: int) -> bool:
    if not sid:
        return False
    if sid in _scratch_ids:
        return True
    try:
        for s in db.list_sessions(limit=200):
            if int(s.get("id") or 0) == sid and s.get("capture_type") == "scratch":
                _scratch_ids.add(sid)
                return True
    except Exception:
        pass
    return False


def _build_chat_history(
    session_id: int,
    context_ids: list,
    reply_snippet: str,
    *,
    exclude_msg_id: int = 0,
) -> list[dict]:
    history: list[dict] = []
    if reply_snippet:
        history.append({"role": "assistant", "content": f"[Replying to]: {reply_snippet[:500]}"})
    for cid in context_ids[:10]:
        try:
            m = db.get_message(int(cid))
        except (TypeError, ValueError):
            continue
        if not m:
            continue
        role = "assistant" if m.get("source") == "ai" else "user"
        content = (m.get("ai_analysis") or m.get("text") or "").strip()
        if content:
            history.append({"role": role, "content": content[:2000]})
    if session_id and not _is_scratch_session(session_id):  # Scratch = no linkage
        for m in db.get_messages(session_id=session_id, limit=24):
            if exclude_msg_id and int(m.get("id") or 0) == exclude_msg_id:
                continue
            role = "assistant" if m.get("source") == "ai" else "user"
            content = (m.get("text") or "").strip()
            if content:
                history.append({"role": role, "content": content[:2000]})
    return history[-12:]


def _chat_stream_events(
    question: str,
    mode: str,
    history: list[dict] | None,
    abort: threading.Event,
    *,
    session_id: int = 0,
    model_tier: str = "high",
    thinking: bool = True,
):
    """Yield stream events; respects abort flag between chunks."""
    if abort.is_set():
        return
    if not _is_online():
        yield {"type": "error", "text": "AI chat needs internet or local API keys. Manual local chat still works."}
        return
    if not _ai_allowed():
        yield {"type": "error", "text": "Trial expired — unlock AirGPT or add your own API keys in Settings."}
        return
    if not ai_engine:
        yield {"type": "error", "text": "AI engine not installed."}
        return
    try:
        business = bool((app_license.get_status() if app_license else {}).get("business_features"))
        for ev in ai_engine.chat_text_stream(
            question,
            mode=mode,
            history=history,
            session_id=session_id,
            business_require=business,
            model_tier=model_tier,
            thinking=thinking,
        ):
            if abort.is_set():
                return
            yield ev
    except Exception as e:
        yield {"type": "error", "text": str(e)[:800]}


def _file_capture_to_vault(msg: dict, msg_id: int, analysis: str, mode: str = "engineering", early: dict | None = None) -> None:
    """Categorize capture into fixed project category."""
    sid = int(msg.get("session_id") or 0)
    if not sid:
        return
    meta = vault.parse_vault_metadata(analysis)
    early = early or {}
    cat = db.MODE_TO_CATEGORY.get(mode, "general")
    if mode == "general":
        cat = early.get("early_category") or meta.get("category", "general")
        if cat not in db.MODE_TO_CATEGORY:
            cat = "general"
    proj = db.get_default_project_for_category(cat)
    title = meta.get("session_title") or early.get("early_title") or msg.get("filename") or f"Capture {msg_id}"
    related = meta.get("related_to") or ""
    vpath = vault.write_session_note(
        project_slug=proj["slug"],
        project_name=proj["name"],
        session_id=sid,
        title=title,
        analysis=analysis,
        image_rel=msg.get("filepath") or "",
        source=msg.get("source") or "capture",
        related=related,
    )
    summary = analysis[:280].replace("\n", " ")
    db.update_session_meta(
        sid, title=title, project_id=proj["id"], summary=summary,
        related_to=related, vault_path=vpath, category=cat,
    )
    print(f"[vault] [{cat}] {title}")
    try:
        import cortex_client
        cortex_client.append_ledger(
            "airgpt",
            "vault.saved",
            {"session_id": sid, "vault_path": vpath, "category": cat, "title": title},
        )
    except Exception:
        pass


def post_capture_image(
    device_ip: str, device_name: str, file_data: bytes, filename: str, source: str,
    *, with_ai: bool | None = None,
) -> dict | None:
    """Route captures:
    - clipboard (no AI) → today's Images daily chat
    - screenshot → today's AI Screenshot Chat (with analysis)
    - AI photo → dedicated chat; title set from first AI reply
    """
    global _latest_capture_session
    use_ai = AI_AUTO and _client_ai_enabled and bool(ai_engine) if with_ai is None else bool(with_ai)

    if source == "clipboard" and not use_ai:
        session = db.get_or_create_daily_image_session()
        _latest_capture_session = session["id"]
        return post_message(
            device_ip, device_name, file_data=file_data, filename=filename,
            source=source, session_id=session["id"], auto_analyze=False,
        )

    # Screenshots → one daily AI Screenshot Chat; global hash so clipboard/folder never double-post
    if source == "screenshot":
        session = db.get_or_create_daily_screenshot_session()
        db.update_session_meta(session["id"], category=db.MODE_TO_CATEGORY.get(_server_mode, "general"))
        _latest_capture_session = session["id"]
        msg = post_message(
            device_ip, device_name, file_data=file_data, filename=filename,
            source=source, session_id=session["id"], auto_analyze=False,
            allow_duplicate=False,  # one image hash → one chat publish
        )
        if msg and use_ai and ai_engine:
            queue_analysis(msg["id"], mode=_server_mode, session_id=session["id"])
        return msg

    # AI photo / other → own chat space (only keep session if message lands)
    session = db.create_capture_session(source)
    db.update_session_meta(session["id"], category=db.MODE_TO_CATEGORY.get(_server_mode, "general"))
    _latest_capture_session = session["id"]
    msg = post_message(
        device_ip, device_name, file_data=file_data, filename=filename,
        source=source, session_id=session["id"], auto_analyze=False,
    )
    if not msg:
        try:
            db.delete_session(session["id"])
        except Exception:
            pass
        if _latest_capture_session == session["id"]:
            _latest_capture_session = 0
        return None
    if use_ai and ai_engine:
        queue_analysis(msg["id"], mode=_server_mode, session_id=session["id"])
    return msg


def _title_from_ai_text(text: str, fallback: str = "") -> str:
    """Prefer SESSION_TITLE / early heading; else first meaningful line."""
    if not text:
        return fallback
    m = re.search(r"SESSION_TITLE:\s*(.+)", text)
    if m:
        return m.group(1).strip()[:80]
    m = re.search(r"\*\*Category:\*\*[^\n]*\n+", text)
    body = text[m.end():] if m else text
    for line in body.splitlines():
        line = line.strip().lstrip("#").strip()
        if not line or line.startswith("---") or line.startswith("**Chain"):
            continue
        if line.startswith("**") and line.endswith("**"):
            line = line.strip("*").strip()
        if len(line) >= 8:
            return line[:80]
    return fallback or "AI chat"


SCREENSHOT_DIRS = [
    Path.home() / "Pictures" / "Screenshots",
    Path.home() / "OneDrive" / "Pictures" / "Screenshots",
]


def hostname() -> str:
    if DEMO_MOCK:
        return DEMO_MOCK_HOSTNAME
    return socket.gethostname()


def local_ips() -> list[str]:
    if DEMO_MOCK:
        return [DEMO_MOCK_LAN_IP]
    ips: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    return ips


def _is_local_host(ip: str) -> bool:
    """Host PC may open http://192.168.x.x:8765 — same machine, full access."""
    if ip in ("127.0.0.1", "::1"):
        return True
    try:
        return ip in local_ips()
    except Exception:
        return False


# Host-only API surfaces (SECURITY_HARDENING #1/#5/#7). These can read/write host
# files, run commands, expose the audit trail, or execute agents — never allowed
# to remote peers (LAN/tunnel), even with a valid chat token or in the default
# no-passcode state. The host machine (127.0.0.1 or its own LAN IP) always passes
# via _is_local_host(); remote OpenIDE would need a distinct capability token (a
# later phase), not the guest chat token.
_HOST_ONLY_PREFIXES: tuple[str, ...] = (
    "/api/fs/",         # workspace read/write/patch/tree/find/checkpoint
    "/api/terminal/",   # command execution
    "/api/workspace",   # bind/open workspace root (covers /api/workspace[/open])
    "/api/git/",        # repo status/diff/checkout/branches
    "/api/agents/",     # agent listing + run (code-execution surface)
    "/api/cortex/",     # agent-brain queue/settings/runs/recipes/isolation
    "/api/invoke/",     # create/update rules & skills (workspace write)
    "/api/openide/",    # IDE backend/ready/last-run/scaffold
    "/api/openvault/",  # OpenVault mesh handshake / connect-pack (D:\OpenVault)
    "/api/openforge/",  # chip design pipeline
    "/api/rag",         # RAG Agent knowledge spaces / ingest / answer (host-only)
    "/api/admin",       # admin dashboard data (covers /api/admin[/*])
    "/api/audit",       # audit trail (covers /api/audit[/*])
)


def _is_host_only_path(path: str) -> bool:
    return any(path == p or path.startswith(p) for p in _HOST_ONLY_PREFIXES)


def _is_tunnel_host(host: str) -> bool:
    h = (host or "").split(":")[0].lower()
    return any(x in h for x in (
        "trycloudflare.com", "lhr.life", "loca.lt", "serveo.net", "localhost.run",
    ))


def _forwarded_client_ip(headers, direct_ip: str) -> str | None:
    """Real remote client when cloudflared (or similar) proxies on loopback."""
    if direct_ip not in ("127.0.0.1", "::1"):
        return None
    if not _is_tunnel_host(headers.get("Host", "")):
        return None
    cf = (headers.get("CF-Connecting-IP") or "").strip()
    if cf:
        return cf
    xff = (headers.get("X-Forwarded-For") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return None


_net_profile_cache: dict = {"ts": 0.0, "value": "Unknown"}


def network_profile() -> str:
    """Cached — PowerShell Get-NetConnectionProfile is ~1–6s and was polled every 3s."""
    now = time.time()
    if now - float(_net_profile_cache["ts"]) < 45.0:
        return str(_net_profile_cache["value"] or "Unknown")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-NetConnectionProfile | Where-Object {$_.IPv4Connectivity -ne 'Disconnected'} "
             "| Select-Object -First 1).NetworkCategory"],
            capture_output=True, text=True, timeout=3,
        )
        val = (r.stdout or "").strip() or "Unknown"
    except Exception:
        val = "Unknown"
    _net_profile_cache["ts"] = now
    _net_profile_cache["value"] = val
    return val


def make_qr_png(text: str) -> bytes:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_H
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_H, box_size=9, border=4)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0b0f14", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_lan_diag_cache: dict = {"ts": 0.0, "value": None}


def lan_diagnostics() -> dict:
    now = time.time()
    cached = _lan_diag_cache.get("value")
    if cached and now - float(_lan_diag_cache["ts"]) < 30.0:
        return dict(cached)
    ips = local_ips()
    profile = network_profile()
    fw = refresh_firewall_status()
    blocked = profile == "Public" and fw != "ok"
    if fw == "ok" and profile == "Private":
        hint = "Same WiFi: scan LAN QR below. Phone must be on the same network as this PC."
    elif fw == "ok" and profile == "Public":
        hint = "Firewall OK but WiFi is Public — run allow_firewall.ps1 as Admin to switch to Private, then scan LAN QR."
    elif profile == "Public":
        hint = "LAN blocked — run allow_firewall.ps1 as Admin (sets Private + opens port 8765). Or use Tunnel QR."
    else:
        hint = "Run allow_firewall.ps1 as Admin to open port 8765. Then scan LAN QR on phone."
    out = {
        "ips": ips,
        "lan_url": f"http://{ips[0]}:{PORT}" if ips else None,
        "network_profile": profile,
        "firewall": fw,
        "listening": f"0.0.0.0:{PORT}",
        "lan_likely_blocked": blocked,
        "hint": hint,
    }
    _lan_diag_cache["ts"] = now
    _lan_diag_cache["value"] = dict(out)
    return out


def device_name_from_ua(ua: str, ip: str) -> str:
    if "iPad" in ua:
        return "iPad"
    if "iPhone" in ua:
        return "iPhone"
    if "Android" in ua:
        return "Android"
    if ip in ("127.0.0.1", "::1"):
        return hostname()
    return hostname() if "Windows" in ua else "Guest"


def save_file(data: bytes, filename: str) -> tuple[str, str, str | None, str]:
    ext = Path(filename).suffix.lower() or ".bin"
    day = datetime.now().strftime("%Y-%m-%d")
    fid = f"{uuid.uuid4().hex[:10]}{ext}"
    rel = f"files/{day}/{fid}"
    dest = db.FILES / day
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / fid
    path.write_bytes(data)
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    thumb = None
    img_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif"}
    if ext in img_exts:
        try:
            from PIL import Image
            tname = f"{Path(fid).stem}.jpg"
            with Image.open(path) as im:
                im.thumbnail((480, 480))
                if im.mode in ("RGBA", "P"):
                    im = im.convert("RGB")
                im.save(db.THUMBS / tname, "JPEG", quality=85)
            thumb = f"thumbs/{tname}"
        except Exception:
            pass
    kind = "video" if ext in {".mp4", ".mov", ".webm", ".mkv", ".avi"} else "image" if ext in img_exts else "file"
    return rel.replace("\\", "/"), mime, thumb, kind


def _normalize_image_bytes(raw: bytes) -> bytes:
    """Stable PNG bytes for dedup (clipboard DIB can vary slightly)."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        return raw


def _looks_like_screenshot(img_bytes: bytes) -> bool:
    """Heuristic: Win+Shift+S / snips are usually larger than icons or small memes."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(img_bytes))
        w, h = im.size
        return w >= 640 and h >= 360
    except Exception:
        return len(img_bytes or b"") > 80_000


def post_message(device_ip: str, device_name: str, text: str = "", file_data: bytes | None = None,
                 filename: str | None = None, source: str = "chat", session_id: int = 0,
                 auto_analyze: bool = True, auto_clipboard: bool = False,
                 allow_duplicate: bool = False) -> dict | None:
    if file_data:
        is_img = (filename or "").lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif"))
        is_img = is_img or file_data.startswith(b"\x89PNG") or file_data.startswith(b"\xff\xd8")
        if is_img:
            file_data = _normalize_image_bytes(file_data)
        h = hashlib.sha256(file_data).hexdigest()
        if allow_duplicate and session_id:
            if db.hash_seen_in_session(h, session_id):
                return None
        elif db.hash_seen(h):
            return None
        rel, mime, thumb, kind = save_file(file_data, filename or "file.bin")
        msg = db.add_message(
            device_ip=device_ip, device_name=device_name, text=text,
            kind=kind, filename=filename, filepath=rel, thumb=thumb, mime=mime,
            size=len(file_data), source=source, content_hash=h, session_id=session_id,
            allow_duplicate=allow_duplicate,
        )
        if msg:
            bump_sync()
            _autosave_snapshot()
        if msg and kind == "image" and AI_AUTO and _client_ai_enabled and ai_engine and auto_analyze and source in ("chat", "drop"):
            queue_analysis(msg["id"], session_id=session_id)
        if msg and auto_clipboard:
            copied = copy_message_to_clipboard(msg)
            if copied:
                print(f"[clip] auto-copied {copied} from {device_name} to Windows clipboard")
        return msg
    if text.strip():
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if source == "clipboard" and db.hash_seen(h):
            return None
        msg = db.add_message(
            device_ip=device_ip, device_name=device_name, text=text, kind="text",
            source=source, content_hash=h, session_id=session_id,
        )
        if msg:
            bump_sync()
            _autosave_snapshot()
        return msg
    raise ValueError("empty message")


def _autosave_snapshot() -> None:
    """Silent autosave after each message — Windows safe path beside app data."""
    try:
        dest = DATA_DIR / "autosave"
        dest.mkdir(parents=True, exist_ok=True)
        md = db.build_day_summary_markdown()
        (dest / "latest.md").write_text(md, encoding="utf-8")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (dest / f"snapshot_{ts}.md").write_text(md, encoding="utf-8")
        # Keep last 20 snapshots
        snaps = sorted(dest.glob("snapshot_*.md"), reverse=True)
        for old in snaps[20:]:
            old.unlink(missing_ok=True)
    except Exception:
        pass


WAITLIST_FILE = DATA_DIR / "waitlist.json"


def _add_waitlist(email: str, reason: str, tier: str = "pro") -> dict:
    entries: list = []
    if WAITLIST_FILE.is_file():
        try:
            entries = json.loads(WAITLIST_FILE.read_text(encoding="utf-8"))
        except Exception:
            entries = []
    email = (email or "").strip()[:120]
    if not email or "@" not in email:
        return {"ok": False, "error": "Valid email required"}
    if any(e.get("email") == email for e in entries):
        return {"ok": True, "message": "Already on waitlist"}
    entries.append({
        "email": email, "reason": (reason or "")[:500], "tier": tier,
        "ts": time.time(),
    })
    WAITLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    WAITLIST_FILE.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    if app_audit:
        app_audit.log("waitlist", detail=f"{email}: {reason[:80]}")
    if email_resend:
        sent = email_resend.send_waitlist(email, reason)
        if sent.get("ok"):
            return {"ok": True, "message": sent.get("message", "Added to waitlist")}
        return {"ok": True, "message": f"Saved locally ({sent.get('error', 'email pending')})"}
    return {"ok": True, "message": "Added to waitlist — we'll email you at launch"}


def _export_package() -> bytes:
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        data_dir = DATA_DIR
        if data_dir.is_dir():
            for p in data_dir.rglob("*"):
                if p.is_file():
                    zf.write(p, Path("data") / p.relative_to(data_dir))
        env = ROOT / "env.local"
        if env.is_file():
            zf.write(env, "env.local")
    return buf.getvalue()


def read_clipboard():
    try:
        import win32clipboard
        import win32con
        from PIL import Image
    except ImportError:
        return "", None, None
    try:
        win32clipboard.OpenClipboard(None)
    except Exception:
        return "", None, None
    try:
        for fmt_name in ("PNG", "JFIF"):
            fmt = win32clipboard.RegisterClipboardFormat(fmt_name)
            if win32clipboard.IsClipboardFormatAvailable(fmt):
                raw = win32clipboard.GetClipboardData(fmt)
                if raw and len(raw) > 80:
                    return "image", bytes(raw), None
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB):
            dib = win32clipboard.GetClipboardData(win32clipboard.CF_DIB)
            _, _, _, _, _, off = struct.unpack("<LLLLLL", dib[:24])
            bmp = b"BM" + struct.pack("<I", len(dib) + 14) + b"\0\0\0\0" + struct.pack("<I", 14 + off) + dib
            img = Image.open(io.BytesIO(bmp))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="PNG")
            return "image", buf.getvalue(), None
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            t = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            if t and str(t).strip():
                return "text", None, str(t)
    except Exception:
        pass
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass
    return "", None, None


def suppress_clipboard_watch(seconds: float = 2.5) -> None:
    global _suppress_clipboard_until
    _suppress_clipboard_until = time.time() + seconds


def write_clipboard_text(text: str) -> bool:
    global _last_text_hash
    try:
        import win32clipboard
        import win32con
        suppress_clipboard_watch()
        win32clipboard.OpenClipboard(None)
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        win32clipboard.CloseClipboard()
        _last_text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return True
    except Exception as e:
        print(f"[clipboard] write text: {e}")
        return False


def write_clipboard_image(data: bytes) -> bool:
    global _last_img_hash
    try:
        import win32clipboard
        from PIL import Image
        if not data:
            return False
        data = _normalize_image_bytes(data)
        im = Image.open(io.BytesIO(data))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "BMP")
        dib = buf.getvalue()[14:]
        buf.close()
        suppress_clipboard_watch()
        win32clipboard.OpenClipboard(None)
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
        win32clipboard.CloseClipboard()
        _last_img_hash = hashlib.sha256(data).hexdigest()
        return True
    except Exception as e:
        print(f"[clipboard] write image: {e}")
        return False


def copy_message_to_clipboard(msg: dict | None) -> str:
    if not msg:
        return ""
    if msg.get("kind") == "text" and msg.get("text"):
        return "text" if write_clipboard_text(msg["text"]) else ""
    if msg.get("kind") == "image":
        p = _image_file_path(msg)
        if p:
            return "image" if write_clipboard_image(p.read_bytes()) else ""
    if msg.get("text"):
        return "text" if write_clipboard_text(msg["text"]) else ""
    return ""


def clipboard_loop():
    global _last_img_hash, _last_text_hash
    while True:
        try:
            if time.time() < _suppress_clipboard_until:
                time.sleep(0.25)
                continue
            kind, img, text = read_clipboard()
            if kind == "image" and img:
                img = _normalize_image_bytes(img)
                h = hashlib.sha256(img).hexdigest()
                if h == _last_img_hash or db.hash_seen(h):
                    _last_img_hash = h
                else:
                    as_shot = bool(
                        _client_ai_enabled and AI_AUTO and ai_engine and _looks_like_screenshot(img)
                    )
                    _last_img_hash = h
                    if as_shot:
                        r = post_capture_image(
                            "127.0.0.1", hostname(), img,
                            f"snip_{datetime.now():%H%M%S}.png", "screenshot",
                            with_ai=True,
                        )
                        if r:
                            print("[clip] clipboard snip → AI Screenshot Chat")
                    else:
                        r = post_capture_image(
                            "127.0.0.1", hostname(), img,
                            f"clipboard_{datetime.now():%H%M%S}.png", "clipboard",
                            with_ai=False,  # plain clipboard image → daily Images chat
                        )
                        if r:
                            print("[clip] new clipboard image → daily image chat")
            elif kind == "text" and text:
                h = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if h == _last_text_hash or db.hash_seen(h):
                    pass
                else:
                    _last_text_hash = h
                    daily = db.get_or_create_daily_text_session()
                    r = post_message(
                        "127.0.0.1", hostname(), text=text, source="clipboard",
                        session_id=daily["id"],
                    )
                    if r:
                        print("[clip] new clipboard text → daily text chat")
        except Exception as e:
            print(f"[clipboard] {e}")
        time.sleep(CLIPBOARD_POLL)


def screenshot_loop():
    global _last_img_hash
    while True:
        try:
            now = time.time()
            for folder in SCREENSHOT_DIRS:
                if not folder.is_dir():
                    continue
                for f in list(folder.glob("*.png")) + list(folder.glob("*.jpg")):
                    mtime = f.stat().st_mtime
                    if now - mtime > 120:
                        continue
                    key = str(f)
                    if _seen_ss.get(key) == mtime:
                        continue
                    # Normalize before post so clipboard/screenshot share the same bytes / hash
                    try:
                        data = _normalize_image_bytes(f.read_bytes())
                    except OSError:
                        continue  # file still writing — retry next poll
                    h = hashlib.sha256(data).hexdigest()
                    _seen_ss[key] = mtime
                    if h == _last_img_hash or db.hash_seen(h):
                        _last_img_hash = h
                        continue
                    r = post_capture_image("127.0.0.1", hostname(), data, f.name, "screenshot")
                    if r:
                        _last_img_hash = h
                        suppress_clipboard_watch(3.0)
                        print(f"[clip] screenshot → AI Screenshot Chat: {f.name}")
                    else:
                        _last_img_hash = h
                        print(f"[clip] screenshot skipped (hash already published): {f.name}")
        except Exception as e:
            print(f"[screenshot] {e}")
        time.sleep(2)


def _parse_multipart(body: bytes, ctype: str) -> dict:
    m = re.search(r"boundary=(.+)", ctype)
    if not m:
        return {}
    b = m.group(1).strip().encode().strip(b'"')
    out = {}
    for part in body.split(b"--" + b):
        if not part or part in (b"--\r\n", b"--"):
            continue
        chunk = part[2:] if part.startswith(b"\r\n") else part
        sep = chunk.find(b"\r\n\r\n")
        if sep < 0:
            continue
        hdr = chunk[:sep].decode("utf-8", errors="replace")
        data = chunk[sep + 4:]
        if data.endswith(b"\r\n"):
            data = data[:-2]
        nm = re.search(r'name="([^"]+)"', hdr)
        fm = re.search(r'filename="([^"]*)"', hdr)
        if not nm:
            continue
        field = nm.group(1)
        if fm is not None or "filename=" in hdr.lower():
            fname = fm.group(1) if fm else ""
            if not fname:
                ct_m = re.search(r"Content-Type:\s*([^\r\n;]+)", hdr, re.I)
                mime = (ct_m.group(1).strip() if ct_m else "") or "application/octet-stream"
                ext = mimetypes.guess_extension(mime) or ".bin"
                if ext == ".jpe":
                    ext = ".jpg"
                fname = f"upload{ext}"
            out[field] = {"filename": fname, "data": data}
        else:
            out[field] = data.decode("utf-8", errors="replace")
    return out


_FIREWALL_RULE_NAMES = (
    "AirGPT LAN Inbound 8765",
    "ClipDrop LAN Port 8765",
    "ClipDrop 8765",
)


def firewall_rule_exists() -> bool:
    try:
        for name in _FIREWALL_RULE_NAMES:
            r = subprocess.run(
                ["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
                capture_output=True, text=True, timeout=6,
            )
            if r.returncode == 0 and "8765" in (r.stdout or ""):
                return True
    except Exception:
        pass
    return False


def try_private_network() -> bool:
    """Set active WiFi/Ethernet to Private so Windows allows LAN inbound."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "$p = Get-NetConnectionProfile | Where-Object {"
             " $_.IPv4Connectivity -eq 'Internet' -or $_.IPv4Connectivity -eq 'LocalNetwork' }; "
             "foreach ($n in $p) { if ($n.NetworkCategory -ne 'Private') { "
             " Set-NetConnectionProfile -InterfaceIndex $n.InterfaceIndex -NetworkCategory Private } }"],
            capture_output=True, text=True, timeout=12,
        )
        return r.returncode == 0
    except Exception:
        return False


def try_firewall() -> str:
    if firewall_rule_exists():
        try_private_network()
        return "ok"
    rules = [
        ("AirGPT LAN Inbound 8765", "in"),
        ("AirGPT LAN Outbound 8765", "out"),
        ("ClipDrop LAN Port 8765", "in"),
        ("ClipDrop 8765", "in"),
    ]
    added = 0
    try:
        for name, direction in rules:
            r = subprocess.run(
                ["netsh", "advfirewall", "firewall", "add", "rule", f"name={name}",
                 f"dir={direction}", "action=allow", "protocol=TCP", f"localport={PORT}",
                 "profile=private,public,domain"],
                capture_output=True, text=True, timeout=8,
            )
            if r.returncode == 0:
                added += 1
        if added or firewall_rule_exists():
            try_private_network()
            return "ok"
        return "run allow_firewall.ps1 as Admin"
    except Exception as e:
        return str(e)[:60]


def refresh_firewall_status() -> str:
    global _firewall_status
    if firewall_rule_exists():
        _firewall_status = "ok"
    return _firewall_status


_cortex_info_cache: dict = {"ts": 0.0, "quick": None, "full": None}


def _cortex_info(*, quick: bool = False) -> dict:
    now = time.time()
    key = "quick" if quick else "full"
    cached = _cortex_info_cache.get(key)
    # Standby/timeout results cache longer so a dead Cortex doesn't tax every poll
    ttl = 8.0 if quick else 15.0
    if cached and now - float(_cortex_info_cache["ts"]) < ttl:
        return dict(cached)
    try:
        import cortex_client
        info = dict(cortex_client.health() or {})
        if not quick:
            try:
                info["audit_sample"] = cortex_client.audit_tail(8)
            except Exception:
                info.setdefault("audit_sample", [])
            try:
                info["ledger_verify"] = cortex_client.verify_ledger()
            except Exception:
                info.setdefault("ledger_verify", {"ok": False})
        else:
            info.setdefault("audit_sample", [])
            info.setdefault("ledger_verify", {"ok": False})
        if info.get("ok") and not info.get("status"):
            info["status"] = "live"
        # If Cortex is offline, don't re-probe every 3–12s — stretch TTL via longer cache
        if not info.get("ok"):
            ttl = 30.0
        _cortex_info_cache["ts"] = now
        _cortex_info_cache[key] = dict(info)
        return info
    except Exception:
        info = {"ok": False, "status": "unavailable", "audit_sample": [], "ledger_verify": {"ok": False}}
        _cortex_info_cache["ts"] = now
        _cortex_info_cache[key] = dict(info)
        return info


def _probe_tunnel_url(url: str, attempts: int = 24, delay: float = 2.0) -> bool:
    import urllib.request
    for _ in range(attempts):
        try:
            req = urllib.request.Request(f"{url.rstrip('/')}/api/probe", headers={"Cache-Control": "no-store"})
            with urllib.request.urlopen(req, timeout=6) as r:
                data = json.loads(r.read())
            if data.get("ok") is True:
                return True
        except Exception:
            time.sleep(delay)
    return False


def _tunnel_provider_label() -> str:
    p = str(_tunnel.get("provider") or "").strip()
    if p:
        return p
    url = str(_tunnel.get("url") or "")
    if "trycloudflare.com" in url:
        return "cloudflared"
    if "loca.lt" in url:
        return "localtunnel"
    if "lhr.life" in url or "localhost.run" in url:
        return "localhost.run"
    if "serveo.net" in url:
        return "serveo.net"
    return ""


def _set_tunnel(url: str, provider: str) -> bool:
    if not _probe_tunnel_url(url):
        _tunnel.update(url="", provider="", status=f"{provider} unreachable", error=f"{url} did not pass /api/probe", healthy=False)
        bump_sync()
        print(f"[tunnel] rejected {provider}: {url} did not pass /api/probe")
        return False
    _tunnel.update(url=url, provider=provider, status="ready", error="", healthy=True, started_at=time.time())
    _qr_join_cache.clear()
    bump_sync()
    print(f"[tunnel] ready → UI sync: {url}")
    return True


def tunnel_health_loop():
    global _health_fails
    import urllib.request
    while True:
        url = _tunnel.get("url")
        healthy = False
        if url:
            try:
                req = urllib.request.Request(f"{url}/api/probe", headers={"Cache-Control": "no-store"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    healthy = json.loads(r.read()).get("ok") is True
            except Exception:
                healthy = False
        _tunnel["healthy"] = healthy
        if url and not healthy:
            _health_fails += 1
            if _tunnel.get("status") == "ready":
                _tunnel["status"] = "degraded"
            if _health_fails >= 3:
                print("[tunnel] unhealthy — auto-restarting tunnel")
                _health_fails = 0
                restart_tunnel()
        elif url and healthy:
            _health_fails = 0
            _tunnel["status"] = "ready"
        time.sleep(15)


def _read_tunnel_url(proc: subprocess.Popen, patterns: list[str], timeout_lines: int = 120) -> str | None:
    _register_tunnel_proc(proc)
    lines: queue.Queue[str] = queue.Queue()

    def _reader() -> None:
        try:
            if proc.stdout:
                for line in proc.stdout:
                    lines.put(line)
        except Exception:
            pass

    threading.Thread(target=_reader, daemon=True).start()
    deadline = time.time() + max(8.0, timeout_lines * 0.4)
    while time.time() < deadline:
        try:
            line = lines.get(timeout=0.4)
        except queue.Empty:
            if proc.poll() is not None:
                return None
            continue
        for pat in patterns:
            m = re.search(pat, line)
            if m:
                return m.group(1)
    return None


def tunnel_cloudflared() -> bool:
    exe = BIN / "cloudflared.exe"
    if not exe.is_file():
        try:
            import urllib.request
            print("[tunnel] downloading cloudflared...")
            urllib.request.urlretrieve(
                "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe", exe)
        except Exception as e:
            print(f"[tunnel] cloudflared download failed: {e}")
            return False
    try:
        proc = subprocess.Popen(
            [str(exe), "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        url = _read_tunnel_url(proc, [r"(https://[a-z0-9-]+\.trycloudflare\.com)"], timeout_lines=180)
        if url:
            _qr_join_cache.clear()
            if _set_tunnel(url, "cloudflared"):
                print(f"[tunnel] cloudflared: {url}")
                return True
            _kill_tunnel_procs()
            return False
        _kill_tunnel_procs()
    except Exception as e:
        print(f"[tunnel] cloudflared: {e}")
    return False


def tunnel_localhost_run() -> bool:
    try:
        proc = subprocess.Popen(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=60",
             "-R", f"80:localhost:{PORT}", "nokey@localhost.run"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        url = _read_tunnel_url(proc, [
            r"(https://[a-zA-Z0-9.-]+\.lhr\.life)",
            r"(https://\S+\.localhost\.run)",
        ], timeout_lines=80)
        if url:
            if _set_tunnel(url, "localhost.run"):
                print(f"[tunnel] localhost.run: {url}")
                return True
            _kill_tunnel_procs()
        _kill_tunnel_procs()
    except Exception as e:
        print(f"[tunnel] localhost.run: {e}")
    return False


def tunnel_localtunnel() -> bool:
    try:
        proc = subprocess.Popen(
            ["npx", "--yes", "localtunnel", "--port", str(PORT)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        url = _read_tunnel_url(proc, [r"(https://[a-z0-9-]+\.loca\.lt)"], timeout_lines=90)
        if url:
            if _set_tunnel(url, "localtunnel"):
                print(f"[tunnel] localtunnel: {url}")
                return True
            _kill_tunnel_procs()
        _kill_tunnel_procs()
    except Exception as e:
        print(f"[tunnel] localtunnel: {e}")
    return False


def tunnel_serveo() -> bool:
    try:
        proc = subprocess.Popen(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=30",
             "-R", f"80:localhost:{PORT}", "serveo.net"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        url = _read_tunnel_url(proc, [
            r"(https://[a-z0-9-]+\.serveo\.net)",
            r"(https://\S+\.serveousercontent\.com)",
        ], timeout_lines=80)
        if url:
            if _set_tunnel(url, "serveo.net"):
                print(f"[tunnel] serveo: {url}")
                return True
            _kill_tunnel_procs()
        _kill_tunnel_procs()
    except Exception as e:
        print(f"[tunnel] serveo: {e}")
    return False


def tunnel_worker():
    global _health_fails
    _health_fails = 0
    _tunnel.update(url="", provider="", status="starting", error="", healthy=False)
    bump_sync()
    providers = [
        (tunnel_cloudflared, "cloudflared"),
        (tunnel_localhost_run, "localhost.run"),
        (tunnel_localtunnel, "localtunnel"),
        (tunnel_serveo, "serveo.net"),
    ]
    for attempt in range(2):
        for fn, name in providers:
            _tunnel.update(status=f"trying {name}" + (f" (retry {attempt + 1})" if attempt else ""))
            bump_sync()
            print(f"[tunnel] {_tunnel['status']}")
            if fn():
                return
            time.sleep(2)
    _tunnel.update(
        url="", provider="",
        status="failed", error="All tunnels failed (Cloudflare may be rate-limited). Use LAN/hotspot or press Restart Tunnel.",
        healthy=False,
    )


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ClipDrop/5"

    def log_message(self, fmt, *args):
        if args and str(args[0]).startswith("GET /api"):
            return
        print(f"[{self.client_address[0]}] {fmt % args}")

    def _request_token(self, allow_query: bool = False) -> str:
        tok = self.headers.get("X-AirGPT-Token") or ""
        if not tok:
            auth_h = self.headers.get("Authorization", "")
            if auth_h.lower().startswith("bearer "):
                tok = auth_h[7:].strip()
        if not tok and allow_query:
            tok = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        return tok

    def _client_ip(self) -> str:
        direct = self.client_address[0]
        return _forwarded_client_ip(self.headers, direct) or direct

    def _join_url(self, base_url: str, requester_ip: str) -> tuple[str, str]:
        if not base_url:
            return "", ""
        if not app_auth:
            return base_url, ""
        if not app_auth.status().get("needs_auth"):
            return base_url, ""
        key = base_url.rstrip("/")
        cached = _qr_join_cache.get(key)
        if cached and cached[2] > time.time():
            return cached[0], cached[1]
        qt = app_auth.issue_qr_token(
            self._request_token(),
            host_verified=_is_local_host(requester_ip),
        )
        if not qt:
            return base_url, ""
        join_url = key + "/?qr=" + qt
        _qr_join_cache[key] = (join_url, qt, time.time() + 540)
        return join_url, qt

    def _auth_ok(self, path: str) -> bool:
        if path in ("/", "/index.html", "/admin", "/admin.html", "/wasm_gate.js", "/manifest.json", "/api/probe", "/api/health", "/healthz", "/health", "/api/auth/status", "/api/netie/account") or path.startswith("/api/qr") or path.startswith("/OpenIDE/ui/"):
            return True
        if path.startswith("/api/auth/") or path.startswith("/api/netie/"):
            return True
        direct = self.client_address[0]
        if _is_local_host(direct) and not _forwarded_client_ip(self.headers, direct):
            return True
        ip = self._client_ip()
        if not app_auth:
            return True
        st = app_auth.status()
        if not st.get("needs_auth"):
            return True
        # Rate-limit brute force from LAN/WiFi attackers
        now = time.time()
        fails = _auth_fails.get(ip, [])
        fails = [t for t in fails if now - t < 300]
        _auth_fails[ip] = fails
        if len(fails) >= 20:
            if app_audit:
                app_audit.log("auth_blocked", ip=ip, detail=path, ok=False)
            return False
        tok = self._request_token(allow_query=path.startswith("/data/"))
        ok = app_auth.verify_token(tok)
        if not ok:
            _auth_fails[ip].append(now)
            if app_audit:
                app_audit.log("auth_fail", ip=ip, detail=path, ok=False)
            if email_resend and len(_auth_fails[ip]) == 10:
                email_resend.send_security_alert(
                    f"10 failed auth from {ip}",
                    f"Path: {path}\nTime: {datetime.now().isoformat()}\nPossible WiFi/port attack.",
                )
        return ok

    def _passcode_rate_limited(self, ip: str) -> bool:
        """Throttle passcode/join-code guessing. Local host is exempt.

        Reuses the _auth_fails window so credential-guessing across token and
        passcode surfaces is counted together. Returns True when blocked.
        """
        if _is_local_host(ip):
            return False
        now = time.time()
        fails = [t for t in _auth_fails.get(ip, []) if now - t < 300]
        _auth_fails[ip] = fails
        return len(fails) >= 20

    def _note_passcode_fail(self, ip: str) -> None:
        if _is_local_host(ip):
            return
        _auth_fails.setdefault(ip, []).append(time.time())

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-AirGPT-Token, Authorization")

    def _send(self, code, body: bytes, ctype):
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return

    def _json(self, code, data):
        self._send(code, json.dumps(data).encode(), "application/json; charset=utf-8")

    def _sse_begin(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Transfer-Encoding", "chunked")
        self._cors()
        self.end_headers()

    def _sse_write_raw(self, data: bytes) -> bool:
        """Write one HTTP/1.1 chunk (required so clients don't block waiting for Content-Length)."""
        try:
            self.wfile.write(f"{len(data):X}\r\n".encode("ascii") + data + b"\r\n")
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return False

    def _sse_send(self, event: dict) -> bool:
        try:
            payload = json.dumps(event, ensure_ascii=False)
            return self._sse_write_raw(f"data: {payload}\n\n".encode("utf-8"))
        except Exception:
            return False

    def _sse_end(self) -> None:
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except Exception:
            pass

    def _handle_chat_stream(self, ip: str, dname: str) -> None:
        if not ai_engine:
            return self._json(503, {"error": "ai_engine not installed"})
        rate_err = _check_ai_rate()
        if rate_err:
            return self._json(429, {"error": rate_err})
        try:
            data = json.loads(self._body().decode() or "{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid json"})

        text = str(data.get("text", "")).strip()
        if not text:
            return self._json(400, {"error": "text required"})

        mode = str(data.get("mode", "general"))
        session_id = int(data.get("session_id", 0) or 0)
        parent_session_id = int(data.get("parent_session_id", 0) or 0)
        reply_to_id = int(data.get("reply_to_id", 0) or 0)
        reply_snippet = str(data.get("reply_snippet", ""))[:500]
        context_ids = data.get("context_ids") or []
        model_tier = str(data.get("model_tier", "high") or "high").strip().lower()
        if model_tier not in ("basic", "high", "max"):
            model_tier = "high"
        thinking_flag = data.get("thinking", True)
        if isinstance(thinking_flag, str):
            thinking_flag = thinking_flag.lower() not in ("0", "false", "no", "off")
        thinking_flag = bool(thinking_flag) and model_tier != "basic"

        if reply_to_id and not reply_snippet:
            rm = db.get_message(reply_to_id)
            if rm:
                reply_snippet = (rm.get("text") or rm.get("ai_analysis") or "")[:500]

        parent_id = parent_session_id or session_id
        if reply_to_id or reply_snippet:
            title = text[:60] or "Reply"
            cat = db.MODE_TO_CATEGORY.get(mode, "general")
            sess = db.create_reply_session(parent_id, title, reply_snippet, category=cat)
            session_id = sess["id"]
        elif not session_id:
            scratch_sid = _route_new_chat(text)
            if scratch_sid:
                session_id = scratch_sid  # small-talk → shared Scratch space
            else:
                cat = db.MODE_TO_CATEGORY.get(mode, "general")
                sess = db.create_session("New chat", capture_type="ai", category=cat)
                session_id = sess["id"]

        db.maybe_set_ai_session_title(session_id, text[:60])
        user_msg = db.add_message(device_ip=ip, device_name=dname, text=text, source="ai-chat", session_id=session_id)
        bump_sync()

        exclude_id = int(user_msg["id"]) if user_msg else 0
        history = _build_chat_history(session_id, context_ids, reply_snippet, exclude_msg_id=exclude_id)

        abort = threading.Event()
        event_q: queue.Queue = queue.Queue()
        done_ev: dict = {"analysis": "", "model": "", "error": ""}

        def _producer() -> None:
            try:
                for ev in _chat_stream_events(
                    text, mode, history, abort,
                    session_id=session_id,
                    model_tier=model_tier,
                    thinking=thinking_flag,
                ):
                    if abort.is_set():
                        break
                    event_q.put(ev)
                    if ev.get("type") == "done":
                        done_ev["analysis"] = ev.get("analysis", "")
                        done_ev["model"] = ev.get("model", "")
                    elif ev.get("type") == "error":
                        done_ev["error"] = ev.get("text", "") or ev.get("error", "")
                        break
            except Exception as e:
                err = str(e)[:400]
                done_ev["error"] = err
                try:
                    event_q.put({"type": "error", "text": err, "session_id": session_id})
                except Exception:
                    pass
            finally:
                # Always close the stream so clients never hang waiting for done
                if not done_ev["error"] and not done_ev["analysis"]:
                    try:
                        event_q.put({
                            "type": "error",
                            "text": "Model returned no text — check API keys / connection",
                            "session_id": session_id,
                        })
                    except Exception:
                        pass
                event_q.put(None)

        threading.Thread(target=_producer, daemon=True).start()
        self._sse_begin()
        # Immediate ack so UI can adopt session before model tokens arrive
        self._sse_send({"type": "thinking", "text": "Connected - generating...", "session_id": session_id})

        idle_ticks = 0
        while True:
            try:
                ev = event_q.get(timeout=0.25)
            except queue.Empty:
                idle_ticks += 1
                # Keepalive every ~2s so proxies/clients don't drop the stream
                if idle_ticks % 8 == 0:
                    if not self._sse_write_raw(b": keepalive\n\n"):
                        abort.set()
                        break
                continue
            idle_ticks = 0
            if ev is None:
                break
            if isinstance(ev, dict):
                ev = {**ev, "session_id": session_id}
            if not self._sse_send(ev):
                abort.set()
                break

        if not abort.is_set() and done_ev["analysis"] and not done_ev["error"]:
            db.add_message(
                device_ip="127.0.0.1",
                device_name="AirGPT",
                text=done_ev["analysis"],
                kind="text",
                source="ai",
                session_id=session_id,
            )
            db.maybe_set_ai_session_title(
                session_id,
                _title_from_ai_text(done_ev["analysis"], fallback=text[:60]),
                summary=done_ev["analysis"][:280].replace("\n", " "),
            )
            bump_sync()
        elif done_ev.get("error"):
            self._sse_send({"type": "error", "error": done_ev["error"], "session_id": session_id})
        self._sse_end()

    def _handle_rag_answer_stream(self) -> None:
        """SSE variant of /api/rag/answers: thinking → meta → citations → delta* → done.

        Host-only + auth are enforced by the do_POST gate before dispatch.
        When use_llm=True, deltas come from ai_engine provider streaming
        (grounded prompt, no vault mix-in). Otherwise extractive text is chunked.
        Persistence is once at the end (answer_events does not write chats).
        """
        try:
            data = json.loads(self._body().decode() or "{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid json"})
        sid = int(data.get("space_id") or 0)
        q = str(data.get("query") or data.get("q") or "").strip()
        if not sid or not q:
            return self._json(400, {"error": "space_id and query required"})
        depth = str(data.get("depth") or "high").lower()
        if depth not in ("basic", "high", "max", "manual"):
            depth = "high"
        chat_id = int(data.get("chat_id") or 0)
        use_llm = True if "use_llm" not in data else bool(data.get("use_llm"))
        try:
            from rag import answer as rag_answer
            from rag import store as rag_store
        except Exception as e:
            return self._json(503, {"error": str(e)[:200]})

        if not chat_id and data.get("new_chat"):
            try:
                chat_id = int(rag_store.create_chat(sid, (q[:60] or "New chat"))["id"])
            except Exception:
                chat_id = 0

        self._sse_begin()
        text = ""
        citations: list = []
        done: dict = {}
        try:
            for ev in rag_answer.answer_events(sid, q, depth=depth, use_llm=use_llm):
                t = ev.get("type")
                if t == "thinking":
                    if not self._sse_send({"type": "thinking", "text": ev.get("text") or "", "space_id": sid, "chat_id": chat_id}):
                        break
                elif t == "meta":
                    payload = {
                        "type": "meta",
                        "depth": ev.get("depth"),
                        "template_id": ev.get("template_id"),
                        "trace_id": ev.get("trace_id"),
                        "space_id": sid,
                        "chat_id": chat_id,
                        "confidence": ev.get("confidence"),
                    }
                    if not self._sse_send(payload):
                        break
                elif t == "citations":
                    citations = ev.get("citations") or []
                    if not self._sse_send({"type": "citations", "citations": citations}):
                        break
                elif t == "delta":
                    piece = ev.get("text") or ""
                    text += piece
                    if not self._sse_send({"type": "delta", "text": piece}):
                        break
                elif t == "error":
                    self._sse_send({"type": "error", "error": str(ev.get("error") or "answer failed")})
                    return self._sse_end()
                elif t == "done":
                    done = ev
                    text = str(ev.get("answer") or text)
                    citations = ev.get("citations") or citations
        except Exception as e:
            self._sse_send({"type": "error", "error": str(e)[:400]})
            return self._sse_end()

        if chat_id:
            try:
                rag_store.add_message(chat_id, "user", q, depth=depth, trace_id=done.get("trace_id") or "")
                rag_store.add_message(
                    chat_id, "assistant", text,
                    citations=citations,
                    depth=depth, trace_id=done.get("trace_id") or "",
                )
            except Exception:
                pass

        self._sse_send({
            "type": "done",
            "answer": text,
            "trace_id": done.get("trace_id"),
            "confidence": done.get("confidence"),
            "stop_reason": done.get("stop_reason"),
            "rounds": done.get("rounds"),
            "coverage": done.get("coverage"),
            "model": done.get("model"),
            "chat_id": chat_id,
        })
        self._sse_end()

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n) if n else b""

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET,HEAD,POST,DELETE,PATCH,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-AirGPT-Token, Authorization")
        self.end_headers()

    def do_HEAD(self):
        """Fast HEAD for probes — never 501, never hang on full GET."""
        path = urlparse(self.path).path
        # Cheap probe/health paths — fixed tiny response
        if path in ("/api/probe", "/api/health", "/healthz", "/health", "/", "/index.html", "/manifest.json", "/api/auth/status"):
            if path in ("/", "/index.html"):
                try:
                    length = (ROOT / "index.html").stat().st_size
                except OSError:
                    length = 0
                ctype = "text/html; charset=utf-8"
            elif path == "/manifest.json":
                mf = ROOT / "manifest.json"
                length = mf.stat().st_size if mf.is_file() else 0
                ctype = "application/manifest+json; charset=utf-8"
            else:
                payload = json.dumps({"ok": True, "service": "airgpt", "version": APP_VERSION}).encode()
                length = len(payload)
                ctype = "application/json; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            return
        # Everything else: headers only via muted body after end_headers
        real_wfile = self.wfile
        real_end = self.end_headers

        def _end_headers_then_discard_body():
            real_end()

            class _Discard:
                def write(self, b):
                    try:
                        return len(b) if b is not None else 0
                    except Exception:
                        return 0

                def flush(self):
                    return None

            self.wfile = _Discard()  # type: ignore[assignment]

        self.end_headers = _end_headers_then_discard_body  # type: ignore[method-assign]
        try:
            self.do_GET()
        finally:
            self.end_headers = real_end  # type: ignore[method-assign]
            self.wfile = real_wfile

    def do_GET(self):
        ip = self._client_ip()
        ua = self.headers.get("User-Agent", "")
        path = urlparse(self.path).path
        if not self._auth_ok(path):
            return self._json(401, {"error": "auth required", "auth": True})
        if _is_host_only_path(path) and not _is_local_host(ip):
            return self._json(403, {"error": "host only"})
        name = device_name_from_ua(ua, ip)
        # Skip SQLite write storm on hot poll + static paths
        if path not in ("/api/wait", "/api/probe", "/api/health", "/healthz", "/health", "/wasm_gate.js", "/manifest.json") and not path.startswith("/OpenIDE/ui/"):
            db.register_device(ip, name, ua)
        q = parse_qs(urlparse(self.path).query)

        if path in ("/api/health", "/healthz", "/health"):
            return self._json(200, {"ok": True, "service": "airgpt", "version": APP_VERSION})

        if path in ("/", "/index.html"):
            body = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("ETag", f'"v{APP_VERSION}-{int(time.time())//3600}"')
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        if path in ("/admin", "/admin.html"):
            body = (ROOT / "admin.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/wasm_gate.js":
            gate = ROOT / "wasm_gate.js"
            if not gate.is_file():
                return self._json(404, {"error": "not found"})
            body = gate.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        # OpenIDE package static assets (CSS/JS under OpenIDE/ui/)
        if path.startswith("/OpenIDE/ui/") and ".." not in path:
            rel = path.lstrip("/")
            asset = (ROOT / rel).resolve()
            try:
                asset.relative_to((ROOT / "OpenIDE" / "ui").resolve())
            except (ValueError, OSError):
                return self._json(400, {"error": "bad path"})
            if not asset.is_file():
                return self._json(404, {"error": "not found"})
            body = asset.read_bytes()
            mime = mimetypes.guess_type(str(asset))[0] or "application/octet-stream"
            if asset.suffix == ".js":
                mime = "application/javascript; charset=utf-8"
            elif asset.suffix == ".css":
                mime = "text/css; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=60")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/manifest.json":
            mf = ROOT / "manifest.json"
            if not mf.is_file():
                return self._json(404, {"error": "not found"})
            body = mf.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/manifest+json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        if path in ("/p2p", "/p2p-drop.html"):
            p2p = ROOT / "p2p-drop.html"
            if not p2p.is_file():
                return self._json(404, {"error": "not found"})
            body = p2p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/admin/overview":
            if not admin_dashboard:
                return self._json(503, {"error": "admin unavailable"})
            return self._json(200, admin_dashboard.overview(include_files=True))

        if path.startswith("/api/admin/worker/"):
            if not admin_dashboard:
                return self._json(503, {"error": "admin unavailable"})
            wid = path.split("/")[-1]
            w = admin_dashboard.worker_detail(wid)
            if not w:
                return self._json(404, {"error": "not found"})
            return self._json(200, w)

        if path == "/api/probe":
            host = self.headers.get("Host", "")
            via = "tunnel" if any(x in host for x in (
                "trycloudflare.com", "lhr.life", "loca.lt", "serveo.net", "localhost.run",
            )) else ("local" if host.startswith("127.") or host.startswith("localhost") else "lan")
            return self._json(200, {
                "ok": True, "ts": int(time.time()), "via": via,
                "tunnel_healthy": _tunnel.get("healthy", False),
            })

        if path == "/api/info":
            ips = local_ips()
            lan = lan_diagnostics()
            lic = app_license.get_status() if app_license else {"can_use_tunnel": True, "can_use_ai": True}
            tunnel_allowed = lic.get("can_use_tunnel", True)
            tunnel_url = (_tunnel.get("url") or None) if tunnel_allowed else None
            tunnel_status = _tunnel.get("status") if tunnel_allowed else "paywall"
            recommended = tunnel_url or lan["lan_url"]
            join_base = tunnel_url or (lan["lan_url"] if tunnel_allowed else None)
            join_url, qr_tok = self._join_url(join_base or "", ip)
            methods = []
            if wifi_access:
                methods = wifi_access.connect_methods(
                    lan_url=lan["lan_url"],
                    tunnel_url=tunnel_url,
                    tunnel_healthy=_tunnel.get("healthy", False),
                    firewall=lan["firewall"],
                    network_profile_name=lan["network_profile"],
                    lan_blocked=lan["lan_likely_blocked"],
                )
            mdns_u = wifi_access.mdns_url() if wifi_access else None
            return self._json(200, {
                "port": PORT, "hostname": hostname(), "ips": ips,
                "app_name": APP_NAME,
                "app_version": APP_VERSION,
                "local_url": f"http://127.0.0.1:{PORT}",
                "lan_url": lan["lan_url"],
                "wifi_url": lan["lan_url"],
                "mdns_url": mdns_u,
                "tunnel_url": tunnel_url,
                "tunnel_healthy": _tunnel.get("healthy", False),
                "recommended_url": recommended,
                "join_url": join_url,
                "qr_token": qr_tok,
                "tunnel_status": _tunnel.get("status"),
                "tunnel_provider": _tunnel_provider_label(),
                "tunnel_error": _tunnel.get("error"),
                "tunnel_uptime_s": int(time.time() - _tunnel["started_at"]) if _tunnel.get("started_at") else 0,
                "devices": db.list_devices(),
                "firewall": _firewall_status,
                "network_profile": lan["network_profile"],
                "lan_hint": lan["hint"],
                "lan_likely_blocked": lan["lan_likely_blocked"],
                "wifi_adapter_up": wifi_access.wifi_adapter_up() if wifi_access else True,
                "bluetooth_present": wifi_access.bluetooth_present() if wifi_access else False,
                "connect_methods": methods,
                "recommended_connect": (
                    (mdns_u if lan["firewall"] == "ok" and not lan["lan_likely_blocked"] and mdns_u else None)
                    or lan["lan_url"]
                    or tunnel_url
                ),
                "latest_id": db.latest_id(),
                "latest_capture_session": _latest_capture_session,
                "server_mode": _server_mode,
                "license": lic,
                "paywall": lic.get("paywall_message", ""),
                "online": _is_online(),
                "ai_rate_limit_sec": AI_RATE_LIMIT_SEC,
                "has_ai_keys": bool(
                    app_settings.get_public_settings().get("has_any_key")
                    if app_settings
                    else False
                ),
                "network_epoch": _network_epoch,
                "input_notes": input_notes.status() if input_notes else {"recording": False},
                "sku": lic.get("sku", "personal"),
                "business_features": bool(lic.get("business_features")),
                "demo_mock": bool(DEMO_MOCK),
                "data_dir": str(DATA_DIR),
                "cortex": _cortex_info(quick=True),
                "online_personal_stub": "NEXT UPDATE: hosted AI + pay-to-continue",
            })

        if path == "/api/input-notes":
            if not input_notes:
                return self._json(503, {"error": "input notes unavailable"})
            name = q.get("file", [""])[0]
            if name:
                body = input_notes.read_note(name)
                if body is None:
                    return self._json(404, {"error": "not found"})
                return self._json(200, {"ok": True, "content": body})
            return self._json(200, {"ok": True, "status": input_notes.status(), "files": input_notes.list_notes()})

        if path == "/api/qr.png":
            url = unquote(q.get("u", [""])[0])
            if not url or len(url) > 2048:
                return self._json(400, {"error": "bad url"})
            try:
                return self._send(200, make_qr_png(url), "image/png")
            except Exception as e:
                return self._json(500, {"error": str(e)})

        if path == "/api/wait":
            since = int(q.get("since", ["0"])[0])
            hist_since = int(q.get("hist_since", ["0"])[0])
            sid_raw = q.get("session_id", [None])[0]
            sid = int(sid_raw) if sid_raw not in (None, "", "0") else None
            # Non-blocking poll — long-wait starved SSE/chat threads under browser spam
            new_chat = db.get_messages(since_id=since, limit=80, session_id=sid) if since else []
            new_hist = db.get_messages(since_id=hist_since, limit=40) if hist_since else []
            # Cheap poll: reuse cached LAN URL / tunnel only — no PowerShell/netsh every tick
            cached = _lan_diag_cache.get("value") or {}
            lan_url = cached.get("lan_url")
            t_url = _tunnel.get("url") if _tunnel_allowed() else None
            j_url = t_url or (lan_url if _tunnel_allowed() else None) or ""
            j_url, qr_tok = self._join_url(j_url, ip) if j_url else ("", "")
            return self._json(200, {
                "sync_version": _sync_version,
                "latest_id": db.latest_id(),
                "new_chat": new_chat,
                "new_hist": new_hist,
                "tunnel_url": t_url,
                "tunnel_healthy": _tunnel.get("healthy", False),
                "tunnel_status": _tunnel.get("status"),
                "tunnel_provider": _tunnel_provider_label(),
                "lan_url": lan_url,
                "join_url": j_url,
                "qr_token": qr_tok,
                "network_epoch": _network_epoch,
            })

        if path == "/api/history":
            since = int(q.get("since", ["0"])[0])
            if since:
                msgs = db.get_messages(since_id=since, limit=200)
                return self._json(200, {"messages": msgs, "latest_id": db.latest_id(), "incremental": True})
            return self._json(200, db.messages_grouped(since_id=0, limit=500))

        if path == "/api/auth/status":
            if app_auth:
                return self._json(200, app_auth.status())
            return self._json(200, {"initialized": False, "needs_auth": False})

        if path == "/api/audit":
            if app_audit:
                return self._json(200, {"events": app_audit.recent(200)})
            return self._json(200, {"events": []})

        if path == "/api/audit/spotcheck":
            try:
                if app_audit and hasattr(app_audit, "spotcheck"):
                    return self._json(200, app_audit.spotcheck(800))
                return self._json(200, {"ok": True, "users": [], "totals": {}})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)[:200]})

        if path == "/api/research":
            try:
                import research as research_lib

                research_lib.ensure()
                research_lib.seed_agents()
                return self._json(200, research_lib.list_library())
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)[:200]})

        if path == "/api/memory/thin":
            try:
                import memory_index as mi

                return self._json(200, mi.thin_memories())
            except Exception as e:
                return self._json(500, {"error": str(e)[:200]})

        if path == "/api/export":
            if q.get("package", ["0"])[0] == "1":
                body = _export_package()
                fname = f"airgpt-export-{datetime.now().strftime('%Y%m%d')}.zip"
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                self.send_header("Content-Length", str(len(body)))
                self._cors()
                self.end_headers()
                self.wfile.write(body)
                return
            md = db.build_day_summary_markdown()
            return self._json(200, {"markdown": md, "export": "history"})

        if path == "/api/online":
            return self._json(200, {"online": _is_online()})

        if path == "/api/license":
            if app_license:
                return self._json(200, app_license.get_status())
            return self._json(200, {"can_use_ai": True, "trial_active": True})

        if path == "/api/netie/account":
            if not netie_id:
                return self._json(200, {"ok": False, "error": "netie_id unavailable"})
            return self._json(200, netie_id.status())

        if path == "/api/settings":
            if app_settings:
                if q.get("keys", ["0"])[0] == "1" and _is_local_host(ip):
                    return self._json(200, {"keys": app_settings.get_secret_keys_local()})
                return self._json(200, app_settings.get_public_settings())
            return self._json(200, {"storage": "local"})

        if path == "/api/keyvault":
            # BYO-key vault: provider registry + configured status (masked, never raw)
            try:
                import key_vault
                return self._json(200, key_vault.snapshot(include_status=_is_local_host(ip)))
            except Exception as e:
                return self._json(500, {"error": f"keyvault: {e}"[:200]})

        if path == "/api/openfree/status":
            try:
                import openfree
                return self._json(200, openfree.status())
            except Exception as e:
                return self._json(500, {"ok": False, "error": f"openfree: {e}"[:200]})

        if path == "/api/ai/config":
            return self._json(200, {
                "auto": AI_AUTO and _client_ai_enabled,
                "client_ai": _client_ai_enabled,
                "available": ai_engine is not None,
                "has_keys": bool(
                    app_settings.get_public_settings().get("has_any_key")
                    if app_settings
                    else False
                ),
            })

        if path == "/api/mode":
            return self._json(200, {"mode": _server_mode})

        if path.startswith("/api/messages/") and path.endswith("/ai"):
            mid = int(path.split("/")[-2])
            msg = db.get_message(mid)
            if not msg:
                return self._json(404, {"error": "not found"})
            return self._json(200, {
                "id": mid,
                "ai_status": msg.get("ai_status", "none"),
                "ai_analysis": msg.get("ai_analysis", ""),
                "ai_model": msg.get("ai_model", ""),
            })

        if path == "/api/sessions":
            lim = min(int(q.get("limit", ["200"])[0] or 200), 500)
            return self._json(200, {"sessions": db.list_sessions(lim)})

        if path == "/api/search":
            sq = q.get("q", [""])[0]
            date_f = q.get("date", [""])[0]
            lim = min(int(q.get("limit", ["80"])[0] or 80), 200)
            return self._json(200, db.search_messages_and_sessions(sq, date_f, lim))

        if path == "/api/vault":
            return self._json(200, db.list_vault_tree())

        if path == "/api/summarize/today":
            md = db.build_day_summary_markdown()
            return self._json(200, {"markdown": md, "date": datetime.now().strftime("%Y-%m-%d")})

        if path == "/api/drops":
            return self._json(200, {"items": db.get_media_messages(), "latest_id": db.latest_id()})

        if path == "/api/messages":
            since = int(q.get("since", ["0"])[0])
            sid = q.get("session_id", [None])[0]
            session_id = int(sid) if sid not in (None, "", "all") else None
            # Scoped share guests may only read their shared session
            if app_auth and hasattr(app_auth, "token_session_acl"):
                scoped = app_auth.token_session_acl(self._request_token())
                if scoped and not _is_local_host(ip):
                    session_id = int(scoped["session_id"])
            if q.get("full", ["0"])[0] == "1":
                return self._json(200, db.messages_grouped(since_id=since, session_id=session_id))
            msgs = db.get_messages(since_id=since, session_id=session_id)
            return self._json(200, {"messages": msgs, "latest_id": db.latest_id()})

        if path.startswith("/data/"):
            rel = unquote(path[6:]).replace("/", os.sep)
            if ".." in rel:
                return self._json(400, {"error": "bad path"})
            try:
                import access_policy
                lic = app_license.get_status() if app_license else {}
                business = bool(lic.get("business_features"))
                if not access_policy.is_download_allowed(
                    ip, is_local=_is_local_host(ip), business=business,
                ):
                    access_policy.request_access(ip, device_name_from_ua(ua, ip))
                    try:
                        if app_audit:
                            app_audit.log("download_denied", ip=ip, detail=rel[:200], ok=False)
                    except Exception:
                        pass
                    return self._json(403, {
                        "error": "download blocked — wait for host IP approval",
                        "access": "pending",
                    })
            except ImportError:
                pass
            data_root = DATA_DIR.resolve()
            p = db.FILES.parent / rel
            if not p.is_file():
                p = DATA_DIR / rel
            if not p.is_file():
                return self._json(404, {"error": "missing"})
            # Containment guard: absolute / drive-relative names must not
            # escape the data directory even though ".." was already rejected.
            try:
                p.resolve().relative_to(data_root)
            except (ValueError, OSError):
                return self._json(400, {"error": "bad path"})
            mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
            return self._send(200, p.read_bytes(), mime)

        if path == "/api/access":
            try:
                import access_policy
                return self._json(200, access_policy.get_policy())
            except ImportError:
                return self._json(503, {"error": "unavailable"})

        if path == "/api/hub":
            try:
                import hub
                import license as app_license_mod
                q = parse_qs(urlparse(self.path).query)
                lic = app_license_mod.get_status() if app_license_mod else {}
                business = bool(lic.get("business_features"))
                join_base = ""
                with _tunnel_lock:
                    join_base = (_tunnel.get("url") or "").rstrip("/")
                if not join_base:
                    ips = local_ips()
                    if ips:
                        join_base = f"http://{ips[0]}:{PORT}"
                join_url, _ = self._join_url(join_base or "", ip)
                snap = hub.get_hub_snapshot(
                    host_ip=ip if _is_local_host(ip) else (local_ips()[0] if local_ips() else "127.0.0.1"),
                    business=business,
                    join_url=join_url,
                )
                return self._json(200, snap)
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path.startswith("/api/hub/peers/") and path.endswith("/events"):
            try:
                import hub
                peer_ip = path.split("/")[-2]
                return self._json(200, {"events": db.list_hub_events(80, ip=peer_ip)})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/cortex/health":
            try:
                import cortex_client
                # CRM snapshot: continuous poller + engine/memory planes
                return self._json(200, cortex_client.snapshot())
            except ImportError:
                return self._json(200, {"ok": False, "status": "unavailable"})

        if path == "/api/agents":
            try:
                import agent_runtime
                import agent_store
                agent_runtime.ensure_default_agent()
                pinned_only = (q.get("pinned", ["0"])[0] or "0") in ("1", "true", "yes")
                return self._json(200, {"agents": agent_store.list_agents(pinned_only=pinned_only)})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path.startswith("/api/agents/") and path.endswith("/runs"):
            try:
                import agent_store
                aid = int(path.split("/")[-2])
                return self._json(200, {"runs": agent_store.list_runs(aid)})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/agents/links":
            try:
                import agent_store
                return self._json(200, {"links": agent_store.list_links()})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/rag/spaces":
            try:
                from rag import store as rag_store
                from rag.agents import seed_rag_agents

                seed_rag_agents()
                rag_store.init()
                return self._json(200, {"ok": True, "spaces": rag_store.list_spaces()})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/export"):
            try:
                from rag import export_import as rag_pack

                sid = int(path.split("/")[4])
                include_chats = q.get("include_chats", ["1"])[0] not in ("0", "false", "no")
                body = rag_pack.export_space(sid, include_chats=include_chats)
                from rag import store as rag_store

                space = rag_store.get_space(sid) or {}
                slug = str(space.get("slug") or f"rag-{sid}")[:60]
                fname = f"airgpt-rag-{slug}-{datetime.now().strftime('%Y%m%d')}.zip"
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                self.send_header("Content-Length", str(len(body)))
                self._cors()
                self.end_headers()
                self.wfile.write(body)
                return
            except ValueError as e:
                return self._json(404 if "not found" in str(e).lower() else 400, {"error": str(e)[:200]})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/sources"):
            try:
                from rag import store as rag_store

                sid = int(path.split("/")[4])
                return self._json(200, {"ok": True, "sources": rag_store.list_sources(sid)})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/samples"):
            try:
                from rag import store as rag_store

                sid = int(path.split("/")[4])
                qs = parse_qs(urlparse(self.path).query or "")
                lim = int((qs.get("limit") or ["8"])[0] or 8)
                lim = max(1, min(lim, 24))
                rows = rag_store.sample_parent_chunks(sid, limit=lim)
                chunks = []
                for r in rows or []:
                    chunks.append(
                        {
                            "id": r.get("id"),
                            "heading": r.get("heading") or "",
                            "path": r.get("path") or "",
                            "kind": r.get("kind") or "parent",
                            "text": (r.get("text") or "")[:500],
                        }
                    )
                return self._json(200, {"ok": True, "chunks": chunks})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/chats"):
            try:
                from rag import store as rag_store

                sid = int(path.split("/")[4])
                return self._json(200, {"ok": True, "chats": rag_store.list_chats(sid)})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/chats/") and path.endswith("/messages"):
            try:
                from rag import store as rag_store

                cid = int(path.split("/")[4])
                return self._json(200, {"ok": True, "messages": rag_store.list_messages(cid)})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/ingest-jobs/"):
            try:
                from rag import store as rag_store

                jid = int(path.rstrip("/").split("/")[-1])
                job = rag_store.get_job(jid)
                if not job:
                    return self._json(404, {"error": "job not found"})
                return self._json(200, {"ok": True, "job": job})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/traces/"):
            try:
                from rag import store as rag_store

                tid = path.rstrip("/").split("/")[-1]
                tr = rag_store.get_trace(tid)
                if not tr:
                    return self._json(404, {"error": "trace not found"})
                return self._json(200, {"ok": True, "trace": tr})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/rag/vectors":
            try:
                from rag import vectors as rag_vectors

                return self._json(200, rag_vectors.available())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/commands":
            try:
                import commands as commands_mod
                q = parse_qs(urlparse(self.path).query)
                prefix = (q.get("q") or q.get("prefix") or [""])[0]
                return self._json(200, {"commands": commands_mod.list_commands(prefix)})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/mentions/suggest":
            try:
                import mentions as mentions_mod
                q = parse_qs(urlparse(self.path).query)
                query = (q.get("q") or [""])[0]
                space_id = int((q.get("space_id") or ["0"])[0] or 0)
                return self._json(200, {"ok": True, "items": mentions_mod.suggest(query, space_id=space_id)})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/memory/overview":
            try:
                import agent_store
                return self._json(200, agent_store.memory_overview())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/memory/goals":
            try:
                import vault as vault_mod
                q = parse_qs(urlparse(self.path).query)
                project = (q.get("project") or ["general"])[0]
                goals = vault_mod.get_goals(project)
                folders = vault_mod.list_project_folders(project)
                return self._json(200, {"ok": True, "goals": goals, "folders": folders})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/memory/panel":
            try:
                import memory_index
                q = parse_qs(urlparse(self.path).query)
                sid = int((q.get("session_id") or ["0"])[0] or 0)
                project = (q.get("project") or [""])[0] or ""
                return self._json(200, memory_index.panel_payload(session_id=sid, project=project))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/memory/search":
            try:
                import memory_index
                q = parse_qs(urlparse(self.path).query)
                query = (q.get("q") or [""])[0]
                project = (q.get("project") or [""])[0]
                sid = int((q.get("session_id") or ["0"])[0] or 0)
                return self._json(200, {"ok": True, "hits": memory_index.search(query, project=project, session_id=sid)})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/models/probe":
            try:
                import model_probe
                return self._json(200, model_probe.probe())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/marketplace":
            try:
                import marketplace
                q = parse_qs(urlparse(self.path).query)
                suitable = (q.get("all") or [""])[0] not in ("1", "true", "yes")
                return self._json(
                    200,
                    marketplace.list_catalog(
                        effort=(q.get("effort") or [""])[0],
                        serving=(q.get("serving") or [""])[0],
                        category=(q.get("category") or [""])[0],
                        sort=(q.get("sort") or ["relevance"])[0],
                        only_fit=(q.get("fit") or [""])[0] in ("1", "true", "yes"),
                        suitable_only=suitable,
                    ),
                )
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/marketplace/jobs":
            try:
                import marketplace
                return self._json(200, marketplace.list_jobs())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/marketplace/trending":
            try:
                import marketplace
                q = parse_qs(urlparse(self.path).query)
                only_fit = (q.get("all") or [""])[0] not in ("1", "true", "yes")
                lim = int((q.get("limit") or ["24"])[0] or 24)
                return self._json(200, marketplace.hf_trending(limit=lim, only_fit=only_fit))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/marketplace/trials":
            try:
                import model_trial
                return self._json(200, model_trial.list_trials())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/profile":
            try:
                import serve_profile
                return self._json(200, serve_profile.detect_profile())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/cortex/isolation":
            try:
                import cortex_runtime
                return self._json(200, cortex_runtime.isolation_status())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/apps":
            try:
                import apps_hub
                return self._json(200, apps_hub.status())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path.startswith("/api/apps/") and path.count("/") == 3:
            # /api/apps/{id} — probe one
            try:
                import apps_hub
                app_id = path.rsplit("/", 1)[-1]
                st = apps_hub.status()
                hit = next((a for a in st.get("apps") or [] if a.get("id") == app_id), None)
                return self._json(200, hit or {"ok": False, "error": "unknown app"})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/video/capability":
            try:
                import ltx2_video
                return self._json(200, ltx2_video.capability())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/video/jobs":
            try:
                import ltx2_video
                return self._json(200, ltx2_video.list_jobs())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path.startswith("/api/video/status/"):
            try:
                import ltx2_video
                return self._json(200, ltx2_video.status(path.rsplit("/", 1)[-1]))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path.startswith("/api/video/result/"):
            try:
                import ltx2_video
                return self._json(200, ltx2_video.result(path.rsplit("/", 1)[-1]))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path.startswith("/api/video/file/"):
            try:
                import ltx2_video
                p = ltx2_video.file_path(path.rsplit("/", 1)[-1])
                if not p:
                    return self._json(404, {"error": "file missing"})
                data = p.read_bytes()
                self.send_response(200)
                ctype = "video/mp4" if p.suffix.lower() == ".mp4" else "text/plain"
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self._cors()
                self.end_headers()
                self.wfile.write(data)
                return
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/hosting":
            try:
                import hosting
                return self._json(200, hosting.status())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/hosting/engines":
            try:
                import netie_engine
                return self._json(200, netie_engine.list_engines())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/hosting/specs":
            try:
                import netie_engine
                return self._json(200, netie_engine.specs())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/usage":
            try:
                import hosting
                q = parse_qs(urlparse(self.path).query)
                lim = int((q.get("limit") or ["80"])[0] or 80)
                if (q.get("format") or [""])[0].lower() == "csv":
                    csv_body = hosting.usage_csv(lim)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition", 'attachment; filename="airgpt-usage.csv"')
                    self._cors()
                    self.end_headers()
                    self.wfile.write(csv_body.encode("utf-8"))
                    return
                return self._json(200, hosting.usage_summary(lim))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/workspace":
            try:
                import workspace_api
                return self._json(200, workspace_api.get_workspace())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/fs/tree":
            try:
                import workspace_api
                q = parse_qs(urlparse(self.path).query)
                rel = (q.get("path") or [""])[0]
                return self._json(200, workspace_api.list_tree(rel))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/fs/read":
            try:
                import workspace_api
                q = parse_qs(urlparse(self.path).query)
                rel = (q.get("path") or [""])[0]
                return self._json(200, workspace_api.read_file(rel))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/fs/find":
            try:
                import workspace_api
                q = parse_qs(urlparse(self.path).query)
                return self._json(200, workspace_api.find_paths((q.get("q") or [""])[0]))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/git/status":
            try:
                import agent_tools
                return self._json(200, agent_tools.git_status())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/git/diff":
            try:
                import agent_tools
                q = parse_qs(urlparse(self.path).query)
                rel = (q.get("path") or [""])[0]
                return self._json(200, agent_tools.git_diff(rel))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/git/fingerprint":
            try:
                import workspace_api
                q = parse_qs(urlparse(self.path).query)
                light = (q.get("light") or ["0"])[0] in ("1", "true", "yes")
                return self._json(200, workspace_api.fingerprint(light=light))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/git/summary":
            try:
                import workspace_api
                return self._json(200, workspace_api.git_summary())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/git/branches":
            try:
                import workspace_api
                return self._json(200, workspace_api.list_branches())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/openide/ready":
            try:
                import key_vault
                import cursor_bridge
                q = parse_qs(urlparse(self.path).query)
                backend = (q.get("backend") or [cursor_bridge.get_backend()])[0]
                return self._json(200, key_vault.ready_for_backend(str(backend)))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/openvault/status":
            try:
                import openvault_bridge
                return self._json(200, openvault_bridge.status())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/openvault/ping":
            try:
                import openvault_bridge
                return self._json(200, openvault_bridge.ping())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/openvault/mesh":
            try:
                import openvault_bridge
                return self._json(200, openvault_bridge.mesh())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/openvault/connect-pack":
            try:
                import openvault_bridge
                return self._json(200, openvault_bridge.connect_pack())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/openvault/keyvault":
            try:
                import openvault_bridge
                return self._json(200, openvault_bridge.keyvault_snapshot())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/openide/last-run":
            try:
                import cursor_bridge
                return self._json(200, cursor_bridge.last_run_info())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/cortex/runs":
            try:
                import agent_store
                q = parse_qs(urlparse(self.path).query)
                lim = int((q.get("limit") or ["30"])[0] or 30)
                aid = (q.get("agent_id") or [""])[0]
                agent_id = int(aid) if aid else None
                return self._json(200, {"runs": agent_store.list_runs(agent_id, lim)})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/cortex/settings":
            try:
                import cortex_orchestrator
                return self._json(200, cortex_orchestrator.get_settings())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/cortex/recipes":
            try:
                import cortex_orchestrator
                return self._json(200, {"recipes": cortex_orchestrator.list_recipes()})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/cortex/pending":
            try:
                import cortex_orchestrator
                return self._json(200, {"runs": cortex_orchestrator.list_pending()})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/cortex/invoke":
            try:
                import invoke_registry
                return self._json(200, invoke_registry.catalog())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/invoke/skills":
            try:
                import invoke_registry
                return self._json(200, {"ok": True, "skills": invoke_registry.list_skills()})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/invoke/rules":
            try:
                import invoke_registry
                return self._json(200, {"ok": True, **invoke_registry.rules_context()})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/openide/backend":
            try:
                import cursor_bridge
                return self._json(200, {"backend": cursor_bridge.get_backend(), "options": cursor_bridge.backends()})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/openforge/status":
            try:
                import openforge_chip
                return self._json(200, openforge_chip.status())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/openforge/designs":
            try:
                import openforge_chip
                return self._json(200, {"designs": openforge_chip.list_designs()})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/terminal/session":
            try:
                import terminal_pty
                import workspace_api
                ws = workspace_api.get_workspace()
                return self._json(200, terminal_pty.start_session(ws.get("root") or ""))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        return self._json(404, {"error": "not found"})

    def do_POST(self):
        global _server_mode, AI_AUTO, _client_ai_enabled
        ip = self._client_ip()
        ua = self.headers.get("User-Agent", "")
        path = urlparse(self.path).path
        if not self._auth_ok(path) and not path.startswith("/api/auth/"):
            return self._json(401, {"error": "auth required", "auth": True})
        if _is_host_only_path(path) and not _is_local_host(ip):
            return self._json(403, {"error": "host only"})

        if path == "/api/chat/stream":
            if app_auth and hasattr(app_auth, "token_session_acl") and not _is_local_host(ip):
                scoped = app_auth.token_session_acl(self._request_token())
                if scoped and scoped.get("acl") == "view":
                    return self._json(403, {"error": "This share is view-only"})
            dname = hostname()
            return self._handle_chat_stream(ip, dname)

        if path == "/api/messages":
            # Share-guest ACL: view-only tokens cannot post
            if app_auth and hasattr(app_auth, "token_session_acl") and not _is_local_host(ip):
                scoped = app_auth.token_session_acl(self._request_token())
                if scoped and scoped.get("acl") == "view":
                    return self._json(403, {"error": "This share is view-only — ask host for post access"})
            ctype = self.headers.get("Content-Type", "")
            dname = hostname()
            if "multipart" in ctype:
                form = _parse_multipart(self._body(), ctype)
                dname = str(form.get("device_name", dname))[:40]
                text = str(form.get("text", ""))
                sid = int(form.get("session_id", 0) or 0)
                skip_ai = str(form.get("no_ai", "")).lower() in ("1", "true", "yes")
                auto_clip = str(form.get("auto_clipboard", "")).lower() in ("1", "true", "yes")
                up = form.get("file")
                if isinstance(up, dict):
                    fdata = up.get("data", b"")
                    if not fdata:
                        return self._json(400, {"error": "empty file"})
                    if len(fdata) > MAX_BYTES:
                        return self._json(400, {"error": "file too large"})
                    is_img = (up.get("filename") or "").lower().endswith(
                        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif")
                    ) or fdata.startswith(b"\x89PNG") or fdata.startswith(b"\xff\xd8")
                    # No session + no AI → today's daily text or image chat
                    if not sid and (skip_ai or not (_client_ai_enabled and AI_AUTO)):
                        if is_img:
                            daily = db.get_or_create_daily_image_session()
                        else:
                            daily = db.get_or_create_daily_text_session()
                        sid = daily["id"]
                        msg = post_message(
                            ip, dname, text=text, file_data=fdata, filename=up.get("filename"),
                            source="chat", session_id=sid, auto_analyze=False, auto_clipboard=auto_clip,
                        )
                    # AI photo without open chat → new categorized AI chat
                    elif not sid and is_img and not skip_ai and _client_ai_enabled and AI_AUTO:
                        msg = post_capture_image(
                            ip, dname, fdata, up.get("filename") or "photo.jpg", "chat", with_ai=True,
                        )
                        if msg:
                            sid = int(msg.get("session_id") or 0)
                    else:
                        if not sid:
                            daily = db.get_or_create_daily_image_session() if is_img else db.get_or_create_daily_text_session()
                            sid = daily["id"]
                        msg = post_message(
                            ip, dname, text=text, file_data=fdata, filename=up.get("filename"),
                            source="chat", session_id=sid, auto_analyze=not skip_ai, auto_clipboard=auto_clip,
                        )
                elif text.strip():
                    if not sid:
                        daily = db.get_or_create_daily_text_session()
                        sid = daily["id"]
                    msg = post_message(ip, dname, text=text, source="chat", session_id=sid)
                else:
                    return self._json(400, {"error": "empty"})
            else:
                data = json.loads(self._body().decode() or "{}")
                dname = str(data.get("device_name", dname))[:40]
                text = str(data.get("text", ""))
                sid = int(data.get("session_id", 0) or 0)
                mode = str(data.get("mode", "engineering"))
                if data.get("ai_mode"):
                    if not text.strip():
                        return self._json(400, {"error": "question required"})
                    reply_to_id = int(data.get("reply_to_id", 0) or 0)
                    reply_snippet = str(data.get("reply_snippet", ""))[:500]
                    parent_session_id = int(data.get("parent_session_id", 0) or 0)
                    if reply_to_id or reply_snippet:
                        if reply_to_id and not reply_snippet:
                            rm = db.get_message(reply_to_id)
                            if rm:
                                reply_snippet = (rm.get("text") or rm.get("ai_analysis") or "")[:500]
                        cat = db.MODE_TO_CATEGORY.get(mode, "general")
                        sess = db.create_reply_session(
                            parent_session_id or sid, text[:60] or "Reply", reply_snippet, category=cat,
                        )
                        sid = sess["id"]
                    elif not sid:
                        scratch_sid = _route_new_chat(text)
                        if scratch_sid:
                            sid = scratch_sid  # small-talk → shared Scratch space
                        else:
                            sess = db.create_session("New chat", capture_type="ai")
                            sid = sess["id"]
                    user_msg = db.add_message(device_ip=ip, device_name=dname, text=text, source="ai-chat", session_id=sid)
                    # Soft-title from first user question until AI replies
                    db.maybe_set_ai_session_title(sid, text.strip()[:60])
                    depth = str(data.get("depth", "normal"))
                    target = None
                    for cid in (data.get("context_ids") or [])[:3]:
                        ctx = db.get_message(int(cid))
                        if ctx and ctx["kind"] == "image":
                            target = ctx
                            break
                    if not target and sid:
                        target = db.get_latest_image_context(sid)
                    if target and (target.get("vision_cache") or target.get("ai_analysis")):
                        queue_analysis(int(target["id"]), text, mode=mode, session_id=sid, depth=depth)
                        return self._json(200, {"ok": True, "message": user_msg, "ai": "queued", "context_id": target["id"], "session_id": sid})
                    queue_text_chat(text, mode=mode, session_id=sid)
                    return self._json(200, {"ok": True, "message": user_msg, "ai": "queued_text", "session_id": sid})
                if not sid:
                    daily = db.get_or_create_daily_text_session()
                    sid = daily["id"]
                msg = post_message(ip, dname, text=text, source="chat", session_id=sid)
            if not msg:
                return self._json(200, {"ok": True, "duplicate": True})
            return self._json(200, {"ok": True, "message": msg})

        if path == "/api/clipboard":
            data = json.loads(self._body().decode() or "{}")
            mid = int(data.get("message_id", 0) or 0)
            text = str(data.get("text", ""))
            if mid:
                msg = db.get_message(mid)
                kind = copy_message_to_clipboard(msg)
                if not kind:
                    return self._json(400, {"error": "nothing to copy"})
                return self._json(200, {"ok": True, "kind": kind})
            if text.strip():
                ok = write_clipboard_text(text)
                return self._json(200 if ok else 500, {"ok": ok, "kind": "text" if ok else ""})
            return self._json(400, {"error": "empty"})

        if path == "/api/input-notes/start":
            if not input_notes:
                return self._json(503, {"error": "input notes unavailable"})
            return self._json(200, input_notes.start_recording())

        if path == "/api/input-notes/stop":
            if not input_notes:
                return self._json(503, {"error": "input notes unavailable"})
            return self._json(200, input_notes.stop_recording())

        if path == "/api/input-notes/append":
            if not input_notes:
                return self._json(503, {"error": "input notes unavailable"})
            data = json.loads(self._body().decode() or "{}")
            ch = data.get("char", "")
            text = data.get("text", "")
            if ch:
                input_notes.append_char(str(ch))
            elif text:
                input_notes.append_text(str(text), source="browser")
            return self._json(200, input_notes.status())

        if path == "/api/admin/validate-all":
            if not admin_dashboard:
                return self._json(503, {"error": "admin unavailable"})
            return self._json(200, admin_dashboard.validate_all())

        if path == "/api/admin/validate":
            if not admin_dashboard:
                return self._json(503, {"error": "admin unavailable"})
            data = json.loads(self._body().decode() or "{}")
            wid = str(data.get("worker_id", ""))
            if not wid:
                return self._json(400, {"error": "worker_id required"})
            return self._json(200, admin_dashboard.validate_worker(wid))

        if path == "/api/analyze":
            data = json.loads(self._body().decode() or "{}")
            mid = int(data.get("message_id", 0))
            question = str(data.get("question", "")).strip() or None
            mode = str(data.get("mode", "engineering"))
            depth = str(data.get("depth", "normal"))
            sid = int(data.get("session_id", 0) or 0)
            msg = db.get_message(mid)
            if not msg or msg["kind"] != "image":
                return self._json(400, {"error": "image message required"})
            queue_analysis(mid, question, mode=mode, session_id=sid, depth=depth)
            return self._json(200, {"ok": True, "status": "queued"})

        if path == "/api/sessions":
            data = json.loads(self._body().decode() or "{}")
            title = str(data.get("title", "New chat"))[:80]
            sess = db.create_session(title)
            cat = db.MODE_TO_CATEGORY.get(_server_mode, "general")
            db.update_session_meta(sess["id"], category=cat)
            return self._json(200, {"session": sess})

        if path == "/api/projects":
            data = json.loads(self._body().decode() or "{}")
            name = str(data.get("name", "")).strip()
            cat = str(data.get("category", "general"))
            if not name:
                return self._json(400, {"error": "name required"})
            return self._json(200, {"project": db.create_project_under_category(name, cat)})

        if path == "/api/access/approve":
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import access_policy
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, access_policy.approve(data.get("ip", ""), data.get("name", "")))
            except ImportError:
                return self._json(503, {"error": "unavailable"})

        if path == "/api/access/deny":
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import access_policy
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, access_policy.deny(data.get("ip", "")))
            except ImportError:
                return self._json(503, {"error": "unavailable"})

        if path == "/api/access/mode":
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import access_policy
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, access_policy.set_mode(str(data.get("mode", "open"))))
            except ImportError:
                return self._json(503, {"error": "unavailable"})

        if path == "/api/mode":
            data = json.loads(self._body().decode() or "{}")
            m = str(data.get("mode", "engineering"))
            if m in db.MODE_TO_CATEGORY:
                _server_mode = m
            return self._json(200, {"mode": _server_mode})

        if path == "/api/ai/config":
            data = json.loads(self._body().decode() or "{}")
            if "auto" in data:
                AI_AUTO = bool(data["auto"])
            if "client_ai" in data:
                _client_ai_enabled = bool(data["client_ai"])
            return self._json(200, {"auto": AI_AUTO and _client_ai_enabled, "client_ai": _client_ai_enabled})

        if path == "/api/ai/mode":
            data = json.loads(self._body().decode() or "{}")
            _client_ai_enabled = bool(data.get("enabled", True))
            if app_audit:
                app_audit.log("ai_mode", ip=ip, detail="on" if _client_ai_enabled else "off")
            return self._json(200, {"enabled": _client_ai_enabled})

        if path == "/api/license":
            data = json.loads(self._body().decode() or "{}")
            if not app_license:
                return self._json(400, {"error": "license module unavailable"})
            if data.get("activate"):
                return self._json(200, app_license.activate_license(
                    str(data.get("key", "")), str(data.get("email", "")),
                ))
            if data.get("email"):
                out = app_license.set_email(str(data["email"]))
                if netie_id:
                    try:
                        netie_id.link_local(email=str(data["email"]), product="airgpt", sku="personal")
                    except Exception:
                        pass
                return self._json(200, out)
            return self._json(400, {"error": "activate or email required"})

        if path == "/api/netie/account":
            if not netie_id:
                return self._json(400, {"error": "netie_id unavailable"})
            data = json.loads(self._body().decode() or "{}")
            action = str(data.get("action") or "link").lower()
            if action == "logout":
                return self._json(200, netie_id.clear_session())
            if action == "login":
                return self._json(200, netie_id.login_online(
                    str(data.get("email") or ""),
                    str(data.get("password") or ""),
                ))
            return self._json(200, netie_id.link_local(
                email=str(data.get("email") or ""),
                product=str(data.get("product") or "airgpt"),
                sku=str(data.get("sku") or "personal"),
                session_token=str(data.get("session_token") or ""),
            ))

        if path == "/api/settings":
            if not app_settings:
                return self._json(400, {"error": "settings unavailable"})
            # Writes provider API keys into env.local — host machine only
            # (matches the host-only gate on reading keys via GET ?keys=1).
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            data = json.loads(self._body().decode() or "{}")
            return self._json(200, app_settings.update_settings(data))

        if path == "/api/openfree/enable":
            # Host-only: sets env flags + launches the OpenFree gateway sidecar.
            if not _is_local_host(ip):
                return self._json(403, {"ok": False, "error": "host only"})
            try:
                import openfree
                if app_settings:
                    app_settings.update_settings(
                        {"OMNIROUTE_ENABLED": "1", "OMNIROUTE_BASE_URL": openfree.BASE_URL}
                    )
                return self._json(200, openfree.enable())
            except Exception as e:
                return self._json(500, {"ok": False, "error": f"openfree: {e}"[:200]})

        if path == "/api/auth/init":
            if not app_auth:
                return self._json(400, {"error": "auth unavailable"})
            data = json.loads(self._body().decode() or "{}")
            return self._json(200, app_auth.init_workspace(
                str(data.get("email", "")), str(data.get("passcode", "")),
            ))

        if path == "/api/auth/join":
            if not app_auth:
                return self._json(400, {"error": "auth unavailable"})
            if self._passcode_rate_limited(ip):
                if app_audit:
                    app_audit.log("auth_blocked", ip=ip, detail="passcode/join throttle", ok=False)
                return self._json(429, {"ok": False, "error": "Too many attempts — wait a few minutes."})
            data = json.loads(self._body().decode() or "{}")
            passcode = str(data.get("passcode", ""))
            join_code = str(data.get("join_code", "") or data.get("code", ""))
            device_id = str(data.get("device_id", "") or self.headers.get("X-Device-Id", ""))[:80]
            display_name = str(data.get("display_name", "") or self.headers.get("X-Device-Name", ""))[:120]
            if join_code and hasattr(app_auth, "redeem_join_code"):
                import hub
                r = hub.redeem_join_code(join_code, ip=ip, device_id=device_id, display_name=display_name)
            else:
                r = app_auth.join_workspace(passcode)
                if r.get("ok"):
                    try:
                        import hub
                        hub.touch_peer(ip, device_id=device_id, display_name=display_name, join_method="passcode")
                    except Exception:
                        pass
            if r.get("ok"):
                if app_audit:
                    app_audit.log("auth_join", ip=ip, detail="join code" if join_code else "passcode join", ok=True)
            else:
                self._note_passcode_fail(ip)
                if app_audit:
                    app_audit.log("auth_fail", ip=ip, detail="join code" if join_code else "passcode join", ok=False)
            return self._json(200, r)

        if path == "/api/hub/join-code":
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import hub
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, hub.create_join_code(
                    str(data.get("access_level", "read_write")),
                    host_token=self._request_token(),
                    host_verified=_is_local_host(ip),
                ))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path.startswith("/api/hub/peers/") and path.endswith("/acl"):
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import hub
                peer_ip = path.split("/")[-2]
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, hub.set_peer_acl(
                    peer_ip,
                    str(data.get("access_level", "read_write")),
                    admin_name=str(data.get("display_name", "")),
                ))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path.startswith("/api/hub/peers/") and path.endswith("/rename"):
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import hub
                peer_ip = path.split("/")[-2]
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, hub.rename_peer(peer_ip, str(data.get("display_name", ""))))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path.startswith("/api/hub/peers/") and path.endswith("/kick"):
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import hub
                peer_ip = path.split("/")[-2]
                return self._json(200, hub.kick_peer(peer_ip))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/auth/qr-redeem":
            if not app_auth:
                return self._json(400, {"error": "auth unavailable"})
            data = json.loads(self._body().decode() or "{}")
            qr_tok = str(data.get("qr_token", ""))
            # Prefer session-share redeem when token is a share token
            r = None
            if hasattr(app_auth, "redeem_session_share"):
                r = app_auth.redeem_session_share(qr_tok)
                if not r.get("ok"):
                    r = app_auth.redeem_qr_token(qr_tok)
            else:
                r = app_auth.redeem_qr_token(qr_tok)
            if r.get("ok") and app_audit:
                detail = "session share" if r.get("session_id") else "auto join via QR"
                app_audit.log("auth_qr_scan", ip=ip, detail=detail, ok=True)
                try:
                    import hub
                    hub.touch_peer(
                        ip,
                        device_id=str(data.get("device_id", "") or self.headers.get("X-Device-Id", ""))[:80],
                        display_name=str(data.get("display_name", "") or self.headers.get("X-Device-Name", ""))[:120],
                        join_method="qr" if r.get("session_id") else "share",
                        logged_in=True,
                        access_level=r.get("access_level", "read_only"),
                    )
                except Exception:
                    pass
            elif app_audit:
                app_audit.log("auth_qr_fail", ip=ip, detail=qr_tok[:20], ok=False)
            return self._json(200, r)

        if path.endswith("/share") and path.startswith("/api/sessions/"):
            if not app_auth:
                return self._json(503, {"error": "auth unavailable"})
            try:
                sid = int(path.rstrip("/").split("/")[-2])
            except ValueError:
                return self._json(400, {"error": "bad session id"})
            data = json.loads(self._body().decode() or "{}")
            acl = str(data.get("acl", "view"))
            access_level = str(data.get("access_level", ""))
            r = app_auth.issue_session_share(
                sid,
                acl=acl,
                access_level=access_level,
                host_token=self._request_token(),
                host_verified=_is_local_host(ip),
            )
            if not r.get("ok"):
                return self._json(400, r)
            # Build share URL from preferred base
            base = ""
            with _tunnel_lock:
                base = (_tunnel.get("url") or "").rstrip("/")
            if not base:
                ips = local_ips()
                if ips:
                    base = f"http://{ips[0]}:{PORT}"
            share_url = ""
            if base and r.get("share_token"):
                share_url = f"{base}/?qr={r['share_token']}&session={sid}"
            if app_audit:
                app_audit.log(
                    "session_share",
                    ip=ip,
                    detail=f"session={sid} acl={acl}",
                    ok=True,
                )
            return self._json(200, {**r, "share_url": share_url})

        if path == "/api/auth/verify-passcode":
            if not app_auth:
                return self._json(400, {"error": "auth unavailable"})
            if self._passcode_rate_limited(ip):
                if app_audit:
                    app_audit.log("auth_blocked", ip=ip, detail="verify-passcode throttle", ok=False)
                return self._json(429, {"ok": False, "error": "Too many attempts — wait a few minutes."})
            data = json.loads(self._body().decode() or "{}")
            ok = app_auth.verify_passcode(str(data.get("passcode", "")))
            if ok:
                tok = self.headers.get("X-AirGPT-Token") or ""
                qt = app_auth.issue_qr_token(tok, host_verified=True)
                if app_audit:
                    app_audit.log("qr_unlock", ip=ip, detail="QR Connect unlocked", ok=True)
                return self._json(200, {"ok": True, "qr_token": qt})
            self._note_passcode_fail(ip)
            if app_audit:
                app_audit.log("auth_fail", ip=ip, detail="verify-passcode", ok=False)
            return self._json(200, {"ok": False, "error": "Wrong passcode"})

        if path == "/api/restart-tunnel":
            restart_tunnel()
            return self._json(200, {"ok": True, "status": "restarting"})

        if path == "/api/adopt-tunnel":
            if not _is_local_host(ip):
                return self._json(403, {"error": "local host only"})
            data = json.loads(self._body().decode() or "{}")
            url = str(data.get("url", "")).strip().rstrip("/")
            if not url.startswith("https://"):
                return self._json(400, {"error": "https tunnel URL required"})
            if _set_tunnel(url, "cloudflared"):
                return self._json(200, {"ok": True, "url": url})
            return self._json(400, {"ok": False, "error": _tunnel.get("error") or "tunnel probe failed"})

        if path == "/api/agents":
            try:
                import agent_runtime
                data = json.loads(self._body().decode() or "{}")
                agent = agent_runtime.create_agent(data)
                return self._json(200, {"ok": True, "agent": agent})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/agents/") and path.endswith("/delete"):
            try:
                import agent_store

                aid = int(path.split("/")[3])
                return self._json(200, agent_store.delete_agent(aid))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/agents/") and path.endswith("/run"):
            try:
                import agent_runtime
                import cortex_orchestrator
                aid = int(path.rstrip("/").split("/")[-2])
                data = json.loads(self._body().decode() or "{}")
                prompt = str(data.get("prompt") or data.get("text") or "").strip()
                if not prompt:
                    return self._json(400, {"error": "prompt required"})
                session_id = int(data.get("session_id") or 0)
                settings = cortex_orchestrator.get_settings()
                thinking_mode = str(data.get("thinking_mode") or settings.get("thinking_mode") or "assist")
                backend = str(data.get("backend") or "local")
                try:
                    import cursor_bridge
                    if backend == "local":
                        backend = cursor_bridge.get_backend()
                except Exception:
                    pass
                self._sse_begin()
                for ev in agent_runtime.run_agent_events(
                    aid,
                    prompt,
                    session_id=session_id,
                    thinking_mode=thinking_mode,
                    max_steps=max(1, min(int(data.get("max_steps") or settings.get("max_steps") or 8), 20)),
                    token_budget=max(100, min(int(data.get("token_budget") or settings.get("token_budget") or 1200), 8000)),
                    backend=backend,
                    require_approval=bool(data.get("require_approval")),
                    file_context=bool(data.get("file_context", True)),
                    active_file=str(data.get("active_file") or ""),
                    resume=bool(data.get("resume")),
                    cursor_run_id=str(data.get("cursor_run_id") or data.get("run_id") or ""),
                    skill_override=str(data.get("skill_pack") or data.get("skill_override") or ""),
                    parent_run_id=int(data.get("parent_run_id") or 0),
                    is_subagent=bool(data.get("is_subagent")),
                ):
                    if not self._sse_send(ev):
                        break
                return
            except Exception as e:
                return self._json(500, {"error": str(e)[:200]})

        if path == "/api/agents/link":
            try:
                import agent_store
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, agent_store.link_agents(int(data.get("a_id") or 0), int(data.get("b_id") or 0), str(data.get("relation") or "a2a")))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/rag/spaces":
            try:
                from rag import store as rag_store
                from rag.agents import seed_rag_agents

                seed_rag_agents()
                data = json.loads(self._body().decode() or "{}")
                space = rag_store.create_space(
                    str(data.get("name") or "RAG"),
                    depth_default=str(data.get("depth_default") or "high"),
                    modalities=data.get("modalities") if isinstance(data.get("modalities"), list) else None,
                    profile=str(data.get("profile") or "local"),
                    config=data.get("config") if isinstance(data.get("config"), dict) else None,
                )
                return self._json(200, {"ok": True, "space": space})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/rag/spaces/import":
            try:
                from rag import export_import as rag_pack

                ctype = self.headers.get("Content-Type", "")
                if "multipart" not in ctype:
                    return self._json(400, {"error": "multipart zip required"})
                form = _parse_multipart(self._body(), ctype)
                up = form.get("file")
                if not isinstance(up, dict) or not up.get("data"):
                    return self._json(400, {"error": "no file"})
                name = form.get("name")
                name_s = str(name).strip() if isinstance(name, str) and name.strip() else None
                out = rag_pack.import_pack(up["data"], name=name_s)
                code = 200 if out.get("ok") else 400
                return self._json(code, out)
            except ValueError as e:
                return self._json(400, {"error": str(e)[:200]})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/sources"):
            try:
                from rag import ingest as rag_ingest
                from rag import store as rag_store

                sid = int(path.split("/")[4])
                data = json.loads(self._body().decode() or "{}")
                paths = data.get("paths") if isinstance(data.get("paths"), list) else []
                if data.get("path"):
                    paths = list(paths) + [str(data.get("path"))]
                session_ids = data.get("session_ids") if isinstance(data.get("session_ids"), list) else []
                research_ids = data.get("research_ids") if isinstance(data.get("research_ids"), list) else []
                urls = data.get("urls") if isinstance(data.get("urls"), list) else []

                ops = []
                if research_ids:
                    ops.append(lambda f: rag_ingest.ingest_research(sid, [str(x) for x in research_ids], force=f))
                if session_ids:
                    ops.append(lambda f: rag_ingest.ingest_sessions(sid, [int(x) for x in session_ids], force=f))
                if urls:
                    ops.append(lambda f: rag_ingest.ingest_urls(sid, [str(x) for x in urls], force=f))
                if paths:
                    ops.append(lambda f: rag_ingest.ingest_paths(sid, paths, force=f))
                if not ops:
                    return self._json(400, {"error": "path, paths, session_ids, research_ids, or urls required"})

                force = bool(data.get("force", True))
                out: dict = {"ok": True}
                carry: dict = {}
                for op in ops:
                    out = op(force)
                    force = False  # only the first ingest may rebuild
                    for key in ("sessions_attached", "research_attached", "urls_attached", "skipped", "failed_urls"):
                        if out.get(key):
                            carry[key] = out[key]
                    if not out.get("ok"):
                        break
                out.update(carry)
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/upload"):
            try:
                from rag import ingest as rag_ingest
                from rag import store as rag_store

                sid = int(path.split("/")[4])
                ctype = self.headers.get("Content-Type", "")
                if "multipart" not in ctype:
                    return self._json(400, {"error": "multipart required"})
                form = _parse_multipart(self._body(), ctype)
                updir = rag_store.BLOB_DIR / str(sid) / "uploads"
                updir.mkdir(parents=True, exist_ok=True)
                saved = []
                for key, val in form.items():
                    if isinstance(val, dict) and val.get("data") is not None:
                        fname = Path(str(val.get("filename") or key or "upload.txt")).name
                        dest = updir / fname
                        dest.write_bytes(val["data"])
                        saved.append(dest)
                if not saved:
                    return self._json(400, {"error": "no files in upload"})
                out = rag_ingest.ingest_paths(sid, saved, force=str(form.get("force") or "") not in ("0", "false"))
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/rag/web-search":
            try:
                from rag import websearch as rag_websearch

                data = json.loads(self._body().decode() or "{}")
                q = str(data.get("query") or data.get("q") or "").strip()
                if not q:
                    return self._json(400, {"error": "query required"})
                out = rag_websearch.search_web(q, max_results=min(int(data.get("max_results") or 8), 15))
                return self._json(200 if out.get("ok") else 502, out)
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/benchmark"):
            try:
                from rag import evaluate as rag_eval

                sid = int(path.split("/")[4])
                data = json.loads(self._body().decode() or "{}")
                golden = data.get("golden") if isinstance(data.get("golden"), list) else []
                if not golden:
                    return self._json(400, {"error": "golden required: [{query, expect_path, task_type}]"})
                depths = data.get("depths") if isinstance(data.get("depths"), list) else ["basic", "high", "max"]
                out = rag_eval.benchmark_modes(
                    sid, golden, depths=tuple(str(d) for d in depths), k=int(data.get("k") or 5)
                )
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/settings"):
            try:
                from rag import store as rag_store

                sid = int(path.split("/")[4])
                data = json.loads(self._body().decode() or "{}")
                space = rag_store.update_space_settings(
                    sid,
                    name=str(data.get("name")) if data.get("name") else None,
                    depth_default=str(data.get("depth_default")) if data.get("depth_default") else None,
                    config=data.get("config") if isinstance(data.get("config"), dict) else None,
                )
                if not space:
                    return self._json(404, {"error": "space not found"})
                return self._json(200, {"ok": True, "space": space})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/archive"):
            try:
                from rag import store as rag_store

                sid = int(path.split("/")[4])
                space = rag_store.archive_space(sid)
                return self._json(200, {"ok": True, "space": space})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/summary"):
            try:
                from rag import answer as rag_answer

                sid = int(path.split("/")[4])
                raw = self._body().decode() or "{}"
                data = json.loads(raw) if raw.strip() else {}
                out = rag_answer.summarize_space(
                    sid,
                    use_llm=True if "use_llm" not in data else bool(data.get("use_llm")),
                    force=bool(data.get("force")),
                )
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/sources/") and path.endswith("/delete"):
            try:
                from rag import store as rag_store

                src_id = int(path.split("/")[4])
                out = rag_store.delete_source(src_id)
                return self._json(200 if out.get("ok") else 404, out)
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/chats"):
            try:
                from rag import store as rag_store

                sid = int(path.split("/")[4])
                data = json.loads(self._body().decode() or "{}")
                chat = rag_store.create_chat(sid, str(data.get("title") or "New chat"))
                return self._json(200, {"ok": True, "chat": chat})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/build"):
            try:
                from rag import ingest as rag_ingest
                from rag import store as rag_store

                sid = int(path.split("/")[4])
                data = json.loads(self._body().decode() or "{}")
                srcs = rag_store.list_sources(sid)
                paths = [s.get("path") for s in srcs if s.get("path")]
                if data.get("paths"):
                    paths = list(data.get("paths"))
                if not paths:
                    return self._json(400, {"error": "no sources to build"})
                out = rag_ingest.ingest_paths(sid, paths, force=True)
                if out.get("ok"):
                    try:
                        rag_store.update_space_settings(sid, config={"corpus_summary": ""})
                    except Exception:
                        pass
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/rag/search":
            try:
                from rag import retrieve as rag_retrieve

                data = json.loads(self._body().decode() or "{}")
                sid = int(data.get("space_id") or 0)
                q = str(data.get("query") or data.get("q") or "").strip()
                if not sid or not q:
                    return self._json(400, {"error": "space_id and query required"})
                out = rag_retrieve.search(
                    sid,
                    q,
                    depth=str(data.get("depth") or "high"),
                    top_k=int(data.get("top_k") or 8),
                    debug=bool(data.get("debug")),
                )
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/rag/answers" and "text/event-stream" in (self.headers.get("Accept", "") or ""):
            return self._handle_rag_answer_stream()

        if path == "/api/rag/answers":
            try:
                from rag import answer as rag_answer

                data = json.loads(self._body().decode() or "{}")
                sid = int(data.get("space_id") or 0)
                q = str(data.get("query") or data.get("q") or "").strip()
                if not sid or not q:
                    return self._json(400, {"error": "space_id and query required"})
                out = rag_answer.answer(
                    sid,
                    q,
                    depth=str(data.get("depth") or "high"),
                    chat_id=int(data.get("chat_id") or 0),
                    use_llm=True if "use_llm" not in data else bool(data.get("use_llm")),
                )
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/rag/intent":
            try:
                from rag.intents import classify_intent

                data = json.loads(self._body().decode() or "{}")
                return self._json(200, {"ok": True, **classify_intent(str(data.get("text") or ""))})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/memory/backend":
            try:
                import agent_store
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, agent_store.set_memory_backend(str(data.get("backend") or "local_vault")))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/memory/drawer":
            try:
                import vault as vault_mod
                data = json.loads(self._body().decode() or "{}")
                project = str(data.get("project") or data.get("category") or "general")
                room = str(data.get("room") or "general")
                title = str(data.get("title") or "note")
                body = str(data.get("body") or "")
                rel = vault_mod.write_drawer(
                    project=project,
                    title=title,
                    body=body,
                    room=room,
                    source=str(data.get("source") or "api"),
                )
                try:
                    import agent_store
                    agent_store.set_memory_backend("project_wing")
                except Exception:
                    pass
                return self._json(200, {"ok": True, "path": rel, "backend": "project_wing"})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/memory/goals":
            try:
                import vault as vault_mod
                data = json.loads(self._body().decode() or "{}")
                project = str(data.get("project") or "general")
                goals = vault_mod.set_goals(
                    project,
                    current_state=data.get("current_state"),
                    next_goals=data.get("next_goals"),
                    long_term=data.get("long_term"),
                )
                return self._json(200, {"ok": True, "goals": goals})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/memory/add":
            try:
                import memory_index
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    memory_index.add_memory(
                        kind=str(data.get("kind") or "memory"),
                        title=str(data.get("title") or ""),
                        body=str(data.get("body") or ""),
                        project=str(data.get("project") or ""),
                        session_id=int(data.get("session_id") or 0),
                        folder=str(data.get("folder") or ""),
                        tags=data.get("tags") if isinstance(data.get("tags"), list) else None,
                        source=str(data.get("source") or "user"),
                        pinned=bool(data.get("pinned")),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/memory/ingest":
            try:
                import memory_index
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    memory_index.ingest_text(
                        str(data.get("text") or data.get("body") or ""),
                        title=str(data.get("title") or ""),
                        project=str(data.get("project") or ""),
                        session_id=int(data.get("session_id") or 0),
                        folder=str(data.get("folder") or "inbox"),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/memory/folder":
            try:
                import memory_index
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    memory_index.attach_folder(
                        session_id=int(data.get("session_id") or 0),
                        name=str(data.get("name") or ""),
                        project=str(data.get("project") or ""),
                        path=str(data.get("path") or ""),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/marketplace/override":
            try:
                import marketplace
                data = json.loads(self._body().decode() or "{}")
                if data.get("clear") or (not data.get("ram_gb") and not data.get("vram_gb") and data.get("note") == "clear"):
                    return self._json(200, marketplace.clear_hardware_override())
                return self._json(200, marketplace.set_hardware_override(data))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/marketplace/install":
            try:
                import marketplace
                data = json.loads(self._body().decode() or "{}")
                item_id = str(data.get("item_id") or data.get("id") or "")
                force = bool(data.get("force") or data.get("confirm"))
                if item_id == "glm-5.2-colibri" and data.get("confirm"):
                    return self._json(200, marketplace.confirm_colibri_install(force=True))
                return self._json(200, marketplace.queue_install(
                    item_id, force=force, confirm=bool(data.get("confirm")),
                ))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/marketplace/serve":
            try:
                import marketplace
                data = json.loads(self._body().decode() or "{}")
                item_id = str(data.get("item_id") or data.get("id") or "")
                port = data.get("port")
                return self._json(200, marketplace.bind_serve(item_id, port=int(port) if port else None))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/marketplace/trial":
            try:
                import model_trial
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    model_trial.run_trial(
                        str(data.get("item_id") or data.get("id") or ""),
                        pull=bool(data.get("pull")),
                        keep=bool(data.get("keep")),
                        verify_cloud=data.get("verify_cloud", True) is not False,
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/optimizers/install":
            try:
                import serve_profile
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    serve_profile.install_optimizer(
                        str(data.get("id") or ""),
                        dry_run=data.get("dry_run", True) is not False,
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/apps/start":
            try:
                import apps_hub
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, apps_hub.start(str(data.get("id") or "")))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/apps/stop":
            try:
                import apps_hub
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, apps_hub.stop(str(data.get("id") or "")))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/apps/open":
            try:
                import apps_hub
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, apps_hub.open_target(str(data.get("id") or "")))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/video/generate":
            try:
                import ltx2_video
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    ltx2_video.submit(
                        str(data.get("prompt") or ""),
                        duration=float(data.get("duration") or 6),
                        width=int(data.get("width") or 1280),
                        height=int(data.get("height") or 720),
                        seed=int(data.get("seed") or 42),
                        mode=data.get("mode"),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/hosting/role":
            try:
                import hosting
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, hosting.set_host_role(str(data.get("role") or "personal")))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/hosting/engine/add":
            try:
                import netie_engine
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, netie_engine.add_engine(str(data.get("id") or "")))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/hosting/engine/remove":
            try:
                import netie_engine
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, netie_engine.remove_engine(str(data.get("id") or "")))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/hosting/engine/config":
            try:
                import netie_engine
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, netie_engine.set_config(data))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/usage":
            try:
                import hosting
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    hosting.log_usage(
                        model=str(data.get("model") or ""),
                        tokens=int(data.get("tokens") or 0),
                        cost=float(data.get("cost") or 0),
                        kind=str(data.get("type") or "included"),
                        detail=str(data.get("detail") or ""),
                        user=str(data.get("user") or ""),
                        ip=ip,
                        session_id=int(data.get("session_id") or 0),
                        tier=str(data.get("tier") or ""),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/research/draft":
            try:
                import research as research_lib

                data = json.loads(self._body().decode() or "{}")
                title = str(data.get("title") or "Research draft")
                body = str(data.get("body") or "")
                md = research_lib.arxiv_skeleton(title, body, abstract=str(data.get("abstract") or ""))
                if data.get("markdown"):
                    md = research_lib.clean_prose(str(data.get("markdown")))
                return self._json(
                    200,
                    research_lib.save_draft(title, md, category=str(data.get("category") or "general")),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/research/upload":
            try:
                import research as research_lib

                ctype = self.headers.get("Content-Type", "")
                if "multipart" not in ctype:
                    return self._json(400, {"error": "multipart required"})
                form = _parse_multipart(self._body(), ctype)
                up = form.get("file")
                if not isinstance(up, dict) or not up.get("data"):
                    return self._json(400, {"error": "no file"})
                cat = str(form.get("category") or "papers")
                return self._json(
                    200,
                    research_lib.ingest_upload(str(up.get("filename") or "paper"), up["data"], category=cat),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/research/certify":
            try:
                import research as research_lib

                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    research_lib.certify_source(
                        str(data.get("path") or data.get("name") or ""),
                        note=str(data.get("note") or ""),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/memory/forget":
            try:
                import memory_index as mi

                data = json.loads(self._body().decode() or "{}")
                if data.get("thin"):
                    return self._json(200, mi.thin_memories(older_than_days=float(data.get("days") or 14)))
                return self._json(200, mi.forget_memories(older_than_days=float(data.get("days") or 90)))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/waitlist":
            data = json.loads(self._body().decode() or "{}")
            return self._json(200, _add_waitlist(
                str(data.get("email", "")), str(data.get("reason", "")),
                str(data.get("tier", "pro")),
            ))

        if path == "/api/workspace/open":
            try:
                import workspace_api
                data = json.loads(self._body().decode() or "{}")
                p = str(data.get("path") or data.get("root") or "").strip()
                if not p:
                    return self._json(400, {"error": "path required"})
                return self._json(200, workspace_api.open_workspace(p, name=str(data.get("name") or "")))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/openide/scaffold":
            try:
                from OpenIDE import scaffold as oide_scaffold
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    oide_scaffold.scaffold(
                        prompt=str(data.get("prompt") or ""),
                        name=str(data.get("name") or ""),
                        template=str(data.get("template") or "auto"),
                        parent=str(data.get("parent") or "apps"),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/openvault/connect":
            try:
                import openvault_bridge
                data = json.loads(self._body().decode() or "{}")
                openvault_bridge.ensure_local_config()
                return self._json(
                    200,
                    openvault_bridge.handshake(
                        name=str(data.get("name") or "AirGPT OpenIDE"),
                        auto_approve=bool(data.get("auto_approve", True)),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/openvault/gate":
            try:
                import openvault_bridge
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    openvault_bridge.gate_check(
                        action=str(data.get("action") or "run"),
                        project_path=str(data.get("project_path") or ""),
                        destination=str(data.get("destination") or ""),
                        required_providers=list(data.get("required_providers") or []),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/git/checkout":
            try:
                import workspace_api
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, workspace_api.checkout_branch(str(data.get("branch") or "")))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/fs/write":
            try:
                import workspace_api
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    workspace_api.write_file(
                        str(data.get("path") or ""),
                        str(data.get("content") or ""),
                        apply=bool(data.get("apply", True)),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/fs/patch":
            try:
                import workspace_api
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    workspace_api.patch_file(
                        str(data.get("path") or ""),
                        str(data.get("old") or ""),
                        str(data.get("new") or ""),
                        apply=bool(data.get("apply", True)),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/fs/checkpoint":
            try:
                import workspace_api
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, workspace_api.checkpoint_create(str(data.get("label") or "")))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/cortex/settings":
            try:
                import cortex_orchestrator
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    cortex_orchestrator.set_settings(
                        thinking_mode=data.get("thinking_mode"),
                        token_budget=data.get("token_budget"),
                        max_steps=data.get("max_steps"),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/cortex/queue":
            try:
                import cortex_orchestrator
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    cortex_orchestrator.queue_run(
                        int(data.get("agent_id") or 0),
                        str(data.get("prompt") or ""),
                        session_id=int(data.get("session_id") or 0),
                        parent_run_id=int(data.get("parent_run_id") or 0),
                        is_subagent=bool(data.get("is_subagent")),
                        skill_pack=str(data.get("skill_pack") or ""),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/invoke/skills":
            try:
                import invoke_registry
                data = json.loads(self._body().decode() or "{}")
                if str(data.get("action") or "").lower() in ("enable", "set_scope", "scope"):
                    return self._json(
                        200,
                        invoke_registry.set_skill_enabled(
                            str(data.get("id") or data.get("skill_id") or ""),
                            scope=str(data.get("scope") or "global"),
                        ),
                    )
                return self._json(
                    200,
                    invoke_registry.save_skill(
                        str(data.get("id") or data.get("skill_id") or ""),
                        str(data.get("body") or data.get("text") or ""),
                        title=str(data.get("title") or data.get("name") or ""),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/invoke/rules":
            try:
                import invoke_registry
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    invoke_registry.save_rules(
                        str(data.get("text") or data.get("body") or ""),
                        prefer=str(data.get("prefer") or "airgpt"),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/openide/backend":
            try:
                import cursor_bridge
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, cursor_bridge.set_backend(str(data.get("backend") or "local")))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/openforge/design":
            try:
                import openforge_chip
                data = json.loads(self._body().decode() or "{}")
                spec = str(data.get("spec") or data.get("text") or "").strip()
                if not spec:
                    return self._json(400, {"error": "spec required"})
                return self._json(200, openforge_chip.design(spec))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/terminal/exec":
            try:
                import terminal_pty
                import workspace_api
                data = json.loads(self._body().decode() or "{}")
                cmd = str(data.get("cmd") or "").strip()
                sid = str(data.get("session_id") or "")
                ws = workspace_api.get_workspace()
                cwd = ws.get("root") or ""
                if sid:
                    return self._json(200, terminal_pty.exec_in_session(sid, cmd))
                return self._json(200, terminal_pty.run_command(cmd, cwd=cwd))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/marketplace/auto-serve":
            try:
                import marketplace
                data = json.loads(self._body().decode() or "{}")
                item_id = str(data.get("item_id") or "mod-llama-cpp")
                job = marketplace.queue_install(item_id, confirm=True)
                bind = marketplace.bind_serve(item_id)
                return self._json(200, {"ok": True, "install": job, "serve": bind})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/import":
            # Restores overwrite files under the app root (source, env.local,
            # HTML) — an unauthenticated/guest write here is remote code
            # execution on next restart. Host machine only.
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            ctype = self.headers.get("Content-Type", "")
            if "multipart" not in ctype:
                return self._json(400, {"error": "multipart zip required"})
            form = _parse_multipart(self._body(), ctype)
            up = form.get("file")
            if not isinstance(up, dict) or not up.get("data"):
                return self._json(400, {"error": "no file"})
            import zipfile
            root_resolved = ROOT.resolve()
            _blocked = {"env.local", ".env", "license.json", "clipdrop.py", "config.py"}
            try:
                with zipfile.ZipFile(io.BytesIO(up["data"])) as zf:
                    for name in zf.namelist():
                        norm = name.replace("\\", "/")
                        if ".." in norm.split("/") or norm.startswith("/") or ":" in norm:
                            continue
                        target = (ROOT / norm.replace("/", os.sep))
                        # Zip-slip guard: resolved path must stay inside ROOT
                        try:
                            resolved = target.resolve()
                            resolved.relative_to(root_resolved)
                        except (ValueError, OSError):
                            continue
                        if resolved.name in _blocked:
                            continue
                        if name.endswith("/"):
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(zf.read(name))
                bump_sync()
                return self._json(200, {"ok": True, "message": "Import complete — refresh page"})
            except Exception as e:
                return self._json(400, {"error": f"import failed: {e}"})

        return self._json(404, {"error": "not found"})

    def do_PATCH(self):
        path = urlparse(self.path).path
        ip = self._client_ip()
        if not self._auth_ok(path):
            return self._json(401, {"error": "auth required", "auth": True})
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return self._json(400, {"error": "bad json"})
        if path.startswith("/api/sessions/"):
            try:
                sid = int(path.rstrip("/").split("/")[-1])
            except ValueError:
                return self._json(400, {"error": "bad id"})
            kw = {}
            if "title" in body:
                kw["title"] = str(body["title"])[:120]
            if "pinned" in body:
                kw["pinned"] = bool(body["pinned"])
            if "archived" in body:
                kw["archived"] = bool(body["archived"])
            if "category" in body:
                kw["category"] = str(body["category"])[:20]
            if "summary" in body:
                kw["summary"] = str(body["summary"])[:500]
            if kw:
                db.update_session_meta(sid, **kw)
            return self._json(200, {"ok": True})
        if path.startswith("/api/agents/"):
            try:
                import agent_store
                aid = int(path.rstrip("/").split("/")[-1])
            except Exception:
                return self._json(400, {"error": "bad id"})
            if "pinned" not in body:
                return self._json(400, {"error": "pinned required"})
            agent = agent_store.set_agent_pinned(aid, bool(body.get("pinned")))
            if not agent:
                return self._json(404, {"error": "agent not found or not pin-able"})
            return self._json(200, {"ok": True, "agent": agent})
        if path == "/api/access/approve":
            try:
                import access_policy
            except ImportError:
                return self._json(503, {"error": "access policy unavailable"})
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            return self._json(200, access_policy.approve(body.get("ip", ""), body.get("name", "")))
        if path == "/api/access/deny":
            try:
                import access_policy
            except ImportError:
                return self._json(503, {"error": "access policy unavailable"})
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            return self._json(200, access_policy.deny(body.get("ip", "")))
        return self._json(404, {"error": "not found"})

    def do_DELETE(self):
        path = urlparse(self.path).path
        ip = self._client_ip()
        if not self._auth_ok(path):
            return self._json(401, {"error": "auth required", "auth": True})
        if path == "/api/messages":
            # Bulk clear wipes every message for everyone — host action only.
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only — bulk clear is a host action"})
            n = db.clear_all_messages()
            return self._json(200, {"ok": True, "deleted": n})
        if path.startswith("/api/sessions/"):
            # Deleting a session removes another peer's chat — host action only.
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            sid = int(path.split("/")[-1])
            db.delete_session(sid)
            return self._json(200, {"ok": True})
        if path.startswith("/api/messages/"):
            mid = int(path.split("/")[-1])
            db.delete_message(mid)
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "not found"})


def _save_network_state(ips: list[str]) -> None:
    try:
        NET_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        lan = f"http://{ips[0]}:{PORT}" if ips else ""
        NET_STATE_FILE.write_text(
            json.dumps({"ip": ips[0] if ips else "", "ips": ips, "lan_url": lan, "ts": int(time.time())}),
            encoding="utf-8",
        )
    except OSError:
        pass


def network_watcher() -> None:
    """Re-sync UI and tunnel when WiFi IP changes (hotspot, home router, etc.)."""
    global _network_epoch
    last = ""
    last_profile = ""
    while True:
        time.sleep(20)
        refresh_firewall_status()
        profile = network_profile()
        if profile != last_profile and last_profile:
            print(f"[network] profile changed {last_profile} -> {profile}")
            bump_sync()
        last_profile = profile
        ips = local_ips()
        key = ",".join(ips)
        if key and key != last:
            if last:
                print(f"[network] IP changed {last} → {key} — restarting tunnel")
                _network_epoch += 1
                _save_network_state(ips)
                bump_sync()
                restart_tunnel()
            else:
                _save_network_state(ips)
            if wifi_access:
                wifi_access.stop_mdns()
                wifi_access.start_mdns(PORT)
            last = key


def _startup_verify() -> None:
    """Auto health-check after server boots."""
    time.sleep(2.5)
    try:
        import urllib.request
        base = f"http://127.0.0.1:{PORT}"
        checks = ["/api/probe", "/api/info", "/api/history", "/api/ai/config", "/api/audit"]
        ok = 0
        for path in checks:
            try:
                r = urllib.request.urlopen(base + path, timeout=5)
                if r.status == 200:
                    ok += 1
            except Exception:
                pass
        print(f"[verify] {ok}/{len(checks)} API checks passed")
        if ok < len(checks):
            print("[verify] Some endpoints failed — check logs")
    except Exception as e:
        print(f"[verify] skipped: {e}")


def main():
    global _firewall_status, AI_AUTO
    AI_AUTO = _load_ai_auto()
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((HOST, PORT))
        probe.close()
    except OSError:
        print(f"Port {PORT} in use. Run restart.bat first.")
        return

    _firewall_status = try_firewall()
    if wifi_access:
        wifi_access.start_mdns(PORT)
    try:
        if app_license:
            hb = app_license.heartbeat()
            print(f"[license] sku={hb.get('sku')} online={hb.get('online', 'n/a')}")
    except Exception as e:
        print(f"[license] heartbeat skip: {e}")
    threading.Thread(target=clipboard_loop, daemon=True).start()
    threading.Thread(target=screenshot_loop, daemon=True).start()
    threading.Thread(target=tunnel_worker, daemon=True).start()
    threading.Thread(target=tunnel_health_loop, daemon=True).start()
    threading.Thread(target=network_watcher, daemon=True).start()
    threading.Thread(target=_startup_verify, daemon=True).start()
    try:
        import cortex_orchestrator
        cortex_orchestrator.ensure_worker()
    except Exception as e:
        print(f"[cortex] orchestrator skip: {e}")

    ips = local_ips()
    print(f"\n=== {APP_NAME} v{APP_VERSION} ===")
    print(f"  PC:     http://127.0.0.1:{PORT}")
    if wifi_access and wifi_access.mdns_url():
        print(f"  WiFi:   {wifi_access.mdns_url()}  (easy name, same WiFi)")
    if ips:
        print(f"  WiFi:   http://{ips[0]}:{PORT}")
    print("  Tunnel: starting (check UI for iPad URL)")
    print("  P2P:    http://127.0.0.1:8765/p2p  (no firewall needed)")
    print("  Restart: run restart.bat when you change WiFi\n")

    # Ensure a clean bind — kill stale listeners / orphan tunnels from prior runs
    _kill_orphan_cloudflared()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()

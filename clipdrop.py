"""ClipDrop v5 — ChatGPT-style LAN chat. SQLite + multi-tunnel."""
from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import os
import queue
import re
import secrets
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
_server_mode = "general"

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
_tunnel = {"url": "", "provider": "", "status": "off", "error": "", "healthy": False, "started_at": 0,
           # last_provider survives a failed sweep; provider is only ever the one serving.
           "last_provider": ""}
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
# Ceiling on skills armed for one send. Each pack costs up to 2000 chars of preamble,
# so an unbounded list is a quiet way to blow the context budget on instructions.
MAX_ARMED_SKILLS = 3
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


def _kill_proc_tree(p: subprocess.Popen) -> None:
    """Kill the process AND its children.

    tunnel_localtunnel spawns `npx localtunnel` with shell=True, so the handle we
    hold is the cmd/npx wrapper - terminate() kills the wrapper and leaves the real
    `lt.js` node process alive, still holding a loca.lt URL nobody is tracking. Two
    orphan pairs were observed on one machine. Orphans accumulate every sweep and
    the provider starts refusing new tunnels, which is what "localtunnel totally
    down" actually looks like. Kill the tree, not the handle.
    """
    pid = getattr(p, "pid", None)
    if os.name == "nt" and pid:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, text=True, timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
        except Exception as e:
            print(f"[tunnel] tree kill {pid} skip: {e}")
    elif pid:
        # No tree kill off Windows. The tunnel children are not spawned with
        # start_new_session, so they sit in our own process group and os.killpg
        # would take AirGPT down with them. terminate() below reaps the wrapper
        # only - which is exactly the orphan this function exists to prevent - so
        # say so out loud rather than degrade in silence.
        print(
            f"[tunnel] no tree kill on os.name={os.name}: terminating wrapper {pid} "
            f"only, its children may orphan"
        )
    try:
        p.terminate()
        p.wait(timeout=2)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def _kill_tunnel_procs() -> None:
    with _tunnel_lock:
        for p in _tunnel_procs:
            _kill_proc_tree(p)
        _tunnel_procs.clear()
    _kill_orphan_cloudflared()


def restart_tunnel() -> None:
    global _qr_join_cache
    _qr_join_cache.clear()
    _kill_tunnel_procs()
    _tunnel.update(url="", provider="", status="restarting", error="", healthy=False)
    threading.Thread(target=tunnel_worker, daemon=True).start()


def _boot_tunnel_threads() -> None:
    """Kill leftover cloudflared *then* start the worker. Never the reverse.

    On Windows `_kill_orphan_cloudflared` is `taskkill /IM cloudflared.exe`.
    `main()` used to start `tunnel_worker` and then kill orphans just before
    bind, which murdered the process the worker had just spawned. Observed as
    cloudflared exiting code 1 after 1s with no forwarding URL on a normal
    `python clipdrop.py` boot.
    """
    _kill_orphan_cloudflared()
    threading.Thread(target=tunnel_worker, daemon=True).start()
    threading.Thread(target=tunnel_health_loop, daemon=True).start()


def _image_file_path(msg: dict) -> Path | None:
    rel = msg.get("filepath")
    if not rel:
        return None
    p = db.FILES.parent / rel.replace("/", os.sep)
    if p.is_file():
        return p
    p2 = DATA_DIR / rel
    return p2 if p2.is_file() else None


def _ai_lockdown_block() -> dict | None:
    """Return error payload when emergency cut-off is on."""
    try:
        import access_policy

        return access_policy.lockdown_block()
    except Exception:
        return None


def _ai_allowed() -> bool:
    if not app_license:
        return True
    return bool(app_license.get_status().get("can_use_ai"))


def _s1_remote_open() -> bool:
    """LAN/tunnel may reach chat only after the host has set a passcode (S1 / D10)."""
    if not app_auth:
        return False
    try:
        return bool(app_auth.status().get("passcode_set"))
    except Exception:
        return False


_S1_OPEN_PATHS = frozenset({
    "/api/probe",
    "/api/health",
    "/healthz",
    "/health",
    "/api/auth/status",
    "/wasm_gate.js",
    "/manifest.json",
})


def _s1_path_open(path: str) -> bool:
    return path in _S1_OPEN_PATHS


def _tunnel_allowed() -> bool:
    if not _s1_remote_open():
        return False
    if not app_license:
        return True
    return bool(app_license.get_status().get("can_use_tunnel"))


_bg_inflight: dict[str, threading.Lock] = {}


def _kick_once(name: str, fn) -> None:
    """One daemon at a time per name. Callers never join it."""
    lock = _bg_inflight.setdefault(name, threading.Lock())
    if not lock.acquire(blocking=False):
        return

    def _run() -> None:
        try:
            fn()
        except Exception as e:
            print(f"[{name}] {type(e).__name__}: {e}")
        finally:
            lock.release()

    threading.Thread(target=_run, daemon=True, name=name).start()


def _probe_online() -> None:
    """Fills _online_cache. Never call from /api/info -- it hits the public internet."""
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
    _online_cache["ts"] = time.time()


def _is_online() -> bool:
    """Internet available. Request-path never waits on Google or Cloudflare.

    A cold cache used to urlopen two public hosts (1.5s each) on every first
    /api/info. Combined with netsh + PowerShell in lan_diagnostics that is the
    12s hang the phone reads as a dead host (HOST-DEMO-03 / R-0011).
    """
    if _tunnel.get("healthy") and _tunnel.get("url"):
        _online_cache.update(ok=True, ts=time.time())
        return True
    now = time.time()
    stale = _online_cache["ts"] == 0 or (now - _online_cache["ts"] >= 20)
    if stale:
        _kick_once("online-probe", _probe_online)
    return bool(_online_cache["ok"])


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


def run_analysis(msg_id: int, question: str | None = None, mode: str = "general", session_id: int = 0, depth: str = "normal") -> None:
    blocked = _ai_lockdown_block()
    if blocked:
        err = "Host disabled AI. Your work is saved."
        if question:
            db.add_message(device_ip="127.0.0.1", device_name="AirGPT", text=err, kind="text", source="ai", session_id=session_id)
            bump_sync()
        else:
            db.update_ai(msg_id, status="error", analysis=err)
            bump_sync()
        return
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
        if result.get("error") == "ai_lockdown":
            err = "Host disabled AI. Your work is saved."
            if question:
                db.add_message(device_ip="127.0.0.1", device_name="AirGPT", text=err, kind="text", source="ai", session_id=session_id)
            else:
                db.update_ai(msg_id, status="error", analysis=err)
            bump_sync()
            return
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


def queue_analysis(msg_id: int, question: str | None = None, mode: str = "general", session_id: int = 0, depth: str = "normal") -> None:
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
    blocked = _ai_lockdown_block()
    if blocked:
        db.add_message(
            device_ip="127.0.0.1",
            device_name="AirGPT",
            text="Host disabled AI. Your work is saved.",
            kind="text",
            source="ai",
            session_id=session_id,
        )
        bump_sync()
        return
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
        if result.get("error") == "ai_lockdown":
            db.add_message(
                device_ip="127.0.0.1",
                device_name="AirGPT",
                text="Host disabled AI. Your work is saved.",
                kind="text",
                source="ai",
                session_id=session_id,
            )
            bump_sync()
            return
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
    web_search: bool = False,
):
    """Yield stream events; respects abort flag between chunks."""
    if abort.is_set():
        return
    blocked = _ai_lockdown_block()
    if blocked:
        yield {
            "type": "error",
            "error": blocked["error"],
            "by": blocked.get("by") or "host",
            "text": "Host disabled AI. Your work is saved.",
            "ok": False,
        }
        return
    import agent_tools as _atools
    if _atools.is_pomodoro_ask(question or ""):
        yield {"type": "thinking", "text": "Scaffolding pomodoro…", "session_id": session_id}
        sc = _atools.scaffold_from_ask(question or "")
        yield {
            "type": "tool",
            "name": "app_scaffold",
            "result": sc,
            "session_id": session_id,
        }
        if sc.get("ok") and sc.get("url"):
            analysis = f"Live app at {sc.get('url')}"
            yield {"type": "token", "text": analysis, "session_id": session_id}
            yield {
                "type": "done",
                "analysis": analysis,
                "model": "app_scaffold",
                "session_id": session_id,
                "stop_reason": "quality",
                "quality_passed": True,
                "runner": "app_scaffold",
            }
            return
        yield {
            "type": "thinking",
            "text": f"Scaffold skipped: {sc.get('error') or 'failed'}",
            "session_id": session_id,
        }
    # F20b / DR-0002: every chat turn is Cortex AGENT_TASK. web_search only
    # adds tools. A ChatGPT-looking composer that skips the loop unless a toggle
    # is on is the same R-0011 as a Saved control that changes nothing.
    try:
        import cortex_client

        yield {"type": "thinking", "text": "Cortex quality loop…", "session_id": session_id}
        loop_prompt = question or ""
        if history:
            prior = []
            for m in history[-8:]:
                if not isinstance(m, dict):
                    continue
                role = str(m.get("role") or "user")
                content = str(m.get("content") or "").strip()[:500]
                if content:
                    prior.append(f"{role}: {content}")
            if prior:
                loop_prompt = "Prior turns:\n" + "\n".join(prior) + "\n\nUser:\n" + loop_prompt
        loop_kw: dict = {
            "session_id": f"chat-{session_id}",
            "max_steps": 6,
            "timeout": 180.0,
        }
        if web_search:
            loop_kw["tools"] = ["web_search", "web_fetch"]
        cortex = cortex_client.engine_agent_loop(loop_prompt, **loop_kw)
    except Exception as e:
        cortex = {"ok": False, "error": str(e)[:200]}
    if isinstance(cortex, dict) and cortex.get("ok") and (cortex.get("content") or "").strip():
        for t in ((cortex.get("telemetry") or {}).get("tools") or []):
            if not isinstance(t, dict):
                continue
            yield {
                "type": "tool",
                "name": str(t.get("tool") or "tool"),
                "result": {"ok": t.get("ok"), "summary": t.get("summary")},
                "session_id": session_id,
            }
        analysis = str(cortex.get("content") or "")
        yield {"type": "token", "text": analysis, "session_id": session_id}
        yield {
            "type": "done",
            "analysis": analysis,
            "model": "cortex-agent",
            "session_id": session_id,
            "stop_reason": cortex.get("stop_reason"),
            "quality_passed": cortex.get("quality_passed"),
            "runner": "agent_task",
        }
        return
    why = ""
    if isinstance(cortex, dict):
        why = str(cortex.get("error") or cortex.get("stop_reason") or "")[:180]
    yield {
        "type": "thinking",
        "text": f"Quality loop skipped: {why or 'no answer'}",
        "session_id": session_id,
    }
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
            force_web=web_search,
        ):
            if abort.is_set():
                return
            yield ev
    except Exception as e:
        yield {"type": "error", "text": str(e)[:800]}


def _skill_tools(path: str) -> list[str]:
    """Tools a skill pack actually names in its text.

    Packs carry no front matter, so there is nothing to declare a tools list. Rather
    than invent one, report the canonical tool names the pack mentions — an empty list
    is an honest answer for a prose-only pack.
    """
    if not path:
        return []
    try:
        import agent_tools

        names = sorted(agent_tools.TOOLS.keys())
    except Exception:
        return []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return []
    return [n for n in names if n in text][:8]


def _file_capture_to_vault(msg: dict, msg_id: int, analysis: str, mode: str = "general", early: dict | None = None) -> None:
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


def _ai_lockdown_payload() -> dict:
    """Emergency AI cut-off state for /api/info and /api/wait."""
    try:
        import access_policy

        return access_policy.get_ai_lockdown()
    except Exception:
        return {"on": False}


def _app_state_payload(q) -> dict:
    """Live App Card shared state delta for /api/wait (no websocket)."""
    try:
        import apps_hub

        since = 0
        try:
            since = int((q.get("app_epoch") or ["0"])[0])
        except Exception:
            since = 0
        return apps_hub.app_state_poll(since)
    except Exception:
        return {"epoch": 0, "updates": []}


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
    "/api/workflows",   # background phased subagent fan-out (runs tools)
    "/api/invoke/",     # create/update rules & skills (workspace write)
    "/api/openide/",    # IDE backend/ready/last-run/scaffold
    "/api/openvault/",  # OpenVault mesh handshake / connect-pack (E:\OpenVault)
    "/api/openforge/",  # chip design pipeline
    "/api/rag",         # RAG Agent knowledge spaces / ingest / answer (host-only)
    "/api/github",      # GitHub OAuth device flow + status (token write)
    "/api/engine",      # engine plan/apply + bakeoff (changes how this PC serves models)
    "/api/desktop",     # computer-use observe/plan/click/type (host PC only)
    "/api/admin",       # admin dashboard data (covers /api/admin[/*])
    "/api/audit",       # audit trail (covers /api/audit[/*])
)


def _is_host_only_path(path: str) -> bool:
    return any(path == p or path.startswith(p) for p in _HOST_ONLY_PREFIXES)


# HOST-DEMO-02 / F8a: non-local clients must complete POST /api/establish before
# /api/ai/* and the chat POST paths the phone uses. Local host keeps today's path.
# A leftover token (issued, never bound) is refused until it is bound here.
AIRGPT_SECURITY_VERSION = "1"
SESSION_NONCE_HEADER = "X-AirGPT-Session-Nonce"
SECURITY_VERSION_HEADER = "X-AirGPT-Security-Version"
_ESTABLISH_CHAT_POSTS = frozenset({
    "/api/chat/stream",
    "/api/chat/project-suggest",
    "/api/messages",
})
_establish: dict[str, dict] = {}
_establish_token: dict[str, str] = {}


def _needs_establish(method: str, path: str) -> bool:
    if path.startswith("/api/ai"):
        return True
    if method == "POST" and (path in _ESTABLISH_CHAT_POSTS or path.startswith("/api/chat/")):
        return True
    return False


def _is_tunnel_host(host: str) -> bool:
    h = (host or "").split(":")[0].lower()
    return any(x in h for x in (
        "trycloudflare.com", "lhr.life", "loca.lt", "serveo.net", "localhost.run",
    ))


# Stands in for a tunnel peer we cannot name. Deliberately not IP-shaped: it must
# never satisfy _is_local_host(), and it should be obvious in an audit row that the
# peer was unidentified rather than at some address we invented.
TUNNEL_PEER = "tunnel-peer"


def _is_host_request(headers, direct_ip: str) -> bool:
    """True only for the host machine itself, never for anything off a tunnel.

    The host-only gate used to be `not _is_local_host(ip)` over an ip that could be
    supplied by the caller. Two independent things had to hold for that to be safe,
    and neither is checked here, so this asks the question directly instead: a
    request carrying a tunnel Host header came from outside this machine, whatever
    any header claims.
    """
    if _is_tunnel_host(headers.get("Host", "")):
        return False
    return _is_local_host(_forwarded_client_ip(headers, direct_ip) or direct_ip)


def _forwarded_client_ip(headers, direct_ip: str) -> str | None:
    """Real remote client when cloudflared (or similar) proxies on loopback."""
    if direct_ip not in ("127.0.0.1", "::1"):
        return None
    if not _is_tunnel_host(headers.get("Host", "")):
        return None
    cf = (headers.get("CF-Connecting-IP") or "").strip()
    xff = (headers.get("X-Forwarded-For") or "").strip()
    cand = cf or (xff.split(",")[0].strip() if xff else "")
    # These headers are client-supplied. Only a provider that overwrites them makes
    # them trustworthy, and we cannot tell from here which provider is in front of
    # us: cloudflared sets CF-Connecting-IP, localtunnel sets X-Forwarded-For and
    # touches nothing Cloudflare-shaped, and serveo/localhost.run are raw ssh
    # forwards that set neither. So a caller could send CF-Connecting-IP: 127.0.0.1
    # and _is_local_host() would hand a remote peer all 17 _HOST_ONLY_PREFIXES,
    # /api/terminal/ and /api/fs/ included. Verified against a live loca.lt tunnel:
    # GET /api/audit returned 403 bare and 200 with that one header.
    # A request that arrived over a tunnel is remote by definition, so a forwarded
    # value claiming to be this machine is always a lie. Refuse it, and fall back to
    # a marker that is deliberately not an address so nothing downstream can mistake
    # it for one.
    if cand and not _is_local_host(cand):
        return cand
    return TUNNEL_PEER


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


def _lan_fallback() -> dict:
    ips = local_ips()
    return {
        "ips": ips,
        "lan_url": f"http://{ips[0]}:{PORT}" if ips else None,
        "network_profile": "Unknown",
        "firewall": _firewall_status or "unknown",
        "listening": f"0.0.0.0:{PORT}",
        "lan_likely_blocked": False,
        "hint": "LAN diagnostics pending -- retry or run enable-lan.bat",
        "pending": True,
    }


def _compute_lan_diagnostics() -> dict:
    """PowerShell + netsh. Background only -- never the /api/info thread."""
    ips = local_ips()
    profile = network_profile()
    fw = refresh_firewall_status()
    blocked = profile == "Public" and fw != "ok"
    if fw == "ok" and profile == "Private":
        hint = "Same WiFi: scan LAN QR below. Phone must be on the same network as this PC."
    elif fw == "ok" and profile == "Public":
        hint = "Firewall OK but WiFi is Public -- run allow_firewall.ps1 as Admin to switch to Private, then scan LAN QR."
    elif profile == "Public":
        hint = "LAN blocked -- run allow_firewall.ps1 as Admin (sets Private + opens port 8765). Or use Tunnel QR."
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
    _lan_diag_cache["ts"] = time.time()
    _lan_diag_cache["value"] = dict(out)
    return out


def lan_diagnostics(*, wait: bool = False) -> dict:
    """LAN snapshot for /api/info. Default is cache-or-fallback, never netsh.

    wait=True is for enable-lan / lag tests that need the computed row.
    """
    now = time.time()
    cached = _lan_diag_cache.get("value")
    if cached and now - float(_lan_diag_cache["ts"]) < 30.0:
        return dict(cached)
    if wait:
        return dict(_compute_lan_diagnostics())
    _kick_once("lan-diag", _compute_lan_diagnostics)
    if cached:
        return dict(cached)
    return _lan_fallback()


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
    """Stable PNG bytes for storage (clipboard DIB can vary slightly)."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        buf = io.BytesIO()
        # Keep ICC out of stored PNG so encode paths stay close; identity
        # dedupe uses _image_content_hash (pixels), not these bytes.
        im_rgb = im.convert("RGB")
        im_rgb.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        return raw


def _image_content_hash(raw: bytes) -> str:
    """SHA-256 over RGB pixels (size + bytes). Ignores ICC/PNG encoding noise."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        w, h = im.size
        return hashlib.sha256(f"{w}x{h}:".encode() + im.tobytes()).hexdigest()
    except Exception:
        return hashlib.sha256(raw or b"").hexdigest()


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
            h = _image_content_hash(file_data)
        else:
            h = hashlib.sha256(file_data).hexdigest()
        hash_preclaimed = False
        if allow_duplicate and session_id:
            if db.hash_seen_in_session(h, session_id):
                return None
        else:
            # Claim before save_file so losers never write orphan media
            if not db.claim_hash(h):
                return None
            hash_preclaimed = True
        rel, mime, thumb, kind = save_file(file_data, filename or "file.bin")
        msg = db.add_message(
            device_ip=device_ip, device_name=device_name, text=text,
            kind=kind, filename=filename, filepath=rel, thumb=thumb, mime=mime,
            size=len(file_data), source=source, content_hash=h, session_id=session_id,
            allow_duplicate=allow_duplicate, hash_preclaimed=hash_preclaimed,
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


# The Windows clipboard is a single global lock held per-thread. The 0.35s
# poller and the HTTP handler threads must never race for it, and nothing slow
# may run while it is held: a stuck holder breaks Ctrl+C for every app on the
# machine (observed: OpenClipboard 0/20, GetOpenClipboardWindow NULL, capture
# dead for 48 minutes).
_CLIPBOARD_LOCK = threading.Lock()
_clip_open_fail_logged = 0.0


def _open_clipboard(win32clipboard, *, attempts: int = 3) -> bool:
    """Open with bounded retry. Never silently swallow a persistent failure."""
    global _clip_open_fail_logged
    last = None
    for i in range(attempts):
        try:
            win32clipboard.OpenClipboard(None)
            return True
        except Exception as e:  # another app owns it for a moment
            last = e
            time.sleep(0.05 * (i + 1))
    now = time.time()
    if now - _clip_open_fail_logged > 60:
        _clip_open_fail_logged = now
        print(f"[clipboard] cannot open (holder busy or stuck): {last}")
    return False


def read_clipboard():
    try:
        import win32clipboard
        import win32con
        from PIL import Image
    except ImportError:
        return "", None, None

    kind = None
    payload = None
    text = None
    # Phase 1: hold the OS lock only long enough to copy bytes out.
    with _CLIPBOARD_LOCK:
        if not _open_clipboard(win32clipboard):
            return "", None, None
        try:
            for fmt_name in ("PNG", "JFIF"):
                fmt = win32clipboard.RegisterClipboardFormat(fmt_name)
                if win32clipboard.IsClipboardFormatAvailable(fmt):
                    raw = win32clipboard.GetClipboardData(fmt)
                    if raw and len(raw) > 80:
                        kind, payload = "encoded", bytes(raw)
                        break
            if kind is None and win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB):
                kind = "dib"
                payload = bytes(win32clipboard.GetClipboardData(win32clipboard.CF_DIB))
            if kind is None and win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                t = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                if t and str(t).strip():
                    kind, text = "text", str(t)
        except Exception:
            pass
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass

    # Phase 2: decode / re-encode with the OS lock released.
    if kind == "encoded":
        return "image", payload, None
    if kind == "dib" and payload:
        try:
            _, _, _, _, _, off = struct.unpack("<LLLLLL", payload[:24])
            bmp = (
                b"BM"
                + struct.pack("<I", len(payload) + 14)
                + b"\0\0\0\0"
                + struct.pack("<I", 14 + off)
                + payload
            )
            img = Image.open(io.BytesIO(bmp))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="PNG", optimize=True)
            return "image", buf.getvalue(), None
        except Exception:
            return "", None, None
    if kind == "text":
        return "text", None, text
    return "", None, None


CLIPBOARD_SNIP_DEFER_SEC = 1.2


def suppress_clipboard_watch(seconds: float = 5.0) -> None:
    global _suppress_clipboard_until
    _suppress_clipboard_until = time.time() + seconds


def write_clipboard_text(text: str) -> bool:
    global _last_text_hash
    try:
        import win32clipboard
        import win32con
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        suppress_clipboard_watch(5.0)
        with _CLIPBOARD_LOCK:
            if not _open_clipboard(win32clipboard):
                return False
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            finally:
                # Without this, a SetClipboardData failure leaks the global
                # clipboard lock for the life of the process.
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass
        _last_text_hash = h
        # Reserve hash so watcher does not re-ingest our own write
        db.claim_hash(h)
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
        h = _image_content_hash(data)
        im = Image.open(io.BytesIO(data))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "BMP")
        dib = buf.getvalue()[14:]
        buf.close()
        suppress_clipboard_watch(5.0)
        _last_img_hash = h
        # Claim before SetClipboardData so a racing watcher cannot publish a replica
        db.claim_hash(h)
        with _CLIPBOARD_LOCK:
            if not _open_clipboard(win32clipboard):
                return False
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
            finally:
                # Without this, a SetClipboardData failure leaks the global
                # clipboard lock for the life of the process.
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass
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
                h = _image_content_hash(img)
                if h == _last_img_hash or db.hash_seen(h):
                    _last_img_hash = h
                else:
                    as_shot = bool(
                        _client_ai_enabled and AI_AUTO and ai_engine and _looks_like_screenshot(img)
                    )
                    if as_shot:
                        # Prefer Screenshots folder watcher; only publish if folder never claims
                        time.sleep(CLIPBOARD_SNIP_DEFER_SEC)
                        if time.time() < _suppress_clipboard_until or h == _last_img_hash or db.hash_seen(h):
                            _last_img_hash = h
                        else:
                            _last_img_hash = h
                            r = post_capture_image(
                                "127.0.0.1", hostname(), img,
                                f"snip_{datetime.now():%H%M%S}.png", "screenshot",
                                with_ai=True,
                            )
                            if r:
                                print("[clip] clipboard snip → AI Screenshot Chat")
                            else:
                                print("[clip] clipboard snip skipped (folder/claim won)")
                    else:
                        _last_img_hash = h
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
                    h = _image_content_hash(data)
                    _seen_ss[key] = mtime
                    if h == _last_img_hash or db.hash_seen(h):
                        _last_img_hash = h
                        continue
                    r = post_capture_image("127.0.0.1", hostname(), data, f.name, "screenshot")
                    if r:
                        _last_img_hash = h
                        suppress_clipboard_watch(5.0)
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


_asset_cache: dict[str, tuple[float, int, bytes, str]] = {}
_asset_gzip: dict[str, bytes] = {}


def _cached_asset(p: Path) -> tuple[bytes, str]:
    """File bytes + a content ETag, re-read only when mtime or size changes."""
    key = str(p)
    st = p.stat()
    hit = _asset_cache.get(key)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2], hit[3]
    body = p.read_bytes()
    etag = '"%s"' % hashlib.sha256(body).hexdigest()[:20]
    _asset_cache[key] = (st.st_mtime, st.st_size, body, etag)
    _asset_gzip.pop(etag, None)
    return body, etag


def _maybe_gzip(body: bytes, accept: str) -> tuple[bytes, str]:
    """Gzip when the client accepts it and it is worth the CPU."""
    if "gzip" not in (accept or "").lower() or len(body) < 1024:
        return body, ""
    etag = '"%s"' % hashlib.sha256(body).hexdigest()[:20]
    cached = _asset_gzip.get(etag)
    if cached is None:
        import gzip as _gzip

        cached = _gzip.compress(body, 6)
        # Only worth serving if it actually got smaller.
        if len(cached) >= len(body):
            cached = b""
        _asset_gzip[etag] = cached
    return (cached, "gzip") if cached else (body, "")


def _with_deadline(fn, default, timeout: float = 2.0):
    """Run fn in a worker; return default if it exceeds timeout (never block /api/info).

    The `with ThreadPoolExecutor(...)` form did not honour the timeout at all: leaving
    the block calls shutdown(wait=True), which waits for the very task the timeout
    just gave up on. `/api/info` blocked for the full duration of whatever it wrapped
    no matter what deadline was passed - the docstring above was describing behaviour
    the code did not have.
    """
    import concurrent.futures

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn).result(timeout=timeout)
    except Exception:
        return default
    finally:
        # wait=False is the whole point: abandon the straggler, do not join it.
        pool.shutdown(wait=False)


# What /api/hosting answers while a cold backend fan-out is still in flight. Say
# "checking", never "offline": a slow probe is not a dead backend, and the poll
# 8s later gets the real verdict off hosting.py's warmed cache.
_HOSTING_PENDING: dict = {
    "ok": True,
    "pending": True,
    "ollama": {"ok": False, "status": "checking"},
    "vllm": {"ok": False, "status": "checking"},
    "sglang": {"ok": False, "status": "checking"},
    "colibri": {"ok": False, "status": "checking"},
    "collaboration": {"note": "Checking backend health…"},
}


def _cortex_info_compute(*, quick: bool = False) -> dict:
    """Hits the Cortex sidecar. Background only -- never the /api/info thread."""
    key = "quick" if quick else "full"
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
        _cortex_info_cache["ts"] = time.time()
        _cortex_info_cache[key] = dict(info)
        return info
    except Exception:
        info = {"ok": False, "status": "unavailable", "audit_sample": [], "ledger_verify": {"ok": False}}
        _cortex_info_cache["ts"] = time.time()
        _cortex_info_cache[key] = dict(info)
        return info


def _cortex_info(*, quick: bool = False) -> dict:
    """Cached Cortex snapshot. A hung :8011 must not stall /api/info."""
    now = time.time()
    key = "quick" if quick else "full"
    cached = _cortex_info_cache.get(key)
    ttl = 8.0 if quick else 15.0
    if cached and now - float(_cortex_info_cache["ts"]) < ttl:
        return dict(cached)
    _kick_once("cortex-info", lambda: _cortex_info_compute(quick=quick))
    if cached:
        return dict(cached)
    return {
        "ok": False,
        "status": "checking",
        "audit_sample": [],
        "ledger_verify": {"ok": False},
        "pending": True,
    }


# --- HOST-DEMO-03 tunnel wall-clock budgets -------------------------------------
# Nothing here bounded time. _probe_tunnel_url ran 24 attempts x (6s urlopen + 2s
# sleep) = up to ~192s for one doomed candidate; the four read windows alone totalled
# ~172s per pass and tunnel_worker made two passes. "No provider is reachable" took
# roughly six minutes to say, which the founder reads as a hang, not as an answer
# (R-0011). Everything below is sized so a sweep either succeeds or reports.
#
# Per-provider slice for reading stdout until a forwarding URL appears. Sized from
# what each provider actually costs to start: npx has to cold-start localtunnel out
# of the registry, so it gets the widest slice; the two ssh providers print their
# banner within a couple of seconds or never; cloudflared answers in single digits
# unless it is rate-limited, in which case it says so immediately. R-0005: these are
# the slow-but-still-working ceiling, not the typical case - a provider that is going
# to work is comfortably inside its slice.
TUNNEL_PROVIDER_BUDGET = {
    "cloudflared": 30.0,
    "localhost.run": 20.0,
    "localtunnel": 25.0,
    "serveo.net": 20.0,
}
# Wall clock for the whole sweep, probes included. 90s fits one honest pass over all
# four providers (30+20+25+20 = 95, the tail clamped by whatever is left).
TUNNEL_SWEEP_BUDGET = 90.0
# Below this there is no honest attempt left to make. Say "not tried" rather than
# starting a provider we are about to cut off mid-handshake.
TUNNEL_MIN_SLICE = 8.0
# Breather between providers so a rate-limiter sees a gap, skipped once the budget
# is thin - it is dead time, and dead time is the thing being bounded.
TUNNEL_PROVIDER_GAP = 2.0
# Reachability budget for a URL that has just been printed. The probe leaves this PC,
# reaches the provider edge and comes back in. trycloudflare often answers HTTP 530
# until the edge registers the origin (~10-30s), so this is registration headroom,
# not a hang. Gate: tests/test_tunnel_bounded_report.py caps this at 30s.
TUNNEL_PROBE_BUDGET = 30.0

# Per-provider outcomes of the current/last sweep, published on /api/info.
_tunnel_attempts: list[dict] = []
# Monotonic wall-clock deadline of the sweep in flight; 0.0 when none is.
_tunnel_deadline: dict = {"at": 0.0}


def _probe_budget() -> float:
    """Probe budget for a URL that just appeared, clamped by the sweep's wall clock.

    Never returns zero: handing a working tunnel a 0s probe would reject it, and a
    control that refuses working work is a failure, not a win (R-0005).
    """
    at = float(_tunnel_deadline.get("at") or 0.0)
    if not at:
        return TUNNEL_PROBE_BUDGET
    return max(4.0, min(TUNNEL_PROBE_BUDGET, at - time.monotonic()))


def _attempt(provider: str, ok: bool, reason: str, url: str = "", started: float = 0.0) -> dict:
    """One provider's outcome, in the shape /api/info publishes."""
    return {
        "provider": provider,
        "ok": ok,
        "reason": reason,
        "url": url,
        "elapsed_s": round(time.monotonic() - started, 1) if started else 0.0,
    }


def _record_attempt(res: dict, attempt: int = 1) -> dict:
    res["attempt"] = attempt
    with _tunnel_lock:
        _tunnel_attempts.append(res)
    return res


def _no_url_reason(proc: subprocess.Popen, started: float) -> str:
    """Why a read window closed without a forwarding URL - exit vs. silence."""
    waited = time.monotonic() - started
    code = proc.poll()
    if code is not None:
        return f"process exited (code {code}) after {waited:.0f}s without printing a forwarding URL"
    return f"no forwarding URL printed in {waited:.0f}s"


def _probe_get_json(url: str, timeout: float) -> dict:
    """GET `url` as JSON. Prefer IPv4 when system getaddrinfo(AF_UNSPEC) 11001s.

    Observed on this host: nslookup A-records for *.trycloudflare.com succeed
    while urllib urlopen raises URLError Errno 11001 getaddrinfo failed, so a
    printed forwarding URL never passed /api/probe (HOST-DEMO-03).
    """
    import ssl
    import urllib.error
    import urllib.request
    from urllib.parse import urlparse

    req = urllib.request.Request(url, headers={"Cache-Control": "no-store"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except (OSError, urllib.error.URLError) as e:
        msg = str(e)
        if "11001" not in msg and "getaddrinfo" not in msg.lower():
            raise
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    ip = infos[0][4][0]
    sock = socket.create_connection((ip, port), timeout=timeout)
    try:
        if parsed.scheme == "https":
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=host)
        sock.sendall(
            f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
            "Cache-Control: no-store\r\nConnection: close\r\n\r\n".encode("ascii")
        )
        raw = b""
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            raw += chunk
    finally:
        try:
            sock.close()
        except OSError:
            pass
    header, _, body = raw.partition(b"\r\n\r\n")
    status_line = header.split(b"\r\n", 1)[0].decode("ascii", "replace")
    parts = status_line.split(" ", 2)
    code = int(parts[1]) if len(parts) > 1 else 0
    if code != 200:
        raise OSError(f"HTTP Error {code}: {status_line[:80]}")
    return json.loads(body)


def _probe_tunnel_url(url: str, attempts: int = 8, delay: float = 1.5,
                      timeout: float = 5.0, budget: float = TUNNEL_PROBE_BUDGET) -> tuple[bool, str]:
    """Does `url` route back to us? Returns (ok, reason) - the reason goes on the wire."""
    deadline = time.monotonic() + max(1.0, budget)
    why = "no probe attempt fitted in the budget"
    tried = 0
    while tried < attempts and time.monotonic() < deadline:
        tried += 1
        try:
            data = _probe_get_json(f"{url.rstrip('/')}/api/probe", timeout)
            if data.get("ok") is True:
                return True, "ok"
            why = "answered /api/probe without ok:true"
        except Exception as e:
            why = f"{type(e).__name__}: {str(e)[:90]}"
        wait = 3.0 if ("HTTP Error 530" in why or "getaddrinfo" in why or "11001" in why) else delay
        if time.monotonic() + wait >= deadline:
            break
        time.sleep(wait)
    return False, f"{why} ({tried} probe attempts, {budget:.0f}s budget)"


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


def _set_tunnel(url: str, provider: str, *, probe_budget: float = TUNNEL_PROBE_BUDGET) -> tuple[bool, str]:
    """Adopt `url` if it probes clean. Returns (ok, reason); the reason is reported,
    not just printed - a rejection the founder cannot see is the R-0011 shape."""
    ok, why = _probe_tunnel_url(url, budget=probe_budget)
    if not ok:
        reason = f"{url} did not pass /api/probe - {why}"
        _tunnel.update(url="", provider="", status=f"{provider} unreachable", error=reason, healthy=False)
        bump_sync()
        print(f"[tunnel] rejected {provider}: {reason}")
        return False, reason
    _tunnel.update(url=url, provider=provider, status="ready", error="", healthy=True, started_at=time.time())
    _qr_join_cache.clear()
    bump_sync()
    # Never let the console codec unwind a successful adopt. cp1252 print of
    # "ready -> UI sync" used to raise UnicodeEncodeError after _tunnel was
    # already ready; the worker then recorded a failure and killed cloudflared.
    try:
        print(f"[tunnel] ready -> UI sync: {url}")
    except UnicodeEncodeError:
        print("[tunnel] ready UI sync")
    return True, "ok"


def tunnel_health_loop():
    global _health_fails
    import urllib.request

    # Backoff for the "no tunnel at all" case. tunnel_worker sweeps its four providers
    # twice and then sets status=failed and stops forever, and the health check below
    # only runs when a URL exists — so a tunnel that failed to come up stayed dead
    # until somebody noticed and pressed Restart Tunnel. Cloudflare rate-limits quick
    # tunnels, so retry slowly rather than hammering: 1m, 2m, 4m … capped at 15m.
    retry_at = 0.0
    retry_delay = 60.0
    RETRY_MAX = 900.0

    while True:
        url = _tunnel.get("url")
        if not url:
            status = str(_tunnel.get("status") or "")
            # "_set_tunnel" stamps "{provider} unreachable" on a failed probe
            # while tunnel_worker is still walking the rest of the sweep.
            # Treating that as idle stacked a second worker and killed the
            # next provider's ssh/npx mid-handshake (localhost.run then
            # RemoteDisconnected). Only an actual finished sweep is idle.
            idle = status in ("", "failed")
            if idle and time.monotonic() >= retry_at:
                retry_at = time.monotonic() + retry_delay
                print(f"[tunnel] down - retrying (next attempt in {retry_delay / 60:.0f}m if this fails)")
                retry_delay = min(retry_delay * 2, RETRY_MAX)
                restart_tunnel()
            time.sleep(15)
            continue
        retry_delay = 60.0  # a live URL resets the ramp
        retry_at = 0.0
        healthy = False
        if url:
            try:
                healthy = _probe_get_json(f"{url.rstrip('/')}/api/probe", 6).get("ok") is True
            except Exception:
                healthy = False
        _tunnel["healthy"] = healthy
        if url and not healthy:
            _health_fails += 1
            if _tunnel.get("status") == "ready":
                _tunnel["status"] = "degraded"
            if _health_fails >= 3:
                print("[tunnel] unhealthy - auto-restarting tunnel")
                _health_fails = 0
                restart_tunnel()
        elif url and healthy:
            _health_fails = 0
            _tunnel["status"] = "ready"
        time.sleep(15)


# Subdomains a provider prints in its startup banner that are not the forwarding
# URL. localhost.run announces its admin console (https://admin.localhost.run)
# several lines before the real *.lhr.life tunnel, and _read_tunnel_url used to
# return the first line matching any pattern - so the console link won every
# time, got probed, failed, and killed the ssh session before the actual URL was
# ever printed. localhost.run could therefore never succeed on any network.
# Reject the class (banner/console hostnames) rather than the one host, so the
# same shape of bug cannot land again on serveo or localtunnel.
_BANNER_LABELS = frozenset({
    "admin", "dashboard", "console", "www", "docs", "status",
    "auth", "login", "billing", "support",
})


def _is_banner_url(url: str) -> bool:
    host = re.sub(r"^https?://", "", url or "").split("/")[0].split(":")[0].lower()
    return host.split(".")[0] in _BANNER_LABELS


def _read_tunnel_url(proc: subprocess.Popen, patterns: list[str], timeout_lines: int = 120,
                     budget: float | None = None) -> str | None:
    """Read stdout for a forwarding URL. `budget` clamps the read window to whatever
    the sweep has left, so one provider cannot eat the whole wall clock."""
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
    window = max(8.0, timeout_lines * 0.4)
    if budget is not None:
        window = max(1.0, min(window, budget))
    deadline = time.time() + window
    while time.time() < deadline:
        try:
            line = lines.get(timeout=0.4)
        except queue.Empty:
            if proc.poll() is not None:
                return None
            continue
        for pat in patterns:
            m = re.search(pat, line)
            if not m:
                continue
            cand = m.group(1)
            if _is_banner_url(cand):
                # Banner text, not a tunnel. Keep reading - the real URL is still
                # to come on a later line. Never return it and never give up here.
                print(f"[tunnel] ignoring banner URL {cand}")
                continue
            return cand
    return None


def tunnel_cloudflared(budget: float | None = None) -> dict:
    started = time.monotonic()
    exe = BIN / "cloudflared.exe"
    if not exe.is_file():
        try:
            import urllib.request
            print("[tunnel] downloading cloudflared...")
            urllib.request.urlretrieve(
                "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe", exe)
        except Exception as e:
            print(f"[tunnel] cloudflared download failed: {e}")
            return _attempt("cloudflared", False,
                            f"cloudflared.exe absent and download failed: {str(e)[:120]}", started=started)
    try:
        proc = subprocess.Popen(
            [str(exe), "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        url = _read_tunnel_url(proc, [r"(https://[a-z0-9-]+\.trycloudflare\.com)"],
                               timeout_lines=180, budget=budget)
        if url:
            _qr_join_cache.clear()
            ok, why = _set_tunnel(url, "cloudflared", probe_budget=_probe_budget())
            if ok:
                print(f"[tunnel] cloudflared: {url}")
                return _attempt("cloudflared", True, "ready", url, started)
            _kill_tunnel_procs()
            return _attempt("cloudflared", False, why, url, started)
        reason = _no_url_reason(proc, started)
        _kill_tunnel_procs()
        return _attempt("cloudflared", False, reason, started=started)
    except Exception as e:
        print(f"[tunnel] cloudflared: {e}")
        return _attempt("cloudflared", False, f"{type(e).__name__}: {str(e)[:120]}", started=started)


def tunnel_localhost_run(budget: float | None = None) -> dict:
    started = time.monotonic()
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
        ], timeout_lines=80, budget=budget)
        if url:
            ok, why = _set_tunnel(url, "localhost.run", probe_budget=_probe_budget())
            if ok:
                print(f"[tunnel] localhost.run: {url}")
                return _attempt("localhost.run", True, "ready", url, started)
            _kill_tunnel_procs()
            return _attempt("localhost.run", False, why, url, started)
        reason = _no_url_reason(proc, started)
        _kill_tunnel_procs()
        return _attempt("localhost.run", False, reason, started=started)
    except Exception as e:
        print(f"[tunnel] localhost.run: {e}")
        return _attempt("localhost.run", False, f"{type(e).__name__}: {str(e)[:120]}", started=started)


def tunnel_localtunnel(budget: float | None = None) -> dict:
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            ["npx", "--yes", "localtunnel", "--port", str(PORT)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        url = _read_tunnel_url(proc, [r"(https://[a-z0-9-]+\.loca\.lt)"],
                               timeout_lines=90, budget=budget)
        if url:
            ok, why = _set_tunnel(url, "localtunnel", probe_budget=_probe_budget())
            if ok:
                print(f"[tunnel] localtunnel: {url}")
                return _attempt("localtunnel", True, "ready", url, started)
            _kill_tunnel_procs()
            return _attempt("localtunnel", False, why, url, started)
        reason = _no_url_reason(proc, started)
        _kill_tunnel_procs()
        return _attempt("localtunnel", False, reason, started=started)
    except Exception as e:
        print(f"[tunnel] localtunnel: {e}")
        return _attempt("localtunnel", False, f"{type(e).__name__}: {str(e)[:120]}", started=started)


def tunnel_serveo(budget: float | None = None) -> dict:
    started = time.monotonic()
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
        ], timeout_lines=80, budget=budget)
        if url:
            ok, why = _set_tunnel(url, "serveo.net", probe_budget=_probe_budget())
            if ok:
                print(f"[tunnel] serveo: {url}")
                return _attempt("serveo.net", True, "ready", url, started)
            _kill_tunnel_procs()
            return _attempt("serveo.net", False, why, url, started)
        reason = _no_url_reason(proc, started)
        _kill_tunnel_procs()
        return _attempt("serveo.net", False, reason, started=started)
    except Exception as e:
        print(f"[tunnel] serveo: {e}")
        return _attempt("serveo.net", False, f"{type(e).__name__}: {str(e)[:120]}", started=started)


def tunnel_worker():
    """Sweep the providers inside TUNNEL_SWEEP_BUDGET and report every outcome.

    Two things used to be missing. There was no wall clock at all - read deadlines
    alone ran ~172s per pass over two passes - and the terminal state was one
    hardcoded sentence, so the per-provider reasons that the code already knew were
    print()ed and thrown away. The phone got "All tunnels failed" and nothing else.
    Every attempt now lands in _tunnel_attempts, which /api/info publishes.
    """
    global _health_fails
    _health_fails = 0
    if not _s1_remote_open():
        _tunnel.update(
            url="", provider="", status="locked",
            error="set a host passcode before tunnel", healthy=False,
        )
        print("[tunnel] S1 locked — set a host passcode before LAN/tunnel")
        bump_sync()
        return
    with _tunnel_lock:
        _tunnel_attempts.clear()
    _tunnel.update(url="", provider="", status="starting", error="", healthy=False, last_provider="")
    deadline = time.monotonic() + TUNNEL_SWEEP_BUDGET
    _tunnel_deadline["at"] = deadline
    bump_sync()
    providers = [
        (tunnel_cloudflared, "cloudflared"),
        (tunnel_localhost_run, "localhost.run"),
        (tunnel_localtunnel, "localtunnel"),
        (tunnel_serveo, "serveo.net"),
    ]
    try:
        for attempt in range(2):
            exhausted = False
            for fn, name in providers:
                remaining = deadline - time.monotonic()
                if remaining < TUNNEL_MIN_SLICE:
                    exhausted = True
                    if attempt == 0:
                        # Named, not silently skipped: "which providers were tried"
                        # has to include the ones we ran out of clock for.
                        _record_attempt(_attempt(
                            name, False,
                            f"not tried - {TUNNEL_SWEEP_BUDGET:.0f}s sweep budget spent on earlier providers"),
                            attempt + 1)
                    continue
                _tunnel.update(
                    status=f"trying {name}" + (f" (retry {attempt + 1})" if attempt else ""),
                    last_provider=name,
                )
                bump_sync()
                print(f"[tunnel] {_tunnel['status']}")
                res = _record_attempt(
                    fn(budget=min(TUNNEL_PROVIDER_BUDGET.get(name, 20.0), remaining)), attempt + 1)
                if res.get("ok"):
                    return
                print(f"[tunnel] {name} failed: {res.get('reason')}")
                if TUNNEL_PROVIDER_GAP and deadline - time.monotonic() >= TUNNEL_MIN_SLICE:
                    time.sleep(TUNNEL_PROVIDER_GAP)
            if exhausted or deadline - time.monotonic() < TUNNEL_MIN_SLICE:
                break
    finally:
        _tunnel_deadline["at"] = 0.0
    with _tunnel_lock:
        # One line per provider - its last word, not one line per attempt.
        last: dict[str, str] = {}
        for a in _tunnel_attempts:
            last[a["provider"]] = a["reason"]
    summary = "; ".join(f"{p}: {why}" for p, why in last.items())
    _tunnel.update(
        url="", provider="",
        status="failed",
        error=(f"No tunnel provider reachable within {TUNNEL_SWEEP_BUDGET:.0f}s — {summary}"
               " · Use LAN/hotspot or press Restart Tunnel.")[:900],
        healthy=False,
    )
    bump_sync()


def _rag_rebuild_paths(srcs: list) -> list:
    """Paths to re-ingest for a full rebuild. Live original, then Docs original
    (#34), then the extracted .txt blob so a rebuild never silently drops sources."""
    from rag import ingest as rag_ingest

    return rag_ingest.rebuild_source_paths(srcs)


def _rag_resolved(raw) -> Path | None:
    """Absolute path with symlinks followed and `..` collapsed, or None."""
    try:
        return Path(str(raw)).resolve()
    except (OSError, ValueError, TypeError, RuntimeError):
        return None


def _rag_space_storage_dirs(space_id: int) -> list[Path]:
    """Directories the space itself owns: the Docs/ byte-faithful originals and
    the extracted .txt blobs. Both are written by ingest, never by a client."""
    from rag import store as rag_store

    base = Path(rag_store.BLOB_DIR) / str(int(space_id))
    return [base / "Docs", base / "sources"]


def _rag_registered_source_paths(srcs: list) -> set[Path]:
    """Every filesystem location the space's own registered sources name, resolved.

    A source can carry four: the live original (``path``), the recorded original
    (``meta.original_path``), the Docs/ audit copy (``meta.docs_path``) and the
    extracted .txt blob (``meta.blob``) — the same set rag.ingest.rebuild_source_paths
    picks a rebuild path out of.
    """
    out: set[Path] = set()
    for s in srcs or []:
        meta = s.get("meta") if isinstance(s.get("meta"), dict) else {}
        for raw in (
            s.get("path"),
            meta.get("original_path"),
            meta.get("docs_path"),
            meta.get("blob"),
        ):
            if not raw:
                continue
            p = _rag_resolved(raw)
            if p is not None:
                out.add(p)
    return out


def _rag_check_build_paths(space_id: int, srcs: list, requested) -> tuple[list[str], str]:
    """Validate a client-supplied ``paths`` override for a space rebuild.

    The override exists so a caller can rebuild a SUBSET of a space's own sources.
    Unvalidated it *replaced* them with any filesystem path, which was then ingested
    and its text became retrievable answer material. Today ``/api/rag`` sits in
    _HOST_ONLY_PREFIXES, so reaching this needs host-level access — it is not a
    remote hole as shipped. It becomes one the moment level-based access grants let
    a client through to ``/api/rag`` (DR-0003), which is why the check lands before
    those grants, not after.

    Compare RESOLVED absolute paths, never strings: a `..` segment and a symlink
    planted inside the space's own Docs/ both still point outside once resolved,
    and either would walk straight past a prefix match on the raw text.

    Returns ``(paths, "")`` when every entry is the space's own, or ``([], reason)``
    — and the caller must then refuse the whole build. Dropping the bad entries and
    building the rest would report success for a build that quietly indexed
    something else, which is the R-0011 defect class.
    """
    if not isinstance(requested, (list, tuple)):
        return [], f"paths must be a list of registered source paths, got {type(requested).__name__}"
    allowed = _rag_registered_source_paths(srcs)
    own_dirs = [d for d in (_rag_resolved(x) for x in _rag_space_storage_dirs(space_id)) if d]
    out: list[str] = []
    for raw in requested:
        text = str(raw)
        p = _rag_resolved(text)
        if p is None:
            return [], f"rejected unreadable path: {text[:200]}"
        # Exact registered source, or genuinely inside the space's own storage.
        # The bare storage directory is not accepted: recursing it would re-open
        # the symlink route this check exists to close. Omit `paths` for a full
        # rebuild instead.
        if p in allowed or any(d in p.parents for d in own_dirs):
            out.append(str(p))
            continue
        detail = f"rejected path: {text[:200]}"
        if str(p) != text:
            detail += f" (resolves to {str(p)[:200]})"
        return [], (
            detail
            + f" — not a registered source of space {int(space_id)}. "            "paths may only name this space's own sources; omit paths to rebuild all."
        )
    return out, ""


def _explicit_consent(data, key: str = "yes") -> tuple[bool, str]:
    """Read a consent flag out of untyped JSON. Only a real boolean `true` is yes.

    `bool("false")` is True in Python, so a JSON *string* "false" — a user saying
    no in as many words — read as consent. Observed over real HTTP (#18):    confirm-identity yes="false" returned status 'confirmed', confirm-amend
    yes="false" returned status 'written' and the salary cell went 50000.0 ->
    54000.0. An unconfirmed amend landed on an explicit no.

    Strings, numbers, null and a missing key are none of them a yes. Ambiguity
    fails CLOSED — it is reported as a refusal, so the pending gate records a
    rejection and nothing is written. Deliberately not raised as an error: an
    error would leave the gate still open, and a malformed consent must not be
    retryable into a write.
    Returns (consent, why); a non-empty `why` names what was sent instead so the
    refusal states its cause rather than looking like an ordinary no.
    """
    if not isinstance(data, dict):
        return False, f"request body must be a JSON object; got {type(data).__name__}. Read as NO."
    if key not in data:
        return False, ""
    v = data[key]
    if v is True:
        return True, ""
    if v is False:
        return False, ""
    # `1 is True` is False in CPython, so an int 1 lands here too — as it must.
    return False, (
        f"{key!r} must be a JSON boolean, not {type(v).__name__} {v!r}. "
        "Read as NO — nothing was written."
    )


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ClipDrop/5"

    # Keep-alive safety. Early error returns (429 rate limit, 403 share ACL, 503 no
    # engine) reply before anyone reads the POST body. On HTTP/1.1 those bytes stay in
    # the socket, so the *next* request on that connection parses mid-JSON garbage as a
    # request line — every following call on that socket dies and the UI looks like the
    # backend crashed. Track whether the body was consumed and drain it before replying.
    _DRAIN_MAX = 4 * 1024 * 1024

    # A phone walking out of WiFi range, a closed tab, or a tunnel reconnect all abort
    # the socket mid-request. That is normal operation, not a fault, but socketserver
    # prints a full traceback for each one — which buried real errors in the console and
    # made a healthy server look like it was crashing. Swallow only the disconnect
    # family; everything else still propagates.
    _BENIGN_DISCONNECTS = (
        ConnectionAbortedError,   # WinError 10053 — host software aborted the connection
        ConnectionResetError,     # WinError 10054 — peer vanished
        BrokenPipeError,
        TimeoutError,             # socket timeout on an idle keep-alive
    )

    def handle_one_request(self):
        self._body_consumed = False
        try:
            super().handle_one_request()
        except self._BENIGN_DISCONNECTS as e:
            self.close_connection = True
            if os.environ.get("AIRGPT_DEBUG_SOCKETS"):
                print(f"[http] client disconnected: {type(e).__name__}")

    def _drain_request_body(self) -> None:
        if getattr(self, "_body_consumed", True):
            return
        self._body_consumed = True
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            return
        if n > self._DRAIN_MAX:
            # Huge upload rejected early — cheaper to drop the socket than read it all
            self.close_connection = True
            return
        try:
            left = n
            while left > 0:
                chunk = self.rfile.read(min(65536, left))
                if not chunk:
                    break
                left -= len(chunk)
        except (OSError, ValueError):
            self.close_connection = True

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

    def _s1_ok(self, path: str) -> bool:
        """False if a refusal was already sent. Local host always passes.

        S1: a phone on LAN/tunnel must not reach chat, establish, or the app
        shell until this machine has a passcode. Probe/health/auth-status stay
        open so the phone can say why it is locked.
        """
        if _is_host_request(self.headers, self.client_address[0]):
            return True
        if _s1_remote_open():
            return True
        if _s1_path_open(path):
            return True
        ip = self._client_ip()
        if app_audit:
            app_audit.log("s1_passcode_required", ip=ip, detail=path, ok=False)
        self._json(403, {
            "ok": False,
            "error": "set a host passcode before LAN or tunnel access",
            "code": "s1_passcode_required",
            "s1": True,
        })
        return False

    def _auth_ok(self, path: str) -> bool:
        if path in ("/", "/index.html", "/admin", "/admin.html", "/wasm_gate.js", "/manifest.json", "/api/probe", "/api/health", "/healthz", "/health", "/api/auth/status", "/api/netie/account", "/api/establish") or path.startswith("/api/qr") or path.startswith("/OpenIDE/ui/") or path.startswith("/ui/"):
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
        # needs_auth is also True when no passcode exists so _join_url mints a
        # QR token (#27 / #40). That is not an HTTP session gate: establish
        # *creates* the session, and a missing passcode is not passcode_required.
        if not st.get("passcode_required"):
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

    def _refuse_establish(self, path: str, code: str, error: str):
        ip = self._client_ip()
        if app_audit:
            app_audit.log(code, ip=ip, detail=path, ok=False)
        return self._json(403, {
            "ok": False,
            "error": error,
            "code": code,
            "establish": True,
        })

    def _establish_ok(self, path: str) -> bool:
        """False if a refusal was already sent. Local host always passes."""
        if path == "/api/establish":
            return True
        if _is_host_request(self.headers, self.client_address[0]):
            return True
        if not _needs_establish(self.command, path):
            return True
        tok = (self._request_token() or "").strip()
        nonce = (self.headers.get(SESSION_NONCE_HEADER) or "").strip()
        if tok and tok not in _establish_token:
            self._refuse_establish(
                path,
                "establish_unbound",
                "token is not bound to a handshake — POST /api/establish",
            )
            return False
        if tok and nonce and _establish_token.get(tok) != nonce:
            self._refuse_establish(
                path,
                "establish_mismatch",
                "session nonce does not match this token",
            )
            return False
        rec = _establish.get(nonce) if nonce else None
        if not rec:
            self._refuse_establish(
                path,
                "establish_required",
                "establish required — POST /api/establish",
            )
            return False
        bound_tok = rec.get("token") or ""
        if bound_tok and bound_tok != tok:
            self._refuse_establish(
                path,
                "establish_mismatch",
                "session nonce does not match this token",
            )
            return False
        return True

    def _handle_establish(self):
        ip = self._client_ip()
        tok = (self._request_token() or "").strip()
        nonce = secrets.token_urlsafe(24)
        if tok:
            old = _establish_token.get(tok)
            if old:
                _establish.pop(old, None)
            _establish_token[tok] = nonce
        _establish[nonce] = {"token": tok, "ip": ip, "ts": time.time()}
        if app_audit:
            app_audit.log("establish", ip=ip, detail="ok", ok=True)
        return self._json(200, {
            "ok": True,
            "session_nonce": nonce,
            "security_version": AIRGPT_SECURITY_VERSION,
        })

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
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-AirGPT-Token, Authorization, X-AirGPT-Session-Nonce",
        )
        self.send_header("Access-Control-Expose-Headers", SECURITY_VERSION_HEADER)

    def _send(self, code, body: bytes, ctype):
        try:
            self._drain_request_body()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header(SECURITY_VERSION_HEADER, AIRGPT_SECURITY_VERSION)
            self._cors()
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return

    def _json(self, code, data):
        self._send(code, json.dumps(data).encode(), "application/json; charset=utf-8")

    def _sse_begin(self) -> None:
        self._drain_request_body()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header(SECURITY_VERSION_HEADER, AIRGPT_SECURITY_VERSION)
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

    def _handle_project_suggest(self) -> None:
        """Observe a turn, or act on the chip. Suggestion only — never an auto-move.

        Three actions on one endpoint so the streak state, the dismissal and the move
        all live in one place instead of being spread across PATCH /api/sessions.
        """
        try:
            import project_suggest
        except Exception as e:
            return self._json(503, {"suggest": False, "error": str(e)[:200]})
        try:
            body = json.loads(self._body().decode() or "{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid json"})

        sid = int(body.get("session_id") or 0)
        action = str(body.get("action") or "observe").strip().lower()
        if not sid:
            return self._json(200, {"suggest": False, "reason": "no session"})

        if action == "dismiss":
            project_suggest.dismiss(sid)
            return self._json(200, {"ok": True, "suggest": False})

        session = db.get_session(sid) or {}

        if action == "move":
            cat = str(body.get("category") or "").strip().lower()
            if cat not in db.MODE_TO_CATEGORY:
                return self._json(400, {"ok": False, "error": "unknown category"})
            proj = db.get_default_project_for_category(cat)
            db.update_session_meta(sid, category=cat, project_id=proj["id"])
            project_suggest.accepted(sid)
            bump_sync()
            return self._json(200, {"ok": True, "category": cat, "project": proj["name"]})

        # Scratch is the deliberately uncategorised space — never nag there.
        if str(session.get("capture_type") or "") == "scratch":
            return self._json(200, {"suggest": False, "reason": "scratch"})

        current = str(session.get("category") or body.get("mode") or "general").lower()
        out = project_suggest.observe(sid, str(body.get("text") or ""), current)
        return self._json(200, out)

    def _handle_chat_stream(self, ip: str, dname: str) -> None:
        if not ai_engine:
            return self._json(503, {"error": "ai_engine not installed"})
        blocked = _ai_lockdown_block()
        if blocked:
            return self._json(
                403,
                {
                    "ok": False,
                    "error": blocked["error"],
                    "by": blocked.get("by") or "host",
                    "reason": blocked.get("reason") or "",
                },
            )
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
        web_search_flag = data.get("web_search", False)
        if isinstance(web_search_flag, str):
            web_search_flag = web_search_flag.lower() not in ("0", "false", "no", "off")
        web_search_flag = bool(web_search_flag)

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

        # Armed skills modify THIS send only. The raw user text is what gets stored
        # above — packs are prepended to the model's copy so the transcript stays
        # readable and the chat history never accumulates skill preambles.
        #
        # `skills` is the list form; `skill` is the original single field and still
        # works, because an older client is still allowed to talk to this server.
        question = text
        wanted: list[str] = []
        raw = data.get("skills")
        for candidate in [data.get("skill")] + (raw if isinstance(raw, list) else []):
            sid = str(candidate or "").strip().lower()
            if sid and sid not in wanted:
                wanted.append(sid)
        if wanted:
            packs: list[str] = []
            for sid in wanted[:MAX_ARMED_SKILLS]:
                try:
                    import invoke_registry

                    body = invoke_registry.load_skill(sid, max_chars=2000).strip()
                except Exception:
                    body = ""
                if body:
                    packs.append(f"[Skill: {sid}]\n{body}")
            if packs:
                question = "\n\n".join(packs) + f"\n\n---\n\n{text}"

        # Reserved for explicit cancellation. Deliberately NOT tripped by the client
        # disconnecting any more — a dropped socket used to abandon generation and
        # discard a finished answer, which is how an iPad on a flaky tunnel ended up
        # with its question sitting there unanswered forever.
        abort = threading.Event()
        event_q: queue.Queue = queue.Queue()
        done_ev: dict = {"analysis": "", "model": "", "error": ""}

        def _producer() -> None:
            try:
                for ev in _chat_stream_events(
                    question, mode, history, abort,
                    session_id=session_id,
                    model_tier=model_tier,
                    thinking=thinking_flag,
                    web_search=web_search_flag,
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

        # A phone on a flaky tunnel drops the stream mid-answer constantly. Losing the
        # socket must stop the WRITING, not the WORK: the model has already been paid
        # for, so let it finish and persist the result. The client picks the reply up
        # on its next poll instead of the question sitting there forever unanswered.
        client_gone = False
        idle_ticks = 0
        while True:
            try:
                ev = event_q.get(timeout=0.25)
            except queue.Empty:
                idle_ticks += 1
                # Keepalive every ~2s so proxies/clients don't drop the stream
                if idle_ticks % 8 == 0 and not client_gone:
                    if not self._sse_write_raw(b": keepalive\n\n"):
                        client_gone = True
                continue
            idle_ticks = 0
            if ev is None:
                break
            if isinstance(ev, dict):
                ev = {**ev, "session_id": session_id}
            if not client_gone and not self._sse_send(ev):
                client_gone = True

        # Persist whenever an answer exists. The old condition also required the client
        # to still be attached, so a tunnel hiccup silently discarded a finished reply.
        if done_ev["analysis"] and not done_ev["error"]:
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
        # "adaptive" is the label the Settings UI shows; "auto" is what the store
        # persists (rag/store.py). Accept both, or a space saved as Adaptive has its
        # depth silently coerced to high on every single answer - the setting appears
        # to save, and never takes effect. R-0011: a silent fallback is a lie.
        if depth == "adaptive":
            depth = "auto"
        if depth not in ("basic", "high", "max", "manual", "auto"):
            depth = "high"
        chat_id = int(data.get("chat_id") or 0)
        use_llm = True if "use_llm" not in data else bool(data.get("use_llm"))
        use_web = data.get("use_web", None)
        if use_web is not None:
            use_web = bool(use_web)
        source_ids = [int(x) for x in data.get("source_ids") or [] if str(x).strip()] or None
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
            for ev in rag_answer.answer_events(
                sid, q, depth=depth, use_llm=use_llm, use_web=use_web, source_ids=source_ids
            ):
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
                elif t == "reasoning":
                    # EPIC-D01 #15. Without this branch the chain is built, yielded,
                    # and dropped here - every browser answer goes over SSE, so the
                    # founder never saw a step of it while unit and JSON-path checks
                    # both passed.
                    reasoning = ev.get("reasoning") or {}
                    if not self._sse_send({"type": "reasoning", "reasoning": reasoning}):
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
            # Rebuilt from a fixed key list, so anything not named here is dropped
            # no matter what answer_events produced. #15's chain was missing.
            "reasoning": done.get("reasoning") or {},
            "trace_id": done.get("trace_id"),
            "confidence": done.get("confidence"),
            "stop_reason": done.get("stop_reason"),
            "rounds": done.get("rounds"),
            "coverage": done.get("coverage"),
            "faithfulness": done.get("faithfulness"),
            "unsupported_claims": done.get("unsupported_claims") or [],
            "model": done.get("model"),
            # Empty string when the preferred provider answered. A fallback used to
            # be indistinguishable from a first-choice reply.
            "degraded": done.get("degraded") or "",
            "chat_id": chat_id,
        })
        self._sse_end()

    def _handle_rag_build_stream(self, sid: int) -> None:
        """SSE ingest/build driving a real 'ready for retrieval' progress bar."""
        try:
            data = json.loads(self._body().decode() or "{}")
        except json.JSONDecodeError:
            data = {}
        try:
            from rag import ingest as rag_ingest
            from rag import store as rag_store
        except Exception as e:
            return self._json(503, {"error": str(e)[:200]})
        srcs = rag_store.list_sources(sid)
        paths = _rag_rebuild_paths(srcs)
        if isinstance(data.get("paths"), list) and data.get("paths"):
            # Same override, same hole as POST /build — validated the same way, before
            # the SSE stream opens so the refusal is a plain 400 the caller can read.
            paths, why = _rag_check_build_paths(sid, srcs, data["paths"])
            if why:
                return self._json(400, {"ok": False, "error": why})
        if not paths:
            return self._json(400, {"error": "no sources to build"})

        evq: queue.Queue = queue.Queue()
        result: dict = {}

        def _progress(stage, pct, detail):
            evq.put({"type": "progress", "stage": stage, "percent": pct, "detail": detail})

        def _producer():
            try:
                result.update(rag_ingest.ingest_paths(sid, paths, force=True, progress=_progress))
            except Exception as e:
                result.update({"ok": False, "error": str(e)[:300]})
            finally:
                evq.put(None)

        threading.Thread(target=_producer, daemon=True).start()
        self._sse_begin()
        self._sse_send({"type": "progress", "stage": "start", "percent": 0, "detail": f"{len(paths)} source(s)"})
        idle = 0
        while True:
            try:
                ev = evq.get(timeout=0.5)
            except queue.Empty:
                idle += 1
                if idle % 4 == 0 and not self._sse_write_raw(b": keepalive\n\n"):
                    break
                continue
            if ev is None:
                break
            if not self._sse_send(ev):
                break
        self._sse_send({
            "type": "done",
            "ok": bool(result.get("ok")),
            "sources": result.get("sources"),
            "chunks": result.get("chunks"),
            "metrics": result.get("metrics"),
            "revision_id": result.get("revision_id"),
            "error": result.get("error"),
        })
        self._sse_end()

    def _body(self):
        self._body_consumed = True
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n) if n else b""

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET,HEAD,POST,DELETE,PATCH,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-AirGPT-Token, Authorization, X-AirGPT-Session-Nonce",
        )
        self.end_headers()

    def do_HEAD(self):
        """Fast HEAD for probes — never 501, never hang on full GET."""
        path = urlparse(self.path).path
        if not self._s1_ok(path):
            return
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
            # Match what GET actually sends for the page, or a HEAD-then-GET client
            # is told the response is uncacheable and then handed an ETag.
            if path in ("/", "/index.html"):
                self.send_header("Cache-Control", "no-cache")
                try:
                    self.send_header("ETag", _cached_asset(ROOT / "index.html")[1])
                except OSError:
                    pass
            else:
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
        if not self._s1_ok(path):
            return
        if not self._auth_ok(path):
            return self._json(401, {"error": "auth required", "auth": True})
        if _is_host_only_path(path) and not _is_host_request(self.headers, self.client_address[0]):
            return self._json(403, {"error": "host only"})
        if path == "/api/establish":
            return self._handle_establish()
        if not self._establish_ok(path):
            return
        name = device_name_from_ua(ua, ip)
        # Skip SQLite write storm on hot poll + static paths
        if path not in ("/api/wait", "/api/probe", "/api/info", "/api/health", "/healthz", "/health", "/wasm_gate.js", "/manifest.json") and not path.startswith("/OpenIDE/ui/") and not path.startswith("/ui/"):
            db.register_device(ip, name, ua)
        q = parse_qs(urlparse(self.path).query)

        if path in ("/api/health", "/healthz", "/health"):
            return self._json(200, {"ok": True, "service": "airgpt", "version": APP_VERSION})

        if path in ("/", "/index.html"):
            # 838KB re-read from disk and re-sent uncompressed on every single request.
            # `no-store` also forbade revalidation, which made the ETag below dead code -
            # the browser could never answer with a conditional request, so every open
            # and every refresh pulled the whole file again.
            body, etag = _cached_asset(ROOT / "index.html")
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-cache")
                self._cors()
                self.end_headers()
                return
            payload, encoding = _maybe_gzip(body, self.headers.get("Accept-Encoding", ""))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            # no-cache, not no-store: revalidate every time (so an edit still shows up
            # immediately) but allow a 304 when nothing changed.
            self.send_header("Cache-Control", "no-cache")
            self.send_header("ETag", etag)
            if encoding:
                self.send_header("Content-Encoding", encoding)
                self.send_header("Vary", "Accept-Encoding")
            self._cors()
            self.end_headers()
            self.wfile.write(payload)
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
        if path.startswith("/ui/") and ".." not in path:
            # Design foundations (motion.js / apple.css). Kept out of index.html so the
            # 700 KB single file does not grow, and so the motion maths can be unit
            # tested in node instead of only being eyeballed in a browser.
            rel = path.lstrip("/")
            asset = (ROOT / rel).resolve()
            try:
                asset.relative_to((ROOT / "ui").resolve())
            except (ValueError, OSError):
                return self._json(400, {"error": "bad path"})
            if not asset.is_file():
                return self._json(404, {"error": "not found"})
            body = asset.read_bytes()
            mime = "application/javascript; charset=utf-8" if asset.suffix == ".js" else (
                "text/css; charset=utf-8" if asset.suffix == ".css"
                else (mimetypes.guess_type(str(asset))[0] or "application/octet-stream")
            )
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=60")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

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
            share_meta: dict = {}
            if app_auth and hasattr(app_auth, "token_session_acl") and not _is_local_host(ip):
                scoped = app_auth.token_session_acl(self._request_token())
                if scoped:
                    share_meta = {
                        "share_acl": scoped.get("acl"),
                        "access_level": scoped.get("access_level"),
                        "session_id": scoped.get("session_id"),
                    }
            try:
                devices = db.list_devices()
            except Exception:
                devices = []
            cortex = _cortex_info(quick=True)
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
                # HOST-DEMO-03: which providers were tried and why each one failed,
                # on the wire the phone reads - not in a log line the founder cannot see.
                "tunnel_attempts": list(_tunnel_attempts),
                "tunnel_last_provider": _tunnel.get("last_provider") or "",
                "tunnel_budget_s": TUNNEL_SWEEP_BUDGET,
                "tunnel_uptime_s": int(time.time() - _tunnel["started_at"]) if _tunnel.get("started_at") else 0,
                "devices": devices,
                "firewall": _firewall_status,
                "network_profile": lan["network_profile"],
                "lan_hint": lan["hint"],
                "lan_likely_blocked": lan["lan_likely_blocked"],
                "wifi_adapter_up": (wifi_access.hw_snapshot()[0] if wifi_access else True),
                "bluetooth_present": (wifi_access.hw_snapshot()[1] if wifi_access else False),
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
                "cortex": cortex,
                "online_personal_stub": "NEXT UPDATE: hosted AI + pay-to-continue",
                "ai_lockdown": _ai_lockdown_payload(),
                **share_meta,
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
            # Every poll is a presence heartbeat — no second timer, no websocket.
            room: list = []
            if sid:
                try:
                    import presence

                    presence.touch(
                        sid,
                        ip,
                        name=(self.headers.get("X-Device-Name") or "").strip() or name,
                        user_agent=ua,
                    )
                    room = presence.members(sid, exclude_ip=ip)
                except Exception:
                    room = []
            return self._json(200, {
                "sync_version": _sync_version,
                "latest_id": db.latest_id(),
                "new_chat": new_chat,
                "new_hist": new_hist,
                "presence": room,
                "tunnel_url": t_url,
                "tunnel_healthy": _tunnel.get("healthy", False),
                "tunnel_status": _tunnel.get("status"),
                "tunnel_provider": _tunnel_provider_label(),
                "lan_url": lan_url,
                "join_url": j_url,
                "qr_token": qr_tok,
                "network_epoch": _network_epoch,
                "ai_lockdown": _ai_lockdown_payload(),
                "app_state": _app_state_payload(q),
            })

        if path == "/api/presence":
            try:
                import presence

                sid_raw = q.get("session_id", [None])[0]
                sid = int(sid_raw) if sid_raw not in (None, "", "0") else None
                if sid:
                    return self._json(200, {"ok": True, "members": presence.members(sid, exclude_ip=ip)})
                return self._json(200, {"ok": True, "rooms": presence.snapshot()})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)[:200]})

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
                lib = research_lib.list_library()
                try:
                    import idea_to_paper

                    lib["runs"] = idea_to_paper.list_runs().get("runs") or []
                except Exception:
                    lib["runs"] = []
                return self._json(200, lib)
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)[:200]})

        if path == "/api/research/runs":
            try:
                import idea_to_paper

                rid = (q.get("id") or [""])[0]
                if rid:
                    return self._json(200, idea_to_paper.get_run(str(rid)))
                return self._json(200, idea_to_paper.list_runs())
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)[:200]})

        if path == "/api/research/artifact":
            try:
                import idea_to_paper

                rid = (q.get("id") or [""])[0]
                name = (q.get("name") or [""])[0]
                fp = idea_to_paper.artifact_path(str(rid), str(name))
                if not fp:
                    return self._json(404, {"ok": False, "error": "artifact not found"})
                data = fp.read_bytes()
                mime = {
                    ".md": "text/markdown; charset=utf-8",
                    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ".pdf": "application/pdf",
                    ".tex": "text/plain; charset=utf-8",
                }.get(fp.suffix.lower(), "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Disposition", f'attachment; filename="{fp.name}"')
                self.send_header("Content-Length", str(len(data)))
                self._cors()
                self.end_headers()
                self.wfile.write(data)
                return
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)[:200]})

        if path == "/api/docs":
            try:
                import docs_lib

                return self._json(200, docs_lib.list_docs())
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)[:200]})

        if path == "/api/docs/file":
            try:
                import docs_lib

                rel = (q.get("path") or [""])[0]
                return self._json(200, docs_lib.read_doc(rel))
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)[:200]})

        if path == "/api/memory/thin":
            # GET must never mutate. This one called thin_memories(), which
            # irreversibly truncates every unpinned body over 160 chars down to ~140
            # in place - so a link prefetch, a browser preconnect or an accidental
            # reload silently destroyed memory text with no undo. Nothing in the UI
            # ever called it, and the destructive path already exists on
            # POST /api/memory/forget {"thin":true}.
            return self._json(
                405,
                {
                    "ok": False,
                    "error": "GET /api/memory/thin is retired - it mutated on a GET",
                    "use": 'POST /api/memory/forget {"thin": true}',
                },
            )

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

        if path == "/api/update":
            if app_license and hasattr(app_license, "check_update"):
                return self._json(200, app_license.check_update())
            try:
                import license as _lic

                return self._json(200, _lic.check_update())
            except Exception as e:
                return self._json(200, {"ok": False, "update": False, "reason": "unavailable", "error": str(e)[:200]})

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

        if path == "/api/github/status":
            try:
                import github_auth
                return self._json(200, github_auth.status())
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)[:200]})

        if path == "/api/desktop/status":
            try:
                import desktop_control
                return self._json(200, desktop_control.available())
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)[:200]})

        if path == "/api/desktop/observe":
            try:
                import desktop_control
                return self._json(200, desktop_control.observe())
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)[:200]})

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

        if path == "/api/projects":
            # POST /api/projects has always written rows; without this nothing
            # could read them back, so no client could offer a project to pick.
            lim = min(int(q.get("limit", ["200"])[0] or 200), 500)
            return self._json(200, {"projects": db.list_projects(lim)})

        if path == "/api/summarize/today":
            summary = db.build_day_summary()
            return self._json(200, summary)

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
                peer_ip = hub.normalize_peer_ip(path.split("/")[-2])
                return self._json(200, {"events": db.list_hub_events(80, ip=peer_ip)})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        # Hub drill-down. A read, so it lives on GET — the Hub UI calls it with fetch().
        if path.startswith("/api/hub/peers/") and path.endswith("/activity"):
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import hub
                peer_ip = hub.normalize_peer_ip(path.split("/")[-2])
                return self._json(200, hub.get_peer_activity(peer_ip, host_ip=ip))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/cortex/health":
            try:
                import cortex_client
                # CRM snapshot: continuous poller + engine/memory planes
                # ?fresh=1 forces a live re-probe (Hosting page)
                q = parse_qs(urlparse(self.path).query)
                fresh = (q.get("fresh") or [""])[0].lower() in ("1", "true", "yes")
                return self._json(200, cortex_client.snapshot(fresh=fresh))
            except ImportError:
                return self._json(200, {"ok": False, "status": "unavailable"})

        if path == "/api/engine/activity":
            try:
                import cortex_client
                data = cortex_client.engine_activity()
                status = 200 if data.get("ok") else 503
                return self._json(status, data)
            except ImportError:
                return self._json(503, {"ok": False, "error": "cortex_client unavailable"})
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        # Cortex Routines / package Apps — namespaced so AirGPT /api/apps (ports) stays intact.
        if path == "/api/cortex/routines":
            try:
                import cortex_client
                data = cortex_client.routines_list()
                return self._json(200 if data.get("ok") else 503, data)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/cortex/routines/") and path.endswith("/runs"):
            try:
                import cortex_client
                rid = path.rstrip("/").split("/")[-2]
                data = cortex_client.routines_runs(rid)
                return self._json(200 if data.get("ok") else int(data.get("_http") or 503), data)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path == "/api/cortex/apps":
            try:
                import cortex_client
                data = cortex_client.cortex_apps_list()
                return self._json(200 if data.get("ok") else 503, data)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path == "/api/cortex/goals":
            try:
                import cortex_client
                data = cortex_client.goals_list()
                return self._json(200 if data.get("ok") else 503, data)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/cortex/goals/") and path.endswith("/seeks"):
            try:
                import cortex_client
                gid = path.split("/")[-2]
                data = cortex_client.goals_seeks(gid)
                return self._json(200 if data.get("ok") else 503, data)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/cortex/goals/") and path.endswith("/values"):
            try:
                import cortex_client
                gid = path.split("/")[-2]
                data = cortex_client.goals_values(gid)
                return self._json(200 if data.get("ok") else 503, data)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/cortex/goals/") and path.count("/") == 3:
            try:
                import cortex_client
                gid = path.rstrip("/").split("/")[-1]
                data = cortex_client.goals_get(gid)
                return self._json(200 if data.get("ok") else 503, data)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path == "/api/engine/just-works":
            # GET = plan only, never applies. The apply path is POST + explicit
            # confirm, so the button can show what it would do first.
            try:
                import cortex_client
                data = cortex_client.engine_just_works({})
                return self._json(200 if data.get("ok") else 503, data)
            except ImportError:
                return self._json(503, {"ok": False, "error": "cortex_client unavailable"})
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path == "/api/agents":
            try:
                import agent_runtime
                import agent_store
                agent_runtime.ensure_default_agent()
                pinned_only = (q.get("pinned", ["0"])[0] or "0") in ("1", "true", "yes")
                return self._json(200, {"agents": agent_store.list_agents(pinned_only=pinned_only)})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/skills":
            try:
                import invoke_registry

                skills = []
                for s in invoke_registry.list_skills():
                    summary = str(s.get("description") or "").strip()
                    # A pack with no real prose is a scratch file, not a skill — showing
                    # it as an empty card is worse than not showing it.
                    if len(summary) < 24:
                        continue
                    skills.append(
                        {
                            "id": s.get("id"),
                            "title": s.get("name") or s.get("id"),
                            "summary": summary[:180],
                            "tools": _skill_tools(s.get("path") or ""),
                            "enabled": bool(s.get("enabled")),
                            "scope": s.get("scope") or "off",
                        }
                    )
                return self._json(200, {"ok": True, "skills": skills})
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200], "skills": []})

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

        if path == "/api/rag/demo-variants":
            try:
                from rag import demo_variants

                return self._json(200, demo_variants.list_variants())
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/ontology"):
            try:
                from rag import ontology as rag_ontology

                sid = int(path.split("/")[4])
                force = (q.get("force", ["0"])[0] if isinstance(q, dict) else "0") in ("1", "true", "yes")
                return self._json(200, rag_ontology.ontology_for_space(sid, force=force))
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/demo-variant"):
            try:
                from rag import demo_variants

                sid = int(path.split("/")[4])
                return self._json(200, {"ok": True, **demo_variants.resolve_for_space(sid)})
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

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

        if path.startswith("/api/rag/spaces/") and path.endswith("/ann-status"):
            try:
                from rag import vectors as rag_vectors

                sid = int(path.split("/")[4])
                return self._json(200, rag_vectors.ann_index_status(sid))
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

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

        if path.startswith("/api/apps/") and path.endswith("/state") and path.count("/") == 4:
            try:
                import apps_hub

                app_id = path.split("/")[3]
                return self._json(200, apps_hub.get_app_state(app_id))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/apps/ports":
            try:
                import apps_hub

                return self._json(200, {"ok": True, "ports": apps_hub.allowlisted_ports()})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path.startswith("/api/apps/") and path.count("/") == 3:
            # /api/apps/{id} — probe one
            try:
                import apps_hub
                app_id = path.rsplit("/", 1)[-1]
                if app_id in ("ports", "register", "start", "stop", "open"):
                    return self._json(404, {"error": "not found"})
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
                # hosting.status() throttles its backend pings behind a TTL, but a cold
                # cache (or a .env re-point) still fans out to four backends. This route
                # is polled every 8s by the Hosting page, so it gets the same treatment
                # as /api/info: never hold the request thread on a hung backend. The
                # abandoned worker keeps running and warms the cache for the next poll.
                return self._json(200, _with_deadline(
                    hosting.status, _HOSTING_PENDING, timeout=3.0))
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

        if path == "/api/openvault/detect":
            try:
                import openvault_bridge
                project = str(q.get("project", [""])[0] or "")
                pth = str(q.get("path", [""])[0] or "")
                return self._json(200, openvault_bridge.detect_project(project, pth))
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

        if path == "/api/workflows":
            try:
                import workflow_engine
                return self._json(200, {"ok": True, "workflows": workflow_engine.list_workflows()})
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/workflows/tasks":
            try:
                import workflow_engine
                return self._json(200, workflow_engine.snapshot())
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path.startswith("/api/workflows/task/") and path.endswith("/events"):
            try:
                import cortex_client

                tid = path[len("/api/workflows/task/") : -len("/events")].strip("/")
                if not tid or tid.startswith("agent_run_"):
                    return self._json(404, {"error": "SSE only for Cortex workflow runs"})
                cortex_client.ensure_engine(wait_sec=4.0)
                base, key = cortex_client._cfg()
                import urllib.request

                req = urllib.request.Request(
                    f"{base}/api/workflows/task/{tid}/events",
                    headers=cortex_client._headers(key),
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                with urllib.request.urlopen(req, timeout=300) as upstream:
                    while True:
                        chunk = upstream.read(1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                return
            except Exception as e:
                try:
                    self.send_response(503)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)[:200]}).encode())
                except Exception:
                    pass
                return

        if path.startswith("/api/workflows/task/"):
            try:
                import workflow_engine
                tid = path.rsplit("/", 1)[-1]
                task = workflow_engine.get_task(tid)
                if not task:
                    return self._json(404, {"error": "unknown task"})
                return self._json(200, {"ok": True, "task": task})
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
        if not self._s1_ok(path):
            return
        if not self._auth_ok(path) and not path.startswith("/api/auth/"):
            return self._json(401, {"error": "auth required", "auth": True})
        if _is_host_only_path(path) and not _is_host_request(self.headers, self.client_address[0]):
            return self._json(403, {"error": "host only"})
        if path == "/api/establish":
            return self._handle_establish()
        if not self._establish_ok(path):
            return

        if path == "/api/presence/typing":
            try:
                import presence

                data = json.loads(self._body().decode() or "{}")
                sid = int(data.get("session_id") or 0)
                return self._json(200, presence.set_typing(sid, ip, bool(data.get("typing"))))
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/chat/stream":
            if app_auth and hasattr(app_auth, "token_session_acl") and not _is_local_host(ip):
                scoped = app_auth.token_session_acl(self._request_token())
                if scoped and scoped.get("acl") == "view":
                    return self._json(403, {"error": "This share is view-only"})
            dname = hostname()
            return self._handle_chat_stream(ip, dname)

        if path == "/api/chat/project-suggest":
            return self._handle_project_suggest()

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
                mode = str(data.get("mode", "general"))
                if data.get("ai_mode"):
                    blocked = _ai_lockdown_block()
                    if blocked:
                        return self._json(
                            403,
                            {
                                "ok": False,
                                "error": blocked["error"],
                                "by": blocked.get("by") or "host",
                            },
                        )
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
            # Phone peers default to llm_edit — clipboard publish requires read_paste.
            if not _is_local_host(ip):
                try:
                    import access_policy as _ap

                    if not _ap.may_clipboard_publish(ip, is_local=False):
                        return self._json(
                            403,
                            {
                                "error": "Clipboard paste disabled for this device. Approve with read_paste, or use LLM chat only.",
                                "capability": "llm_edit",
                            },
                        )
                except Exception:
                    pass
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
            mode = str(data.get("mode", "general"))
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
            # New chats default to General unless the client already picked a mode.
            cat = db.MODE_TO_CATEGORY.get(str(data.get("mode") or "general"), "general")
            db.update_session_meta(sess["id"], category=cat)
            return self._json(200, {"session": sess})

        if path == "/api/projects":
            data = json.loads(self._body().decode() or "{}")
            name = str(data.get("name", "")).strip()
            cat = str(data.get("category", "general"))
            if not name:
                return self._json(400, {"error": "name required"})
            return self._json(200, {"project": db.create_project_under_category(name, cat)})

        if path == "/api/access/passcode-required":
            # Host-only, and deliberately NOT under /api/auth/ — _auth_ok lets every
            # /api/auth/* path through unauthenticated, so a phone could have flipped
            # its own gate off. A valid guest token is not enough either: the request
            # must come from this machine, unproxied.
            direct = self.client_address[0]
            # Stricter than _forwarded_client_ip, which only trusts these headers when
            # the Host looks like a known tunnel domain. The UI running on this PC never
            # sends any of them, so their mere presence means something relayed the
            # request — and a relayed request must not be able to open the LAN.
            proxied = any(
                (self.headers.get(h) or "").strip()
                for h in ("X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP", "Forwarded")
            )
            if not _is_local_host(direct) or proxied:
                if app_audit:
                    app_audit.log("passcode_toggle", ip=ip, detail="refused: not host", ok=False)
                return self._json(403, {"ok": False, "error": "Host only — change this on the PC"})
            if not app_auth:
                return self._json(503, {"ok": False, "error": "auth unavailable"})
            try:
                data = json.loads(self._body().decode() or "{}")
            except json.JSONDecodeError:
                return self._json(400, {"ok": False, "error": "invalid json"})
            required = data.get("required", True)
            if isinstance(required, str):
                required = required.lower() not in ("0", "false", "no", "off")
            out = app_auth.set_passcode_required(bool(required))
            if app_audit:
                app_audit.log(
                    "passcode_toggle", ip=ip,
                    detail=("armed" if required else "DISARMED — LAN open"),
                    ok=bool(out.get("ok")),
                )
            return self._json(200 if out.get("ok") else 400, out)

        if path == "/api/access/approve":
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import access_policy
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, access_policy.approve(data.get("ip", ""), data.get("name", ""), capability=str(data.get("capability", "llm_edit") or "llm_edit")))
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
            m = str(data.get("mode", "general"))
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

        if path == "/api/github/auth/start":
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import github_auth
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, github_auth.start_device_flow(broad=bool(data.get("broad"))))
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)[:200]})

        if path == "/api/github/auth/poll":
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import github_auth
                data = json.loads(self._body().decode() or "{}")
                out = github_auth.poll_device_flow(str(data.get("device_code") or ""))
                if out.get("ok") and out.get("access_token"):
                    token = out.pop("access_token")
                    saved = github_auth.persist_token(token, app_settings)
                    if not saved.get("ok"):
                        return self._json(500, saved)
                    st = github_auth.status()
                    return self._json(200, {
                        "ok": True,
                        "connected": st.get("connected"),
                        "login": st.get("login"),
                        "scope": out.get("scope"),
                    })
                return self._json(200, out)
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)[:200]})

        if path == "/api/github/auth/disconnect":
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import github_auth
                return self._json(200, github_auth.clear_token(app_settings))
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)[:200]})

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
                # Must normalize — encodeURIComponent IPv6 without unquote used to
                # create ghost peers keyed as 2a02%3A… / 2a02%253A…
                peer_ip = hub.normalize_peer_ip(path.split("/")[-2])
                if not peer_ip:
                    return self._json(400, {"error": "invalid peer ip"})
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
                peer_ip = hub.normalize_peer_ip(path.split("/")[-2])
                if not peer_ip:
                    return self._json(400, {"error": "invalid peer ip"})
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, hub.rename_peer(peer_ip, str(data.get("display_name", ""))))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path.startswith("/api/hub/peers/") and path.endswith("/kick"):
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import hub
                peer_ip = hub.normalize_peer_ip(path.split("/")[-2]) or path.split("/")[-2]
                return self._json(200, hub.kick_peer(peer_ip))
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/hub/lockdown":
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import hub
                data = json.loads(self._body().decode() or "{}")
                on = bool(data.get("on"))
                return self._json(
                    200,
                    hub.set_lockdown(
                        on,
                        reason=str(data.get("reason") or ""),
                        by=str(data.get("by") or "host"),
                    ),
                )
            except Exception as e:
                return self._json(503, {"error": str(e)[:200]})

        if path == "/api/auth/qr-redeem":
            if not app_auth:
                return self._json(400, {"error": "auth unavailable"})
            data = json.loads(self._body().decode() or "{}")
            qr_tok = str(data.get("qr_token", ""))
            # Prefer session-share redeem when token is a share token
            r = None
            if hasattr(app_auth, "redeem_project_share"):
                r = app_auth.redeem_project_share(qr_tok)
                if r.get("ok"):
                    if app_audit:
                        app_audit.log("auth_project_share_ok", ip=ip, detail=qr_tok[:20], ok=True)
                    try:
                        import hub
                        hub.touch_peer(
                            ip,
                            device_id=str(data.get("device_id", "") or self.headers.get("X-Device-Id", ""))[:80],
                            display_name=str(data.get("display_name", "") or self.headers.get("X-Device-Name", ""))[:120],
                            join_method="qr",
                            logged_in=True,
                            access_level=r.get("access_level", "read_only"),
                        )
                    except Exception:
                        pass
                    return self._json(200, r)
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

        if path.endswith("/share") and path.startswith("/api/projects/"):
            if not app_auth:
                return self._json(503, {"error": "auth unavailable"})
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            parts = path.rstrip("/").split("/")
            # /api/projects/<key>/share
            try:
                key_idx = parts.index("projects") + 1
                project_key = parts[key_idx]
            except (ValueError, IndexError):
                return self._json(400, {"error": "bad project key"})
            if not project_key or project_key == "share":
                return self._json(400, {"error": "project key required"})
            data = json.loads(self._body().decode() or "{}")
            acl = str(data.get("acl") or data.get("access_level") or "read_only")
            if not hasattr(app_auth, "issue_project_share"):
                return self._json(503, {"error": "project share unavailable"})
            r = app_auth.issue_project_share(
                project_key,
                acl=acl,
                host_token=self._request_token(),
                host_verified=_is_local_host(ip),
            )
            if not r.get("ok"):
                return self._json(400, r)
            base = ""
            with _tunnel_lock:
                base = (_tunnel.get("url") or "").rstrip("/")
            if not base:
                ips = local_ips()
                if ips:
                    base = f"http://{ips[0]}:{PORT}"
            share_url = ""
            tok = r.get("share_token") or r.get("token")
            if base and tok:
                share_url = f"{base}/?qr={tok}&project={project_key}"
            if app_audit:
                app_audit.log(
                    "project_share",
                    ip=ip,
                    detail=f"project={project_key} acl={acl}",
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
            ok, why = _set_tunnel(url, "cloudflared")
            if ok:
                return self._json(200, {"ok": True, "url": url})
            return self._json(400, {"ok": False, "error": why or _tunnel.get("error") or "tunnel probe failed"})

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
                blocked = _ai_lockdown_block()
                if blocked:
                    return self._json(
                        403,
                        {
                            "ok": False,
                            "error": blocked["error"],
                            "by": blocked.get("by") or "host",
                        },
                    )
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
                return self._sse_end()
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
                run_async = bool(data.get("async") or data.get("background"))

                def _run_ops(force_flag: bool) -> dict:
                    out_local: dict = {"ok": True}
                    carry_local: dict = {}
                    f = force_flag
                    for op in ops:
                        out_local = op(f)
                        f = False  # only the first ingest may rebuild
                        for key in ("sessions_attached", "research_attached", "urls_attached", "skipped", "failed_urls"):
                            if out_local.get(key):
                                carry_local[key] = out_local[key]
                        if not out_local.get("ok"):
                            break
                    out_local.update(carry_local)
                    return out_local

                if run_async:
                    box: dict = {"job_id": None, "out": None}

                    def _bg() -> None:
                        try:
                            result = _run_ops(force)
                            box["out"] = result
                            if result.get("job_id"):
                                box["job_id"] = result["job_id"]
                        except Exception as exc:
                            box["out"] = {"ok": False, "error": str(exc)[:200]}

                    threading.Thread(target=_bg, daemon=True, name=f"rag-ingest-{sid}").start()
                    for _ in range(50):
                        if box["job_id"] or box["out"] is not None:
                            break
                        time.sleep(0.02)
                    return self._json(
                        202,
                        {
                            "ok": True,
                            "async": True,
                            "job_id": box.get("job_id"),
                            "space_id": sid,
                        },
                    )

                out = _run_ops(force)
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

        if path.startswith("/api/rag/spaces/") and path.endswith("/self-score"):
            try:
                from rag import evaluate as rag_eval

                sid = int(path.split("/")[4])
                data = json.loads(self._body().decode() or "{}")
                depths = data.get("depths") if isinstance(data.get("depths"), list) else ["basic", "high", "max"]
                out = rag_eval.self_score(
                    sid, n=int(data.get("n") or 12), k=int(data.get("k") or 5),
                    depths=tuple(str(d) for d in depths),
                    hard=bool(data.get("hard")),
                )
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/purge-chats"):
            try:
                from rag import store as rag_store

                sid = int(path.split("/")[4])
                out = rag_store.purge_chat_sources(sid)
                return self._json(200, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/scrub-authority"):
            try:
                from rag import store as rag_store

                sid = int(path.split("/")[4])
                data = json.loads(self._body().decode() or "{}")
                out = rag_store.scrub_authority(sid, dry_run=bool(data.get("dry_run")))
                return self._json(200, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/scrub-authority":
            try:
                from rag import store as rag_store

                data = json.loads(self._body().decode() or "{}")
                sid = data.get("space_id")
                out = rag_store.scrub_authority(
                    int(sid) if sid is not None else None,
                    dry_run=bool(data.get("dry_run")),
                )
                return self._json(200, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/settings"):
            try:
                from rag import store as rag_store

                sid = int(path.split("/")[4])
                data = json.loads(self._body().decode() or "{}")
                space = rag_store.update_space_settings(
                    sid,
                    name=str(data.get("name")) if data.get("name") else None,
                    depth_default=str(data.get("depth_default")) if data.get("depth_default") else None,
                    profile=str(data.get("profile")) if data.get("profile") else None,
                    config=data.get("config") if isinstance(data.get("config"), dict) else None,
                )
                if not space:
                    return self._json(404, {"error": "space not found"})
                return self._json(200, {"ok": True, "space": space})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/rag/demo-variants":
            try:
                from rag import demo_variants

                return self._json(200, demo_variants.list_variants())
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/insights-export":
            try:
                import sys
                from pathlib import Path as _P

                rag_tests = _P(__file__).resolve().parent / "tests" / "RAG"
                if str(rag_tests) not in sys.path:
                    sys.path.insert(0, str(rag_tests))
                import insights_export as _ix

                data = json.loads(self._body().decode() or "{}")
                excl = data.get("exclude") or []
                if isinstance(excl, str):
                    excl = [s.strip() for s in excl.split(",") if s.strip()]
                out = _ix.run_pipeline(
                    ask=str(data.get("ask") or "Top 5 selling SKUs by revenue"),
                    n=int(data.get("n") or 5),
                    file_type=str(data.get("file_type") or "xlsx"),
                    graph_type=str(data.get("graph_type") or "bar"),
                    exclude=excl or None,
                )
                return self._json(200, out)
            except Exception as e:
                return self._json(
                    400,
                    {
                        "ok": False,
                        "error": str(e)[:300],
                        "honesty": "Cortex-direct, not OpenVault-gated",
                    },
                )

        if path.startswith("/api/rag/spaces/") and path.endswith("/demo-variant"):
            try:
                from rag import demo_variants

                sid = int(path.split("/")[4])
                data = json.loads(self._body().decode() or "{}")
                name = str(data.get("variant") or data.get("name") or "").strip()
                if not name:
                    return self._json(200, {"ok": True, **demo_variants.resolve_for_space(sid)})
                out = demo_variants.select_variant(sid, name)
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/ontology"):
            try:
                from rag import ontology as rag_ontology

                sid = int(path.split("/")[4])
                data = json.loads(self._body().decode() or "{}")
                out = rag_ontology.ontology_for_space(sid, force=bool(data.get("force")))
                if out.get("ok"):
                    out["artifact"] = str(rag_ontology.save_ontology_artifact(sid))
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/ops/identify":
            try:
                from rag import ops_amend

                data = json.loads(self._body().decode() or "{}")
                out = ops_amend.identify_employee(
                    str(data.get("path") or ""),
                    str(data.get("ask") or data.get("query") or ""),
                )
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/ops/confirm-identity":
            try:
                from rag import ops_amend

                data = json.loads(self._body().decode() or "{}")
                # Strict: only a real JSON boolean true is consent (#18).
                consent, why = _explicit_consent(data)
                out = ops_amend.confirm_identity(str(data.get("token") or ""), consent)
                if why and isinstance(out, dict):                    out["consent_warning"] = why
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/ops/propose-amend":
            try:
                from rag import ops_amend

                data = json.loads(self._body().decode() or "{}")
                out = ops_amend.propose_amend(
                    str(data.get("token") or ""),
                    new_salary=float(data["new_salary"]) if data.get("new_salary") is not None else None,
                    increment_pct=float(data["increment_pct"]) if data.get("increment_pct") is not None else None,
                )
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/ops/confirm-amend":
            try:
                from rag import ops_amend

                data = json.loads(self._body().decode() or "{}")
                # Strict: only a real JSON boolean true authorises the write (#18).
                consent, why = _explicit_consent(data)
                out = ops_amend.confirm_amend(str(data.get("token") or ""), consent)
                if why and isinstance(out, dict):                    out["consent_warning"] = why
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/ops/continue":
            try:
                from rag import ops_amend

                data = json.loads(self._body().decode() or "{}")
                out = ops_amend.continue_loop(
                    str(data.get("token") or ""),
                    ask=str(data.get("ask") or ""),
                    next_row=bool(data.get("next_row")),
                )
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/ops/chain":
            try:
                from rag import ops_amend

                data = json.loads(self._body().decode() or "{}")
                out = ops_amend.chain(str(data.get("token") or ""))
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/xlsx-orch/identify":
            try:
                from rag import xlsx_orch

                data = json.loads(self._body().decode() or "{}")
                sid = data.get("space_id")
                out = xlsx_orch.identify_and_pack(
                    ask=str(data.get("ask") or data.get("query") or ""),
                    space_id=int(sid) if sid not in (None, "") else None,
                    path=str(data.get("path") or ""),
                )
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/xlsx-orch/handoff":
            try:
                from rag import xlsx_orch

                data = json.loads(self._body().decode() or "{}")
                out = xlsx_orch.consume_result(
                    pack_id=str(data.get("pack_id") or ""),
                    result_path=str(data.get("result_path") or data.get("path") or ""),
                )
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/xlsx-orch/reveal":
            try:
                from rag import xlsx_orch

                data = json.loads(self._body().decode() or "{}")
                out = xlsx_orch.reveal_handoff(
                    pack_id=str(data.get("pack_id") or ""),
                    path=str(data.get("path") or ""),
                    which=str(data.get("which") or "result"),
                )
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/reveal-path":
            try:
                from rag import reveal as rag_reveal

                data = json.loads(self._body().decode() or "{}")
                return self._json(200, rag_reveal.reveal_path(str(data.get("path") or "")))
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/archive"):
            try:
                from rag import store as rag_store

                sid = int(path.split("/")[4])
                space = rag_store.archive_space(sid)
                return self._json(200, {"ok": True, "space": space})
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/ann-backfill"):
            try:
                from rag import vectors as rag_vectors

                sid = int(path.split("/")[4])
                return self._json(200, rag_vectors.backfill_ann_index(sid))
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

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

        if path.startswith("/api/rag/sources/") and path.endswith("/reveal"):
            try:
                from rag import reveal as rag_reveal
                from rag import store as rag_store

                src_id = int(path.split("/")[4])
                src = rag_store.get_source(src_id)
                if not src:
                    return self._json(404, {"ok": False, "error": "source not found"})
                out = rag_reveal.reveal_source(src)
                return self._json(200 if out.get("ok") else 404, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

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

        if path.startswith("/api/rag/spaces/") and path.endswith("/build-stream"):
            return self._handle_rag_build_stream(int(path.split("/")[4]))

        if path.startswith("/api/rag/spaces/") and path.endswith("/build"):
            try:
                from rag import ingest as rag_ingest
                from rag import store as rag_store

                sid = int(path.split("/")[4])
                data = json.loads(self._body().decode() or "{}")
                srcs = rag_store.list_sources(sid)
                paths = _rag_rebuild_paths(srcs)
                if data.get("paths"):
                    # A client may narrow the rebuild to a subset of this space's own
                    # sources — it may not point the ingest at arbitrary host files.
                    paths, why = _rag_check_build_paths(sid, srcs, data.get("paths"))
                    if why:
                        return self._json(400, {"ok": False, "error": why})
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
                    source_ids=[int(x) for x in data.get("source_ids") or [] if str(x).strip()]
                    or None,
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
                depth = str(data.get("depth") or "").strip()
                if not depth:
                    try:
                        from rag import demo_variants

                        depth = str(demo_variants.resolve_for_space(sid).get("depth") or "high")
                    except Exception:
                        depth = "high"
                out = rag_answer.answer(
                    sid,
                    q,
                    depth=depth,
                    chat_id=int(data.get("chat_id") or 0),
                    use_llm=True if "use_llm" not in data else bool(data.get("use_llm")),
                    use_web=bool(data["use_web"]) if "use_web" in data else None,
                    source_ids=[int(x) for x in data.get("source_ids") or [] if str(x).strip()]
                    or None,
                )
                if isinstance(out, dict):
                    try:
                        from rag import demo_variants

                        out.setdefault("honesty", demo_variants.HONESTY)
                        out.setdefault("variant", demo_variants.resolve_for_space(sid).get("name"))
                    except Exception:
                        pass
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
                    instructions=data.get("instructions"),
                    memory=data.get("memory"),
                    scheduled=data.get("scheduled") if isinstance(data.get("scheduled"), list) else None,
                    context_files=data.get("context_files") if isinstance(data.get("context_files"), list) else None,
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

        if path == "/api/apps/register":
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import apps_hub

                data = json.loads(self._body().decode() or "{}")
                return self._json(200, apps_hub.register_app(data if isinstance(data, dict) else {}))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/apps/") and path.endswith("/start") and path.count("/") == 4:
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            try:
                import apps_hub

                app_id = path.split("/")[3]
                return self._json(200, apps_hub.start(app_id))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/apps/") and path.endswith("/state") and path.count("/") == 4:
            try:
                import apps_hub

                app_id = path.split("/")[3]
                # read_only peers cannot write shared card state
                if app_auth and hasattr(app_auth, "token_session_acl") and not _is_local_host(ip):
                    scoped = app_auth.token_session_acl(self._request_token()) or {}
                    level = str(scoped.get("access_level") or "")
                    if scoped.get("acl") == "view" or level in ("read_only", "limited"):
                        return self._json(403, {"ok": False, "error": "view only"})
                data = json.loads(self._body().decode() or "{}")
                state = data.get("state") if isinstance(data, dict) else {}
                if not isinstance(state, dict):
                    state = {"value": state}
                return self._json(200, apps_hub.set_app_state(app_id, state))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path.startswith("/api/apps/") and path.endswith("/mount") and path.count("/") == 4:
            # Start app + insert app_card message into session
            try:
                import apps_hub
                import json as _json

                app_id = path.split("/")[3]
                data = json.loads(self._body().decode() or "{}")
                session_id = int(data.get("session_id") or 0)
                started = apps_hub.start(app_id)
                health = "live" if started.get("ok") else "error"
                if started.get("status") == "already_running":
                    health = "live"
                app = started.get("app") or {}
                port = int(app.get("port") or data.get("port") or 0)
                name = str(data.get("name") or app.get("name") or app_id)
                card = {
                    "app_id": app_id,
                    "name": name,
                    "port": port,
                    "health": health if started.get("ok") or health == "live" else "error",
                    "slug": app_id,
                    "error": started.get("error") or "",
                }
                msg = None
                if session_id:
                    msg = db.add_message(
                        device_ip="127.0.0.1",
                        device_name="AirGPT",
                        text=_json.dumps(card),
                        kind="app_card",
                        source="ai",
                        session_id=session_id,
                    )
                    bump_sync()
                return self._json(200, {"ok": True, "card": card, "start": started, "message": msg})
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

        if path == "/api/research/idea-to-paper":
            try:
                import idea_to_paper

                data = json.loads(self._body().decode() or "{}")
                rid = str(data.get("run_id") or "").strip()
                if rid and data.get("repackage"):
                    return self._json(200, idea_to_paper.start_run(repackage_id=rid, sync=True))
                if rid and data.get("resume"):
                    return self._json(200, idea_to_paper.start_run(resume_id=rid, sync=bool(data.get("sync"))))
                if rid and (data.get("continue") or data.get("continue_run")):
                    return self._json(200, idea_to_paper.start_run(continue_id=rid, sync=bool(data.get("sync"))))
                return self._json(
                    200,
                    idea_to_paper.start_run(
                        str(data.get("idea") or ""),
                        str(data.get("non_goals") or ""),
                        domain_hint=str(data.get("domain") or "software"),
                        sync=bool(data.get("sync")),
                    ),
                )
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

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

        if path == "/api/openvault/sync":
            try:
                import openvault_bridge
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    openvault_bridge.sync_project(
                        str(data.get("project") or data.get("name") or ""),
                        str(data.get("source") or data.get("path") or ""),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/openvault/detect":
            try:
                import openvault_bridge
                # GET query or POST body
                project = ""
                pth = ""
                if self.command == "GET":
                    project = str(q.get("project", [""])[0] or "")
                    pth = str(q.get("path", [""])[0] or "")
                else:
                    data = json.loads(self._body().decode() or "{}")
                    project = str(data.get("project") or data.get("name") or "")
                    pth = str(data.get("path") or "")
                return self._json(200, openvault_bridge.detect_project(project, pth))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/openvault/build":
            try:
                import openvault_bridge
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    openvault_bridge.build_project(
                        str(data.get("project") or data.get("name") or ""),
                        str(data.get("path") or ""),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/openvault/ship":
            try:
                import openvault_bridge
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    openvault_bridge.ship_project(
                        str(data.get("project") or data.get("name") or ""),
                        str(data.get("path") or ""),
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

        if path == "/api/cortex/ensure":
            try:
                import cortex_client
                data = json.loads(self._body().decode() or "{}")
                force = bool(data.get("force", True))
                wait_sec = float(data.get("wait_sec") or 20)
                wait_sec = max(1.0, min(wait_sec, 60.0))
                result = cortex_client.ensure_engine(force=force, wait_sec=wait_sec)
                # Refresh CRM cache so Hosting UI sees live immediately
                snap = cortex_client.refresh_snapshot()
                return self._json(
                    200 if result.get("ok") else 503,
                    {**result, "snapshot": snap},
                )
            except ImportError:
                return self._json(503, {"ok": False, "error": "cortex_client unavailable"})
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path == "/api/engine/just-works":
            try:
                import cortex_client
                body = json.loads(self._body().decode() or "{}")
                # apply is opt-in: the button plans first, the user confirms.
                out = cortex_client.engine_just_works(
                    {
                        "apply": bool(body.get("apply")),
                        "research": bool(body.get("research")),
                        "prefer": str(body.get("prefer") or ""),
                    }
                )
                return self._json(200 if out.get("ok") else 503, out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path == "/api/engine/bakeoff":
            try:
                import cortex_client
                body = json.loads(self._body().decode() or "{}")
                out = cortex_client.engine_bakeoff(body)
                return self._json(200 if out.get("ok") else 503, out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path == "/api/desktop/plan":
            try:
                import desktop_playbook
                body = json.loads(self._body().decode() or "{}")
                out = desktop_playbook.plan_task(
                    str(body.get("goal") or ""),
                    tokens_left=body.get("tokens_left"),
                    prefer=str(body.get("prefer") or "") or None,
                    act=bool(body.get("act")),
                )
                return self._json(200, out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path == "/api/desktop/act":
            # Unified input gate: click|type|scroll|drag|hotkey — always needs confirmed.
            try:
                import desktop_control
                body = json.loads(self._body().decode() or "{}")
                confirmed = bool(body.get("confirmed"))
                kind = str(body.get("kind") or body.get("action") or "").lower()
                if kind == "click":
                    out = desktop_control.click(
                        int(body.get("x") or 0), int(body.get("y") or 0),
                        button=str(body.get("button") or "left"), confirmed=confirmed,
                    )
                elif kind == "type":
                    out = desktop_control.type_text(str(body.get("text") or ""), confirmed=confirmed)
                elif kind == "scroll":
                    out = desktop_control.scroll(int(body.get("dy") or -3), confirmed=confirmed)
                elif kind == "drag":
                    out = desktop_control.drag(
                        int(body.get("x1") or 0), int(body.get("y1") or 0),
                        int(body.get("x2") or 0), int(body.get("y2") or 0),
                        confirmed=confirmed,
                    )
                elif kind == "hotkey":
                    keys = body.get("keys") or []
                    if isinstance(keys, str):
                        keys = keys.split("+")
                    out = desktop_control.hotkey(*[str(k) for k in keys], confirmed=confirmed)
                else:
                    out = {"ok": False, "error": "unknown kind (click|type|scroll|drag|hotkey)"}
                return self._json(200 if out.get("ok") or out.get("error") == "confirm_required" else 400, out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path == "/api/cortex/routines/draft":
            try:
                import cortex_client
                body = json.loads(self._body().decode() or "{}")
                out = cortex_client.routines_draft(str(body.get("goal") or ""))
                return self._json(int(out.get("_http") or (200 if out.get("ok") else 400)), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path == "/api/cortex/routines":
            try:
                import cortex_client
                body = json.loads(self._body().decode() or "{}")
                out = cortex_client.routines_create(
                    str(body.get("goal") or body.get("prompt") or ""),
                    agent_id=int(body.get("agent_id") or 0),
                )
                return self._json(int(out.get("_http") or (200 if out.get("ok") else 400)), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/cortex/routines/") and path.endswith("/pause"):
            try:
                import cortex_client
                rid = path.split("/")[-2]
                body = json.loads(self._body().decode() or "{}")
                out = cortex_client.routines_pause(rid, str(body.get("reason") or "user"))
                return self._json(int(out.get("_http") or 200), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/cortex/routines/") and path.endswith("/resume"):
            try:
                import cortex_client
                rid = path.split("/")[-2]
                out = cortex_client.routines_resume(rid)
                return self._json(int(out.get("_http") or 200), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/cortex/routines/") and path.endswith("/run"):
            try:
                import cortex_client
                rid = path.split("/")[-2]
                out = cortex_client.routines_run(rid)
                return self._json(int(out.get("_http") or 200), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path == "/api/cortex/apps/import-folder":
            try:
                import cortex_client
                body = json.loads(self._body().decode() or "{}")
                out = cortex_client.cortex_apps_import_folder(
                    str(body.get("path") or ""),
                    name=(str(body["name"]) if body.get("name") else None),
                )
                return self._json(int(out.get("_http") or (200 if out.get("ok") else 400)), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/cortex/apps/") and path.endswith("/approve"):
            try:
                import cortex_client
                app_id = path.split("/")[-2]
                out = cortex_client.cortex_apps_approve(app_id)
                return self._json(int(out.get("_http") or 200), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/cortex/apps/") and path.endswith("/reject"):
            try:
                import cortex_client
                app_id = path.split("/")[-2]
                body = json.loads(self._body().decode() or "{}")
                out = cortex_client.cortex_apps_reject(app_id, str(body.get("reason") or "rejected"))
                return self._json(int(out.get("_http") or 200), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/cortex/apps/") and path.endswith("/dockerize"):
            try:
                import cortex_client
                app_id = path.split("/")[-2]
                out = cortex_client.cortex_apps_dockerize(app_id)
                return self._json(int(out.get("_http") or 200), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/cortex/apps/") and path.endswith("/start"):
            try:
                import cortex_client
                app_id = path.split("/")[-2]
                out = cortex_client.cortex_apps_start(app_id)
                return self._json(int(out.get("_http") or 200), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/cortex/apps/") and path.endswith("/stop"):
            try:
                import cortex_client
                app_id = path.split("/")[-2]
                out = cortex_client.cortex_apps_stop(app_id)
                return self._json(int(out.get("_http") or 200), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path == "/api/cortex/goals":
            try:
                import cortex_client
                body = json.loads(self._body().decode() or "{}")
                out = cortex_client.goals_create(
                    str(body.get("statement") or ""),
                    org_id=str(body.get("org_id") or ""),
                    measurable_criteria=body.get("measurable_criteria") or None,
                    soft_preferences=body.get("soft_preferences") or None,
                )
                return self._json(int(out.get("_http") or (200 if out.get("ok") else 400)), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path == "/api/engine/seek":
            try:
                import cortex_client
                body = json.loads(self._body().decode() or "{}")
                out = cortex_client.engine_seek(
                    str(body["goal_id"]) if body.get("goal_id") else None,
                    trigger=str(body.get("trigger") or "manual"),
                    limit=int(body.get("limit") or 8),
                )
                http = int(out.get("_http") or (200 if out.get("ok") else 404))
                return self._json(http, out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/cortex/goals/") and path.endswith("/outcome"):
            try:
                import cortex_client
                body = json.loads(self._body().decode() or "{}")
                gid = path.split("/")[-2]
                out = cortex_client.goals_outcome(
                    gid,
                    str(body.get("proposal_id") or ""),
                    str(body.get("outcome") or ""),
                )
                return self._json(int(out.get("_http") or (200 if out.get("ok") else 400)), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})

        if path == "/api/workflows/run":
            try:
                import workflow_engine
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    workflow_engine.start(
                        str(data.get("workflow_id") or ""),
                        goal=str(data.get("goal") or ""),
                        breadth=int(data.get("breadth") or 3),
                    ),
                )
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/workflows/cancel":
            try:
                import workflow_engine
                data = json.loads(self._body().decode() or "{}")
                return self._json(200, workflow_engine.cancel(str(data.get("task_id") or "")))
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/workflows/clear":
            try:
                import workflow_engine
                return self._json(200, workflow_engine.clear_finished())
            except Exception as e:
                return self._json(400, {"error": str(e)[:200]})

        if path == "/api/workflows/recognize":
            try:
                import workflow_engine
                data = json.loads(self._body().decode() or "{}")
                return self._json(
                    200,
                    workflow_engine.recognize(str(data.get("prompt") or data.get("text") or "")),
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
        raw = self._body() or b"{}"
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
            if "project_id" in body:
                try:
                    pid = int(body["project_id"])
                except (TypeError, ValueError):
                    return self._json(400, {"error": "bad project_id"})
                # 0 clears the assignment. Any other id must name a real row -
                # an unknown one would park the chat in a project no listing
                # can show, and the client would never see it again.
                if pid and not db.get_project(pid):
                    return self._json(404, {"error": "project not found"})
                kw["project_id"] = pid
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
            return self._json(200, access_policy.approve(body.get("ip", ""), body.get("name", ""), capability=str(body.get("capability", "llm_edit") or "llm_edit")))
        if path == "/api/access/deny":
            try:
                import access_policy
            except ImportError:
                return self._json(503, {"error": "access policy unavailable"})
            if not _is_local_host(ip):
                return self._json(403, {"error": "host only"})
            return self._json(200, access_policy.deny(body.get("ip", "")))
        if path.startswith("/api/cortex/routines/"):
            # reserved for future patch; keep namespace owned
            return self._json(405, {"error": "use pause/resume/run POST actions"})
        return self._json(404, {"error": "not found"})

    def do_DELETE(self):
        path = urlparse(self.path).path
        ip = self._client_ip()
        if not self._s1_ok(path):
            return
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
        if path.startswith("/api/cortex/routines/"):
            try:
                import cortex_client
                rid = path.rstrip("/").split("/")[-1]
                out = cortex_client.routines_delete(rid)
                return self._json(int(out.get("_http") or 200), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})
        if path.startswith("/api/cortex/apps/"):
            try:
                import cortex_client
                app_id = path.rstrip("/").split("/")[-1]
                out = cortex_client.cortex_apps_delete(app_id)
                return self._json(int(out.get("_http") or 200), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})
        if path.startswith("/api/cortex/goals/"):
            try:
                import cortex_client
                gid = path.rstrip("/").split("/")[-1]
                out = cortex_client.goals_delete(gid)
                return self._json(int(out.get("_http") or 200), out)
            except Exception as e:
                return self._json(503, {"ok": False, "error": str(e)[:200]})
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


def _port_holder(port: int) -> str:
    """PID currently LISTENING on `port`, for an actionable error message."""
    try:
        if os.name != "nt":
            return ""
        r = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=6,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        for line in (r.stdout or "").splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].endswith(f":{port}"):
                return parts[4]
    except Exception:
        pass
    return ""


def _wait_for_port(host: str, port: int, *, seconds: float = 20.0) -> bool:
    """Wait until `port` can actually be bound the way the real server binds it.

    Two things used to make a restart leave the engine dead. The probe was a plain
    socket while the server is a ThreadingHTTPServer with allow_reuse_address=1, so
    a socket sitting in TIME_WAIT failed the probe even though the server itself
    would have bound it fine - the check was stricter than the thing it guarded.
    And it gave up on the first failure, when a restart is inherently a race with
    the previous process letting go of the port.
    """
    deadline = time.time() + max(0.0, seconds)
    delay = 0.25
    while True:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Match the server's own option, or the probe rejects ports it could use.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host, port))
            return True
        except OSError:
            if time.time() >= deadline:
                return False
            print(f"[start] port {port} still busy - retrying...", flush=True)
            time.sleep(delay)
            delay = min(delay * 1.6, 2.0)
        finally:
            try:
                probe.close()
            except Exception:
                pass


def main():
    global _firewall_status, AI_AUTO
    try:
        import crashlog
        crashlog.install("airgpt")
    except Exception as e:
        print(f"[crashlog] disabled: {e}")
    AI_AUTO = _load_ai_auto()
    if not _wait_for_port(HOST, PORT):
        holder = _port_holder(PORT)
        who = f" Held by PID {holder}." if holder else ""
        print(f"Port {PORT} in use.{who} Run restart.bat, or stop that process first.")
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
    _boot_tunnel_threads()
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

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    # Netie Space is the front-door UI; set AIRGPT_NO_BROWSER=1 for backend-only.
    if os.environ.get("AIRGPT_NO_BROWSER", "").strip() not in ("1", "true", "TRUE", "yes", "YES"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    else:
        print("  UI:     browser suppressed (AIRGPT_NO_BROWSER=1) — use Netie Space\n")
    # serve_forever() should never raise — socketserver swallows per-request errors — but
    # if the accept loop itself trips, resume instead of taking the whole app down with it.
    while True:
        try:
            server.serve_forever()
            break
        except KeyboardInterrupt:
            server.server_close()
            break
        except Exception as e:
            print(f"[serve] accept loop error, resuming: {e}")
            try:
                import crashlog
                crashlog.exception("serve_forever", e)
            except Exception:
                pass
            time.sleep(0.5)


if __name__ == "__main__":
    main()

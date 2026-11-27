"""Host-only browser control through a local Playwright session.

Off unless AIRGPT_BROWSER_MCP=1. Element refs come from the accessibility
tree. Typing, clicking, choosing a dropdown option, and submit do nothing
unless confirmed is the boolean True. Opening a new origin (a different
scheme, host, or port, including the first page) needs that same confirm.
Same-origin navigation does not: the human already approved this origin.
A caller bound with bind_caller who fails clipdrop._is_host_request gets
host_only and no driver is started.

Sync Playwright is tied to the thread that started it. One owner thread
holds the browser. Other threads, including agent runs, only enqueue work.
The owner closes the browser when the session stops, on error, and at
process exit. Playwright is imported only when a host action needs a
session. A missing driver returns driver_missing.
"""
from __future__ import annotations

import atexit
import contextvars
import os
import queue
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_FLAG = "AIRGPT_BROWSER_MCP"
_caller: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "airgpt_browser_caller_host", default=None
)
_launches = 0
_state_lock = threading.Lock()
_owner_lock = threading.RLock()
_owner_thread: threading.Thread | None = None
_owner_queue: queue.Queue | None = None
_current_origin: tuple[str, str, int] | None = None
_pids: list[int] = []

_SECRET_RE = re.compile(
    r"(?i)(bearer\s+\S+|sk-[a-z0-9]{8,}|api[_-]?key[=:\s]+\S+"
    r"|token[=:\s]+\S+|password[=:\s]+\S+|cookie[=:\s]+\S+)"
)
_USERINFO_RE = re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@")
_SENSITIVE_QUERY = {
    "token",
    "key",
    "password",
    "passwd",
    "secret",
    "code",
    "auth",
    "session",
    "cookie",
    "access_token",
}
_DROP_KEYS = {
    "cookies",
    "cookie",
    "set-cookie",
    "authorization",
    "headers",
    "storage_state",
}
_NODE_CAP = 400
_DEPTH_CAP = 30


@dataclass
class _Session:
    pw: object
    browser: object
    context: object
    page: object
    refs: dict


_session: _Session | None = None


def enabled() -> bool:
    return (os.environ.get(_FLAG) or "").strip().lower() in {"1", "true", "yes", "on"}


def launch_count() -> int:
    return _launches


def caller_is_host() -> bool:
    """Unbound means this process (the host). A bound request uses the host gate."""
    bound = _caller.get()
    if bound is None:
        return True
    return bool(bound)


def bind_caller(headers, direct_ip: str) -> bool:
    """Record whether this request is the host. Fail closed if the gate cannot load."""
    try:
        import clipdrop

        ok = bool(clipdrop._is_host_request(headers, direct_ip or ""))
    except Exception:
        ok = False
    _caller.set(ok)
    return ok


def clear_caller() -> None:
    _caller.set(None)


def public_url(url: str) -> str:
    """URL safe to return to a model: no userinfo, no sensitive query, no fragment."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except Exception:
        return ""
    if parsed.scheme not in ("http", "https"):
        return ""
    host = parsed.hostname or ""
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in _SENSITIVE_QUERY:
            pairs.append((key, "[redacted]"))
        else:
            pairs.append((key, value))
    return urlunparse((parsed.scheme, netloc, parsed.path, "", urlencode(pairs), ""))


def _redact(text: str) -> str:
    if not text:
        return ""
    cleaned = _USERINFO_RE.sub(r"\1", text)
    return _SECRET_RE.sub("[redacted]", cleaned)


def _safe_detail(exc: BaseException) -> str:
    msg = _redact(str(exc)).replace("\n", " ")
    return f"{type(exc).__name__}: {msg[:160]}"


def _scrub(obj: Any, secrets: list[str]) -> Any:
    if isinstance(obj, str):
        out = _redact(obj)
        for secret in secrets:
            if secret and secret in out:
                out = out.replace(secret, "[redacted]")
        return out
    if isinstance(obj, list):
        return [_scrub(item, secrets) for item in obj]
    if isinstance(obj, dict):
        cleaned = {}
        for key, value in obj.items():
            if str(key).lower() in _DROP_KEYS:
                continue
            cleaned[str(key)] = _scrub(value, secrets)
        return cleaned
    return obj


def _masked_secret(value: str) -> bool:
    return bool(value) and set(value) <= {"•", "*", "●"}


def _collect_secrets(page) -> list[str]:
    """Password and hidden field values. Used only to strip, never returned."""
    try:
        vals = page.eval_on_selector_all(
            "input[type='password'], input[type='hidden']",
            "els => els.map(e => e.value || '')",
        )
    except Exception:
        return []
    found = []
    for value in vals or []:
        if isinstance(value, str) and len(value) >= 4:
            found.append(value)
    return found


def _url_block_reason(url: str) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return "empty_url"
    if len(raw) > 2000:
        return "url_too_long"
    if "://" in raw:
        rest = raw.split("://", 1)[1]
        hostpart = rest.split("/", 1)[0].split("?", 1)[0]
        if "@" in hostpart:
            return "credentials_in_url"
    try:
        parsed = urlparse(raw)
    except Exception:
        return "bad_url"
    if parsed.scheme not in ("http", "https"):
        return "unsupported_scheme"
    if parsed.username or parsed.password:
        return "credentials_in_url"
    if not parsed.hostname:
        return "bad_url"
    return None


def _caller_gate(*, mutating: bool, confirmed: bool) -> dict | None:
    """Host and confirm checks on the calling thread. Context vars do not cross threads."""
    if not enabled():
        _stop_owner()
        return {"ok": False, "error": "browser_mcp_disabled", "performed": False}
    if not caller_is_host():
        return {"ok": False, "error": "host_only", "performed": False}
    if mutating and confirmed is not True:
        return {
            "ok": False,
            "error": "confirm_required",
            "performed": False,
            "hint": "Typing, clicking, submit, and a new origin need confirmed=true after the human approves.",
        }
    return None


def _origin_of(url: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlparse(url or "")
    except Exception:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return (parsed.scheme, parsed.hostname.lower(), int(port))


def _is_new_origin(url: str) -> bool:
    """True when url leaves the origin already confirmed, or there is no page yet."""
    target = _origin_of(url)
    with _state_lock:
        current = _current_origin
    if target is None or current is None:
        return True
    return target != current


def _remember_origin(url: str) -> None:
    global _current_origin
    with _state_lock:
        _current_origin = _origin_of(url)


def _start_playwright():
    from playwright.sync_api import sync_playwright

    return sync_playwright().start()


def _candidate_executables() -> list[str | None]:
    found: list[str | None] = []
    env = (os.environ.get("AIRGPT_BROWSER_EXECUTABLE") or "").strip()
    if env and os.path.isfile(env):
        found.append(env)
    found.append(None)
    for path in (
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ):
        if path not in found and os.path.isfile(path):
            found.append(path)
    return found


def _launch_args() -> list[str]:
    flag = (os.environ.get("AIRGPT_BROWSER_NO_SANDBOX") or "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return ["--no-sandbox", "--disable-dev-shm-usage"]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return ["--no-sandbox", "--disable-dev-shm-usage"]
    return []


def _headless() -> bool:
    raw = (os.environ.get("AIRGPT_BROWSER_HEADLESS") or "1").strip().lower()
    return raw not in {"0", "false", "no"}


def _allow_request(url: str) -> bool:
    return url.startswith(("http://", "https://", "about:", "blob:"))


def _ensure_session() -> tuple[_Session | None, dict | None]:
    global _session, _launches
    if _session is not None:
        return _session, None
    try:
        pw = _start_playwright()
    except Exception:
        return None, {"ok": False, "error": "driver_missing", "performed": False}
    browser = None
    last = "driver_missing"
    for cand in _candidate_executables():
        try:
            kwargs: dict[str, Any] = {"headless": _headless(), "args": _launch_args()}
            if cand:
                kwargs["executable_path"] = cand
            browser = pw.chromium.launch(**kwargs)
            break
        except Exception as exc:
            last = _safe_detail(exc)
            browser = None
    if browser is None:
        try:
            pw.stop()
        except Exception:
            pass
        err: dict[str, Any] = {"ok": False, "error": "driver_missing", "performed": False}
        if last and last != "driver_missing":
            err["detail"] = last
        return None, err
    try:
        context = browser.new_context(viewport={"width": 800, "height": 600})
        page = context.new_page()
        page.set_default_timeout(8000)

        def _route(route):
            if _allow_request(route.request.url):
                route.continue_()
            else:
                route.abort()

        page.route("**/*", _route)
    except Exception as exc:
        try:
            browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass
        return None, {"ok": False, "error": "driver_failed", "performed": False, "detail": _safe_detail(exc)}
    _launches += 1
    created = _Session(pw=pw, browser=browser, context=context, page=page, refs={})
    with _state_lock:
        _session = created
    _publish_pids(_driver_pids(browser))
    return created, None


def _driver_pids(browser) -> list[int]:
    """Playwright driver pid plus its child browser processes, when we can see them."""
    pids: list[int] = []
    try:
        proc = browser._impl_obj._connection._transport._proc
        driver = int(getattr(proc, "pid", 0) or 0)
    except Exception:
        driver = 0
    if not driver:
        return pids
    pids.append(driver)
    if os.name == "nt":
        return pids
    try:
        for name in os.listdir("/proc"):
            if not name.isdigit() or int(name) == driver:
                continue
            try:
                stat = open(f"/proc/{name}/stat", encoding="utf-8", errors="replace").read().split()
                if int(stat[3]) == driver:
                    pids.append(int(name))
            except Exception:
                continue
    except Exception:
        pass
    return pids


def _publish_pids(pids: list[int]) -> None:
    global _pids
    with _state_lock:
        _pids = list(pids)


def _shutdown() -> None:
    """Close Playwright. Only the owner thread may call this."""
    global _session, _current_origin, _pids
    with _state_lock:
        sess = _session
        _session = None
        _current_origin = None
        _pids = []
    if sess is None:
        return
    for closer in (
        getattr(sess.context, "close", None),
        getattr(sess.browser, "close", None),
        getattr(sess.pw, "stop", None),
    ):
        if closer is None:
            continue
        try:
            closer()
        except Exception:
            pass


def _owner_main() -> None:
    try:
        while True:
            job = _owner_queue.get() if _owner_queue is not None else None
            if job is None:
                break
            fn, ev, box = job
            try:
                box["result"] = fn()
            except BaseException as exc:
                box["exc"] = exc
            finally:
                ev.set()
    finally:
        try:
            _shutdown()
        except Exception:
            pass


def _ensure_owner() -> threading.Thread:
    global _owner_thread, _owner_queue
    with _owner_lock:
        if _owner_thread is not None and _owner_thread.is_alive():
            return _owner_thread
        _owner_queue = queue.Queue()
        thread = threading.Thread(target=_owner_main, name="airgpt-browser-owner", daemon=True)
        _owner_thread = thread
        thread.start()
        return thread


def _on_owner(fn: Callable[[], dict], timeout: float = 45) -> dict:
    """Run fn on the Playwright owner thread. The caller thread only waits."""
    if _owner_thread is not None and threading.current_thread() is _owner_thread:
        return fn()
    ev = threading.Event()
    box: dict[str, Any] = {}
    with _owner_lock:
        _ensure_owner()
        assert _owner_queue is not None
        _owner_queue.put((fn, ev, box))
    if not ev.wait(timeout):
        return {"ok": False, "error": "browser_timeout", "performed": False}
    if "exc" in box:
        raise box["exc"]
    return box["result"]


def _clear_idle_origin() -> None:
    global _current_origin, _pids
    with _state_lock:
        _current_origin = None
        _pids = []


def _stop_owner() -> None:
    """Ask the owner to close the browser, then wait until that thread is gone."""
    global _owner_thread
    with _owner_lock:
        thread = _owner_thread
        jobs = _owner_queue
        if thread is None or not thread.is_alive():
            _owner_thread = None
            _clear_idle_origin()
            return
        if jobs is not None:
            jobs.put(None)
    thread.join(timeout=15)
    with _owner_lock:
        if _owner_thread is thread and not thread.is_alive():
            _owner_thread = None


def _shutdown_at_exit() -> None:
    try:
        _stop_owner()
    except Exception:
        pass


atexit.register(_shutdown_at_exit)


def session_open() -> bool:
    with _state_lock:
        return _session is not None


def browser_pids() -> list[int]:
    with _state_lock:
        return list(_pids)


def owner_thread_ident() -> int | None:
    thread = _owner_thread
    if thread is None or not thread.is_alive():
        return None
    return thread.ident


def _public_node(node: dict, counter: list, seen: dict, refs: dict, truncated: dict, depth: int) -> dict | None:
    if not isinstance(node, dict):
        return None
    if depth > _DEPTH_CAP or counter[0] >= _NODE_CAP:
        truncated["hit"] = True
        return None
    counter[0] += 1
    role = str(node.get("role") or "")
    raw_name = str(node.get("name") or "")
    nth = seen.get((role, raw_name), 0)
    seen[(role, raw_name)] = nth + 1
    ref = f"e{counter[0]}"
    refs[ref] = {"role": role, "name": raw_name, "nth": nth}
    public: dict[str, Any] = {"ref": ref, "role": role, "name": _redact(raw_name)}
    if node.get("value") is not None:
        raw_value = str(node.get("value") or "")
        public["value"] = "[redacted]" if _masked_secret(raw_value) else _redact(raw_value)
    children = []
    for child in node.get("children") or []:
        built = _public_node(child, counter, seen, refs, truncated, depth + 1)
        if built:
            children.append(built)
    if children:
        public["children"] = children
    return public


def _join(tree: dict | None) -> str:
    parts: list[str] = []

    def walk(node: dict) -> None:
        if not isinstance(node, dict):
            return
        name = str(node.get("name") or "")
        if name:
            parts.append(name)
        value = str(node.get("value") or "")
        if value and value != name:
            parts.append(value)
        for child in node.get("children") or []:
            walk(child)

    if isinstance(tree, dict):
        walk(tree)
    return "\n".join(parts)[:8000]


def _snapshot_dict(sess: _Session) -> dict:
    secrets = _collect_secrets(sess.page)
    try:
        raw = sess.page.accessibility.snapshot() or {}
    except Exception as exc:
        return {
            "ok": False,
            "error": "snapshot_failed",
            "performed": False,
            "detail": _safe_detail(exc),
            "text": "",
            "tree": {},
        }
    counter = [0]
    seen: dict = {}
    refs: dict = {}
    truncated = {"hit": False}
    tree = _public_node(raw, counter, seen, refs, truncated, 0) or {}
    sess.refs = refs
    tree = _scrub(tree, secrets)
    try:
        title = sess.page.title()
    except Exception:
        title = ""
    try:
        current = sess.page.url
    except Exception:
        current = ""
    return {
        "ok": True,
        "url": _scrub(public_url(current), secrets),
        "title": _scrub(_redact(title or ""), secrets),
        "tree": tree,
        "text": _join(tree if isinstance(tree, dict) else {}),
        "truncated": bool(truncated["hit"]),
    }


def _done(sess: _Session) -> dict:
    try:
        _remember_origin(sess.page.url)
    except Exception:
        pass
    snap = _snapshot_dict(sess)
    snap["performed"] = True
    return snap


def _locator(page, info: dict):
    role = info.get("role") or ""
    name = info.get("name") or ""
    nth = int(info.get("nth") or 0)
    if not role or not name:
        raise LookupError("unnamed_target")
    return page.get_by_role(role, name=name, exact=True).nth(nth)


def _perform(sess: _Session, kind: str, info: dict, *, text: str = "", option: str = "") -> None:
    loc = _locator(sess.page, info)
    if kind in ("click", "submit"):
        loc.click()
    elif kind == "type":
        loc.fill(text)
    elif kind == "select":
        loc.select_option(label=option)
    else:
        raise LookupError("unknown_kind")


def _act_impl(kind: str, ref: str, *, text: str = "", option: str = "") -> dict:
    sess, err = _ensure_session()
    if err:
        return err
    info = (sess.refs or {}).get(ref or "")
    if not info:
        return {"ok": False, "error": "unknown_ref", "performed": False}
    if not info.get("role") or not info.get("name"):
        return {"ok": False, "error": "unnamed_target", "performed": False}
    try:
        _perform(sess, kind, info, text=text, option=option)
    except Exception as exc:
        return {"ok": False, "error": "action_failed", "performed": False, "detail": _safe_detail(exc)}
    return _done(sess)


def _navigate_impl(url: str) -> dict:
    sess, err = _ensure_session()
    if err:
        return err
    try:
        sess.page.goto(url, wait_until="domcontentloaded")
    except Exception as exc:
        return {"ok": False, "error": "navigate_failed", "performed": False, "detail": _safe_detail(exc)}
    return _done(sess)


def _snapshot_impl() -> dict:
    sess, err = _ensure_session()
    if err:
        return err
    snap = _snapshot_dict(sess)
    snap["performed"] = False
    return snap


def status() -> dict:
    if not enabled():
        _stop_owner()
        return {"ok": True, "enabled": False, "launched": False, "performed": False}
    if not caller_is_host():
        return {"ok": False, "error": "host_only", "performed": False}
    return {
        "ok": True,
        "enabled": True,
        "launched": session_open(),
        "performed": False,
    }


def close() -> dict:
    if not caller_is_host():
        return {"ok": False, "error": "host_only", "performed": False}
    _stop_owner()
    return {"ok": True, "enabled": enabled(), "launched": session_open(), "performed": False}


def navigate(url: str = "", *, submit: bool = False, confirmed: bool = False) -> dict:
    if not enabled():
        _stop_owner()
        return {"ok": False, "error": "browser_mcp_disabled", "performed": False}
    if not caller_is_host():
        return {"ok": False, "error": "host_only", "performed": False}
    reason = _url_block_reason(url)
    if reason:
        return {"ok": False, "error": reason, "performed": False}
    # Same-origin GET stays unconfirmed: this scheme+host+port was already approved.
    # The first page has no origin yet, so it is a new origin and needs confirm.
    # submit=True is a navigation that sends the page, so it always needs confirm.
    if (submit or _is_new_origin(url)) and confirmed is not True:
        return {
            "ok": False,
            "error": "confirm_required",
            "performed": False,
            "hint": "Opening a new origin needs confirmed=true after the human approves.",
        }
    return _on_owner(lambda: _navigate_impl(url))


def snapshot() -> dict:
    denied = _caller_gate(mutating=False, confirmed=False)
    if denied:
        return denied
    return _on_owner(_snapshot_impl)


def click(ref: str = "", *, confirmed: bool = False) -> dict:
    denied = _caller_gate(mutating=True, confirmed=confirmed)
    if denied:
        return denied
    return _on_owner(lambda: _act_impl("click", ref))


def type_text(ref: str = "", text: str = "", *, confirmed: bool = False) -> dict:
    denied = _caller_gate(mutating=True, confirmed=confirmed)
    if denied:
        return denied
    if not text:
        return {"ok": False, "error": "empty_text", "performed": False}
    return _on_owner(lambda: _act_impl("type", ref, text=text))


def select_option(ref: str = "", option: str = "", *, confirmed: bool = False) -> dict:
    denied = _caller_gate(mutating=True, confirmed=confirmed)
    if denied:
        return denied
    if not option:
        return {"ok": False, "error": "empty_option", "performed": False}
    return _on_owner(lambda: _act_impl("select", ref, option=option))


def submit(ref: str = "", *, confirmed: bool = False) -> dict:
    denied = _caller_gate(mutating=True, confirmed=confirmed)
    if denied:
        return denied
    return _on_owner(lambda: _act_impl("submit", ref))

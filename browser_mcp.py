"""Host-only browser control through a local Playwright session.

Off unless AIRGPT_BROWSER_MCP=1. Element refs come from the accessibility
tree. Typing, clicking, choosing a dropdown option, and submit do nothing
unless confirmed is the boolean True. A caller bound with bind_caller who
fails clipdrop._is_host_request gets host_only and no driver is started.

Playwright is imported only when a host action actually needs a session.
The package is optional: a missing driver returns driver_missing.
"""
from __future__ import annotations

import atexit
import contextvars
import os
import re
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_FLAG = "AIRGPT_BROWSER_MCP"
_caller: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "airgpt_browser_caller_host", default=None
)
_lock = threading.RLock()
_launches = 0

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


def _precheck(*, mutating: bool, confirmed: bool) -> dict | None:
    if not enabled():
        _shutdown()
        return {"ok": False, "error": "browser_mcp_disabled", "performed": False}
    if not caller_is_host():
        return {"ok": False, "error": "host_only", "performed": False}
    if mutating and confirmed is not True:
        return {
            "ok": False,
            "error": "confirm_required",
            "performed": False,
            "hint": "Typing, clicking, and submit need confirmed=true after the human approves.",
        }
    return None


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
    _session = _Session(pw=pw, browser=browser, context=context, page=page, refs={})
    return _session, None


def _shutdown() -> None:
    global _session
    sess = _session
    _session = None
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


def _shutdown_at_exit() -> None:
    try:
        with _lock:
            _shutdown()
    except Exception:
        pass


atexit.register(_shutdown_at_exit)


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


def _act(kind: str, ref: str, *, confirmed: bool, text: str = "", option: str = "") -> dict:
    denied = _precheck(mutating=True, confirmed=confirmed)
    if denied:
        return denied
    if kind == "type" and not text:
        return {"ok": False, "error": "empty_text", "performed": False}
    if kind == "select" and not option:
        return {"ok": False, "error": "empty_option", "performed": False}
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


def status() -> dict:
    with _lock:
        if not enabled():
            _shutdown()
            return {"ok": True, "enabled": False, "launched": False, "performed": False}
        if not caller_is_host():
            return {"ok": False, "error": "host_only", "performed": False}
        return {
            "ok": True,
            "enabled": True,
            "launched": _session is not None,
            "performed": False,
        }


def close() -> dict:
    with _lock:
        if not caller_is_host():
            return {"ok": False, "error": "host_only", "performed": False}
        _shutdown()
        return {"ok": True, "enabled": enabled(), "launched": False, "performed": False}


def navigate(url: str = "", *, submit: bool = False, confirmed: bool = False) -> dict:
    with _lock:
        denied = _precheck(mutating=bool(submit), confirmed=confirmed)
        if denied:
            return denied
        reason = _url_block_reason(url)
        if reason:
            return {"ok": False, "error": reason, "performed": False}
        sess, err = _ensure_session()
        if err:
            return err
        try:
            sess.page.goto(url, wait_until="domcontentloaded")
        except Exception as exc:
            return {"ok": False, "error": "navigate_failed", "performed": False, "detail": _safe_detail(exc)}
        return _done(sess)


def snapshot() -> dict:
    with _lock:
        denied = _precheck(mutating=False, confirmed=False)
        if denied:
            return denied
        sess, err = _ensure_session()
        if err:
            return err
        snap = _snapshot_dict(sess)
        snap["performed"] = False
        return snap


def click(ref: str = "", *, confirmed: bool = False) -> dict:
    with _lock:
        return _act("click", ref, confirmed=confirmed)


def type_text(ref: str = "", text: str = "", *, confirmed: bool = False) -> dict:
    with _lock:
        return _act("type", ref, confirmed=confirmed, text=text or "")


def select_option(ref: str = "", option: str = "", *, confirmed: bool = False) -> dict:
    with _lock:
        return _act("select", ref, confirmed=confirmed, option=option or "")


def submit(ref: str = "", *, confirmed: bool = False) -> dict:
    with _lock:
        return _act("submit", ref, confirmed=confirmed)

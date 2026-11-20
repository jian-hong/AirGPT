"""AirGPT workspace auth — host passcode, encrypted local storage."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import threading
import time

from config import DATA_DIR

WORKSPACE_FILE = DATA_DIR / "workspace.json"
TOKENS_FILE = DATA_DIR / "auth_tokens.json"
TOKEN_TTL = 86400 * 30
QR_TOKEN_TTL = 600  # 10 min one-time scan tokens
_tokens: dict[str, float] = {}
_qr_tokens: dict[str, float] = {}


_tokens_lock = threading.RLock()


def _load_tokens() -> None:
    global _tokens
    if not TOKENS_FILE.is_file():
        return
    with _tokens_lock:
        try:
            raw = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
            now = time.time()
            _tokens = {k: float(v) for k, v in raw.items() if float(v) > now}
        except Exception:
            _tokens = {}


def _swap(tmp, path) -> None:
    """os.replace that waits out a reader. On Windows a file cannot be replaced while
    anything (another request, a virus scanner, the indexer) still has it open."""
    for attempt in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.025)


def _save_tokens() -> None:
    # Swap the file in one step under the lock. Two phones joining at once used to
    # leave it half written; the next read then emptied the list and logged everyone out.
    with _tokens_lock:
        TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = TOKENS_FILE.with_name(TOKENS_FILE.name + ".tmp")
        tmp.write_text(json.dumps(_tokens), encoding="utf-8")
        _swap(tmp, TOKENS_FILE)


_acl_lock = threading.RLock()


def _read_acl_map() -> dict:
    """The share scopes, read under the same lock the writer holds.

    A file that is there but cannot be read raises. It must never read as "no
    scopes": a share guest without a scope is an ordinary device and sees every chat.
    """
    path = DATA_DIR / "token_session_acl.json"
    with _acl_lock:
        if not path.is_file():
            return {}
        acl_map = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(acl_map, dict):
        raise ValueError("token_session_acl.json is not a map")
    return acl_map


def _update_acl_map(mutate) -> None:
    """Change token_session_acl.json under a lock and swap the file in one step.

    A reader that caught the file half-written, or a second redeem that overwrote the
    first, made a share guest look like an ordinary device, and an ordinary device
    sees every chat.
    """
    path = DATA_DIR / "token_session_acl.json"
    with _acl_lock:
        acl_map = _read_acl_map()  # unreadable: raise, never start again from empty
        mutate(acl_map)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(acl_map), encoding="utf-8")
        _swap(tmp, path)


def _bind_scope(tok: str, scope: dict) -> None:
    """Tie a fresh guest token to its scope. If that fails the token is withdrawn:
    a token that exists without its scope would be a full-access device."""
    try:
        _update_acl_map(lambda acl_map: acl_map.__setitem__(tok, scope))
    except Exception:
        _tokens.pop(tok, None)
        _save_tokens()
        raise


_load_tokens()


def _hash_passcode(passcode: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", passcode.encode("utf-8"), salt.encode("utf-8"), 120_000,
    ).hex()


DAMAGED_MSG = (
    "The passcode file on the host PC is damaged, so remote access is off. "
    "A copy was kept as workspace.json.bad in the data folder. On the host PC, "
    "restore it from a backup or remove workspace.json and set a new passcode."
)


def _load() -> dict:
    """The workspace file. A file that is there but unreadable must never read as
    "no passcode": that would open the gate. It reads as damaged, which refuses
    remote access, and the bad file is kept as workspace.json.bad."""
    if not WORKSPACE_FILE.is_file():
        return {}
    try:
        data = json.loads(WORKSPACE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    bad = WORKSPACE_FILE.with_name(WORKSPACE_FILE.name + ".bad")
    try:
        if not bad.exists():
            shutil.copyfile(WORKSPACE_FILE, bad)
    except OSError:
        pass
    return {"_damaged": True, "pass_hash": "!damaged", "salt": "", "email": ""}


def _save(data: dict) -> None:
    if data.get("_damaged"):
        raise RuntimeError(DAMAGED_MSG)
    WORKSPACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = WORKSPACE_FILE.with_name(WORKSPACE_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _swap(tmp, WORKSPACE_FILE)


def passcode_required() -> bool:
    """Is the phone passcode gate armed? Default on whenever a passcode exists."""
    ws = _load()
    if not ws.get("pass_hash"):
        return False
    return not bool(ws.get("passcode_off"))


def set_passcode_required(required: bool) -> dict:
    """Arm or disarm the phone gate WITHOUT destroying the passcode.

    Keeping `pass_hash` means re-arming is one tap instead of a fresh workspace setup —
    the point of this switch is a way back in for someone locked out of their own
    laptop, not a convenience default. Callers must enforce host-only; this function
    does not know who is asking.
    """
    ws = _load()
    if ws.get("_damaged"):
        return {"ok": False, "error": DAMAGED_MSG}
    if not ws.get("pass_hash"):
        return {"ok": False, "error": "No passcode set on this machine yet"}
    ws["passcode_off"] = not bool(required)
    ws["passcode_changed_at"] = time.time()
    _save(ws)
    return {"ok": True, "passcode_required": passcode_required()}


def status() -> dict:
    ws = _load()
    required = passcode_required()
    no_passcode = not bool(ws.get("pass_hash"))
    passcode_set = bool(ws.get("pass_hash"))
    damaged = bool(ws.get("_damaged"))
    return {
        "damaged": damaged,
        "damaged_reason": DAMAGED_MSG if damaged else "",
        "initialized": passcode_set,
        "host_email": ws.get("email", ""),
        # Disarming the gate opens LAN access on purpose — the UI shows a standing
        # warning while this is false. An *unset* passcode is not that opt-in:
        # needs_auth True is what makes clipdrop._join_url mint a QR token
        # instead of returning a bare URL (HOST-DEMO-05 / #27).
        "needs_auth": True if no_passcode else required,
        "passcode_required": required,
        "passcode_set": passcode_set,
        # S1 / EPIC-D10: LAN and tunnel stay closed until a passcode exists.
        # Disarming after that is the existing host-only switch, not this flag.
        "s1_remote_open": passcode_set,
    }


def init_workspace(email: str, passcode: str) -> dict:
    email = (email or "").strip()[:120]
    passcode = (passcode or "").strip()
    if len(passcode) < 4:
        return {"ok": False, "error": "Passcode must be at least 4 characters"}
    if not email or "@" not in email:
        return {"ok": False, "error": "Valid email required for host"}
    ws = _load()
    if ws.get("_damaged"):
        return {"ok": False, "error": DAMAGED_MSG}
    if ws.get("pass_hash"):
        return {"ok": False, "error": "Workspace already initialized on this machine"}
    salt = secrets.token_hex(16)
    # Keep OpenIDE root/name if they already share this file. Do not wipe
    # the bound repo just because the host is creating a passcode.
    ws = dict(ws)
    ws.update({
        "email": email,
        "salt": salt,
        "pass_hash": _hash_passcode(passcode, salt),
        "created_at": time.time(),
    })
    _save(ws)
    tok = _issue_token()
    return {"ok": True, "token": tok, "role": "host", "email": email}


def join_workspace(passcode: str) -> dict:
    passcode = (passcode or "").strip()
    ws = _load()
    if ws.get("_damaged"):
        return {"ok": False, "error": DAMAGED_MSG}
    if not ws.get("pass_hash"):
        return {"ok": False, "error": "Host has not set up this workspace yet"}
    salt = ws.get("salt", "")
    if _hash_passcode(passcode, salt) != ws["pass_hash"]:
        return {"ok": False, "error": "Wrong passcode — access denied"}
    tok = _issue_token()
    return {"ok": True, "token": tok, "role": "guest", "email": ws.get("email", "")}


def _issue_token() -> str:
    tok = secrets.token_urlsafe(32)
    with _tokens_lock:
        _tokens[tok] = time.time() + TOKEN_TTL
        _save_tokens()
    return tok


def verify_token(token: str | None) -> bool:
    if not token:
        return False
    if token in _revoked_tokens:
        return False
    _load_tokens()
    ws = _load()
    if ws.get("_damaged"):
        return False
    if not ws.get("pass_hash"):
        return True
    exp = _tokens.get(token)
    if not exp:
        return False
    if time.time() > exp:
        _tokens.pop(token, None)
        _save_tokens()
        return False
    return True


def issue_qr_token(host_token: str | None = None, host_verified: bool = False) -> str | None:
    """Mint a one-time QR join token. Host machine or authenticated host only.

    A missing passcode is not an open invitation: we still mint a token so the
    share QR carries a credential instead of a bare URL (HOST-DEMO-05 / #27).
    Only the host machine may mint in that state — a remote token is not enough,
    because verify_token treats any token as valid when no pass_hash exists.
    """
    ws = _load()
    if not host_verified:
        if not ws.get("pass_hash"):
            return None
        if not host_token or not verify_token(host_token):
            return None
    tok = secrets.token_urlsafe(20)
    _qr_tokens[tok] = time.time() + QR_TOKEN_TTL
    return tok


def redeem_qr_token(qr_token: str) -> dict:
    qr_token = (qr_token or "").strip()
    exp = _qr_tokens.get(qr_token)
    if not exp or time.time() > exp:
        _qr_tokens.pop(qr_token, None)
        return {"ok": False, "error": "QR expired — ask host to refresh QR Connect"}
    _qr_tokens.pop(qr_token, None)
    tok = _issue_token()
    return {"ok": True, "token": tok, "role": "guest"}


def verify_passcode(passcode: str) -> bool:
    ws = _load()
    if not ws.get("pass_hash"):
        return True
    salt = ws.get("salt", "")
    return _hash_passcode((passcode or "").strip(), salt) == ws["pass_hash"]


def export_workspace_hint() -> str:
    return str(WORKSPACE_FILE)


# --- Per-session share tokens (view / post ACL) ---
SESSION_SHARES_FILE = DATA_DIR / "session_shares.json"
_session_shares: dict[str, dict] = {}
SESSION_SHARE_TTL = 86400 * 7  # 7 days


def _load_session_shares() -> None:
    global _session_shares
    if not SESSION_SHARES_FILE.is_file():
        _session_shares = {}
        return
    try:
        raw = json.loads(SESSION_SHARES_FILE.read_text(encoding="utf-8"))
        now = time.time()
        _session_shares = {
            k: v for k, v in raw.items()
            if isinstance(v, dict) and float(v.get("exp", 0)) > now
        }
    except Exception:
        _session_shares = {}


def _save_session_shares() -> None:
    SESSION_SHARES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_SHARES_FILE.write_text(json.dumps(_session_shares), encoding="utf-8")


_load_session_shares()


def token_session_acl(token: str | None) -> dict | None:
    """Return {session_id, acl, access_level, ai_mode, limited} if scoped, else None.

    None means "this token has no scope" and nothing else. A scope file that cannot
    be read, or a damaged entry, raises instead: the caller then refuses the request
    rather than treating a share guest as an ordinary device. The scope lasts as long
    as the token does (verify_token decides that); it does not lapse on its own.
    """
    if not token:
        return None
    entry = _read_acl_map().get(token)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise ValueError("damaged share scope")
    level = entry.get("access_level") or entry.get("acl", "view")
    acl = entry.get("acl") or _level_to_acl(level)
    return {
        "session_id": int(entry.get("session_id") or 0),
        "acl": acl,
        "access_level": level,
        "ai_mode": entry.get("ai_mode", "host" if level == "use_host_ai" else "own" if level == "use_own_ai" else ""),
        "limited": bool(entry.get("limited") or level == "limited"),
    }


# --- Hub access levels ---
ACL_LEVELS = ("read_only", "read_write", "use_host_ai", "use_own_ai", "limited")
JOIN_CODES_FILE = DATA_DIR / "join_codes.json"
JOIN_CODE_TTL = 86400 * 2  # 48h
TOKEN_META_FILE = DATA_DIR / "token_meta.json"
_revoked_tokens: set[str] = set()


def _level_to_acl(level: str) -> str:
    level = (level or "").strip().lower()
    if level in ("read_only", "limited", "view"):
        return "view"
    return "post"


def _acl_to_level(acl: str) -> str:
    acl = (acl or "").strip().lower()
    if acl == "view":
        return "read_only"
    return "read_write"


def _load_join_codes() -> dict:
    if not JOIN_CODES_FILE.is_file():
        return {}
    try:
        raw = json.loads(JOIN_CODES_FILE.read_text(encoding="utf-8"))
        now = time.time()
        return {k: v for k, v in raw.items() if isinstance(v, dict) and float(v.get("exp", 0)) > now}
    except Exception:
        return {}


def _save_join_codes(codes: dict) -> None:
    JOIN_CODES_FILE.parent.mkdir(parents=True, exist_ok=True)
    JOIN_CODES_FILE.write_text(json.dumps(codes, indent=2), encoding="utf-8")


def issue_join_code(
    access_level: str = "read_write",
    *,
    host_token: str | None = None,
    host_verified: bool = False,
) -> dict:
    """Teams-style short join code."""
    level = (access_level or "read_write").strip().lower()
    if level not in ACL_LEVELS:
        level = "read_write"
    ws = _load()
    if ws.get("pass_hash") and not host_verified:
        if not host_token or not verify_token(host_token):
            return {"ok": False, "error": "host auth required"}
    code = secrets.token_hex(3).upper()  # 6-char hex
    codes = _load_join_codes()
    while code in codes:
        code = secrets.token_hex(3).upper()
    exp = time.time() + JOIN_CODE_TTL
    codes[code] = {
        "access_level": level,
        "exp": exp,
        "created_at": time.time(),
    }
    _save_join_codes(codes)
    return {"ok": True, "code": code, "access_level": level, "expires_at": exp}


def redeem_join_code(code: str) -> dict:
    code = (code or "").strip().upper()
    codes = _load_join_codes()
    entry = codes.get(code)
    if not entry or float(entry.get("exp", 0)) <= time.time():
        return {"ok": False, "error": "Invalid or expired join code"}
    tok = _issue_token()
    level = entry.get("access_level", "read_write")
    _set_token_meta(tok, {
        "access_level": level,
        "join_method": "team",
        "role": "guest",
    })
    return {
        "ok": True,
        "token": tok,
        "role": "guest",
        "access_level": level,
        "join_method": "team",
    }


def _set_token_meta(token: str, meta: dict) -> None:
    try:
        data = json.loads(TOKEN_META_FILE.read_text(encoding="utf-8")) if TOKEN_META_FILE.is_file() else {}
    except Exception:
        data = {}
    data[token] = {**meta, "exp": time.time() + TOKEN_TTL}
    TOKEN_META_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_META_FILE.write_text(json.dumps(data), encoding="utf-8")


def token_meta(token: str | None) -> dict | None:
    if not token:
        return None
    if token in _revoked_tokens:
        return None
    if not TOKEN_META_FILE.is_file():
        return None
    try:
        data = json.loads(TOKEN_META_FILE.read_text(encoding="utf-8"))
        entry = data.get(token)
        if not entry or float(entry.get("exp", 0)) <= time.time():
            return None
        return entry
    except Exception:
        return None


def revoke_token(token: str) -> dict:
    token = (token or "").strip()
    if not token:
        return {"ok": False, "error": "token required"}
    _revoked_tokens.add(token)
    _tokens.pop(token, None)
    _save_tokens()
    if (DATA_DIR / "token_session_acl.json").is_file():
        try:
            _update_acl_map(lambda acl_map: acl_map.pop(token, None))
        except Exception:
            pass
    if TOKEN_META_FILE.is_file():
        try:
            data = json.loads(TOKEN_META_FILE.read_text(encoding="utf-8"))
            data.pop(token, None)
            TOKEN_META_FILE.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass
    return {"ok": True, "revoked": True}


def issue_session_share(
    session_id: int,
    acl: str = "view",
    *,
    host_token: str | None = None,
    host_verified: bool = False,
    access_level: str = "",
) -> dict:
    """Mint a share token for a specific chat session."""
    acl = (acl or "view").strip().lower()
    level = (access_level or _acl_to_level(acl)).strip().lower()
    if level not in ACL_LEVELS:
        level = _acl_to_level(acl)
    if acl not in ("view", "post"):
        acl = _level_to_acl(level)
    if int(session_id or 0) <= 0:
        return {"ok": False, "error": "session_id required"}
    ws = _load()
    if ws.get("pass_hash") and not host_verified:
        if not host_token or not verify_token(host_token):
            return {"ok": False, "error": "host auth required to share"}
    tok = secrets.token_urlsafe(20)
    exp = time.time() + SESSION_SHARE_TTL
    _session_shares[tok] = {
        "session_id": int(session_id),
        "acl": acl,
        "access_level": level,
        "exp": exp,
        "created_at": time.time(),
    }
    _save_session_shares()
    return {
        "ok": True,
        "share_token": tok,
        "session_id": int(session_id),
        "acl": acl,
        "access_level": level,
        "expires_at": exp,
    }


def redeem_session_share(share_token: str) -> dict:
    """One-time redeem of a session share → workspace token + scoped ACL."""
    share_token = (share_token or "").strip()
    _load_session_shares()
    entry = _session_shares.get(share_token)
    if not entry or float(entry.get("exp", 0)) <= time.time():
        _session_shares.pop(share_token, None)
        _save_session_shares()
        return {"ok": False, "error": "Share link expired — ask host for a fresh QR"}
    # Keep reusable for TTL (multi-device), but still issue a guest token
    tok = _issue_token()
    # Bind ACL to guest token
    _bind_scope(tok, {
        "session_id": int(entry["session_id"]),
        "acl": entry.get("acl", "view"),
        "access_level": entry.get("access_level", _acl_to_level(entry.get("acl", "view"))),
        "ai_mode": "host" if entry.get("access_level") == "use_host_ai" else (
            "own" if entry.get("access_level") == "use_own_ai" else ""
        ),
        "limited": entry.get("access_level") == "limited",
        "exp": time.time() + TOKEN_TTL,
    })
    _set_token_meta(tok, {
        "access_level": entry.get("access_level", _acl_to_level(entry.get("acl", "view"))),
        "join_method": "qr",
        "role": "share_guest",
        "session_id": int(entry["session_id"]),
    })
    return {
        "ok": True,
        "token": tok,
        "role": "share_guest",
        "session_id": int(entry["session_id"]),
        "acl": entry.get("acl", "view"),
        "access_level": entry.get("access_level", _acl_to_level(entry.get("acl", "view"))),
    }


# --- Project-level share (same mint/redeem shape as session share) ---
PROJECT_SHARES_FILE = DATA_DIR / "project_shares.json"
_project_shares: dict[str, dict] = {}
PROJECT_SHARE_TTL = 86400 * 7


def _load_project_shares() -> None:
    global _project_shares
    if not PROJECT_SHARES_FILE.is_file():
        _project_shares = {}
        return
    try:
        raw = json.loads(PROJECT_SHARES_FILE.read_text(encoding="utf-8"))
        now = time.time()
        _project_shares = {
            k: v for k, v in raw.items()
            if isinstance(v, dict) and float(v.get("exp", 0)) > now
        }
    except Exception:
        _project_shares = {}


def _save_project_shares() -> None:
    PROJECT_SHARES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROJECT_SHARES_FILE.write_text(json.dumps(_project_shares), encoding="utf-8")


_load_project_shares()


def issue_project_share(
    project_key: str,
    acl: str = "read_only",
    *,
    host_token: str | None = None,
    host_verified: bool = False,
) -> dict:
    """Mint a share token for a project category key. Defaults to read_only."""
    key = (project_key or "").strip()
    if not key:
        return {"ok": False, "error": "project_key required"}
    level = (acl or "read_only").strip().lower()
    if level not in ACL_LEVELS:
        level = "read_only"
    view_acl = _level_to_acl(level)
    ws = _load()
    if ws.get("pass_hash") and not host_verified:
        if not host_token or not verify_token(host_token):
            return {"ok": False, "error": "host auth required to share"}
    tok = secrets.token_urlsafe(20)
    exp = time.time() + PROJECT_SHARE_TTL
    _project_shares[tok] = {
        "project_key": key,
        "acl": view_acl,
        "access_level": level,
        "exp": exp,
        "created_at": time.time(),
    }
    _save_project_shares()
    return {
        "ok": True,
        "share_token": tok,
        "token": tok,
        "project_key": key,
        "acl": view_acl,
        "access_level": level,
        "expires_at": exp,
    }


def redeem_project_share(share_token: str) -> dict:
    """Redeem a project share → workspace token with project-scoped ACL."""
    share_token = (share_token or "").strip()
    _load_project_shares()
    entry = _project_shares.get(share_token)
    if not entry or float(entry.get("exp", 0)) <= time.time():
        _project_shares.pop(share_token, None)
        _save_project_shares()
        return {"ok": False, "error": "Share link expired — ask host for a fresh QR"}
    tok = _issue_token()
    level = entry.get("access_level", "read_only")
    _bind_scope(tok, {
        "project_key": entry.get("project_key"),
        "acl": entry.get("acl", "view"),
        "access_level": level,
        "ai_mode": "host" if level == "use_host_ai" else (
            "own" if level == "use_own_ai" else ""
        ),
        "limited": level == "limited",
        "exp": time.time() + TOKEN_TTL,
    })
    _set_token_meta(tok, {
        "access_level": level,
        "join_method": "qr",
        "role": "project_guest",
        "project_key": entry.get("project_key"),
    })
    return {
        "ok": True,
        "token": tok,
        "role": "project_guest",
        "project_key": entry.get("project_key"),
        "acl": entry.get("acl", "view"),
        "access_level": level,
    }

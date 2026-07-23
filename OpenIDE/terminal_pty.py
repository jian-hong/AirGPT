"""PTY sessions for OpenIDE terminal (allowlisted commands)."""
from __future__ import annotations

import os
import shlex
import subprocess
import time
import uuid
from pathlib import Path

# Exact argv[0] names or first-two-token prefixes for git
ALLOWED_BINARIES = frozenset(
    {
        "python",
        "python3",
        "py",
        "pip",
        "pip3",
        "npm",
        "npx",
        "node",
        "pytest",
        "cargo",
        "go",
        "dir",
        "ls",
        "echo",
        "git",
        "gh",
    }
)
ALLOWED_GIT_SUB = frozenset(
    {
        "status",
        "diff",
        "log",
        "branch",
        "show",
        "rev-parse",
        "add",
        "commit",
        "push",
        "fetch",
        "checkout",
        "worktree",
        "remote",
    }
)
ALLOWED_GH_PR_SUB = frozenset({"create", "view", "status", "list", "checks"})
# Block dangerous python / py flags that enable arbitrary code
BLOCKED_FLAGS = frozenset({"-c", "-m", "--command"})


def _allowed(cmd: str) -> bool:
    c = (cmd or "").strip()
    if not c:
        return False
    # No shell metacharacters — we never use shell=True
    if any(x in c for x in ("|", "&", ";", "`", "$(", ">", "<", "\n", "\r")):
        return False
    try:
        parts = shlex.split(c, posix=os.name != "nt")
    except ValueError:
        return False
    if not parts:
        return False
    bin0 = Path(parts[0]).name.lower()
    if bin0.endswith(".exe"):
        bin0 = bin0[:-4]
    if bin0 not in ALLOWED_BINARIES:
        return False
    if bin0 in ("python", "python3", "py"):
        # Allow: python path/to/script.py …  or  python -m pytest …
        rest = [p.lower() for p in parts[1:]]
        if "-c" in rest or "--command" in rest:
            return False
        if "-m" in rest:
            # only allow a few modules
            try:
                mi = rest.index("-m")
                mod = rest[mi + 1] if mi + 1 < len(rest) else ""
            except ValueError:
                mod = ""
            if mod not in ("pytest", "pip", "http.server"):
                return False
        return True
    if bin0 == "git":
        if len(parts) < 2:
            return False
        sub = parts[1].lower()
        if sub not in ALLOWED_GIT_SUB:
            return False
        # worktree: only list / add / prune (no remove of arbitrary trees)
        if sub == "worktree":
            if len(parts) < 3:
                return False
            return parts[2].lower() in ("list", "add", "prune")
        # push: no --force
        if sub == "push" and any(p in ("--force", "-f", "--force-with-lease") for p in parts[2:]):
            return False
        return True
    if bin0 == "gh":
        # Read-only auth probe (no interactive login — that stays out-of-band)
        if len(parts) >= 3 and parts[1].lower() == "auth" and parts[2].lower() == "status":
            return True
        # gh pr create|view|status|list|checks …
        if len(parts) < 3 or parts[1].lower() != "pr":
            return False
        return parts[2].lower() in ALLOWED_GH_PR_SUB
    return True


def _argv(cmd: str) -> list[str]:
    return shlex.split(cmd.strip(), posix=os.name != "nt")


def run_command(cmd: str, *, cwd: str = "", timeout: float = 120.0) -> dict:
    if not _allowed(cmd):
        return {"ok": False, "error": "command not allowlisted", "exit_code": -1, "stdout": "", "stderr": ""}
    work = cwd if cwd and Path(cwd).is_dir() else os.getcwd()
    try:
        argv = _argv(cmd)
        proc = subprocess.run(
            argv,
            shell=False,
            cwd=work,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": (proc.stdout or "")[-12000:],
            "stderr": (proc.stderr or "")[-4000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "exit_code": -1, "stdout": "", "stderr": "timeout"}
    except OSError as e:
        return {"ok": False, "error": str(e)[:200], "exit_code": -1, "stdout": "", "stderr": ""}


_sessions: dict[str, dict] = {}


def start_session(cwd: str = "") -> dict:
    sid = uuid.uuid4().hex[:12]
    work = cwd if cwd and Path(cwd).is_dir() else os.getcwd()
    _sessions[sid] = {"cwd": work, "created": time.time(), "output": [], "running": False}
    return {"ok": True, "session_id": sid, "cwd": work}


def exec_in_session(session_id: str, cmd: str) -> dict:
    sess = _sessions.get(session_id)
    if not sess:
        return {"ok": False, "error": "unknown session"}
    res = run_command(cmd, cwd=sess["cwd"])
    line = f"$ {cmd}\n{(res.get('stdout') or '')}{(res.get('stderr') or '')}"
    sess["output"].append(line[-16000:])
    if len(sess["output"]) > 50:
        sess["output"] = sess["output"][-50:]
    return {**res, "session_id": session_id}


def read_session(session_id: str) -> dict:
    sess = _sessions.get(session_id)
    if not sess:
        return {"ok": False, "error": "unknown session"}
    return {"ok": True, "session_id": session_id, "output": "\n".join(sess["output"])[-32000:]}

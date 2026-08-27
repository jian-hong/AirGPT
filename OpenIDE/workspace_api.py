"""OpenIDE workspace: repo bind, path-jailed filesystem, checkpoints."""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import time
from pathlib import Path

from config import DATA_DIR

WORKSPACE_FILE = DATA_DIR / "workspace.json"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
DENY_NAMES = frozenset(
    {
        "env.local",
        ".env",
        "license.json",
        "agents.db",
        "clipdrop.db",
    }
)
# Heavy dirs — never walk on OpenIDE tree / find (human lag on big repos)
SKIP_DIRS = frozenset(
    {
        "node_modules",
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "target",
        ".next",
        "vendor",
        "research",
        "CortexOS",
        ".cursor",
        "video-assets",
        "third_party",
    }
)
_fp_cache: list = [0.0, {}]  # monotonic, fingerprint dict


def _load() -> dict:
    if WORKSPACE_FILE.is_file():
        try:
            return json.loads(WORKSPACE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(data: dict) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def get_workspace() -> dict:
    d = _load()
    root = str(d.get("root") or "")
    if root and Path(root).is_dir():
        return {"ok": True, "root": root, "name": d.get("name") or Path(root).name}
    return {"ok": False, "root": "", "name": ""}


def open_workspace(path: str, *, name: str = "") -> dict:
    p = Path(path).resolve()
    if not p.is_dir():
        return {"ok": False, "error": "not a directory"}
    data = {"root": str(p), "name": (name or p.name)[:120], "opened_at": time.time()}
    _save(data)
    return {"ok": True, **data}


def _root() -> Path | None:
    ws = get_workspace()
    if not ws.get("ok"):
        return None
    return Path(ws["root"]).resolve()


def resolve_rel(rel: str) -> tuple[Path | None, str | None]:
    root = _root()
    if not root:
        return None, "no workspace open"
    rel = (rel or "").replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        return None, "path escape denied"
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None, "path escape denied"
    if target.name in DENY_NAMES:
        return None, "path denied"
    return target, None


def list_tree(rel: str = "", *, max_depth: int = 1) -> dict:
    """Shallow tree by default (depth 1) — expand dirs on click. Skips heavy folders."""
    root = _root()
    if not root:
        return {"ok": False, "error": "no workspace", "entries": []}
    base, err = resolve_rel(rel)
    if err or not base:
        return {"ok": False, "error": err or "invalid path", "entries": []}
    if not base.is_dir():
        return {"ok": False, "error": "not a directory", "entries": []}

    def walk(dir_path: Path, depth: int) -> list[dict]:
        out: list[dict] = []
        if depth > max_depth:
            return out
        try:
            items = sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except OSError:
            return out
        count = 0
        for p in items:
            if count >= 250:
                out.append({"name": f"+{len(items) - count} more…", "path": "", "type": "more"})
                break
            if p.name.startswith(".") and p.name not in (".airgpt",):
                continue
            if p.name in DENY_NAMES or p.name in SKIP_DIRS:
                continue
            rel_p = str(p.relative_to(root)).replace("\\", "/")
            if p.is_dir():
                # Lazy: only expand children when depth allows; else mark expandable
                children = walk(p, depth + 1) if depth < max_depth else []
                out.append({"name": p.name, "path": rel_p, "type": "dir", "children": children})
            else:
                try:
                    out.append({"name": p.name, "path": rel_p, "type": "file", "size": p.stat().st_size})
                except OSError:
                    pass
            count += 1
        return out

    return {"ok": True, "root": str(root), "path": rel, "entries": walk(base, 0)}


def read_file(rel: str, *, max_bytes: int = 512_000) -> dict:
    target, err = resolve_rel(rel)
    if err or not target:
        return {"ok": False, "error": err or "invalid"}
    if not target.is_file():
        return {"ok": False, "error": "not a file"}
    try:
        data = target.read_bytes()[:max_bytes]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return {"ok": False, "error": "binary file"}
        return {"ok": True, "path": rel, "content": text, "truncated": target.stat().st_size > max_bytes}
    except OSError as e:
        return {"ok": False, "error": str(e)[:200]}


def line_deltas(before: str, after: str) -> tuple[int, int]:
    """Return (added_lines, deleted_lines) so the host shell can show +N -M."""
    a = (before or "").splitlines()
    b = (after or "").splitlines()
    added = deleted = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b).get_opcodes():
        if tag == "insert":
            added += j2 - j1
        elif tag == "delete":
            deleted += i2 - i1
        elif tag == "replace":
            deleted += i2 - i1
            added += j2 - j1
    return added, deleted


def _file_text(target: Path) -> str:
    if not target.is_file():
        return ""
    try:
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def write_file(rel: str, content: str, *, apply: bool = True) -> dict:
    target, err = resolve_rel(rel)
    if err or not target:
        return {"ok": False, "error": err or "invalid"}
    after = content or ""
    added, deleted = line_deltas(_file_text(target), after)
    if not apply:
        return {
            "ok": True,
            "preview": True,
            "path": rel,
            "bytes": len(after),
            "added_lines": added,
            "deleted_lines": deleted,
        }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(after, encoding="utf-8")
        return {
            "ok": True,
            "path": rel,
            "bytes": len(after),
            "added_lines": added,
            "deleted_lines": deleted,
        }
    except OSError as e:
        return {"ok": False, "error": str(e)[:200]}


def ensure_dir(rel: str) -> dict:
    """Create a path-jailed directory (parents ok)."""
    target, err = resolve_rel(rel)
    if err or not target:
        return {"ok": False, "error": err or "invalid"}
    try:
        target.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "path": rel}
    except OSError as e:
        return {"ok": False, "error": str(e)[:200]}


def write_tree(files: dict[str, str], *, apply: bool = True) -> dict:
    """Write many relative files under the open workspace. All-or-nothing on first error."""
    if not isinstance(files, dict) or not files:
        return {"ok": False, "error": "files required"}
    written: list[str] = []
    for rel, content in files.items():
        r = write_file(str(rel), str(content if content is not None else ""), apply=apply)
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error") or "write failed", "path": rel, "written": written}
        written.append(str(rel).replace("\\", "/"))
    return {"ok": True, "written": written, "count": len(written), "preview": not apply}


def patch_file(rel: str, old: str, new: str, *, apply: bool = True) -> dict:
    rf = read_file(rel)
    if not rf.get("ok"):
        return rf
    content = rf.get("content") or ""
    if old not in content:
        return {"ok": False, "error": "old text not found"}
    updated = content.replace(old, new, 1)
    added, deleted = line_deltas(content, updated)
    diff = {
        "path": rel,
        "before_len": len(content),
        "after_len": len(updated),
        "added_lines": added,
        "deleted_lines": deleted,
    }
    if not apply:
        return {
            "ok": True,
            "preview": True,
            "diff": diff,
            "content": updated,
            "added_lines": added,
            "deleted_lines": deleted,
        }
    return {**write_file(rel, updated, apply=True), "diff": diff}


def search_files(query: str, *, glob_pat: str = "**/*") -> dict:
    root = _root()
    if not root:
        return {"ok": False, "error": "no workspace", "matches": []}
    q = (query or "").lower()
    matches: list[dict] = []
    try:
        for p in root.glob(glob_pat):
            if not p.is_file() or p.name in DENY_NAMES:
                continue
            if p.name.startswith("."):
                continue
            # Skip heavy / vendor trees (same as find_paths)
            try:
                parts = set(p.relative_to(root).parts)
            except ValueError:
                continue
            if parts & SKIP_DIRS:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if q in text.lower():
                rel_p = str(p.relative_to(root)).replace("\\", "/")
                idx = text.lower().find(q)
                matches.append({"path": rel_p, "excerpt": text[max(0, idx - 40) : idx + 120]})
            if len(matches) >= 40:
                break
    except OSError:
        pass
    return {"ok": True, "matches": matches}


def find_paths(query: str, *, limit: int = 30) -> dict:
    """Filename / relative-path matcher for @file picker (skips heavy dirs)."""
    root = _root()
    if not root:
        return {"ok": False, "error": "no workspace", "matches": []}
    q = (query or "").lower().replace("\\", "/")
    matches: list[dict] = []
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            # prune in-place
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS and not (d.startswith(".") and d != ".airgpt")
            ]
            for name in filenames:
                if name in DENY_NAMES or name.startswith("."):
                    continue
                p = Path(dirpath) / name
                rel_p = str(p.relative_to(root)).replace("\\", "/")
                if not q or q in rel_p.lower() or q in name.lower():
                    matches.append({"path": rel_p, "name": name})
                if len(matches) >= limit:
                    return {"ok": True, "matches": matches}
    except OSError:
        pass
    return {"ok": True, "matches": matches}


def glob_paths(pattern: str) -> dict:
    root = _root()
    if not root:
        return {"ok": False, "error": "no workspace", "paths": []}
    paths: list[str] = []
    try:
        for p in root.glob(pattern or "**/*"):
            if p.is_file() and p.name not in DENY_NAMES:
                paths.append(str(p.relative_to(root)).replace("\\", "/"))
            if len(paths) >= 200:
                break
    except OSError:
        pass
    return {"ok": True, "paths": paths}


def checkpoint_create(label: str = "") -> dict:
    root = _root()
    if not root:
        return {"ok": False, "error": "no workspace"}
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    cid = f"cp_{int(time.time())}"
    dest = CHECKPOINT_DIR / cid
    try:
        shutil.copytree(root, dest, ignore=shutil.ignore_patterns("__pycache__", "node_modules", ".git"), dirs_exist_ok=True)
        meta = {"id": cid, "label": (label or "")[:120], "root": str(root), "created_at": time.time()}
        (CHECKPOINT_DIR / f"{cid}.json").write_text(json.dumps(meta), encoding="utf-8")
        return {"ok": True, **meta}
    except OSError as e:
        return {"ok": False, "error": str(e)[:200]}


def rules_text() -> str:
    """Workspace rules: .airgpt/rules.md, else AGENTS.md (via invoke_registry)."""
    root = _root()
    try:
        import invoke_registry

        ctx = invoke_registry.rules_context(root)
        return str(ctx.get("text") or "")
    except Exception:
        pass
    if not root:
        return ""
    for path in (root / ".airgpt" / "rules.md", root / "AGENTS.md"):
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8")[:8000]
            except OSError:
                pass
    return ""


def fingerprint(*, use_cache: bool = True, light: bool = False) -> dict:
    """Branch + HEAD sha + dirty count for OpenIDE agent context.

    Parallel git subprocesses + 3s TTL cache. ``light=True`` skips log/worktrees
    (agent run path).
    """
    ws = get_workspace()
    if not ws.get("ok"):
        return {"ok": False, "error": "no workspace"}
    now = time.monotonic()
    if use_cache and _fp_cache[1] and now - float(_fp_cache[0]) < 3.0:
        cached = dict(_fp_cache[1])
        if light or cached.get("log") is not None:
            return cached
    root = ws["root"]
    out: dict = {"ok": True, "root": root, "name": ws.get("name") or ""}
    try:
        from . import terminal_pty
        from concurrent.futures import ThreadPoolExecutor

        cmds = {
            "head": "git rev-parse HEAD",
            "branch": "git branch --show-current",
            "status": "git status --porcelain",
        }
        if not light:
            cmds["log"] = "git log -5 --oneline"
            cmds["worktrees"] = "git worktree list"

        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=5) as pool:
            futs = {k: pool.submit(terminal_pty.run_command, cmd, cwd=root) for k, cmd in cmds.items()}
            for k, fut in futs.items():
                try:
                    results[k] = fut.result(timeout=8)
                except Exception as e:
                    results[k] = {"ok": False, "stdout": "", "error": str(e)[:120]}

        porcelain = (results.get("status", {}).get("stdout") or "").strip()
        dirty_lines = [ln for ln in porcelain.splitlines() if ln.strip()]
        head = results.get("head", {})
        branch = results.get("branch", {})
        out.update(
            {
                "head": ((head.get("stdout") or "").strip()[:40] if head.get("ok") else ""),
                "branch": ((branch.get("stdout") or "").strip() if branch.get("ok") else ""),
                "dirty_count": len(dirty_lines),
                "dirty_sample": dirty_lines[:20],
                "log": ((results.get("log", {}).get("stdout") or "").strip()[:800] if results.get("log", {}).get("ok") else ""),
                "worktrees": (
                    (results.get("worktrees", {}).get("stdout") or "").strip()[:600]
                    if results.get("worktrees", {}).get("ok")
                    else ""
                ),
            }
        )
        _fp_cache[0] = now
        _fp_cache[1] = dict(out)
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)[:200]
    return out


def git_summary() -> dict:
    """One round-trip for OpenIDE Git panel: fingerprint + status + diff."""
    from . import terminal_pty
    from concurrent.futures import ThreadPoolExecutor

    ws = get_workspace()
    if not ws.get("ok"):
        return {"ok": False, "error": "no workspace"}
    root = ws["root"]
    fp = fingerprint(use_cache=True, light=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        st_f = pool.submit(terminal_pty.run_command, "git status", cwd=root)
        df_f = pool.submit(terminal_pty.run_command, "git diff", cwd=root)
        try:
            st = st_f.result(timeout=10)
        except Exception as e:
            st = {"ok": False, "stdout": "", "error": str(e)[:120]}
        try:
            diff = df_f.result(timeout=10)
        except Exception as e:
            diff = {"ok": False, "stdout": "", "error": str(e)[:120]}
    d = diff.get("stdout") or ""
    plus = len([ln for ln in d.splitlines() if ln.startswith("+") and not ln.startswith("+++")])
    minus = len([ln for ln in d.splitlines() if ln.startswith("-") and not ln.startswith("---")])
    return {
        "ok": True,
        "fingerprint": fp,
        "status": st,
        "diff": diff,
        "plus": plus,
        "minus": minus,
    }


def list_branches() -> dict:
    """Local branch names + current for OpenIDE Branch menu."""
    ws = get_workspace()
    if not ws.get("ok"):
        return {"ok": False, "error": "no workspace", "branches": [], "current": ""}
    root = ws["root"]
    try:
        from . import terminal_pty

        cur = terminal_pty.run_command("git branch --show-current", cwd=root)
        listing = terminal_pty.run_command("git branch --list --format=%(refname:short)", cwd=root)
        current = (cur.get("stdout") or "").strip() if cur.get("ok") else ""
        branches: list[str] = []
        if listing.get("ok"):
            for ln in (listing.get("stdout") or "").splitlines():
                name = ln.strip().lstrip("*").strip()
                if name and name not in branches:
                    branches.append(name)
        if current and current not in branches:
            branches.insert(0, current)
        return {"ok": True, "branches": branches, "current": current, "root": root}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "branches": [], "current": ""}


def checkout_branch(branch: str) -> dict:
    """Checkout a local branch in the open workspace; return updated fingerprint."""
    name = (branch or "").strip()
    if not name or any(c in name for c in (" ", ";", "|", "&", "`", "$", "\n", "\r")):
        return {"ok": False, "error": "invalid branch name"}
    if ".." in name or name.startswith("-"):
        return {"ok": False, "error": "invalid branch name"}
    ws = get_workspace()
    if not ws.get("ok"):
        return {"ok": False, "error": "no workspace"}
    root = ws["root"]
    try:
        from . import terminal_pty

        listed = list_branches()
        current = (listed.get("current") or "").strip()
        # Already on this branch (incl. unborn/no-commits repos) — treat as success
        if current and current == name:
            fp = fingerprint(use_cache=False, light=False)
            return {"ok": True, "branch": name, "fingerprint": fp, "noop": True}
        if listed.get("ok") and listed.get("branches") and name not in listed["branches"]:
            return {"ok": False, "error": f"unknown branch: {name}"}
        r = terminal_pty.run_command(f"git checkout {name}", cwd=root)
        if not r.get("ok"):
            err = (r.get("stderr") or r.get("error") or r.get("stdout") or "checkout failed")[:200]
            # Unborn branch / empty repo: stay on current
            if "pathspec" in err and current == name:
                fp = fingerprint(use_cache=False, light=False)
                return {"ok": True, "branch": name, "fingerprint": fp, "noop": True}
            return {"ok": False, "error": err}
        global _fp_cache
        _fp_cache = [0.0, {}]
        fp = fingerprint(use_cache=False, light=False)
        return {"ok": True, "branch": name, "fingerprint": fp}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

"""Unified invoke catalog — Rules (always-on), Skills (/ on-demand), slash + agents.

Cursor/Claude analogue for AirGPT + Cortex awareness. Local-first: never requires
CortexOS online.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import DATA_DIR, ROOT

_PRODUCT_SKILLS_DIR = DATA_DIR / "skills"
SKILLS_DIR = _PRODUCT_SKILLS_DIR
CURSOR_SKILLS_ROOT = ROOT / ".cursor" / "skills"
RULES_CAP = 4000
SKILL_CAP = 6000


def skills_dir() -> Path:
    """Product packs: data/skills (gitignored). Tests pin SKILLS_DIR to tests/fixtures/skills."""
    return SKILLS_DIR


def _parse_skill_md(path: Path, sid: str) -> tuple[str, str]:
    name = sid.replace("-", " ").replace("_", " ").title()
    desc = ""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
    except OSError:
        return name, desc
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm, body = parts[1], parts[2]
            for line in fm.splitlines():
                s = line.strip()
                if s.startswith("name:"):
                    name = s.split(":", 1)[1].strip().strip("\"'") or name
            if "description:" in fm:
                after = fm.split("description:", 1)[1]
                chunk: list[str] = []
                for ln in after.splitlines():
                    st = ln.strip()
                    if st.endswith(":") and not st.startswith("-") and chunk:
                        break
                    st = st.lstrip(">").lstrip("-").strip().strip("\"'")
                    if st:
                        chunk.append(st)
                if chunk:
                    desc = " ".join(chunk)[:160]
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            name = s.lstrip("#").strip() or name
            continue
        if not desc:
            desc = s[:160]
        break
    return name, desc


def _skill_entry(sid: str, path: Path, state: dict[str, str]) -> dict[str, Any]:
    name, desc = _parse_skill_md(path, sid)
    scope = str(state.get(sid) or "off")
    if scope not in ("off", "global", "project"):
        scope = "off"
    return {
        "id": sid,
        "name": name,
        "description": desc or f"Skill pack: {sid}",
        "path": str(path),
        "body": _read_skill_text(path),
        "enabled": scope != "off",
        "scope": scope,
    }


def _read_skill_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:SKILL_CAP]
    except OSError:
        return ""


def list_skills() -> list[dict[str, Any]]:
    """Scan data/skills/*.md plus committed .cursor/skills/<id>/SKILL.md in product mode."""
    state = _skill_state()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    root = skills_dir()
    if root.is_dir():
        for p in sorted(root.glob("*.md")):
            if p.name.startswith("_"):
                continue
            sid = p.stem.strip().lower()
            if not sid:
                continue
            seen.add(sid)
            out.append(_skill_entry(sid, p, state))
    # Fixtures pin SKILLS_DIR away from the product dir; do not leak laptop packs into those tests.
    if skills_dir() == _PRODUCT_SKILLS_DIR and CURSOR_SKILLS_ROOT.is_dir():
        for d in sorted(CURSOR_SKILLS_ROOT.iterdir()):
            skill_md = d / "SKILL.md"
            if not d.is_dir() or not skill_md.is_file():
                continue
            sid = d.name.strip().lower()
            if not sid or sid in seen:
                continue
            seen.add(sid)
            out.append(_skill_entry(sid, skill_md, state))
    return out


def _skill_state_path() -> Path:
    return skills_dir() / "_state.json"


def _skill_state() -> dict[str, str]:
    p = _skill_state_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def set_skill_enabled(skill_id: str, *, scope: str = "global") -> dict[str, Any]:
    """Enable/disable a skill for global AirGPT or this project workspace.

    scope: off | global | project
    """
    sid = (skill_id or "").strip().lower()
    if not sid or "/" in sid or "\\" in sid or ".." in sid:
        return {"ok": False, "error": "invalid skill id"}
    scope_n = (scope or "off").strip().lower()
    if scope_n not in ("off", "global", "project"):
        return {"ok": False, "error": "scope must be off|global|project"}
    if scope_n == "project":
        # Project enable also writes .airgpt/enabled_skills.json when workspace open
        try:
            import workspace_api

            ws = workspace_api.get_workspace()
            if ws.get("ok") and ws.get("root"):
                root = Path(str(ws["root"]))
                air = root / ".airgpt"
                air.mkdir(parents=True, exist_ok=True)
                ep = air / "enabled_skills.json"
                cur: list[str] = []
                if ep.is_file():
                    try:
                        raw = json.loads(ep.read_text(encoding="utf-8"))
                        if isinstance(raw, list):
                            cur = [str(x) for x in raw]
                    except Exception:
                        cur = []
                if sid not in cur:
                    cur.append(sid)
                ep.write_text(json.dumps(cur, indent=2), encoding="utf-8")
        except Exception:
            pass
    elif scope_n == "off":
        try:
            import workspace_api

            ws = workspace_api.get_workspace()
            if ws.get("ok") and ws.get("root"):
                ep = Path(str(ws["root"])) / ".airgpt" / "enabled_skills.json"
                if ep.is_file():
                    try:
                        raw = json.loads(ep.read_text(encoding="utf-8"))
                        if isinstance(raw, list):
                            cur = [str(x) for x in raw if str(x) != sid]
                            ep.write_text(json.dumps(cur, indent=2), encoding="utf-8")
                    except Exception:
                        pass
        except Exception:
            pass
    skills_dir().mkdir(parents=True, exist_ok=True)
    state = _skill_state()
    if scope_n == "off":
        state.pop(sid, None)
    else:
        state[sid] = scope_n
    try:
        _skill_state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": True, "id": sid, "scope": scope_n, "enabled": scope_n != "off"}


def active_skill_ids(*, workspace_root: str | Path | None = None) -> list[str]:
    """Skills enabled globally or for the current project."""
    state = _skill_state()
    out: list[str] = [k for k, v in state.items() if v == "global"]
    root: Path | None = Path(workspace_root) if workspace_root else None
    if root is None:
        try:
            import workspace_api

            ws = workspace_api.get_workspace()
            if ws.get("ok") and ws.get("root"):
                root = Path(str(ws["root"]))
        except Exception:
            root = None
    if root:
        for k, v in state.items():
            if v == "project" and k not in out:
                out.append(k)
        ep = root / ".airgpt" / "enabled_skills.json"
        if ep.is_file():
            try:
                raw = json.loads(ep.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    for x in raw:
                        s = str(x).strip().lower()
                        if s and s not in out:
                            out.append(s)
            except Exception:
                pass
    return out


def load_skill(skill_id: str, *, max_chars: int = SKILL_CAP) -> str:
    """Load Markdown skill pack body. Empty if missing."""
    sid = (skill_id or "").strip().lower()
    if not sid or "/" in sid or "\\" in sid or ".." in sid:
        return ""
    p = skills_dir() / f"{sid}.md"
    if not p.is_file() and skills_dir() == _PRODUCT_SKILLS_DIR:
        p = CURSOR_SKILLS_ROOT / sid / "SKILL.md"
    if not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8-sig", errors="ignore")[: max(200, int(max_chars))]
    except OSError:
        return ""


def rules_context(workspace_root: str | Path | None = None, *, max_chars: int = RULES_CAP) -> dict[str, Any]:
    """Prefer .airgpt/rules.md, else AGENTS.md in workspace root."""
    root: Path | None = None
    if workspace_root:
        root = Path(workspace_root)
    else:
        try:
            import workspace_api

            ws = workspace_api.get_workspace()
            if ws.get("ok") and ws.get("root"):
                root = Path(str(ws["root"]))
        except Exception:
            root = None

    if not root or not root.is_dir():
        return {"present": False, "source": "", "text": ""}

    candidates = [
        (root / ".airgpt" / "rules.md", ".airgpt/rules.md"),
        (root / "AGENTS.md", "AGENTS.md"),
    ]
    for path, label in candidates:
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")[: max(200, int(max_chars))]
                if text.strip():
                    return {"present": True, "source": label, "text": text}
            except OSError:
                continue
    return {"present": False, "source": "", "text": ""}


def skill_slash_commands() -> list[dict[str, Any]]:
    """Dynamic slash entries for each skill pack + meta /skill /rules /subagent."""
    cmds: list[dict[str, Any]] = [
        {"name": "skill", "description": "Force a skill pack (always wins over auto-wire)", "args": "<pack> [global|project|off] [job]"},
        {"name": "anthropic-skills", "description": "Force a skill pack (colon form)", "args": ":<pack> [job]"},
        {"name": "rules", "description": "Show or open workspace rules", "args": "[edit]"},
        {"name": "subagent", "description": "Queue a helper subagent with a prompt", "args": "<prompt>"},
        {"name": "create-subagent", "description": "Create a focused subagent and open Cortex", "args": "<name> [prompt]"},
        {"name": "edit", "description": "Hint / open tweak panel for the last agent", "args": "[what to change]"},
    ]
    for sk in list_skills():
        sid = sk["id"]
        cmds.append(
            {
                "name": f"skill-{sid}",
                "description": sk.get("description") or f"Load skill pack {sid}",
                "args": "",
            }
        )
    return cmds


def save_skill(skill_id: str, body: str, *, title: str = "") -> dict[str, Any]:
    """Create or overwrite data/skills/<id>.md."""
    sid = (skill_id or "").strip().lower().replace(" ", "-")
    sid = "".join(c for c in sid if c.isalnum() or c in "-_")
    if not sid or len(sid) > 64:
        return {"ok": False, "error": "invalid skill id"}
    text = (body or "").strip()
    if not text:
        return {"ok": False, "error": "skill body required"}
    root = skills_dir()
    root.mkdir(parents=True, exist_ok=True)
    heading = (title or sid.replace("-", " ").title()).strip()
    if not text.lstrip().startswith("#"):
        text = f"# {heading}\n{text}\n"
    path = root / f"{sid}.md"
    try:
        path.write_text(text[:SKILL_CAP], encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": True, "id": sid, "path": str(path), "chars": len(text)}


def delete_skill(skill_id: str) -> dict[str, Any]:
    """Delete data/skills/<id>.md and forget its on/off state. Built-in packs cannot be deleted."""
    sid = (skill_id or "").strip().lower()
    sid = "".join(c for c in sid if c.isalnum() or c in "-_")
    if not sid or len(sid) > 64:
        return {"ok": False, "error": "invalid skill id"}
    path = skills_dir() / f"{sid}.md"
    if not path.is_file():
        if skills_dir() == _PRODUCT_SKILLS_DIR and (CURSOR_SKILLS_ROOT / sid / "SKILL.md").is_file():
            return {"ok": False, "error": "This skill ships with AirGPT and cannot be deleted. Turn it off instead."}
        return {"ok": False, "error": "skill not found"}
    try:
        path.unlink()
        state = _skill_state()
        if state.pop(sid, None) is not None:
            _skill_state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": True, "id": sid}


def save_rules(text: str, *, workspace_root: str | Path | None = None, prefer: str = "airgpt") -> dict[str, Any]:
    """Write workspace rules to .airgpt/rules.md (default) or AGENTS.md."""
    body = (text or "").strip()
    if not body:
        return {"ok": False, "error": "rules text required"}
    root: Path | None = None
    if workspace_root:
        root = Path(workspace_root)
    else:
        try:
            import workspace_api

            ws = workspace_api.get_workspace()
            if ws.get("ok") and ws.get("root"):
                root = Path(str(ws["root"]))
        except Exception:
            root = None
    if not root or not root.is_dir():
        return {"ok": False, "error": "no workspace — open a folder in OpenIDE first"}
    prefer = (prefer or "airgpt").lower()
    if prefer == "agents":
        path = root / "AGENTS.md"
        label = "AGENTS.md"
    else:
        (root / ".airgpt").mkdir(parents=True, exist_ok=True)
        path = root / ".airgpt" / "rules.md"
        label = ".airgpt/rules.md"
    try:
        path.write_text(body[:RULES_CAP], encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": True, "source": label, "path": str(path), "chars": len(body)}


def catalog() -> dict[str, Any]:
    """Cortex + UI surface: rules, skills, commands, agents."""
    rules = rules_context()
    skills = list_skills()
    try:
        import commands as commands_mod

        cmds = commands_mod.list_commands()
    except Exception:
        cmds = skill_slash_commands()

    agents: list[dict[str, Any]] = []
    try:
        import agent_store

        agent_store.init()
        for a in agent_store.list_agents(limit=40):
            agents.append(
                {
                    "id": a.get("id"),
                    "name": a.get("name"),
                    "kind": a.get("kind"),
                    "skill_pack": a.get("skill_pack") or "",
                    "pinned": bool(a.get("pinned")),
                }
            )
    except Exception:
        pass

    return {
        "ok": True,
        "invoke": ["rules", "skills", "slash", "subagents"],
        "rules": {
            "present": bool(rules.get("present")),
            "source": rules.get("source") or "",
            "chars": len(rules.get("text") or ""),
            "text": rules.get("text") or "",
        },
        "skills": [{"id": s["id"], "name": s["name"], "description": s["description"]} for s in skills],
        "commands": cmds,
        "agents": agents,
    }

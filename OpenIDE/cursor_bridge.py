"""Optional Cursor SDK bridge for OpenIDE agent backends."""
from __future__ import annotations

import os
from typing import Iterator

_last_run: dict[str, object] = {"run_id": "", "backend": "", "cwd": ""}


def backends() -> list[str]:
    return ["local", "cursor_local", "cursor_cloud"]


def get_backend() -> str:
    from config import ENV_FILE

    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("AGENT_BACKEND="):
                v = line.split("=", 1)[1].strip().lower()
                if v in backends():
                    return v
    return "local"


def set_backend(name: str) -> dict:
    name = (name or "local").lower()
    if name not in backends():
        return {"ok": False, "error": "invalid backend"}
    from config import ENV_FILE

    lines: list[str] = []
    found = False
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("AGENT_BACKEND="):
                lines.append(f"AGENT_BACKEND={name}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"AGENT_BACKEND={name}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "backend": name}


def _load_api_key() -> str:
    api_key = os.environ.get("CURSOR_API_KEY", "")
    if api_key:
        return api_key
    try:
        from config import ENV_FILE

        if ENV_FILE.is_file():
            for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().startswith("CURSOR_API_KEY="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def _git_remote_url(cwd: str) -> str:
    if not cwd:
        return ""
    try:
        import subprocess

        r = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def last_run_info() -> dict:
    return {
        "ok": bool(_last_run.get("run_id")),
        "run_id": str(_last_run.get("run_id") or ""),
        "backend": str(_last_run.get("backend") or ""),
        "cwd": str(_last_run.get("cwd") or ""),
        "model": "composer-2.5",
    }


def run_cursor_events(
    prompt: str,
    *,
    cwd: str = "",
    backend: str = "",
    resume: bool = False,
    run_id: str = "",
) -> Iterator[dict]:
    """Stream agent events via cursor-sdk when available."""
    api_key = _load_api_key()
    if not api_key:
        yield {"type": "error", "text": "CURSOR_API_KEY not set in env.local — open Key Vault"}
        return
    try:
        from cursor_sdk import Agent, CloudAgentOptions, LocalAgentOptions
    except ImportError:
        yield {"type": "error", "text": "cursor-sdk not installed (pip install cursor-sdk)"}
        return

    backend = (backend or get_backend()).lower()
    if backend == "local":
        backend = "cursor_local"

    yield {"type": "thinking", "text": f"Starting Cursor SDK ({backend})…", "ms": 0}
    kwargs: dict = {"model": {"id": "composer-2.5"}, "api_key": api_key}
    # Older SDKs accept model as string — try dict first via create
    model_kw_variants = (
        {"model": {"id": "composer-2.5"}, "api_key": api_key},
        {"model": "composer-2.5", "api_key": api_key},
    )

    if backend == "cursor_cloud":
        remote = _git_remote_url(cwd)
        if not remote:
            yield {"type": "error", "text": "cursor_cloud needs a git remote origin URL in the workspace"}
            return
    else:
        remote = ""

    agent = None
    last_err = ""
    for base_kw in model_kw_variants:
        try:
            kw = dict(base_kw)
            if backend == "cursor_cloud":
                kw["cloud"] = CloudAgentOptions(repos=[{"url": remote}])
            else:
                kw["local"] = LocalAgentOptions(cwd=cwd or os.getcwd())
            agent = Agent.create(**kw)
            break
        except TypeError as e:
            last_err = str(e)[:200]
            continue
        except Exception as e:
            last_err = str(e)[:500]
            break
    if agent is None:
        yield {"type": "error", "text": f"Cursor Agent.create failed: {last_err or 'unknown'}"}
        return

    try:
        with agent:
            rid = run_id or str(_last_run.get("run_id") or "")
            if resume and rid and hasattr(agent, "resume"):
                yield {"type": "status", "text": f"Resuming Cursor run {rid[:12]}…"}
                try:
                    run = agent.resume(rid)  # type: ignore[attr-defined]
                except Exception:
                    run = agent.send(prompt)
            elif resume and hasattr(Agent, "resume"):
                yield {"type": "status", "text": "Resuming via Agent.resume…"}
                try:
                    run = Agent.resume(rid, api_key=api_key)  # type: ignore[attr-defined]
                except Exception:
                    run = agent.send(prompt)
            else:
                run = agent.send(prompt)

            run_id_out = getattr(run, "id", None) or getattr(run, "run_id", None) or ""
            if run_id_out:
                _last_run["run_id"] = str(run_id_out)
                _last_run["backend"] = backend
                _last_run["cwd"] = cwd or ""
                yield {"type": "status", "text": "Cursor run started", "run_id": str(run_id_out)}

            for message in run.messages():
                mtype = getattr(message, "type", None)
                if mtype == "thinking" or getattr(message, "thinking", None):
                    text = getattr(message, "text", None) or getattr(message, "thinking", None) or ""
                    if text:
                        yield {"type": "thinking", "text": str(text)[:2000]}
                    continue
                if mtype in ("tool_call", "tool"):
                    name = getattr(message, "name", None) or getattr(message, "tool", None) or "tool"
                    yield {"type": "tool_call", "name": str(name)}
                    continue
                if mtype == "assistant" or True:
                    msg = getattr(message, "message", None)
                    content = getattr(msg, "content", None) if msg is not None else None
                    if content is None:
                        content = getattr(message, "content", None) or []
                    for block in content or []:
                        btype = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
                        text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
                        if (btype == "text" or text) and text:
                            yield {"type": "token", "text": text}
            result = run.wait()
            status = getattr(result, "status", None) or (result.get("status") if isinstance(result, dict) else None)
            rid2 = getattr(result, "id", None) or run_id_out or ""
            if rid2:
                _last_run["run_id"] = str(rid2)
            if status == "error":
                yield {"type": "error", "text": f"Cursor run failed: {rid2}"}
            else:
                yield {"type": "done", "analysis": "Cursor run complete", "run_id": str(rid2 or "")}
    except Exception as e:
        name = type(e).__name__
        if "CursorAgentError" in name or name == "CursorAgentError":
            yield {"type": "error", "text": f"Cursor startup failed: {getattr(e, 'message', str(e))[:500]}"}
        else:
            yield {"type": "error", "text": str(e)[:500]}


def open_in_cursor_uri(folder: str) -> str:
    from urllib.parse import quote

    p = (folder or "").replace("\\", "/")
    return f"cursor://file/{quote(p, safe='/:.')}"

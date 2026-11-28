"""Start AirGPT with DMS and OpenVault on this machine.

    python -m bundle.launch --check
    python -m bundle.launch --ui
    python -m bundle.launch --up --detach

The service token is created on first run and is never printed.
DMS and OpenVault start only when DMS_CMD / DMS_ARGV or OPENVAULT_CMD /
OPENVAULT_ARGV is set (or a checkout path is set and a command is given).
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

from bundle.onboarding import STEPS
from bundle.posture import LOOPBACK, TUNNEL_OPT_IN_WARNING
from bundle.token_store import describe, ensure, home_dir

REPO = Path(__file__).resolve().parents[1]
AIRGPT_PORT = 8765
DMS_PORT = 8011
OPENVAULT_PORT = 5000


def _state_path() -> Path:
    return home_dir() / "bundle-state.json"


def _argv_from_env(prefix: str) -> list[str] | None:
    raw = (os.environ.get(f"{prefix}_ARGV") or "").strip()
    if raw:
        data = json.loads(raw)
        if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
            raise SystemExit(f"{prefix}_ARGV must be a JSON list of strings")
        return data
    cmd = (os.environ.get(f"{prefix}_CMD") or "").strip()
    if cmd:
        return shlex.split(cmd)
    return None


def _root_from_env(names: tuple[str, ...]) -> str:
    for name in names:
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return raw
    return ""


def _child_env(token_file: str) -> dict[str, str]:
    env = dict(os.environ)
    env["AIRGPT_BIND"] = LOOPBACK
    env["AIRGPT_TUNNEL"] = "0"
    env["AIRGPT_NO_BROWSER"] = "1"
    env["NETIE_TOKEN_FILE"] = token_file
    for key in ("NETIE_SERVICE_TOKEN", "AIRGPT_SERVICE_TOKEN"):
        env.pop(key, None)
    return env


def plan() -> list[dict]:
    info = ensure()
    token_file = info.get("path") or ""
    base_env = {
        "AIRGPT_BIND": LOOPBACK,
        "AIRGPT_TUNNEL": "0",
        "AIRGPT_NO_BROWSER": "1",
        "NETIE_TOKEN_FILE": token_file,
    }
    air_argv = _argv_from_env("AIRGPT")
    if air_argv is None:
        air_argv = [sys.executable, str(REPO / "clipdrop.py")]
    rows = [
        {
            "name": "airgpt",
            "port": int(os.environ.get("AIRGPT_PORT") or AIRGPT_PORT),
            "bind": LOOPBACK,
            "argv": air_argv,
            "cwd": str(REPO),
            "env": dict(base_env),
            "state": "ready",
            "note": "this repo",
        }
    ]
    siblings = (
        ("dms", DMS_PORT, "DMS", ("DMS_ROOT", "CORTEX_ROOT"), "DMS_PORT"),
        ("openvault", OPENVAULT_PORT, "OPENVAULT", ("OPENVAULT_ROOT",), "OPENVAULT_PORT"),
    )
    for name, default_port, prefix, root_keys, port_key in siblings:
        argv = _argv_from_env(prefix)
        root = _root_from_env(root_keys)
        port = int(os.environ.get(port_key) or default_port)
        if argv:
            state = "ready"
            note = "command set"
        elif root:
            state = "checkout"
            note = f"checkout at {root}; set {prefix}_CMD to start it"
            argv = []
        else:
            state = "absent"
            note = f"set {prefix}_CMD or {root_keys[0]}"
            argv = []
        rows.append({
            "name": name,
            "port": port,
            "bind": LOOPBACK,
            "argv": argv,
            "cwd": root or str(REPO),
            "env": dict(base_env),
            "state": state,
            "note": note,
        })
    return rows


def _print_plan(rows: list[dict], info: dict) -> None:
    print("Netie bundle")
    for index, step in enumerate(STEPS, start=1):
        print(f"{index}. {step['title']}")
        print(f"   {step['body']}")
    where = info.get("where") or "file"
    path = info.get("path") or ""
    print(f"Token store: {where}")
    if path:
        print(f"Token file: {path}")
    print("The token was not printed.")
    print(TUNNEL_OPT_IN_WARNING)
    for row in rows:
        print(
            f"{row['name']:10} http://{row['bind']}:{row['port']}  "
            f"{row['state']}  {row['note']}"
        )


def _confirm(yes: bool) -> bool:
    if yes:
        return True
    try:
        if not sys.stdin.isatty():
            return True
    except Exception:
        return True
    answer = input("Create or reuse the local service token and continue? [y/N] ")
    return answer.strip().lower() in ("y", "yes")


def start_rows(rows: list[dict]) -> list[int]:
    pids: list[int] = []
    records = []
    for row in rows:
        argv = row.get("argv") or []
        if row["state"] != "ready" or not argv:
            print(f"{row['name']}: skipped ({row['note']})")
            continue
        env = _child_env(row["env"].get("NETIE_TOKEN_FILE") or "")
        proc = subprocess.Popen(
            argv,
            cwd=row.get("cwd") or None,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pids.append(proc.pid)
        records.append({"name": row["name"], "pid": proc.pid, "port": row["port"]})
        print(f"{row['name']}: started pid {proc.pid} on http://{LOOPBACK}:{row['port']}")
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pids": records}, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(path, 0o600)
    return pids


def stop_rows() -> int:
    path = _state_path()
    if not path.is_file():
        print("nothing to stop")
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        print("state file was not readable")
        return 1
    for row in data.get("pids") or []:
        pid = int(row.get("pid") or 0)
        if not pid:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"stopped {row.get('name') or 'process'} pid {pid}")
        except OSError:
            print(f"already stopped pid {pid}")
    try:
        path.unlink()
    except OSError:
        pass
    return 0


def wait_for_interrupt() -> None:
    print("Bundle is up. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_rows()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the Netie bundle on this machine.")
    parser.add_argument("--check", action="store_true", help="Create the token and print the plan.")
    parser.add_argument("--up", action="store_true", help="Start configured programs.")
    parser.add_argument("--detach", action="store_true", help="With --up, return after start.")
    parser.add_argument("--stop", action="store_true", help="Stop programs started by --up.")
    parser.add_argument("--ui", action="store_true", help="Serve the first-run page on loopback.")
    parser.add_argument("--ui-port", type=int, default=8764)
    parser.add_argument("--yes", action="store_true", help="Do not prompt.")
    args = parser.parse_args(argv)

    if args.stop:
        return stop_rows()

    if args.ui:
        from bundle.wizard_http import serve

        print(f"First-run page: http://{LOOPBACK}:{args.ui_port}/")
        print("The token is not printed.")
        serve(args.ui_port)
        return 0

    if not _confirm(args.yes):
        print("Stopped before creating a token.")
        return 1

    info = ensure()
    rows = plan()
    _print_plan(rows, info)
    if args.up:
        start_rows(rows)
        if not args.detach:
            wait_for_interrupt()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

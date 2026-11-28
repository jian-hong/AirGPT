"""READY-03: loopback bind, tunnel opt-in, pinned deps, bundle token.

These tests run on Linux and Windows. They start real processes and a real
HTTP server. They do not open a public tunnel and they do not print the token.
"""
from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")
sys.path.insert(0, str(ROOT))

from bundle.onboarding import STEPS  # noqa: E402
from bundle.posture import (  # noqa: E402
    BIND_ALL_WARNING,
    TUNNEL_OPT_IN_WARNING,
    resolve_bind_host,
    tunnel_opted_in,
)
from bundle.token_store import ensure, file_mode, load_token  # noqa: E402
from bundle.wizard_http import serve_background  # noqa: E402


def _no_dash(text: str) -> None:
    assert "\u2014" not in text
    assert "\u2013" not in text


def test_default_bind_is_loopback_and_tunnel_is_off():
    assert resolve_bind_host({}) == "127.0.0.1"
    assert resolve_bind_host({"AIRGPT_BIND": "localhost"}) == "127.0.0.1"
    assert resolve_bind_host({"AIRGPT_BIND": "0.0.0.0"}) == "0.0.0.0"
    assert tunnel_opted_in({}) is False
    assert tunnel_opted_in({"AIRGPT_TUNNEL": "0"}) is False
    assert tunnel_opted_in({"AIRGPT_TUNNEL": "1"}) is True
    assert "internet" in TUNNEL_OPT_IN_WARNING
    assert "127.0.0.1" in BIND_ALL_WARNING
    _no_dash(TUNNEL_OPT_IN_WARNING)
    _no_dash(BIND_ALL_WARNING)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((resolve_bind_host({}), 0))
        assert sock.getsockname()[0] == "127.0.0.1"
    finally:
        sock.close()
    source = (ROOT / "clipdrop.py").read_text(encoding="utf-8")
    assert 'HOST = resolve_bind_host()' in source
    assert 'HOST = "0.0.0.0"' not in source


def test_windows_deps_are_marked_and_lock_is_pinned():
    direct = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    _no_dash(direct)
    _no_dash(lock)
    seen_pywin = False
    for blob in (direct, lock):
        for line in blob.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            name = stripped.split(";", 1)[0].split("==", 1)[0].split(">=", 1)[0].strip().lower()
            if name in ("pywin32", "pywin32-ctypes"):
                seen_pywin = True
                assert 'sys_platform == "win32"' in stripped, stripped
    assert seen_pywin
    for line in lock.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert "==" in stripped.split(";", 1)[0]
    compose = (ROOT / "bundle" / "docker-compose.yml").read_text(encoding="utf-8")
    _no_dash(compose)
    assert "127.0.0.1:8765:8765" in compose
    assert "127.0.0.1:8011:8011" in compose
    assert "127.0.0.1:5000:5000" in compose
    assert "AIRGPT_TUNNEL" in compose
    assert "0.0.0.0" not in compose
    for name in ("airgpt:", "dms:", "openvault:"):
        assert name in compose


def test_onboarding_steps_match_the_page_and_the_guide():
    html = (ROOT / "ui" / "onboarding.html").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "ONBOARDING.md").read_text(encoding="utf-8")
    _no_dash(html)
    _no_dash(guide)
    assert len(STEPS) >= 6
    for step in STEPS:
        assert step["title"] in html
        assert step["title"] in guide
        _no_dash(step["title"])
        _no_dash(step["body"])


def test_token_file_is_private_and_not_printed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NETIE_HOME", str(tmp_path))
    monkeypatch.setenv("NETIE_TOKEN_FILE", str(tmp_path / "service-token"))
    monkeypatch.setenv("NETIE_TOKEN_STORE", "file")
    info = ensure()
    assert info["where"] == "file"
    assert "token" not in info or info.get("token") in (None, "")
    path = Path(info["path"])
    secret = path.read_text(encoding="utf-8").strip()
    assert secret
    assert load_token() == secret
    again = ensure()
    assert again["path"] == info["path"]
    assert path.read_text(encoding="utf-8").strip() == secret
    if os.name != "nt":
        assert file_mode(path) == 0o600
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    caught = capsys.readouterr()
    assert secret not in caught.out
    assert secret not in caught.err
    blob = json.dumps(info)
    assert secret not in blob


def test_keyring_store_roundtrip_does_not_print(tmp_path, monkeypatch, capsys):
    keyring = pytest.importorskip("keyring")
    from keyring.backend import KeyringBackend

    class Memory(KeyringBackend):
        priority = 100

        def __init__(self):
            self.data: dict[tuple[str, str], str] = {}

        def get_password(self, service, username):
            return self.data.get((service, username))

        def set_password(self, service, username, password):
            self.data[(service, username)] = password

        def delete_password(self, service, username):
            self.data.pop((service, username), None)

    monkeypatch.setenv("NETIE_HOME", str(tmp_path))
    monkeypatch.setenv("NETIE_TOKEN_FILE", str(tmp_path / "service-token"))
    monkeypatch.delenv("NETIE_TOKEN_STORE", raising=False)
    previous = keyring.get_keyring()
    keyring.set_keyring(Memory())
    try:
        info = ensure()
        assert info["where"] == "keyring"
        secret = (tmp_path / "service-token").read_text(encoding="utf-8").strip()
        assert keyring.get_password("netie-bundle", "service-token") == secret
        if os.name != "nt":
            assert file_mode(tmp_path / "service-token") == 0o600
        caught = capsys.readouterr()
        assert secret not in caught.out
        assert secret not in caught.err
        assert secret not in json.dumps(info)
    finally:
        keyring.set_keyring(previous)


def test_wizard_http_hides_the_token(tmp_path, monkeypatch):
    monkeypatch.setenv("NETIE_HOME", str(tmp_path))
    monkeypatch.setenv("NETIE_TOKEN_FILE", str(tmp_path / "service-token"))
    monkeypatch.setenv("NETIE_TOKEN_STORE", "file")
    server, port = serve_background(0)
    try:
        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(base + "/", timeout=5) as page:
            assert page.status == 200
            html = page.read().decode("utf-8")
        for step in STEPS:
            assert step["title"] in html
        req = urllib.request.Request(base + "/api/bundle/setup", data=b"{}", method="POST")
        with urllib.request.urlopen(req, timeout=5) as res:
            body = res.read().decode("utf-8")
            payload = json.loads(body)
        secret = (tmp_path / "service-token").read_text(encoding="utf-8").strip()
        assert payload["ok"] is True
        assert payload["token_where"] == "file"
        assert "token" not in payload
        assert secret not in body
        assert secret not in html
    finally:
        server.shutdown()
        server.server_close()


def _listeners(port: int) -> list[str]:
    path = Path("/proc/net/tcp")
    if not path.is_file():
        return []
    found = []
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        local, state = parts[1], parts[3]
        ip_hex, port_hex = local.split(":")
        if int(port_hex, 16) != port or state != "0A":
            continue
        raw = bytes.fromhex(ip_hex)
        found.append(".".join(str(b) for b in reversed(raw)))
    return found


def test_launcher_starts_three_loopback_programs(tmp_path, monkeypatch):
    monkeypatch.setenv("NETIE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NETIE_TOKEN_FILE", str(tmp_path / "home" / "service-token"))
    monkeypatch.setenv("NETIE_TOKEN_STORE", "file")
    ports = {}
    for name in ("airgpt", "dms", "openvault"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        ports[name] = sock.getsockname()[1]
        sock.close()
        script = tmp_path / f"{name}.py"
        script.write_text(
            textwrap.dedent(
                f"""
                from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
                class H(BaseHTTPRequestHandler):
                    def do_GET(self):
                        body = b"{name}"
                        self.send_response(200)
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    def log_message(self, *args):
                        return
                ThreadingHTTPServer(("127.0.0.1", {ports[name]}), H).serve_forever()
                """
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv(f"{name.upper()}_ARGV", json.dumps([sys.executable, str(script)]))
        monkeypatch.setenv(f"{name.upper()}_PORT", str(ports[name]))
    # AIRGPT_ARGV is the name the launcher reads, not AIRGPT from the loop... 
    # the loop used AIRGPT_ARGV via name.upper() which is AIRGPT. Good.
    from bundle.launch import main

    assert main(["--up", "--detach", "--yes"]) == 0
    secret = (tmp_path / "home" / "service-token").read_text(encoding="utf-8").strip()
    try:
        for name, port in ports.items():
            deadline = time.time() + 5
            body = b""
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as res:
                        body = res.read()
                    break
                except Exception:
                    time.sleep(0.05)
            assert body == name.encode(), name
            if Path("/proc/net/tcp").is_file():
                addrs = _listeners(port)
                assert "127.0.0.1" in addrs
                assert "0.0.0.0" not in addrs
        assert secret not in json.dumps(ports)
    finally:
        assert main(["--stop"]) == 0


def test_check_command_does_not_print_the_token(tmp_path, monkeypatch):
    env = dict(os.environ)
    env["NETIE_HOME"] = str(tmp_path)
    env["NETIE_TOKEN_FILE"] = str(tmp_path / "service-token")
    env["NETIE_TOKEN_STORE"] = "file"
    env["AIRGPT_NO_BROWSER"] = "1"
    env.pop("NETIE_SERVICE_TOKEN", None)
    proc = subprocess.run(
        [sys.executable, "-m", "bundle.launch", "--check", "--yes"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    secret = (tmp_path / "service-token").read_text(encoding="utf-8").strip()
    assert secret not in proc.stdout
    assert secret not in proc.stderr
    assert "airgpt" in proc.stdout
    assert "dms" in proc.stdout
    assert "openvault" in proc.stdout
    assert "127.0.0.1:8765" in proc.stdout
    assert "The token was not printed." in proc.stdout
    from bundle.launch import plan

    monkeypatch.setenv("NETIE_HOME", str(tmp_path))
    monkeypatch.setenv("NETIE_TOKEN_FILE", str(tmp_path / "service-token"))
    monkeypatch.setenv("NETIE_TOKEN_STORE", "file")
    monkeypatch.delenv("AIRGPT_ARGV", raising=False)
    rows = plan()
    air = next(row for row in rows if row["name"] == "airgpt")
    assert air["env"]["AIRGPT_BIND"] == "127.0.0.1"
    assert air["env"]["AIRGPT_TUNNEL"] == "0"
    assert any(str(part).endswith("clipdrop.py") for part in air["argv"])
    assert secret not in json.dumps(rows)


def test_server_refuses_tunnel_until_confirmed():
    import clipdrop

    assert "/api/bundle" in clipdrop._HOST_ONLY_PREFIXES
    assert clipdrop._is_host_only_path("/api/bundle/setup", "POST")
    calls: list[str] = []
    orig_boot = clipdrop._boot_tunnel_threads
    orig_restart = clipdrop.restart_tunnel

    def _boot():
        calls.append("boot")

    def _restart():
        calls.append("restart")

    clipdrop._boot_tunnel_threads = _boot
    clipdrop.restart_tunnel = _restart
    previous = os.environ.get("AIRGPT_TUNNEL")
    os.environ["AIRGPT_TUNNEL"] = "0"
    server = clipdrop.ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        def post(payload):
            req = urllib.request.Request(
                base + "/api/restart-tunnel",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as res:
                    return res.status, json.loads(res.read().decode())
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read().decode() or "{}")

        code, body = post({})
        assert code == 409, body
        assert body["warning"] == TUNNEL_OPT_IN_WARNING
        assert calls == []
        code, body = post({"confirm_public": True})
        assert code == 200, body
        assert body["warning"] == TUNNEL_OPT_IN_WARNING
        assert calls == ["boot"]
        assert os.environ.get("AIRGPT_TUNNEL") == "1"
    finally:
        clipdrop._boot_tunnel_threads = orig_boot
        clipdrop.restart_tunnel = orig_restart
        if previous is None:
            os.environ.pop("AIRGPT_TUNNEL", None)
        else:
            os.environ["AIRGPT_TUNNEL"] = previous
        server.shutdown()
        server.server_close()


def test_server_setup_does_not_return_the_token(tmp_path, monkeypatch):
    import clipdrop

    monkeypatch.setenv("NETIE_HOME", str(tmp_path))
    monkeypatch.setenv("NETIE_TOKEN_FILE", str(tmp_path / "service-token"))
    monkeypatch.setenv("NETIE_TOKEN_STORE", "file")
    server = clipdrop.ThreadingHTTPServer(("127.0.0.1", 0), clipdrop.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/api/bundle/status", timeout=10) as res:
            status = json.loads(res.read().decode())
        assert status["bind"] == "127.0.0.1" or status["bind"] == resolve_bind_host()
        assert status["tunnel"] in ("off", "on")
        assert "token" not in status
        req = urllib.request.Request(
            base + "/api/bundle/setup",
            data=b"{}",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            raw = res.read().decode()
        payload = json.loads(raw)
        secret = (tmp_path / "service-token").read_text(encoding="utf-8").strip()
        assert payload["token_stored"] is True
        assert secret not in raw
        assert "token" not in payload
        page = urllib.request.urlopen(base + "/ui/onboarding.html", timeout=10)
        html = page.read().decode("utf-8")
        assert "Create the local service token" in html
        assert secret not in html
    finally:
        server.shutdown()
        server.server_close()

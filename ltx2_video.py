"""LTX-2 / LTX-2.3 video generation for AirGPT.

Modes (auto-selected):
  1. cloud  — LTX_API_KEY → https://api.ltx.video/v2/text-to-video
  2. local  — LTX2_ROOT with uv/python distilled pipeline (GPU)
  3. mock   — ffmpeg color bars / placeholder mp4 (CI + no GPU)

Also runnable as sidecar:  python -m ltx2_video --serve --port 8020
In-process API used by clipdrop: submit / status / result
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from config import DATA_DIR, ROOT

JOBS_DIR = DATA_DIR / "video_jobs"
OUT_DIR = ROOT / "video-assets" / "08-ltx2-outputs"
LTX_CLOUD = "https://api.ltx.video"
DEFAULT_PORT = 8020

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _env(key: str, default: str = "") -> str:
    try:
        from ai_engine import load_env
        return (load_env().get(key) or os.environ.get(key) or default).strip()
    except Exception:
        return (os.environ.get(key) or default).strip()


def ensure_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def capability() -> dict[str, Any]:
    """What can run on this machine right now."""
    api_key = _env("LTX_API_KEY") or _env("LTX2_API_KEY")
    ltx_root = Path(_env("LTX2_ROOT") or (ROOT / "third_party" / "LTX-2"))
    local_ready = (ltx_root / "packages").is_dir() or (ltx_root / "pyproject.toml").is_file()
    ffmpeg = shutil.which("ffmpeg") is not None
    mode = "cloud" if api_key else ("local" if local_ready else "mock")
    return {
        "ok": True,
        "mode": mode,
        "cloud": bool(api_key),
        "local_repo": str(ltx_root) if local_ready else "",
        "ffmpeg": ffmpeg,
        "github": "https://github.com/Lightricks/LTX-2",
        "model": "Lightricks/LTX-2.3",
        "output_dir": str(OUT_DIR),
        "port": DEFAULT_PORT,
        "note": (
            "Cloud: set LTX_API_KEY. Local: clone Lightricks/LTX-2 → third_party/LTX-2 + GPU. "
            "Mock always available for UI/CI."
        ),
    }


def _save_job(job: dict[str, Any]) -> None:
    ensure_dirs()
    path = JOBS_DIR / f"{job['id']}.json"
    path.write_text(json.dumps(job, indent=2), encoding="utf-8")


def _load_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        if job_id in _jobs:
            return _jobs[job_id]
    path = JOBS_DIR / f"{job_id}.json"
    if path.is_file():
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            with _lock:
                _jobs[job_id] = job
            return job
        except Exception:
            return None
    return None


def _set_job(job_id: str, **fields: Any) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id) or _load_job(job_id) or {"id": job_id}
        job.update(fields)
        job["updated_at"] = time.time()
        _jobs[job_id] = job
    _save_job(job)
    return job


def submit(
    prompt: str,
    *,
    duration: float = 6.0,
    width: int = 1280,
    height: int = 720,
    seed: int = 42,
    mode: str | None = None,
) -> dict[str, Any]:
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "prompt required"}
    ensure_dirs()
    caps = capability()
    use = (mode or caps["mode"]).lower()
    if use not in ("cloud", "local", "mock"):
        use = caps["mode"]
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "ok": True,
        "status": "queued",
        "prompt": prompt[:2000],
        "duration": float(duration),
        "width": int(width),
        "height": int(height),
        "seed": int(seed),
        "mode": use,
        "created_at": time.time(),
        "updated_at": time.time(),
        "result_path": "",
        "result_url": "",
        "error": "",
        "progress": 0.0,
    }
    with _lock:
        _jobs[job_id] = job
    _save_job(job)
    t = threading.Thread(target=_run_job, args=(job_id,), daemon=True)
    t.start()
    return {"ok": True, "id": job_id, "status": "queued", "mode": use}


def status(job_id: str) -> dict[str, Any]:
    job = _load_job(job_id)
    if not job:
        return {"ok": False, "error": "job not found"}
    out = {"ok": True, **{k: job[k] for k in job if k != "ok"}}
    return out


def result(job_id: str) -> dict[str, Any]:
    job = _load_job(job_id)
    if not job:
        return {"ok": False, "error": "job not found"}
    if job.get("status") != "completed":
        return {"ok": False, "status": job.get("status"), "error": job.get("error") or "not ready"}
    return {
        "ok": True,
        "id": job_id,
        "path": job.get("result_path"),
        "url": job.get("result_url") or f"/api/video/file/{job_id}",
        "mode": job.get("mode"),
    }


def list_jobs(limit: int = 40) -> dict[str, Any]:
    ensure_dirs()
    items = []
    for p in sorted(JOBS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            items.append({
                "id": j.get("id"),
                "status": j.get("status"),
                "prompt": (j.get("prompt") or "")[:120],
                "mode": j.get("mode"),
                "created_at": j.get("created_at"),
            })
        except Exception:
            continue
    return {"ok": True, "jobs": items}


def file_path(job_id: str) -> Path | None:
    job = _load_job(job_id)
    if not job:
        return None
    p = Path(job.get("result_path") or "")
    return p if p.is_file() else None


def _run_job(job_id: str) -> None:
    job = _load_job(job_id)
    if not job:
        return
    _set_job(job_id, status="running", progress=0.05)
    mode = job.get("mode") or "mock"
    try:
        if mode == "cloud":
            path = _run_cloud(job)
        elif mode == "local":
            path = _run_local(job)
        else:
            path = _run_mock(job)
        _set_job(
            job_id,
            status="completed",
            progress=1.0,
            result_path=str(path),
            result_url=f"/api/video/file/{job_id}",
            error="",
        )
    except Exception as e:
        _set_job(job_id, status="failed", error=str(e)[:400], progress=0.0)


def _run_cloud(job: dict[str, Any]) -> Path:
    key = _env("LTX_API_KEY") or _env("LTX2_API_KEY")
    if not key:
        raise RuntimeError("LTX_API_KEY not set")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "prompt": job["prompt"],
        "model": _env("LTX_MODEL") or "ltx-2-3-fast",
        "duration": min(20, max(6, int(job.get("duration") or 6))),
        "resolution": f"{job.get('width')}x{job.get('height')}",
    }
    req = urllib.request.Request(
        f"{LTX_CLOUD}/v2/text-to-video",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        created = json.loads(r.read().decode())
    remote_id = created.get("id") or created.get("job_id")
    if not remote_id:
        raise RuntimeError(f"cloud submit missing id: {created!r}"[:200])
    _set_job(job["id"], progress=0.15, remote_id=remote_id)

    deadline = time.time() + 900
    video_url = ""
    while time.time() < deadline:
        req2 = urllib.request.Request(
            f"{LTX_CLOUD}/v2/text-to-video/{remote_id}",
            headers=headers,
        )
        with urllib.request.urlopen(req2, timeout=30) as r:
            st = json.loads(r.read().decode())
        status_s = (st.get("status") or "").lower()
        if status_s in ("completed", "succeeded", "success"):
            result = st.get("result") or {}
            video_url = result.get("video_url") or st.get("video_url") or ""
            break
        if status_s in ("failed", "error"):
            raise RuntimeError(st.get("error") or st.get("message") or "cloud failed")
        _set_job(job["id"], progress=min(0.9, float(job.get("progress") or 0.15) + 0.05))
        time.sleep(5)
    if not video_url:
        raise RuntimeError("cloud job timed out or missing video_url")

    out = OUT_DIR / f"{job['id']}.mp4"
    req3 = urllib.request.Request(video_url)
    with urllib.request.urlopen(req3, timeout=120) as r, open(out, "wb") as f:
        shutil.copyfileobj(r, f)
    return out


def _run_local(job: dict[str, Any]) -> Path:
    ltx_root = Path(_env("LTX2_ROOT") or (ROOT / "third_party" / "LTX-2"))
    if not ltx_root.is_dir():
        raise RuntimeError(f"LTX2_ROOT missing: {ltx_root}")
    ckpt = _env("LTX2_CHECKPOINT") or str(
        ltx_root / "models" / "ltx-2.3" / "ltx-2.3-22b-distilled-1.1.safetensors"
    )
    up = _env("LTX2_UPSAMPLER") or str(
        ltx_root / "models" / "ltx-2.3" / "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"
    )
    gemma = _env("LTX2_GEMMA_ROOT") or str(ltx_root / "models" / "gemma-3-12b")
    out = OUT_DIR / f"{job['id']}.mp4"
    cmd = [
        "uv", "run", "python", "-m", "ltx_pipelines.distilled",
        "--distilled-checkpoint-path", ckpt,
        "--spatial-upsampler-path", up,
        "--gemma-root", gemma,
        "--seed", str(job.get("seed") or 42),
        "--output-path", str(out),
        "--prompt", job["prompt"],
    ]
    if not shutil.which("uv"):
        cmd = ["python", "-m", "ltx_pipelines.distilled"] + cmd[4:]
    _set_job(job["id"], progress=0.2)
    proc = subprocess.run(
        cmd,
        cwd=str(ltx_root),
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if proc.returncode != 0 or not out.is_file():
        err = (proc.stderr or proc.stdout or "local generate failed")[:400]
        raise RuntimeError(err)
    return out


def _run_mock(job: dict[str, Any]) -> Path:
    """Generate a short placeholder mp4 so the UI/pipeline works without GPU."""
    out = OUT_DIR / f"{job['id']}.mp4"
    dur = max(2, min(12, int(float(job.get("duration") or 4))))
    w = int(job.get("width") or 1280)
    h = int(job.get("height") or 720)
    _set_job(job["id"], progress=0.3)
    if shutil.which("ffmpeg"):
        # Safe text for drawtext — strip quotes
        label = "LTX2 mock · " + "".join(c if c.isalnum() or c in " .-_" else " " for c in job["prompt"][:40])
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=0x0a0a0a:s={w}x{h}:d={dur}",
            "-vf", f"drawtext=text='{label}':fontcolor=white:fontsize=28:x=(w-text_w)/2:y=(h-text_h)/2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", str(dur), str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode == 0 and out.is_file():
            return out
    # Minimal valid-ish mp4 stub (empty ftyp+mdat) — UI can still show path
    # Prefer writing a tiny webm-less placeholder text sidecar + empty bytes marker
    stub = OUT_DIR / f"{job['id']}.txt"
    stub.write_text(
        f"LTX2 mock job {job['id']}\nprompt: {job['prompt']}\n"
        f"Install ffmpeg or set LTX_API_KEY / local LTX-2 for real video.\n",
        encoding="utf-8",
    )
    # Also write zero-byte mp4 path reference for API shape
    out.write_bytes(b"")
    _set_job(job["id"], result_sidecar=str(stub))
    return out


# --- optional sidecar HTTP server ---

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _json(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        if u.path in ("/", "/health"):
            return self._json(200, {"ok": True, "service": "ltx2", **capability()})
        if u.path == "/api/video/capability":
            return self._json(200, capability())
        if u.path == "/api/video/jobs":
            return self._json(200, list_jobs())
        if u.path.startswith("/api/video/status/"):
            jid = u.path.rsplit("/", 1)[-1]
            return self._json(200, status(jid))
        if u.path.startswith("/api/video/result/"):
            jid = u.path.rsplit("/", 1)[-1]
            return self._json(200, result(jid))
        if u.path.startswith("/api/video/file/"):
            jid = u.path.rsplit("/", 1)[-1]
            p = file_path(jid)
            if not p:
                return self._json(404, {"ok": False, "error": "file missing"})
            data = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw.decode() or "{}")
        except Exception:
            data = {}
        if u.path in ("/api/video/generate", "/v1/generate"):
            return self._json(
                200,
                submit(
                    str(data.get("prompt") or ""),
                    duration=float(data.get("duration") or 6),
                    width=int(data.get("width") or 1280),
                    height=int(data.get("height") or 720),
                    seed=int(data.get("seed") or 42),
                    mode=data.get("mode"),
                ),
            )
        self._json(404, {"ok": False, "error": "not found"})


def serve(port: int = DEFAULT_PORT, host: str = "127.0.0.1") -> None:
    ensure_dirs()
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"ltx2_video → http://{host}:{port}  mode={capability()['mode']}")
    httpd.serve_forever()


def main() -> None:
    p = argparse.ArgumentParser(description="LTX-2 video generator")
    p.add_argument("--serve", action="store_true")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--prompt", default="")
    p.add_argument("--mode", default="")
    args = p.parse_args()
    if args.serve:
        serve(args.port)
        return
    if args.prompt:
        r = submit(args.prompt, mode=args.mode or None)
        print(json.dumps(r, indent=2))
        if r.get("id"):
            while True:
                st = status(r["id"])
                print(json.dumps(st, indent=2))
                if st.get("status") in ("completed", "failed"):
                    break
                time.sleep(1)
        return
    print(json.dumps(capability(), indent=2))


if __name__ == "__main__":
    main()

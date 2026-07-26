"""Keep AirGPT alive: respawn on unexpected exit, persist console output.

`python clipdrop.py` writes everything to a console window that vanishes with the
process, and nothing restarts it. Run this instead:

    python supervisor.py            # supervise clipdrop.py
    python supervisor.py --once     # run once, still tee logs, no restart

Behaviour
- stdout/stderr are teed to the live console *and* appended to data/server.out.log /
  data/server.err.log (size-capped, one rollover kept).
- A non-zero or unexpected exit triggers a restart with exponential backoff
  (2s → 60s). Ctrl-C, or a clean exit code 0, stops for good.
- More than MAX_RESTARTS_PER_HOUR crashes means something is genuinely broken; the
  supervisor stops rather than hammering a broken build forever.
- Every transition is recorded via crashlog.note(), so data/crash.log holds the whole
  lifecycle next to the tracebacks.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from config import DATA_DIR, ROOT

import crashlog

TARGET = ROOT / "clipdrop.py"
MAX_LOG_BYTES = 4 * 1024 * 1024
MAX_RESTARTS_PER_HOUR = 12
BACKOFF_START = 2.0
BACKOFF_MAX = 60.0


def _rotate(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            old = path.with_suffix(path.suffix + ".1")
            if old.exists():
                old.unlink()
            path.rename(old)
    except OSError:
        pass


def _tee(stream, sink: Path, mirror) -> threading.Thread:
    """Pump one child pipe into both the console and a rotating file."""
    def _pump() -> None:
        _rotate(sink)
        try:
            with sink.open("a", encoding="utf-8", errors="replace") as fh:
                for raw in iter(stream.readline, b""):
                    line = raw.decode("utf-8", errors="replace")
                    try:
                        mirror.write(line)
                        mirror.flush()
                    except Exception:
                        pass
                    fh.write(line)
                    fh.flush()
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    t = threading.Thread(target=_pump, daemon=True)
    t.start()
    return t


def run_once() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(TARGET)],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    crashlog.note("supervisor_spawn", child_pid=proc.pid, target=str(TARGET))
    threads = [
        _tee(proc.stdout, DATA_DIR / "server.out.log", sys.stdout),
        _tee(proc.stderr, DATA_DIR / "server.err.log", sys.stderr),
    ]
    try:
        code = proc.wait()
    except KeyboardInterrupt:
        crashlog.note("supervisor_interrupt", child_pid=proc.pid)
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
            code = proc.wait(timeout=10)
        except Exception:
            proc.kill()
            code = -1
        raise
    finally:
        for t in threads:
            t.join(timeout=3)
    return code


def main() -> int:
    once = "--once" in sys.argv[1:]
    if not TARGET.is_file():
        print(f"[supervisor] missing {TARGET}")
        return 2

    backoff = BACKOFF_START
    crashes: list[float] = []
    print(f"[supervisor] watching {TARGET.name} — logs in {DATA_DIR}")
    while True:
        started = time.monotonic()
        try:
            code = run_once()
        except KeyboardInterrupt:
            print("\n[supervisor] stopped by user")
            return 0
        ran = time.monotonic() - started

        if code == 0:
            crashlog.note("supervisor_clean_exit", ran_sec=round(ran, 1))
            print("[supervisor] clean exit — not restarting")
            return 0
        if once:
            crashlog.note("supervisor_exit_once", code=code, ran_sec=round(ran, 1))
            print(f"[supervisor] exit code {code} (--once, not restarting)")
            return code

        now = time.time()
        crashes = [t for t in crashes if now - t < 3600] + [now]
        crashlog.note("supervisor_crash", code=code, ran_sec=round(ran, 1),
                      crashes_this_hour=len(crashes))
        if len(crashes) > MAX_RESTARTS_PER_HOUR:
            print(f"[supervisor] {len(crashes)} crashes in an hour — stopping. "
                  f"See {crashlog.log_path()}")
            crashlog.note("supervisor_giveup", crashes_this_hour=len(crashes))
            return code

        # A process that survived a while is a one-off; reset the ramp.
        backoff = BACKOFF_START if ran > 120 else min(backoff * 2, BACKOFF_MAX)
        print(f"[supervisor] exit code {code} after {ran:.0f}s — restarting in {backoff:.0f}s")
        try:
            time.sleep(backoff)
        except KeyboardInterrupt:
            print("\n[supervisor] stopped by user")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())

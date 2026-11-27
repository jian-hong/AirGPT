"""Stamp a bench JSON with the git SHA and a timestamp, and compare runs.

A fresh run always has a new timestamp. The commit that contains this file
cannot contain its own SHA. Drift checks therefore ignore `commit_sha` and
`generated_at` (and other wall-clock or machine fields) and compare the
measured payload. The CI job still requires the fresh run's `commit_sha` to
be the checkout it just executed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{40}$")
_CLOCK = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_OPS_TOKEN = re.compile(r"ops_\d+_\d+")

# Not measurements. A second run on another machine or a later minute differs
# here even when every score is the same.
VOLATILE_KEYS = frozenset({
    "commit_sha",
    "generated_at",
    "ts",
    "started",
    "finished",
    "ms",
    "fixture",
    "scratch",
    "space_id",
    "url",
    "citations",
    "path",
})

RETRIEVAL_NOTE = (
    "recall_at_1 and recall_at_5 are success@k counts: how many questions "
    "placed their one gold passage in the top k. They are not set-recall. "
    "With one gold passage the count matches recall@k. See rag/metrics.py."
)

PROVENANCE_NOTE = (
    "commit_sha is the git HEAD the harness process ran against. "
    "generated_at is the wall clock of that process. A drift check ignores "
    "both, plus timings, space ids and absolute paths."
)


def git_sha() -> str:
    """Full SHA of the code this process is running. Env override is for tests."""
    for key in ("AIRGPT_BENCH_SHA",):
        raw = (os.environ.get(key) or "").strip().lower()
        if _SHA.match(raw):
            return raw
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    sha = (proc.stdout or "").strip().lower()
    if proc.returncode != 0 or not _SHA.match(sha):
        raise RuntimeError(f"git rev-parse HEAD failed: {(proc.stderr or '').strip()[:200]}")
    return sha


def stamp(payload: dict, *, retrieval: bool = False) -> dict:
    """Return a copy with provenance fields set. Does not write."""
    out = dict(payload)
    out["commit_sha"] = git_sha()
    out["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out["provenance_note"] = PROVENANCE_NOTE
    if retrieval and "metric_note" not in out:
        out["metric_note"] = RETRIEVAL_NOTE
    return out


def write_json(path: Path, payload: dict, *, retrieval: bool = False) -> dict:
    stamped = stamp(payload, retrieval=retrieval)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stamped, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return stamped


def _rel_path(text: str) -> str:
    """Drop the machine-specific prefix of a path that lives in this repo.

    Also blank wall-clock stamps and ops tokens. Those show up in the ops
    audit detail and are not the measurement.
    """
    text = _CLOCK.sub("TIMESTAMP", text)
    text = _OPS_TOKEN.sub("TOKEN", text)
    norm = text.replace("\\", "/")
    marker = "tests/RAG/"
    j = norm.find(marker)
    if j < 0:
        low = norm.lower()
        j = low.find("tests/rag/")
        if j >= 0:
            norm = norm[:j] + "tests/RAG/" + norm[j + len("tests/rag/"):]
            marker = "tests/RAG/"
    if j >= 0:
        k = j
        while k > 0 and norm[k - 1] not in " \t\n":
            k -= 1
        return norm[:k] + norm[j:]
    return text


def canonical(obj):
    """Measured content only, so two runs of one SHA can be compared."""
    if isinstance(obj, dict):
        return {k: canonical(v) for k, v in obj.items() if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [canonical(v) for v in obj]
    if isinstance(obj, str):
        return _rel_path(obj)
    return obj


def diff_paths(left: Path, right: Path, *, limit: int = 8) -> list[str]:
    """Human-readable differences between two bench JSON files. Empty means equal."""
    a = canonical(json.loads(left.read_text(encoding="utf-8")))
    b = canonical(json.loads(right.read_text(encoding="utf-8")))
    found: list[str] = []

    def walk(x, y, where: str) -> None:
        if len(found) >= limit:
            return
        if type(x) is not type(y):
            found.append(f"{where}: {type(x).__name__} vs {type(y).__name__}")
            return
        if isinstance(x, dict):
            keys = sorted(set(x) | set(y))
            for k in keys:
                if k not in x:
                    found.append(f"{where}.{k}: missing on left")
                elif k not in y:
                    found.append(f"{where}.{k}: missing on right")
                else:
                    walk(x[k], y[k], f"{where}.{k}")
                if len(found) >= limit:
                    return
            return
        if isinstance(x, list):
            if len(x) != len(y):
                found.append(f"{where}: length {len(x)} vs {len(y)}")
                return
            for i, (xi, yi) in enumerate(zip(x, y)):
                walk(xi, yi, f"{where}[{i}]")
                if len(found) >= limit:
                    return
            return
        if x != y:
            found.append(f"{where}: {x!r} vs {y!r}")

    walk(a, b, "$")
    return found


def require_stamp(payload: dict, *, label: str) -> str:
    """Return commit_sha or raise ValueError. Timestamp must be present too."""
    sha = str(payload.get("commit_sha") or "")
    when = str(payload.get("generated_at") or "")
    if not _SHA.match(sha):
        raise ValueError(f"{label}: commit_sha is not a 40-char hex SHA ({sha!r})")
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", when):
        raise ValueError(f"{label}: generated_at is not UTC Zulu ({when!r})")
    return sha


def is_ancestor(sha: str, head: str = "HEAD") -> bool:
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, head],
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0

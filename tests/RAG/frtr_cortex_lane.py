"""Cortex/DMS cross-test lane for FRTR (HTTP on :8010)."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("CORTEX_BASE", "http://127.0.0.1:8010")
ROOT = Path(__file__).resolve().parent
SANITIZED = ROOT / "frtr_sanitized"
RESULTS = ROOT / "results"


def _req(method: str, path: str, payload: dict | None = None, timeout: int = 120) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = os.environ.get("CORTEX_CONTRACT_TOKEN") or os.environ.get("CORTEX_API_KEY") or ""
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {"ok": True, "status": resp.status}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "status": e.code, "error": err[:800]}


def ingest_file(path: Path) -> dict:
    raw = path.read_bytes()
    import base64

    payload = {
        "filename": path.name,
        "content_b64": base64.b64encode(raw).decode("ascii"),
    }
    return _req("POST", "/dms/ingest/file", payload, timeout=180)


def ask(question: str) -> dict:
    return _req("POST", "/dms/query", {"question": question, "session_id": "frtr-bench"})


def main():
    wb = SANITIZED / "frtr_0001_quarterly-summary.xlsx"
    print("ingest", wb, flush=True)
    ing = ingest_file(wb)
    print(json.dumps(ing, indent=2)[:1200], flush=True)
    time.sleep(1)
    q = "What is total revenue in Q2 2024?"
    print("query", q, flush=True)
    ans = ask(q)
    print(json.dumps(ans, indent=2)[:2000], flush=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = {"ingest": ing, "query": q, "answer": ans}
    (RESULTS / "cortex_frtr_0001.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

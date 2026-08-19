"""EPIC-D01 #20 gate: the Docs copy must be the founder's original bytes.

The previous claim for this ticket ("space 8 is 6/6 identical") came from a bench
script that made its own copies, not from the product. Production ingest wrote
post-extraction *text* into the blob store, so a founder who ingested an .xlsx
through the UI got no original back - `rag/reveal.py` had a `docs` branch that
never had anything to serve.

This gate asserts the artifact a founder receives (R-0001): it drives the real
`ingest_paths`, then hashes the retained file against the source. A text blob or a
missing `meta.docs_path` fails it. Comparing anything other than raw bytes would
let an extracted copy pass as an original, which is the exact bug it exists for.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

PASS = 0
FAIL: list[str] = []


def check(ok: bool, label: str) -> None:
    global PASS
    if ok:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL.append(label)
        print(f"  FAIL  {label}")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    from rag import ingest, store

    src = Path("tests/RAG/warehouse/wh_02_inventory.xlsx").resolve()
    if not src.is_file():
        print(f"fixture missing: {src}")
        return 2

    print("=" * 68)
    print("EPIC-D01 #20 - byte-faithful Docs original")
    print("=" * 68)
    print(f"source: {src.name}  sha256={sha256(src)[:16]}...  {src.stat().st_size:,} bytes")

    space = store.create_space(f"docs20-gate-{uuid.uuid4().hex[:8]}")
    sid = int(space["id"])
    # Ingest from a copy outside the blob store: ingesting a file that already
    # lives under the space's own Docs/ would trivially "retain" itself and the
    # gate would pass without the writer existing at all.
    with tempfile.TemporaryDirectory() as td:
        staged = Path(td) / src.name
        shutil.copy2(src, staged)
        ingest.ingest_paths(sid, [str(staged)])

    rows = store.list_sources(sid)
    check(bool(rows), f"ingest produced a source row (space {sid})")
    if not rows:
        return 1

    meta = rows[0].get("meta")
    if isinstance(meta, str):
        meta = json.loads(meta or "{}")
    meta = meta or {}
    print(f"  meta keys: {sorted(meta.keys())}")

    docs_path = str(meta.get("docs_path") or "")
    check(bool(docs_path), "meta.docs_path is set by production ingest")
    if not docs_path:
        return 1

    dp = Path(docs_path)
    check(dp.is_file(), f"retained file exists on disk ({dp.name})")
    if not dp.is_file():
        return 1

    check(dp.suffix.lower() == src.suffix.lower(),
          f"retained file keeps the original extension ({dp.suffix})")
    check(dp.stat().st_size == src.stat().st_size,
          f"byte length matches ({dp.stat().st_size:,} == {src.stat().st_size:,})")
    check(sha256(dp) == sha256(src), "sha256 is identical - the bytes are the original")

    # The failure this ticket was closed on: a text blob passing as an original.
    head = dp.open("rb").read(4)
    check(head[:2] == b"PK", f"retained file is still a real .xlsx container (magic {head[:2]!r})")

    print()
    print(f"{PASS}/{PASS + len(FAIL)} checks passed")
    for f in FAIL:
        print(f"  FAILED: {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

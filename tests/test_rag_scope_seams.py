"""A question scoped to some files is answered from those files only, by every lane.

Round 3b added two ways to reach past the first search: the bridge hop (retrieve) and
the name lookup before judging (answer.rescue_hits). The hop was found reading files
outside the scope and was fixed; the name lookup searched the whole space, so a question
limited to public.md could be answered, and cited, from a file the user left out.
"""
from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import rag.store as store  # noqa: E402
from rag import answer, embed, ingest  # noqa: E402

SECRET = "# Accounts\n\nThe retention period for the Wexganpim account is QV-4517.\n"
PUBLIC = "# Notes\n\nThe retention period for most accounts is set by the policy team each year.\n"


@contextmanager
def space(files: dict[str, str]):
    embed.reset_embedder_cache()
    saved = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        root = Path(tmp.name)
        store.RAG_DIR = root / "rag"
        store.DB_PATH = store.RAG_DIR / "rag.db"
        store.BLOB_DIR = store.RAG_DIR
        store.init()
        sid = int(store.create_space("scope", depth_default="high")["id"])
        paths = []
        for name, body in files.items():
            p = root / name
            p.write_text(body, encoding="utf-8")
            paths.append(p)
        ingest.ingest_paths(sid, paths)
        yield sid
    finally:
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = saved
        embed.reset_embedder_cache()
        tmp.cleanup()


def _source_ids(sid: int, needle: str) -> list[int]:
    with store._conn() as conn:
        rows = conn.execute("SELECT id, path FROM sources WHERE space_id=?", (sid,)).fetchall()
    return [int(r["id"]) for r in rows if needle in str(r["path"])]


def _everything_shown(out: dict) -> str:
    parts = [str(out.get("answer") or "")]
    for key in ("hits", "citations"):
        for item in out.get(key) or []:
            parts.append(str(item.get("text") or item.get("snippet") or "") if isinstance(item, dict) else str(item))
            if isinstance(item, dict):
                parts.append(str(item.get("path") or ""))
    return "\n".join(parts)


def test_a_name_lookup_does_not_leave_the_files_the_user_chose():
    q = "What is the retention period for the Wexganpim account?"
    with space({"secret.md": SECRET, "public.md": PUBLIC}) as sid:
        only_public = _source_ids(sid, "public")
        assert only_public, "public.md was not ingested"
        out = answer.answer(sid, q, use_llm=False, source_ids=only_public)
        shown = _everything_shown(out)
        assert "QV-4517" not in shown, "the answer used a file outside the chosen scope"
        assert "secret.md" not in shown, "the answer named a file outside the chosen scope"
        # Unscoped, the same question finds it: the scope, not the lookup, is what hid it.
        out = answer.answer(sid, q, use_llm=False)
        assert "QV-4517" in _everything_shown(out)

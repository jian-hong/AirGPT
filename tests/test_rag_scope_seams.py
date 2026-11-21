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
def space(files: dict):
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
            if isinstance(body, bytes):
                p.write_bytes(body)
            else:
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
        items = out.get(key)
        for item in items if isinstance(items, list) else []:
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


ALPHA = "Region,Amount\nNorth,100\nSouth,200\nNorth,50\n"
BETA = "Region,Amount\nNorth,9000\nSouth,8000\nNorth,7000\n"


def test_sheet_maths_uses_only_the_chosen_files():
    q = "What is the total Amount for North?"
    files = {"alpha_sales.csv": ALPHA, "beta_secret.csv": BETA, "notes.md": "# Notes\n\nGeneral notes.\n"}
    with space(files) as sid:
        out = answer.answer(sid, q, depth="high", use_llm=False, source_ids=_source_ids(sid, "alpha"))
        shown = _everything_shown(out) + str(out.get("provenance")) + str(out.get("sql"))
        assert "150" in out["answer"]
        for leak in ("beta_secret", "16150", "16000"):
            assert leak not in shown, leak
        # Scoped to a file with no table, nothing is calculated from the other files.
        out = answer.answer(sid, q, depth="high", use_llm=False, source_ids=_source_ids(sid, "notes"))
        shown = _everything_shown(out) + str(out.get("provenance")) + str(out.get("sql"))
        assert "150" not in shown and "16000" not in shown and "csv" not in shown.lower()
        # Unscoped it is still calculated, across both.
        out = answer.answer(sid, q, depth="high", use_llm=False)
        assert "16150" in out["answer"]


def _docx_with_table(rows: list[tuple[str, str]]) -> bytes:
    """A minimal Word file built with the standard library: python-docx is optional and
    the Windows CI runner does not have it (the app reads Word without it)."""
    import io
    import zipfile
    from xml.sax.saxutils import escape

    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    cell = lambda t: f'<w:tc><w:p><w:r><w:t xml:space="preserve">{escape(t)}</w:t></w:r></w:p></w:tc>'
    tbl = "<w:tbl>" + "".join("<w:tr>" + "".join(cell(c) for c in r) + "</w:tr>" for r in rows) + "</w:tbl>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="xml" ContentType="application/xml"/></Types>')
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{ns}"><w:body><w:p><w:r><w:t>Report</w:t></w:r></w:p>{tbl}</w:body></w:document>')
    return buf.getvalue()


def test_document_table_maths_follows_the_scope():
    files = {"report.docx": _docx_with_table([("Region", "Amount"), ("North", "1,200"), ("North", "450")]),
             "sales.csv": ALPHA}
    q = "What is the total Amount for North?"
    with space(files) as sid:
        out = answer.answer(sid, q, depth="high", use_llm=False, source_ids=_source_ids(sid, "sales"))
        assert "150" in out["answer"] and "1650" not in out["answer"] and "report.docx" not in _everything_shown(out)
        out = answer.answer(sid, q, depth="high", use_llm=False, source_ids=_source_ids(sid, "report"))
        assert "1650" in out["answer"] and "sales.csv" not in _everything_shown(out)


def test_the_inventory_lists_only_the_chosen_files_and_keeps_the_cached_summary():
    files = {
        "public.md": "# Public\n\nThe office opens at nine.\n",
        "salaries_secret.md": "# Salaries\n\nThe salary of Wexganpim is 9999.\n",
        "budget_confidential.md": "# Budget\n\nThe budget of Projekt Orion is 777.\n",
    }
    with space(files) as sid:
        only = _source_ids(sid, "public")
        for depth in ("basic", "high"):
            for q in ("What does this space contain?", "List all the documents",
                      "Summarize the budget_confidential document"):
                out = answer.answer(sid, q, depth=depth, use_llm=False, source_ids=only)
                shown = _everything_shown(out)
                assert "public.md" in shown, (depth, q)
                for leak in ("salaries_secret", "budget_confidential", "Salaries", "3 indexed", "3 sources"):
                    assert leak not in out["answer"] or leak in q, (depth, q, leak)
                assert "salaries_secret" not in shown
        # The scoped run must not leave its summary behind as the space's own.
        out = answer.answer(sid, "What does this space contain?", depth="basic", use_llm=False)
        assert "salaries_secret" in out["answer"] and "budget_confidential" in out["answer"]
        cached = answer.summarize_space(sid, use_llm=False)
        assert "salaries_secret" in cached["summary"]


_NAMES = ["Zerbruwex", "Halvorsen", "Quisenbru", "Ophzertas", "Wexdovula", "Mikophhal", "Fenquidov", "Lontasoph"]
_CITIES = ["Tromso", "Kragero", "Lillesand", "Haugesund", "Odense", "Aalborg", "Esbjerg", "Vaasa"]


def _register() -> str:
    parts = ["# Account register", ""]
    for i, n in enumerate(_NAMES):
        parts += [f"## Region {i} accounts", "", f"The retention period for the {n} account is ZQ-{4400 + i}.", ""]
    parts += ["# Offices", ""]
    for n, c in zip(_NAMES, _CITIES):
        parts += [f"The headquarters city for the {n} account is {c}.", ""]
    return "\n".join(parts)


def test_whose_and_has_questions_are_not_refused_for_their_own_words():
    qs = ["What is the retention period for the account whose headquarters city is Tromso?",
          "Which account has Tromso as headquarters city, and what is its retention period?"]
    with space({"register.md": _register()}) as sid:
        for depth in ("basic", "high", "max"):
            for q in qs:
                out = answer.answer(sid, q, depth=depth, use_llm=False)
                assert "ZQ-4400" in out["answer"], (depth, q, out["answer"][:200])
                assert "does not contain enough" not in out["answer"]
        # A name nobody holds is still refused.
        out = answer.answer(sid, qs[0].replace("Tromso", "Oslo"), depth="high", use_llm=False)
        assert out["answer"].startswith('The space does not mention "Oslo"')

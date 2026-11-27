"""GitHub repo ingest (RAG-SRC-01). Local fixture only: no live GitHub calls."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

SHA = "0123456789abcdef0123456789abcdef01234567"
API_SHA = "abcdef1234567890abcdef1234567890abcdef12"
REPO = "example/fixture"


def _chunks(store, sid: int) -> list[dict]:
    with store._conn() as conn:
        rows = conn.execute(
            "SELECT id, path, text, meta, kind FROM chunks WHERE space_id=? ORDER BY id",
            (int(sid),),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        meta = item.get("meta") or "{}"
        item["meta"] = json.loads(meta) if isinstance(meta, str) else meta
        out.append(item)
    return out


def _write_fixture(root: Path) -> None:
    (root / "src").mkdir()
    (root / "skip").mkdir()
    (root / "assets").mkdir()
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "README.md").write_text(
        "# Fixture\n\nThe fixture beacon is Orbitrimble and it lives in the pinned readme.\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "src" / "guide.md").write_text(
        "# Guide\n\nThe guide beacon is Guidetrimble and it lives beside the readme.\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "node_modules" / "pkg" / "index.js").write_text(
        "The package beacon is Nodetrimble and must not be indexed at all.\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "skip" / "hidden.md").write_text(
        "The hidden beacon is Skiptrimble and must not be indexed at all.\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\nBintrimble-png")
    (root / "weird.txt").write_bytes(b"The binary beacon is Bintrimble\x00\x01\x02")


@pytest.fixture()
def space(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRGPT_RAG_EMBED", "hash")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    import rag.store as store
    from rag import embed

    embed.reset_embedder_cache()
    monkeypatch.setattr(store, "RAG_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "BLOB_DIR", tmp_path / "rag")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "rag" / "rag.db")
    store.init()
    sid = int(store.create_space("github")["id"])
    yield sid, store
    embed.reset_embedder_cache()


def test_flag_off_does_not_ingest_or_call_out(space, tmp_path, monkeypatch):
    sid, store = space
    monkeypatch.delenv("AIRGPT_RAG_SOURCES_GITHUB", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    _write_fixture(root)
    from rag import ingest

    def boom(*_a, **_k):
        raise AssertionError("network or vault used while the flag is off")

    monkeypatch.setattr(ingest, "_urlopen", boom)
    monkeypatch.setattr(ingest, "_openvault_github_token", boom)
    out = ingest.ingest_github(sid, REPO, sha=SHA, root=root, ignore=["skip/**"])
    assert out["ok"] is False
    assert out.get("disabled") is True
    assert store.list_sources(sid) == []


def test_pinned_fixture_cites_path_at_sha_and_skips_ignored(space, tmp_path, monkeypatch):
    sid, store = space
    monkeypatch.setenv("AIRGPT_RAG_SOURCES_GITHUB", "1")
    root = tmp_path / "repo"
    root.mkdir()
    _write_fixture(root)
    from rag import ingest, retrieve

    def boom(*_a, **_k):
        raise AssertionError("fixture ingest must not use the network")

    monkeypatch.setattr(ingest, "_urlopen", boom)
    out = ingest.ingest_github(sid, REPO, sha=SHA, root=root, ignore=["skip/**"])
    assert out["ok"] is True, out
    assert out["sha"] == SHA
    assert out["files"] == ["README.md", "src/guide.md"]
    skipped = {item["path"] for item in out["skipped"]}
    assert "node_modules/pkg/index.js" in skipped
    assert "skip/hidden.md" in skipped
    assert "assets/logo.png" in skipped
    assert "weird.txt" in skipped

    rows = _chunks(store, sid)
    assert rows
    blob = "\n".join(row["text"] for row in rows)
    assert "Orbitrimble" in blob
    assert "Guidetrimble" in blob
    for banned in ("Nodetrimble", "Skiptrimble", "Bintrimble"):
        assert banned not in blob
    expect = {f"README.md@{SHA}", f"src/guide.md@{SHA}"}
    for row in rows:
        assert row["path"] in expect
        assert row["path"].endswith("@" + SHA)
        assert row["meta"].get("locator") == row["path"]
    sources = store.list_sources(sid)
    assert sources
    for src in sources:
        meta = src.get("meta") or {}
        assert meta.get("github_sha") == SHA
        assert meta.get("locator", "").endswith("@" + SHA)
        assert meta.get("github_path") in {"README.md", "src/guide.md"}

    for token, locator in (("Orbitrimble", f"README.md@{SHA}"), ("Guidetrimble", f"src/guide.md@{SHA}")):
        found = retrieve.search(sid, token, depth="basic")
        cites = [c.get("path") for c in (found.get("citations") or [])]
        assert locator in cites, cites

    ids = [row["id"] for row in rows]
    again = ingest.ingest_github(sid, REPO, sha=SHA, root=root, ignore=["skip/**"])
    assert again["ok"] is True
    assert [row["id"] for row in _chunks(store, sid)] == ids


def test_private_repo_without_token_is_a_clean_error(space, monkeypatch):
    sid, _store = space
    monkeypatch.setenv("AIRGPT_RAG_SOURCES_GITHUB", "1")
    monkeypatch.setenv("GH_TOKEN", "env-should-not-be-read")
    monkeypatch.setenv("GITHUB_TOKEN", "env-should-not-be-read")
    import openvault_bridge
    from rag import ingest

    monkeypatch.setattr(openvault_bridge, "github_token", lambda: "")

    def boom(*_a, **_k):
        raise AssertionError("missing token must not call GitHub")

    monkeypatch.setattr(ingest, "_urlopen", boom)
    out = ingest.ingest_github(
        sid,
        "https://userinfo-secret@github.com/acme/hidden",
        private=True,
    )
    dumped = json.dumps(out)
    assert out["ok"] is False
    assert out["error"] == ingest._GH_TOKEN_MISSING
    assert "userinfo-secret" not in dumped
    assert "env-should-not-be-read" not in dumped
    assert "ghp_" not in dumped


def test_private_repo_uses_openvault_token_and_does_not_leak_it(space, monkeypatch):
    sid, store = space
    monkeypatch.setenv("AIRGPT_RAG_SOURCES_GITHUB", "1")
    monkeypatch.setenv("GH_TOKEN", "env-should-not-be-read")
    monkeypatch.setenv("GITHUB_TOKEN", "env-should-not-be-read")
    import openvault_bridge
    from rag import ingest

    token = "vault-github-token"
    monkeypatch.setattr(openvault_bridge, "github_token", lambda: token)
    seen: list[tuple[str, str]] = []

    class _Resp:
        def __init__(self, body: bytes, status: int = 200):
            self._body = body
            self.status = status

        def read(self, n=-1):
            if n is None or n < 0:
                return self._body
            return self._body[:n]

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def fake_open(req, timeout=20):
        url = req.full_url
        auth = req.get_header("Authorization") or ""
        seen.append((url, auth))
        assert token not in url
        assert "env-should-not-be-read" not in url
        if "/git/trees/" in url:
            body = json.dumps({
                "sha": API_SHA,
                "truncated": False,
                "tree": [
                    {"path": "README.md", "type": "blob", "size": 80},
                    {"path": "node_modules/pkg/index.js", "type": "blob", "size": 20},
                    {"path": "logo.png", "type": "blob", "size": 10},
                ],
            }).encode()
            return _Resp(body)
        if "/contents/README.md" in url:
            return _Resp(b"The private beacon is Vaulttrimble and it was fetched with the vault token only.\n")
        raise AssertionError(f"unexpected GitHub URL {url}")

    monkeypatch.setattr(ingest, "_urlopen", fake_open)
    out = ingest.ingest_github(sid, "acme/private", sha=API_SHA, private=True)
    dumped = json.dumps(out)
    assert out["ok"] is True, out
    assert token not in dumped
    assert "env-should-not-be-read" not in dumped
    assert seen
    assert all(auth == "Bearer " + token for _url, auth in seen)
    assert all("env-should-not-be-read" not in auth for _url, auth in seen)
    assert not any("node_modules" in url or url.endswith(".png") for url, _auth in seen)
    blob = "\n".join(row["text"] for row in _chunks(store, sid))
    assert "Vaulttrimble" in blob
    assert all(row["path"] == f"README.md@{API_SHA}" for row in _chunks(store, sid))


def test_github_error_redacts_the_token(space, monkeypatch):
    sid, _store = space
    monkeypatch.setenv("AIRGPT_RAG_SOURCES_GITHUB", "1")
    import openvault_bridge
    from rag import ingest

    token = "vault@secret"
    monkeypatch.setattr(openvault_bridge, "github_token", lambda: token)

    def boom(req, timeout=20):
        raise OSError(f"connection failed for {token} and vault%40secret")

    monkeypatch.setattr(ingest, "_urlopen", boom)
    out = ingest.ingest_github(sid, "acme/private", sha=API_SHA, private=True)
    dumped = json.dumps(out)
    assert out["ok"] is False
    assert token not in dumped
    assert "vault%40secret" not in dumped
    assert "[redacted]" in out["error"]


def test_github_token_reads_openvault_and_ignores_env(monkeypatch):
    import openvault_bridge
    from OpenIDE import openvault_bridge as ov

    monkeypatch.setenv("GH_TOKEN", "env-should-not-be-read")
    monkeypatch.setenv("GITHUB_TOKEN", "env-should-not-be-read")

    def down(method, url, body=None, timeout=8.0):
        raise OSError("openvault down")

    monkeypatch.setattr(ov, "_http_json", down)
    assert openvault_bridge.github_token() == ""
    assert ov.github_token() == ""

    def payload(method, url, body=None, timeout=8.0):
        if str(url).endswith("/api/keys/GH_TOKEN"):
            return {"secret": "vault-github-token"}
        return {}

    monkeypatch.setattr(ov, "_http_json", payload)
    assert ov.github_token() == "vault-github-token"
    # The value came back from OpenVault, not from the environment.
    assert ov.github_token() != "env-should-not-be-read"

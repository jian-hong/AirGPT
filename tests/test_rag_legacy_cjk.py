"""Legacy Chinese, Japanese and Korean text files are read, not refused as binary (i-rag.0)."""
import gzip
import random

import pytest

ZH = "起初，我们在槟城的仓库有一百二十个托盘。退货期限是三十天。\n"
ZH_TW = "起初，我們在檳城的倉庫有一百二十個托盤。退貨期限是三十天。\n"
JA = "今季の売上は伸びた。倉庫は四千五百パレットを出荷した。\n"
KO = "이번 분기 매출이 늘었습니다. 창고에서 팔레트 사천오백 개를 출하했습니다.\n"

CASES = [
    ("gbk", ZH, "gbk", "托盘"),
    ("gb18030", ZH, "gb18030", "托盘"),
    ("big5", ZH_TW, "big5", "托盤"),
    ("sjis", JA, "shift_jis", "パレット"),
    ("eucjp", JA, "euc_jp", "パレット"),
    ("euckr", KO, "euc_kr", "팔레트"),
    ("u16le_nobom", ZH, "utf-16-le", "托盘"),
    ("u16be_nobom", JA, "utf-16-be", "パレット"),
]


@pytest.mark.parametrize("name,text,enc,word", CASES)
def test_legacy_cjk_is_text_and_decodes_right(tmp_path, name, text, enc, word):
    from rag import ingest

    raw = (text * 40).encode(enc)
    p = tmp_path / f"{name}.txt"
    p.write_bytes(raw)
    assert ingest.looks_binary(p) is False
    assert ingest.unreadable_reason(p) == ""
    assert ingest._decode(raw) == text * 40


@pytest.mark.parametrize("name,text,enc,word", CASES)
def test_big_legacy_cjk_sampled_file_is_text(tmp_path, name, text, enc, word):
    from rag import ingest

    p = tmp_path / f"big_{name}.txt"
    p.write_bytes((text * 100000).encode(enc))
    assert p.stat().st_size > 4 * 1024 * 1024
    assert ingest.looks_binary(p) is False


_RNG = random.Random(11)
JUNK = [
    ("random.txt", bytes(_RNG.randrange(256) for _ in range(6000))),
    ("high.txt", bytes(_RNG.randrange(128, 256) for _ in range(6000))),
    ("gzip.txt", gzip.compress(("hello world " * 400).encode())),
    ("png.txt", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(_RNG.randrange(256) for _ in range(3000))),
    ("elf.txt", b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 200 + bytes(_RNG.randrange(256) for _ in range(3000))),
]


@pytest.mark.parametrize("name,data", JUNK)
def test_junk_is_still_refused_as_binary(tmp_path, name, data):
    from rag import ingest

    p = tmp_path / name
    p.write_bytes(data)
    assert ingest.looks_binary(p) is True
    assert ingest.unreadable_reason(p) == ingest.BINARY_REASON


def test_valid_text_in_an_unknowable_encoding_says_so(tmp_path):
    from rag import ingest

    # Real GBK, but only rare characters: it is text, yet no code page can be named.
    raw = ("龘靐齉爨籱饕餮" * 60).encode("gb18030")
    p = tmp_path / "rare.txt"
    p.write_bytes(raw)
    assert ingest.looks_binary(p) is True
    assert ingest.unreadable_reason(p) == (
        "Could not tell which text encoding this file uses. Save it as UTF-8 and add it again."
    )


def test_search_finds_and_cites_each_language(tmp_path, monkeypatch):
    from rag import ingest, retrieve, store

    root = tmp_path / "d"
    root.mkdir()
    monkeypatch.setattr(store, "RAG_DIR", root / "rag")
    monkeypatch.setattr(store, "DB_PATH", root / "rag" / "rag.db")
    monkeypatch.setattr(store, "BLOB_DIR", root / "rag")
    store.init()
    for name, text, enc, word in CASES:
        sid = int(store.create_space(name, depth_default="high")["id"])
        p = tmp_path / f"{name}.txt"
        p.write_bytes((text * 5).encode(enc))
        out = ingest.ingest_paths(sid, [p], force=True)
        assert not out.get("skipped"), (name, out)
        assert out["chunks"] >= 1, (name, out)
        hits = retrieve.sparse_search(sid, word) + retrieve.script_search(sid, word)
        assert hits, name
        assert any(word in (h.payload.get("text", "") if hasattr(h, "payload") else str(h))
                   for h in hits), (name, hits[:1])

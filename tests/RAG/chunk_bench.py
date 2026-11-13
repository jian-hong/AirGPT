"""Chunking bench: does one chunk hold a whole fact, with its column names, in any script?

filetype_bench asks "can a fact be found again". This asks the question underneath it:
when a long document is cut into chunks, does a fact SURVIVE the cut? A fact that is
split across two chunks, or a sheet row that reaches the reader without its column
names, cannot be answered correctly however good retrieval is.

Documents (generated here, ingested into a temp store, no model, no network):
  sheet   xlsx, 640 rows x 4 columns, some blank cells (Region every 7th row, Note
          every 5th), 30 rows picked from deep in the sheet
  pdf     3 long pages of running prose, hard-wrapped at ~95 columns like a real PDF
          (so one page arrives as one paragraph with single newlines)
  zh ja th ar   long single-paragraph documents with 30 facts each

Each fact is two sentences (about 300-400 characters in Latin script) with the
entity in the first and the value in the second. In the PDF, half of the facts are
aimed at the span the OLD chunker cut by character count (stride 640, window 800),
so they straddle its cuts by construction; the other half sit anywhere.

Reported:
  header_share      share of the sheet's child chunks that contain the header row
  sentence_share    share of prose child chunks that start AND end on a sentence
                    boundary (Thai has no sentence mark: a space also counts there)
  tokens            chunk length per document, in reference tokens
  facts_whole       of 30 facts, how many sit whole in ONE child chunk (table: the
                    exact row, blank cells in their column, plus the header row)

Reference tokens are a fixed table of characters per token below. They are a round
assumption, not a measured tokenizer, and they are the same numbers the chunker's
own estimate uses, so they show whether the budget is kept, not whether it is right.

    python tests/RAG/chunk_bench.py --no-write
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, Path(__file__).resolve().parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

RESULTS = Path(__file__).resolve().parent / "results" / "chunk_bench_latest.json"
N_FACTS = 30
ROWS = 640
HEADER = ["Account", "Region", "Balance", "Note"]
# Old chunker: hard split stride (800 - 160) and window, used only to AIM facts.
OLD_STRIDE, OLD_WINDOW = 640, 800

_SYL = ["hal", "vor", "sen", "mik", "ado", "ren", "tas", "kel", "bru", "nim", "oph", "ula",
        "zer", "yth", "gan", "dov", "pim", "sar", "wex", "lon", "qui", "fen", "jor", "bax"]
_BRANCH = ["Ostrava", "Tampere", "Gdansk", "Porto", "Bergen", "Leiden", "Aarhus", "Tartu"]

# reference characters per token (round figures, see module docstring)
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")
_THAI = re.compile(r"[฀-๿]")
_ARAB = re.compile(r"[؀-ۿ]")


# Measured with this bench on the character-count chunker (commit 37c6bfc), seed 1.
# Kept so the gate can show the new numbers are a change and not a fixture that was
# always easy. Per document: facts whole of 30, share of chunks, and the largest chunk.
BASELINE_OLD = {
    "commit": "37c6bfc",
    "sheet": {"facts_whole": 0, "header_share": 0.03, "facts_blank_cell_whole": 0, "max_tokens": 199.8},
    "pdf": {"facts_whole": 18, "facts_aimed_whole": 8, "sentence_share": 0.0, "max_tokens": 393.8},
    "zh": {"facts_whole": 30, "sentence_share": 0.05, "max_tokens": 926.2},
    "ja": {"facts_whole": 30, "sentence_share": 0.08, "max_tokens": 1208.2},
    "th": {"facts_whole": 26, "sentence_share": 0.0, "max_tokens": 367.0},
    "ar": {"facts_whole": 30, "sentence_share": 0.03, "max_tokens": 279.1},
}


def ref_tokens(text: str) -> float:
    n_cjk = len(_CJK.findall(text))
    n_thai = len(_THAI.findall(text))
    n_arab = len(_ARAB.findall(text))
    rest = len(text) - n_cjk - n_thai - n_arab
    return n_cjk * 1.0 + n_thai * 0.5 + n_arab * 0.4 + rest / 4.0


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _entity(rng: random.Random, seen: set) -> str:
    while True:
        e = "".join(rng.sample(_SYL, 3)).capitalize()
        if e not in seen:
            seen.add(e)
            return e


def _value(rng: random.Random, i: int) -> str:
    return f"{rng.choice('BCDFGHJKLMNPQRSTVWXZ')}{rng.choice('BCDFGHJKLMNPQRSTVWXZ')}-{rng.randint(1000, 9999)}{i:02d}"


# --- the sheet ---------------------------------------------------------------

def make_sheet(path: Path, seed: int = 1) -> list[dict]:
    import openpyxl

    rng = random.Random(f"sheet:{seed}")
    seen: set = set()
    rows = []
    for i in range(ROWS):
        acct = f"{_entity(rng, seen)}{i}"
        region = "" if i % 7 == 0 else rng.choice(_BRANCH)
        bal = f"{rng.randint(100, 99999)}.{rng.randint(0, 99):02d}"
        note = "" if i % 5 == 0 else f"ref {rng.randint(10000, 99999)}"
        rows.append([acct, region, bal, note])
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Balances"
    ws.append(HEADER)
    for r in rows:
        ws.append([c if c != "" else None for c in r])
    wb.save(path)
    picks = sorted(rng.sample(range(200, ROWS), N_FACTS))
    facts = []
    for i in picks:
        cells = list(rows[i])
        while cells and not cells[-1]:
            cells.pop()
        facts.append({"row": " | ".join(cells), "blank": "" in rows[i]})
    return facts


# --- prose -------------------------------------------------------------------

def _latin(rng, ent, br, val):
    f1 = (f"The {ent} account is held by the {br} branch and was opened under the "
          f"{rng.choice(_SYL)} programme after a full mandate review.")
    f2 = (f" Its retention period is {val}, which the audit team confirmed in writing "
          f"and which applies to every linked sub-account.")
    return f1 + f2


def _filler_latin(rng):
    nm = rng.choice(_SYL).capitalize() + rng.choice(_SYL)
    t = rng.choice([
        f"Warehouse {rng.randint(1, 99)} finished its routine stock count in month {rng.randint(1, 12)} under {nm}.",
        f"The {nm} team filed quarterly report {rng.randint(1000, 9999)} and passed it to the audit group.",
        f"Client {nm} asked for the payment schedule to be updated before month {rng.randint(1, 12)} and the records were filed.",
        f"No exception was raised on ledger {rng.randint(1000, 9999)} during the review by {nm}.",
    ])
    return t


LANGS = {
    "zh": dict(
        fact=lambda rng, e, b, v: f"{e}账户由{b}分行负责管理，开户时已经核对全部授权文件。该账户的保留期限为{v}，审计小组已书面确认。",
        filler=lambda rng, n: rng.choice([
            f"第{rng.randint(1, 99)}号仓库在{rng.randint(1, 12)}月完成了例行盘点，负责人是{n}。",
            f"{n}部门提交了编号为{rng.randint(1000, 9999)}的季度报告，随后转交审计组。",
            f"客户{n}要求在{rng.randint(1, 12)}月之前更新付款安排，相关记录已归档。",
        ]),
        sep="", terminals="。！？"),
    "ja": dict(
        fact=lambda rng, e, b, v: f"{e}口座は{b}支店が管理しており、開設時に全ての委任状を確認しました。この口座の保存期間は{v}であり、監査チームが書面で確認しました。",
        filler=lambda rng, n: rng.choice([
            f"第{rng.randint(1, 99)}倉庫は{rng.randint(1, 12)}月に定期棚卸を完了し、担当者は{n}でした。",
            f"{n}部門が番号{rng.randint(1000, 9999)}の四半期報告書を提出し、その後監査チームに回付されました。",
            f"顧客{n}は{rng.randint(1, 12)}月までに支払い計画の更新を求め、関連記録は保管されました。",
        ]),
        sep="", terminals="。！？"),
    "th": dict(
        fact=lambda rng, e, b, v: f"บัญชี {e} อยู่ในความดูแลของสาขา {b} และได้ตรวจสอบเอกสารมอบอำนาจทั้งหมดแล้วตั้งแต่เปิดบัญชี ระยะเวลาเก็บรักษาของบัญชีนี้คือ {v} และทีมตรวจสอบยืนยันเป็นลายลักษณ์อักษรแล้ว",
        filler=lambda rng, n: rng.choice([
            f"คลังสินค้าหมายเลข {rng.randint(1, 99)} ตรวจนับตามปกติเสร็จในเดือน {rng.randint(1, 12)} โดยผู้รับผิดชอบคือ {n}",
            f"แผนก {n} ส่งรายงานรายไตรมาสหมายเลข {rng.randint(1000, 9999)} แล้วจึงส่งต่อให้ทีมตรวจสอบ",
            f"ลูกค้า {n} ขอให้ปรับปรุงตารางการชำระเงินภายในเดือน {rng.randint(1, 12)} และเก็บบันทึกไว้แล้ว",
        ]),
        sep=" ", terminals=""),
    "ar": dict(
        fact=lambda rng, e, b, v: f"حساب {e} يديره فرع {b} وقد تمت مراجعة جميع وثائق التفويض عند فتحه. مدة الاحتفاظ بهذا الحساب هي {v} وقد أكد فريق التدقيق ذلك كتابيا.",
        filler=lambda rng, n: rng.choice([
            f"تم الانتهاء من جرد المستودع رقم {rng.randint(1, 99)} في الشهر {rng.randint(1, 12)} وكان المسؤول {n}.",
            f"قدم قسم {n} التقرير الفصلي رقم {rng.randint(1000, 9999)} ثم أحيل إلى فريق التدقيق.",
            f"هل أكد {n} موعد التسليم في الشهر {rng.randint(1, 12)}؟",
        ]),
        sep=" ", terminals="."),
}


def _wrap(text: str, width: int = 95) -> list[str]:
    lines, cur = [], ""
    for w in text.split(" "):
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def make_pdf(path: Path, seed: int = 1) -> tuple[list[dict], set, set]:
    """3 pages, 10 facts each, wrapped lines. Returns facts and the sentence start/end sets."""
    from filetype_bench import pdf_bytes

    rng = random.Random(f"pdf:{seed}")
    seen: set = set()
    pages, facts, starts, ends = [], [], set(), set()
    for pg in range(3):
        title = f"Branch review {pg + 1}"
        starts.add(_norm(title)[:12])
        ends.add(_norm(title)[-12:])
        sents: list[str] = []
        pos = 0
        for k in range(10):
            aim = k % 2 == 0
            for _ in range(rng.randint(3, 7)):
                s = _filler_latin(rng)
                sents.append(s)
                pos += len(s) + 1
            if aim:
                for _ in range(20):
                    if 570 <= pos % OLD_STRIDE <= 630:
                        break
                    s = _filler_latin(rng)
                    sents.append(s)
                    pos += len(s) + 1
            ent = _entity(rng, seen)
            val = _value(rng, len(facts))
            text = _latin(rng, ent, rng.choice(_BRANCH), val)
            s1, s2 = text.split(". ", 1)[0] + ".", text.split(". ", 1)[1]
            sents.extend([s1, s2])
            pos += len(text) + 1
            facts.append({"text": _norm(text), "aimed": aim and 570 <= (pos - len(text) - 1) % OLD_STRIDE <= 630})
        for s in sents:
            starts.add(_norm(s)[:12])
            ends.add(_norm(s)[-12:])
        pages.append([title] + _wrap(" ".join(sents)))
    path.write_bytes(pdf_bytes(pages))
    return facts, starts, ends


def make_lang(path: Path, lang: str, seed: int = 1) -> tuple[list[dict], set, set]:
    cfg = LANGS[lang]
    rng = random.Random(f"{lang}:{seed}")
    seen: set = set()
    sents: list[str] = []
    facts = []
    fact_at = set(rng.sample(range(30, 330), N_FACTS))
    nfill = 0
    for i in range(360):
        if i in fact_at:
            ent = _entity(rng, seen)
            text = cfg["fact"](rng, ent, rng.choice(_BRANCH), _value(rng, len(facts)))
            facts.append({"text": _norm(text), "aimed": False})
            sents.append(text)  # one item, so a paragraph break never lands inside a fact
        else:
            sents.append(cfg["filler"](rng, rng.choice(_SYL).capitalize() + rng.choice(_SYL)))
            nfill += 1
    paras = [cfg["sep"].join(sents[i:i + 80]) for i in range(0, len(sents), 80)]
    path.write_text("\n\n".join(paras) + "\n", encoding="utf-8")
    units = [u for s in sents for u in _split_fact(s, cfg)]
    if lang == "th":  # Thai: phrases are space-separated
        units = [u for s in sents for u in re.split(r"(?<=[\u0e00-\u0e7f]) +(?=[\u0e00-\u0e7f])", s)]
    starts = {_norm(s)[:12] for s in units}
    ends = {_norm(s)[-12:] for s in units}
    return facts, starts, ends


def _split_fact(text: str, cfg: dict) -> list[str]:
    if cfg["terminals"]:
        parts = re.split(f"(?<=[{re.escape(cfg['terminals'])}])", text)
        return [p.strip() for p in parts if p.strip()]
    return [text]


# --- the run -------------------------------------------------------------------

def _pct(v: list[float], q: float) -> float:
    v = sorted(v)
    return round(v[min(len(v) - 1, int(q * len(v)))], 1) if v else 0.0


def run(seed: int = 1) -> dict:
    os.environ["AIRGPT_RAG_EMBED"] = "hash"
    import rag.store as store
    from rag import embed, index_fingerprint, ingest

    embed.reset_embedder_cache()
    saved = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        root = Path(tmp.name)
        store.RAG_DIR = root / "rag"
        store.DB_PATH = store.RAG_DIR / "rag.db"
        store.BLOB_DIR = store.RAG_DIR
        store.init()
        sid = int(store.create_space("chunk bench", depth_default="high")["id"])
        corpus = root / "corpus"
        corpus.mkdir()

        sheet_facts = make_sheet(corpus / "sheet.xlsx", seed)
        prose: dict[str, tuple[list[dict], set, set]] = {"pdf": make_pdf(corpus / "pages.pdf", seed)}
        names = {"pdf": "pages.pdf"}
        for lang in LANGS:
            prose[lang] = make_lang(corpus / f"doc_{lang}.txt", lang, seed)
            names[lang] = f"doc_{lang}.txt"
        out = ingest.ingest_paths(sid, sorted(corpus.iterdir()))
        if out.get("skipped"):
            raise RuntimeError(f"bench fixture skipped: {out['skipped']}")

        with store._conn() as c:
            rows = c.execute("SELECT path, text FROM chunks WHERE space_id=? AND kind='child'", (sid,)).fetchall()
        by_doc: dict[str, list[str]] = {}
        for r in rows:
            by_doc.setdefault(Path(r[0]).name, []).append(r[1])

        result: dict = {"documents": {}}
        # sheet (the "## Spreadsheet index" chunk lists sheets, it is not rows)
        chunks = [t for t in by_doc.get("sheet.xlsx", []) if not t.startswith("## Spreadsheet index")]
        header_line = " | ".join(HEADER)
        with_header = sum(1 for t in chunks if header_line in t.splitlines() or header_line in t)
        whole = 0
        for f in sheet_facts:
            if any(f["row"] in t.splitlines() or f"\n{f['row']}\n" in f"\n{t}\n" for t in chunks if header_line in t):
                whole += 1
        toks = [ref_tokens(t) for t in chunks]
        result["documents"]["sheet"] = {
            "chunks": len(chunks), "header_chunks": with_header,
            "header_share": round(with_header / max(1, len(chunks)), 3),
            "facts_whole": whole, "facts": len(sheet_facts),
            "facts_blank_cell_whole": sum(1 for f in sheet_facts if f["blank"] and any(
                f["row"] in t.splitlines() for t in chunks if header_line in t)),
            "facts_blank_cell": sum(1 for f in sheet_facts if f["blank"]),
            "tokens": {"p10": _pct(toks, .1), "median": _pct(toks, .5), "p90": _pct(toks, .9), "max": round(max(toks or [0]), 1)},
        }
        # prose
        for key, (facts, starts, ends) in prose.items():
            chunks = by_doc.get(names[key], [])
            norm_chunks = [_norm(t) for t in chunks]
            lang_th = key == "th"

            def start_ok(t: str) -> bool:
                return t[:12] in starts or t.startswith("## ")

            def end_ok(t: str) -> bool:
                return t[-12:] in ends

            ok_s = sum(1 for t in norm_chunks if start_ok(t))
            ok_e = sum(1 for t in norm_chunks if end_ok(t))
            both = sum(1 for t in norm_chunks if start_ok(t) and end_ok(t))
            whole = sum(1 for f in facts if any(f["text"] in t for t in norm_chunks))
            toks = [ref_tokens(t) for t in chunks]
            doc = {
                "chunks": len(chunks),
                "starts_on_boundary": ok_s, "ends_on_boundary": ok_e,
                "sentence_share": round(both / max(1, len(chunks)), 3),
                "facts_whole": whole, "facts": len(facts),
                "tokens": {"p10": _pct(toks, .1), "median": _pct(toks, .5), "p90": _pct(toks, .9), "max": round(max(toks or [0]), 1)},
            }
            if key == "pdf":
                aimed = [f for f in facts if f["aimed"]]
                doc["facts_aimed_at_old_cut"] = len(aimed)
                doc["facts_aimed_whole"] = sum(1 for f in aimed if any(f["text"] in t for t in norm_chunks))
            if lang_th:
                doc["note"] = "Thai: unit = phrase between two spaces; Thai has no sentence mark"
            result["documents"][key] = doc
        return {
            "bench": "chunk_bench",
            "seed": seed,
            "index_fingerprint": index_fingerprint.fingerprint(extra={"pack": "chunk_bench"}),
            "old_code_baseline": BASELINE_OLD,
            "honesty": "synthetic documents, hash embedder, no model. A fact is 'whole' when one child chunk holds "
                       "it verbatim (table rows: exact row plus the header row). Reference tokens are round "
                       "per-script assumptions, not a measured tokenizer. n=30 facts per document.",
            **result,
        }
    finally:
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = saved
        embed.reset_embedder_cache()
        tmp.cleanup()


def render(res: dict) -> str:
    lines = [f"{'doc':<6}{'chunks':>7}{'header':>8}{'sentence':>10}{'facts whole':>13}   tokens p10/med/p90/max"]
    for k, d in res["documents"].items():
        t = d["tokens"]
        hdr = f"{d['header_share']:.0%}" if "header_share" in d else "-"
        sen = f"{d['sentence_share']:.0%}" if "sentence_share" in d else "-"
        lines.append(f"{k:<6}{d['chunks']:>7}{hdr:>8}{sen:>10}{d['facts_whole']:>8}/{d['facts']:<4}   "
                     f"{t['p10']}/{t['median']}/{t['p90']}/{t['max']}")
    pdf = res["documents"].get("pdf", {})
    if pdf:
        lines.append(f"pdf facts aimed at the old character cut: {pdf['facts_aimed_whole']}/{pdf['facts_aimed_at_old_cut']} whole")
    sh = res["documents"]["sheet"]
    lines.append(f"sheet rows with a blank cell: {sh['facts_blank_cell_whole']}/{sh['facts_blank_cell']} whole")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    res = run(args.seed)
    print(render(res))
    if not args.no_write:
        RESULTS.parent.mkdir(parents=True, exist_ok=True)
        RESULTS.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {RESULTS}")

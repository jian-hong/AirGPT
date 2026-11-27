"""Real-document retrieval pack (RAG-BENCH-17).

A small company archive, not one planted sentence per file: a register, an HTML
policy, a city-to-desk memo, a spreadsheet ledger full of look-alike rows, a
PDF page and a Word cover letter. Gold is the value itself (a code), not "a
passage came back".

Three styles:

  verbatim   the question uses the document's words and the account name
  synonym    the account name is kept; "retention period" is asked as
             "how long are records kept"
  cross_file the question names a city. The memo maps that city to a desk
             number and does not contain the code. The code is one row of
             ledger.xlsx, under hundreds of penalty rows that do not name
             the city. The desk number is a bare number, which the retriever
             does not treat as a name, and the word penalty is everywhere.

success@k: the gold code occurs in the top k hit texts.
nDCG@10: binary, one relevant hit, 1/log2(rank+2) if that hit is inside 10
else 0. That is not success@k (rag/metrics.py).

    python tests/RAG/real_doc_bench.py --write-corpus
    python tests/RAG/real_doc_bench.py
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import random
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAG = Path(__file__).resolve().parent
CORPUS = RAG / "real_docs"
GOLD_PATH = CORPUS / "gold.json"
RESULTS = RAG / "results" / "real_doc_bench_latest.json"
for _p in (str(ROOT), str(RAG)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

N_VERBATIM = 80
N_SYNONYM = 40
N_CROSS = 80
N_DISTRACTOR_ROWS = 300

_STEMS = [
    "Halvor", "Berg", "Nord", "Fjelde", "Dal", "Vik", "Strand", "Holm",
    "Lind", "Bakke", "Sol", "Moen", "Haug", "Eide", "Ness", "Aas",
]
_TAILS = ["sen", "stad", "land", "vik", "berg", "dal", "nes", "rud"]
_CITIES = [
    "Tromso", "Bergen", "Stavanger", "Alesund", "Haugesund", "Kristiansand", "Drammen", "Skien",
    "Tonsberg", "Fredrikstad", "Sarpsborg", "Sandnes", "Bodoe", "Tromsdalen", "Harstad", "Molde",
    "Lillehammer", "Gjovik", "Hamar", "Kongsberg", "Narvik", "Alta", "Kiruna", "Lulea",
    "Umea", "Visby", "Malmo", "Uppsala", "Vasteras", "Orebro", "Linkoping", "Helsingborg",
    "Jonkoping", "Norrkoping", "Lund", "Umeahed", "Pori", "Vaasa", "Tampere", "Oulu",
    "Turku", "Espoo", "Jyvaskyla", "Lahti", "Kuopio", "Joensuu", "Rovaniemi", "Kemi",
    "Gdansk", "Gdynia", "Sopot", "Torun", "Lodz", "Poznan", "Wroclaw", "Krakow",
    "Lublin", "Bialystok", "Szczecin", "Katowice", "Bydgoszcz", "Rzeszow", "Olsztyn", "Opole",
    "Brno", "Plzen", "Ostrava", "Olomouc", "Liberec", "Pardubice", "Zlin", "Jihlava",
    "Graz", "Linz", "Salzburg", "Innsbruck", "Klagenfurt", "Villach", "Wels", "Dornbirn",
]


def _names(n: int) -> list[str]:
    out = []
    seen: set[str] = set()
    i = 0
    while len(out) < n:
        name = _STEMS[i % len(_STEMS)] + _TAILS[(i // len(_STEMS)) % len(_TAILS)]
        if name in seen:
            name = f"{name}{i}"
        seen.add(name)
        out.append(name)
        i += 1
    return out


def questions() -> list[dict]:
    """Value-level gold. The value string is not in the question."""
    names = _names(N_VERBATIM + N_SYNONYM)
    cities = _CITIES[:N_CROSS]
    if len(cities) != N_CROSS or len(set(cities)) != N_CROSS:
        raise RuntimeError(f"need {N_CROSS} unique cities, have {len(set(cities))}")
    rows: list[dict] = []
    for i, name in enumerate(names[:N_VERBATIM]):
        value = f"ZQ-R17-{i + 1:03d}"
        rows.append({
            "id": f"v-{i + 1:03d}",
            "style": "verbatim",
            "question": f"What is the audit reference for the {name} account?",
            "value": value,
            "file": "register.md",
        })
    for i, name in enumerate(names[N_VERBATIM:]):
        value = f"SPAN-R17-{i + 1:03d}"
        rows.append({
            "id": f"s-{i + 1:03d}",
            "style": "synonym",
            "question": f"How long are records kept for the {name} account?",
            "value": value,
            "file": "policy.html",
        })
    for i, city in enumerate(cities):
        value = f"AMT-R17-{i + 1:03d}"
        rows.append({
            "id": f"x-{i + 1:03d}",
            "style": "cross_file",
            "question": f"What is the penalty code for the account headquartered in {city}?",
            "value": value,
            "file": "ledger.xlsx",
            "desk": i + 1,
            "city": city,
        })
    if len(rows) < 200:
        raise RuntimeError(f"only {len(rows)} questions")
    values = [r["value"] for r in rows]
    if len(values) != len(set(values)):
        raise RuntimeError("gold values are not unique")
    for r in rows:
        if r["value"] in r["question"]:
            raise RuntimeError(f"value leaked into question {r['id']}")
    return rows


def _para(text: str) -> str:
    return f"<w:p><w:r><w:t xml:space=\"preserve\">{html.escape(text)}</w:t></w:r></w:p>"


def _write_docx(path: Path, paragraphs: list[str]) -> None:
    body = "".join(_para(t) for t in paragraphs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        z.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{body}</w:body></w:document>",
        )


def write_corpus(dest: Path | None = None) -> Path:
    """Write the archive next to this file (or under dest). Returns the directory."""
    dest = Path(dest) if dest else CORPUS
    dest.mkdir(parents=True, exist_ok=True)
    qs = questions()
    names = _names(N_VERBATIM + N_SYNONYM)
    verbatim = [r for r in qs if r["style"] == "verbatim"]
    synonym = [r for r in qs if r["style"] == "synonym"]
    cross = [r for r in qs if r["style"] == "cross_file"]

    reg = ["# Account register", "", "Internal audit references. Each account is one paragraph.", ""]
    for r, name in zip(verbatim, names[:N_VERBATIM]):
        reg.append(f"The audit reference for the {name} account is {r['value']}.")
        reg.append("")
    (dest / "register.md").write_text("\n".join(reg), encoding="utf-8")

    blocks = ["<h1>Retention policy</h1>"]
    for r, name in zip(synonym, names[N_VERBATIM:]):
        blocks.append(f"<p>The retention period for the {html.escape(name)} account is {r['value']}.</p>")
    (dest / "policy.html").write_text(
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>Retention</title></head><body>"
        + "".join(blocks) + "</body></html>\n",
        encoding="utf-8",
    )

    memo = ["# Headquarters desks", "", "Each city is filed under one desk. Amounts are not kept in this memo.", ""]
    for r in cross:
        memo.append(f"City {r['city']} maps to desk {r['desk']}.")
    (dest / "desks.md").write_text("\n".join(memo) + "\n", encoding="utf-8")

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lines"
    ws.append(["desk", "kind", "code"])
    rng = random.Random(17)
    for i in range(N_DISTRACTOR_ROWS):
        ws.append([5000 + i, "penalty", f"AMT-NOISE-{i + 1:04d}"])
    for r in cross:
        ws.append([r["desk"], "penalty", r["value"]])
    # A second sheet of unrelated freight codes, so the workbook is not one column.
    fr = wb.create_sheet("Freight")
    fr.append(["lane", "code"])
    for i in range(40):
        fr.append([rng.choice(["North", "South", "East", "West"]), f"FRT-NOISE-{i + 1:03d}"])
    wb.save(dest / "ledger.xlsx")

    noise = ["# Boilerplate", ""]
    for n in range(12):
        bits = [f"desk {d}" for d in range(1, N_CROSS + 1)]
        noise.append(
            f"Section {n + 1}. The penalty schedule mentions " + ", ".join(bits)
            + ". Penalty codes are looked up on the ledger, not copied here."
        )
        noise.append("")
    (dest / "noise.md").write_text("\n".join(noise), encoding="utf-8")

    _write_docx(dest / "cover.docx", [
        "Cover letter",
        "This letter confirms the archive was assembled for the retrieval bench.",
        "It names no account and it quotes no penalty code.",
        "Please use the register, the policy, the desk memo and the ledger.",
    ])

    from filetype_bench import pdf_bytes
    page = ["Penalty notice", "This page discusses penalty handling in general.",
            "It does not list AMT-R17 codes or ZQ-R17 codes or SPAN-R17 codes."]
    (dest / "notice.pdf").write_bytes(pdf_bytes([page]))

    (dest / "gold.json").write_text(json.dumps(qs, indent=2) + "\n", encoding="utf-8")
    return dest


def ndcg_at_10(rank: int | None) -> float:
    """Binary nDCG@10 with one relevant hit. rank is 0-based, or None if absent.

    Ideal DCG is 1 (the relevant hit at rank 1). A hit at 0-based rank r
    scores 1/log2(r+2). Outside the top 10 the score is 0. This is not success@k.
    """
    if rank is None or rank < 0 or rank >= 10:
        return 0.0
    return 1.0 / math.log2(rank + 2)


def run(corpus: Path | None = None, top_k: int = 10, depth: str = "high") -> dict:
    os.environ["AIRGPT_RAG_EMBED"] = "hash"
    import rag.store as store
    from rag import embed, index_fingerprint, ingest, retrieve

    corpus = Path(corpus) if corpus else CORPUS
    gold = json.loads((corpus / "gold.json").read_text(encoding="utf-8"))
    files = [corpus / name for name in (
        "register.md", "policy.html", "desks.md", "ledger.xlsx", "noise.md", "cover.docx", "notice.pdf",
    )]
    missing = [str(p) for p in files if not p.is_file()]
    if missing:
        raise SystemExit(f"corpus missing {missing}; run with --write-corpus")

    embed.reset_embedder_cache()
    saved = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        root = Path(tmp.name)
        store.RAG_DIR = root / "rag"
        store.DB_PATH = store.RAG_DIR / "rag.db"
        store.BLOB_DIR = store.RAG_DIR
        store.init()
        sid = int(store.create_space("real doc bench", depth_default="high")["id"])
        ing = ingest.ingest_paths(sid, [str(p) for p in files])
        if not ing.get("ok"):
            raise SystemExit(f"ingest failed: {ing}")

        by = {s: {"n": 0, "success_at_1": 0, "success_at_5": 0, "ndcg_at_10": 0.0} for s in
              ("verbatim", "synonym", "cross_file")}
        misses = {s: [] for s in by}
        ndcg_sum = 0.0
        s1 = s5 = 0
        for item in gold:
            hits = retrieve.search(sid, item["question"], depth=depth, top_k=top_k).get("hits") or []
            rank = next((i for i, h in enumerate(hits) if item["value"] in str(h.get("text") or "")), None)
            cell = by[item["style"]]
            cell["n"] += 1
            hit1 = rank == 0
            hit5 = rank is not None and rank < 5
            cell["success_at_1"] += int(hit1)
            cell["success_at_5"] += int(hit5)
            cell["ndcg_at_10"] += ndcg_at_10(rank)
            s1 += int(hit1)
            s5 += int(hit5)
            ndcg_sum += ndcg_at_10(rank)
            if not hit5 and len(misses[item["style"]]) < 3:
                misses[item["style"]].append(item["id"] + " " + item["question"])
        n = len(gold)
        for cell in by.values():
            cell["ndcg_at_10"] = round(cell["ndcg_at_10"] / max(1, cell["n"]), 4)
        return {
            "bench": "real_doc_bench",
            "n": n,
            "top_k": top_k,
            "depth": depth,
            "success_at_1": {"hit": s1, "n": n, "rate": round(s1 / n, 4)},
            "success_at_5": {"hit": s5, "n": n, "rate": round(s5 / n, 4)},
            "ndcg_at_10": round(ndcg_sum / n, 4),
            "by_style": by,
            "sample_misses": misses,
            "harder_than_paraphrase_success_at_5": s5 < n,
            "index_fingerprint": index_fingerprint.fingerprint(extra={"pack": "real_doc_bench"}),
            "metric_note": (
                "success_at_1 and success_at_5 count questions whose gold value string "
                "appears in the top 1 or top 5 hit texts. One gold value per question, "
                "so this is success@k, not set-recall. ndcg_at_10 is binary nDCG with "
                "one relevant hit (see ndcg_at_10 in this harness and rag/metrics.py). "
                "It is not success@k."
            ),
            "honesty": (
                "Retrieval only, hash embedder, committed documents under tests/RAG/real_docs, "
                "no model call. Gold is a value (a code), not merely that some passage was "
                "returned. cross_file asks for a code that is not in the memo the city "
                "appears in. Measures; rag/ was not tuned to this pack. A saturated "
                "success@5 would mean the pack is not harder than the paraphrase board."
            ),
        }
    finally:
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = saved
        embed.reset_embedder_cache()
        tmp.cleanup()


def render(res: dict) -> str:
    lines = [f"n={res['n']} success@1 {res['success_at_1']['hit']}/{res['n']} "
             f"success@5 {res['success_at_5']['hit']}/{res['n']} nDCG@10 {res['ndcg_at_10']}"]
    for style, cell in res["by_style"].items():
        lines.append(
            f"  {style:<12} @1 {cell['success_at_1']}/{cell['n']}  "
            f"@5 {cell['success_at_5']}/{cell['n']}  nDCG@10 {cell['ndcg_at_10']}"
        )
    lines.append("harder than saturated success@5: " + str(res["harder_than_paraphrase_success_at_5"]))
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-corpus", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if args.write_corpus:
        print(f"wrote {write_corpus()}")
        if args.no_write:
            raise SystemExit(0)
    res = run()
    print(render(res))
    if not args.no_write:
        from bench_stamp import write_json
        dest = Path(args.out) if args.out else RESULTS
        write_json(dest, res)
        print(f"wrote {dest}")

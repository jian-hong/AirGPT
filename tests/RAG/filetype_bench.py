"""Per-file-type retrieval bench: can a fact be found again, and is it cited to a place?

Every file type gets the same job. A fixture is generated with N planted facts
("The retention period for the Halvorsen account is ZQ-4471."), all types are
ingested into ONE space so they distract each other, and each fact is asked for
by name. No model is called: this scores ingest + retrieval, the part an answer
cannot recover from.

Per type it reports:
  ingested      the file produced chunks at all (else the stated reason)
  recall@1/@5   the value is in the top 1 / top 5 hits
  locator       the top hit holding the value names where it is (page, slide,
                sheet, section, function). Types with no natural place skip it.

Fixtures are written with the stdlib (zip + XML for docx/pptx, a hand-built PDF)
so the bench does not depend on the libraries it is judging.

    python tests/RAG/filetype_bench.py            # n=30 per type, writes results json
    python tests/RAG/filetype_bench.py --n 6      # quick
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import random
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULTS = Path(__file__).resolve().parent / "results" / "filetype_bench_latest.json"
GROUP = 5  # facts per page / slide / sheet / section

_ATTRS = [
    "retention period", "escalation code", "billing cycle", "renewal window",
    "audit reference", "support tier", "shipping lane", "discount band",
    "contract owner", "compliance tag",
]
_SYL = ["hal", "vor", "sen", "mik", "ado", "ren", "tas", "kel", "bru", "nim", "oph", "ula",
        "zer", "yth", "gan", "dov", "pim", "sar", "wex", "lon", "qui", "fen", "jor", "bax"]


@dataclass
class Fact:
    entity: str
    attr: str
    value: str
    group: int

    @property
    def sentence(self) -> str:
        return f"The {self.attr} for the {self.entity} account is {self.value}."

    @property
    def question(self) -> str:
        return f"What is the {self.attr} for the {self.entity} account?"


def make_facts(kind: str, n: int, seed: int = 1) -> list[Fact]:
    rng = random.Random(f"{kind}:{seed}")
    facts, seen = [], set()
    while len(facts) < n:
        entity = "".join(rng.sample(_SYL, 3)).capitalize()
        if entity in seen:
            continue
        seen.add(entity)
        i = len(facts)
        value = f"{rng.choice('BCDFGHJKLMNPQRSTVWXZ')}{rng.choice('BCDFGHJKLMNPQRSTVWXZ')}-{rng.randint(1000, 9999)}{i:02d}"
        facts.append(Fact(entity, _ATTRS[i % len(_ATTRS)], value, i // GROUP))
    return facts


def _groups(facts: list[Fact]) -> list[list[Fact]]:
    out: list[list[Fact]] = []
    for f in facts:
        while len(out) <= f.group:
            out.append([])
        out[f.group].append(f)
    return out


# --- fixture writers: (path, facts) -> {entity: expected locator text or None} ---

def w_txt(p: Path, facts):
    p.write_text("\n\n".join(f.sentence for f in facts), encoding="utf-8")
    return {}


def w_md(p: Path, facts):
    parts = ["# Account register"]
    for g, fs in enumerate(_groups(facts)):
        parts.append(f"## Region {g + 1} accounts\n\n" + "\n\n".join(f.sentence for f in fs))
    p.write_text("\n\n".join(parts), encoding="utf-8")
    return {f.entity: f"Region {f.group + 1} accounts" for f in facts}


def w_html(p: Path, facts):
    body = "".join(
        f"<h2>Region {g + 1} accounts</h2>" + "".join(f"<p>{escape(f.sentence)}</p>" for f in fs)
        for g, fs in enumerate(_groups(facts))
    )
    p.write_text(
        "<html><head><title>Account register</title><style>p{color:red}</style></head>"
        f"<body><nav>Home | About</nav>{body}<script>var x=1;</script></body></html>",
        encoding="utf-8",
    )
    return {f.entity: f"Region {f.group + 1} accounts" for f in facts}


def w_json(p: Path, facts):
    p.write_text(
        json.dumps({"accounts": [{"account": f.entity, f.attr.replace(" ", "_"): f.value} for f in facts]}, indent=1),
        encoding="utf-8",
    )
    return {}


def w_csv(p: Path, facts):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["account", "attribute", "value"])
    for f in facts:
        w.writerow([f.entity, f.attr, f.value])
    p.write_text(buf.getvalue(), encoding="utf-8")
    return {}


def w_xlsx(p: Path, facts):
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for g, fs in enumerate(_groups(facts)):
        ws = wb.create_sheet(f"Region{g + 1}")
        ws.append(["account", "attribute", "value"])
        for f in fs:
            ws.append([f.entity, f.attr, f.value])
    wb.save(p)
    return {f.entity: f"Region{f.group + 1}" for f in facts}


def w_py(p: Path, facts):
    p.write_text(
        '"""Account lookups."""\n\n'
        + "\n\n".join(
            f'def lookup_{f.entity.lower()}():\n    """{f.sentence}"""\n    return "{f.value}"\n' for f in facts
        ),
        encoding="utf-8",
    )
    return {f.entity: f"lookup_{f.entity.lower()}" for f in facts}


def w_eml(p: Path, facts):
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = "ops@example.com"
    msg["To"] = "desk@example.com"
    msg["Subject"] = "Quarterly account register"
    msg["Date"] = "Mon, 02 Mar 2026 09:00:00 +0000"
    msg.set_content("Hello,\n\n" + "\n\n".join(f.sentence for f in facts) + "\n\nRegards")
    msg.add_alternative("<html><body>" + "".join(f"<p>{escape(f.sentence)}</p>" for f in facts) + "</body></html>",
                        subtype="html")
    p.write_bytes(msg.as_bytes())
    return {f.entity: "Quarterly account register" for f in facts}


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def w_docx(p: Path, facts):
    """Headings carry the section. Odd groups hold their facts in a table."""
    def para(text, style=None):
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        return f"<w:p>{ppr}<w:r><w:t xml:space=\"preserve\">{escape(text)}</w:t></w:r></w:p>"

    body = [para("Account register", "Title")]
    for g, fs in enumerate(_groups(facts)):
        body.append(para(f"Region {g + 1} accounts", "Heading1"))
        if g % 2:
            rows = "".join(
                "<w:tr>" + "".join(f"<w:tc>{para(c)}</w:tc>" for c in (f.entity, f.attr, f.value)) + "</w:tr>"
                for f in fs
            )
            body.append(f"<w:tbl>{rows}</w:tbl>")
        else:
            body.extend(para(f.sentence) for f in fs)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="xml" ContentType="application/xml"/></Types>')
        z.writestr("word/document.xml", f'<w:document xmlns:w="{_W}"><w:body>{"".join(body)}</w:body></w:document>')
    return {f.entity: f"Region {f.group + 1} accounts" for f in facts}


_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/package/2006/relationships"


def w_pptx(p: Path, facts):
    """One slide per group. The last fact of each slide lives only in speaker notes,
    and notes files are numbered in reverse so only the slide's .rels can pair them."""
    def shape(lines):
        return "".join(f"<a:p><a:r><a:t>{escape(t)}</a:t></a:r></a:p>" for t in lines)

    groups = _groups(facts)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="xml" ContentType="application/xml"/></Types>')
        for g, fs in enumerate(groups):
            n, note_n = g + 1, len(groups) - g
            z.writestr(f"ppt/slides/slide{n}.xml",
                       f'<p:sld xmlns:p="{_P}" xmlns:a="{_A}"><p:txBody>'
                       f'{shape([f"Region {n} accounts"] + [f.sentence for f in fs[:-1]])}</p:txBody></p:sld>')
            z.writestr(f"ppt/slides/_rels/slide{n}.xml.rels",
                       f'<Relationships xmlns="{_R}"><Relationship Id="rId1" '
                       'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" '
                       f'Target="../notesSlides/notesSlide{note_n}.xml"/></Relationships>')
            z.writestr(f"ppt/notesSlides/notesSlide{note_n}.xml",
                       f'<p:notes xmlns:p="{_P}" xmlns:a="{_A}"><p:txBody>{shape([fs[-1].sentence])}</p:txBody></p:notes>')
    return {f.entity: f"Slide {f.group + 1}" for f in facts}


def w_tsv(p: Path, facts):
    p.write_text("account\tattribute\tvalue\n" + "\n".join(f"{f.entity}\t{f.attr}\t{f.value}" for f in facts),
                 encoding="utf-8")
    return {}


def w_xml(p: Path, facts):
    """Regions of account records. The place is the element path."""
    regions = "".join(
        f'<region name="Region {g + 1} accounts">'
        + "".join(
            f"<account><name>{f.entity}</name><attribute>{escape(f.attr)}</attribute><value>{f.value}</value></account>"
            for f in fs
        )
        + "</region>"
        for g, fs in enumerate(_groups(facts))
    )
    p.write_text(f'<?xml version="1.0" encoding="utf-8"?><register>{regions}</register>', encoding="utf-8")
    return {f.entity: f"region[{f.group + 1}]" for f in facts}


def w_log(p: Path, facts):
    """One day per group. Every third fact sits in an ERROR record whose stack trace
    follows it, so the record has to stay in one piece to be found."""
    lines = []
    for i, f in enumerate(facts):
        day = f"2026-03-{f.group + 1:02d}"
        stamp = f"{day} 09:{i % 60:02d}:00"
        if i % 3 == 2:
            lines += [f"{stamp} ERROR billing.worker {f.sentence}",
                      "Traceback (most recent call last):",
                      '  File "worker.py", line 42, in run',
                      "    raise LookupError(code)",
                      "LookupError: stale"]
        else:
            lines.append(f"{stamp} INFO billing.worker {f.sentence}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {f.entity: f"2026-03-{f.group + 1:02d}" for f in facts}


def w_ipynb(p: Path, facts):
    """A markdown heading cell per group; even groups state facts in markdown, odd
    groups in a code cell (with a comment line) and an output that repeats them."""
    cells = []
    for g, fs in enumerate(_groups(facts)):
        cells.append({"cell_type": "markdown", "metadata": {}, "source": [f"## Region {g + 1} accounts\n"]})
        if g % 2:
            src = "# lookup table\n" + "\n".join(f'print("{f.sentence}")' for f in fs)
            cells.append({"cell_type": "code", "metadata": {}, "execution_count": g, "source": src.splitlines(True),
                          "outputs": [{"output_type": "stream", "name": "stdout", "text": ["done\n"]}]})
        else:
            cells.append({"cell_type": "markdown", "metadata": {}, "source": ["\n\n".join(f.sentence for f in fs)]})
    p.write_text(json.dumps({"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}), encoding="utf-8")
    return {f.entity: f"Region {f.group + 1} accounts" for f in facts}


def w_rtf(p: Path, facts):
    paras = "".join("\\pard " + f.sentence + "\\par\n" for f in facts)
    p.write_text("{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Times New Roman;}}{\\colortbl;\\red0\\green0\\blue0;}"
                 "{\\*\\generator Hand 1.0;}\\f0\\fs24 Account register\\par\n" + paras + "}", encoding="utf-8")
    return {}


def pdf_bytes(pages: list[list[str]]) -> bytes:
    """A text PDF, one list of lines per page, written by hand (no PDF library)."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    objs: list[bytes] = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        stream = "BT /F1 11 Tf 50 760 Td 16 TL " + " ".join(f"({esc(t)}) Tj T*" for t in lines) + " ET"
        data = stream.encode("latin-1")
        objs.append(b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream")
        content_no = len(objs)
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_no)
        kids.append(len(objs))
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def w_pdf(p: Path, facts):
    """One page per group."""
    p.write_bytes(pdf_bytes(
        [[f"Region {g + 1} accounts"] + [f.sentence for f in fs] for g, fs in enumerate(_groups(facts))]
    ))
    return {f.entity: f"Page {f.group + 1}" for f in facts}


TYPES = {
    "txt": w_txt, "md": w_md, "html": w_html, "json": w_json, "csv": w_csv, "xlsx": w_xlsx,
    "py": w_py, "docx": w_docx, "pptx": w_pptx, "pdf": w_pdf, "eml": w_eml,
    "tsv": w_tsv, "xml": w_xml, "log": w_log, "ipynb": w_ipynb, "rtf": w_rtf,
}


def space_groups(kinds: list[str]) -> list[list[str]]:
    """One shared space, so every type distracts every other."""
    return [kinds]


def run(n: int = 30, seed: int = 1, top_k: int = 5, types: list[str] | None = None) -> dict:
    """Generate, ingest per space group (see CORE_TYPES), ask every fact. Returns the scoreboard."""
    os.environ["AIRGPT_RAG_EMBED"] = "hash"  # deterministic, offline
    import rag.store as store
    from rag import embed, index_fingerprint, ingest, retrieve

    embed.reset_embedder_cache()
    saved = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        root = Path(tmp.name)
        store.RAG_DIR = root / "rag"
        store.DB_PATH = store.RAG_DIR / "rag.db"
        store.BLOB_DIR = store.RAG_DIR
        store.init()
        board: dict[str, dict] = {}
        for gi, kinds in enumerate(space_groups(types or list(TYPES))):
            sid = int(store.create_space(f"filetype bench {gi}", depth_default="high")["id"])
            corpus = root / f"corpus{gi}"
            corpus.mkdir()
            plan: dict[str, tuple[list[Fact], dict]] = {}
            for kind in kinds:
                facts = make_facts(kind, n, seed)
                path = corpus / f"register_{kind}.{kind}"
                plan[kind] = (facts, TYPES[kind](path, facts))

            out = ingest.ingest_paths(sid, [corpus / f"register_{k}.{k}" for k in plan])
            skipped = {Path(s["path"]).suffix.lstrip("."): s["reason"] for s in out.get("skipped") or []}
            indexed = {Path(str(s.get("title") or s.get("path") or "")).suffix.lstrip(".")
                       for s in store.list_sources(sid)}

            for kind, (facts, locators) in plan.items():
                row = {"n": len(facts), "ingested": kind not in skipped, "reason": skipped.get(kind, ""),
                       "recall_at_1": 0, "recall_at_5": 0, "locator_n": 0, "locator_ok": 0, "misses": []}
                if row["ingested"] and kind not in indexed and not row["reason"]:
                    row["ingested"], row["reason"] = False, "not accepted by ingest (unsupported type)"
                for f in facts:
                    hits = retrieve.search(sid, f.question, depth="high", top_k=top_k).get("hits") or []
                    rank = next((i for i, h in enumerate(hits) if f.value in str(h.get("text") or "")), None)
                    if rank is None:
                        row["misses"].append(f.question)
                        continue
                    row["recall_at_5"] += 1
                    row["recall_at_1"] += int(rank == 0)
                    want = locators.get(f.entity)
                    if want:
                        row["locator_n"] += 1
                        row["locator_ok"] += int(want.lower() in str(hits[rank].get("heading") or "").lower())
                row["misses"] = row["misses"][:3]
                board[kind] = row
        return {
            "bench": "filetype_bench",
            "n_per_type": n, "seed": seed, "top_k": top_k,
            "n_total": sum(r["n"] for r in board.values()),
            "index_fingerprint": index_fingerprint.fingerprint(extra={"pack": "filetype_bench"}),
            "honesty": "retrieval only, hash embedder, synthetic facts, no model call. "
                       "Counts, not rates: n per type is too small to claim zero error.",
            "types": board,
        }
    finally:
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = saved
        embed.reset_embedder_cache()
        tmp.cleanup()


def render(result: dict) -> str:
    lines = [f"{'type':<6} {'ingest':<7} {'r@1':>7} {'r@5':>7} {'locator':>9}  reason"]
    for kind, r in result["types"].items():
        loc = f"{r['locator_ok']}/{r['locator_n']}" if r["locator_n"] else "-"
        lines.append(f"{kind:<6} {'yes' if r['ingested'] else 'NO':<7} {r['recall_at_1']:>4}/{r['n']:<2} "
                     f"{r['recall_at_5']:>4}/{r['n']:<2} {loc:>9}  {r['reason']}")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    res = run(args.n, args.seed)
    print(render(res))
    if not args.no_write:
        from bench_stamp import write_json
        dest = Path(args.out) if args.out else RESULTS
        write_json(dest, res, retrieval=True)
        print(f"wrote {dest}")

"""Multilingual retrieval + offline-answer bench: no embedding model, one shared space.

Same shape as filetype_bench.py. For each language 30 planted facts are written in
that language's own words (hand-built sentence templates) and spread over four file
types (md, docx, pdf, xlsx). All languages are ingested into ONE space, together with
20 look-alike distractor facts per language (same sentence, same attribute, a name
that differs from a real one by a single character or syllable), so the languages
and the near-duplicates distract each other.

Each fact is asked three ways:
  a  own language, full question            "<name>客户的保留期限是什么？"
  b  own language, name only                "<name>客户的情况"
  c  ENGLISH question about the non-English document
     Needs a cross-language embedder. Nothing here has one (parked as P13), so
     this is a NAMED WEAKNESS with a deliberately weak floor, not a target.

Scored per language and style: recall@1, recall@5 (the value is in the top hits),
the top hit holding the value names its place (locator), and whether the offline
answer (rag.answer.extractive_answer) contains the value. Per language, 10
unanswerable questions (5 about a name the space never mentions, 5 about an
attribute nobody recorded for a name that exists) score whether the offline answer
abstains. Answerable questions that get an abstention count as false abstentions.

Hindi is NOT in the board: rag.sira.tokenize drops Devanagari entirely (vowel signs
are not alphabetic, so every run is shorter than 2 and is discarded). See
tokenizer_gaps in the output.

PDF: the hand-written writer in filetype_bench.py is Latin-1 only. Here the PDF is a
Type0 / Identity-H font with a ToUnicode map, also written by hand, so the text layer
carries any script and pypdf reads it back the way a real PDF reader would.

    python tests/RAG/multilingual_bench.py            # n=30 per language, writes json
    python tests/RAG/multilingual_bench.py --n 8      # quick
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULTS = Path(__file__).resolve().parent / "results" / "multilingual_bench_latest.json"
GROUP = 4  # facts per section / page / sheet inside one file
N_DISTRACTORS = 20
N_UNANSWERABLE = 10
FORMATS = ["md", "docx", "pdf", "xlsx"]
# pypdf 6.17 (what rag.ingest uses) drops the text of a line whose direction changes
# (Arabic then a Latin code). Arabic facts therefore skip pdf here; the loss itself is
# measured live by pdf_rtl_probe() so it stays on the board instead of hiding.
NO_FORMAT = {("ar", "pdf")}

ATTRS_EN = [
    "retention period", "escalation code", "billing cycle", "renewal window",
    "audit reference", "support tier", "shipping lane", "discount band",
    "contract owner", "compliance tag",
]


def _hangul_topic(word: str) -> str:
    """은 after a final consonant, 는 after a vowel."""
    last = word[-1]
    return "은" if 0xAC00 <= ord(last) <= 0xD7A3 and (ord(last) - 0xAC00) % 28 else "는"


@dataclass(frozen=True)
class Lang:
    code: str
    parts: list          # one pool per position of a name
    join: str
    attrs: list          # the ten attributes in the language's words, same order as ATTRS_EN
    absent: str          # an attribute nobody records (the mascot)
    section: str         # the word for "region", used in headings
    header: tuple        # xlsx column headers
    fact: str            # {e} {a} {v}
    ask: str             # {e} {a}
    about: str           # {e}
    cap: bool = False    # capitalise names (Latin scripts)


def _syl(s: str) -> list:
    return s.split()


LANGS: dict[str, Lang] = {
    "zh": Lang("zh", [list("华兴盛达远东恒信瑞丰泰宏林海安康明德伟建国志强文杰")] * 3, "",
               ["保留期限", "升级代码", "结算周期", "续约窗口", "审计编号", "支持等级", "运输线路", "折扣档位", "合同负责人", "合规标签"],
               "公司吉祥物", "区域", ("客户", "属性", "值"),
               "{e}客户的{a}是{v}。", "{e}客户的{a}是什么？", "{e}客户的情况"),
    "ja": Lang("ja", [list("アカサタナハマラヤコセテノヒミリケユスチトニフホムルレロ")] * 4, "",
               ["保存期間", "エスカレーションコード", "請求サイクル", "更新期間", "監査番号", "サポート階層", "配送ルート", "割引区分", "契約担当者", "コンプライアンスタグ"],
               "マスコット", "地域", ("お客様", "項目", "値"),
               "{e}のお客様の{a}は{v}です。", "{e}のお客様の{a}は何ですか？", "{e}のお客様について教えてください。"),
    "ko": Lang("ko", [list("한국민서준하윤지우도현수아태영진혜소은재승경호미")] * 3, "",
               ["보존 기간", "에스컬레이션 코드", "청구 주기", "갱신 기간", "감사 번호", "지원 등급", "배송 노선", "할인 구간", "계약 담당자", "규정 준수 태그"],
               "마스코트", "지역", ("고객", "항목", "값"),
               "{e} 고객의 {a}{t} {v}입니다.", "{e} 고객의 {a}{t} 무엇입니까?", "{e} 고객에 대해 알려 주세요."),
    "ar": Lang("ar", [_syl("سالم خالد يوسف منصور فيصل عادل ناصر ماجد وليد طارق سعيد هاشم"),
                      _syl("الراشد الحربي القحطاني العتيبي الزهراني الغامدي الشمري المطيري الدوسري السبيعي البلوي الخالدي")], " ",
               ["مدة الاحتفاظ", "رمز التصعيد", "دورة الفوترة", "فترة التجديد", "مرجع التدقيق", "مستوى الدعم", "مسار الشحن", "فئة الخصم", "مالك العقد", "وسم الامتثال"],
               "تميمة الشركة", "المنطقة", ("العميل", "السمة", "القيمة"),
               "{a} للعميل {e} هو {v}.", "ما هو {a} للعميل {e}؟", "معلومات عن العميل {e}"),
    "th": Lang("th", [_syl("สม ชาย มา นี วัน ดี สุข จิต ใจ รัก ทอง คำ พร นก ปราณ เพ็ญ แก้ว ศรี บุญ")] * 3, "",
               ["ระยะเวลาการเก็บรักษา", "รหัสการยกระดับ", "รอบการเรียกเก็บเงิน", "ช่วงเวลาต่ออายุ", "หมายเลขอ้างอิงการตรวจสอบ", "ระดับการสนับสนุน", "เส้นทางการจัดส่ง", "ช่วงส่วนลด", "ผู้รับผิดชอบสัญญา", "ป้ายการปฏิบัติตามข้อกำหนด"],
               "มาสคอตของบริษัท", "ภูมิภาค", ("ลูกค้า", "หัวข้อ", "ค่า"),
               "{a}ของลูกค้า {e} คือ {v}", "{a}ของลูกค้า {e} คืออะไร", "ข้อมูลของลูกค้า {e}"),
    "ru": Lang("ru", [_syl("Бел Ков Мор Зар Лев Тар Гор Сав Пет Ник Дан Фил Рог Хол Куз Шир"), _syl("ов ин ский енко ук ев ич")], "",
               ["срок хранения", "код эскалации", "цикл выставления счетов", "окно продления", "ссылка на аудит", "уровень поддержки", "маршрут доставки", "категория скидки", "владелец договора", "метка соответствия"],
               "талисман компании", "Регион", ("Клиент", "Поле", "Значение"),
               "Для клиента {e} значение поля «{a}» — {v}.", "Что указано в поле «{a}» для клиента {e}?", "Расскажите о клиенте {e}."),
    "ms": Lang("ms", [_syl("hal vor sen mik ado ren tas kel bru nim oph ula zer yth gan dov")] * 3, "",
               ["tempoh pengekalan", "kod peningkatan", "kitaran pengebilan", "tempoh pembaharuan", "rujukan audit", "tahap sokongan", "laluan penghantaran", "jalur diskaun", "pemilik kontrak", "tag pematuhan"],
               "maskot syarikat", "Wilayah", ("Akaun", "Atribut", "Nilai"),
               "{A} bagi akaun {e} ialah {v}.", "Apakah {a} bagi akaun {e}?", "Maklumat tentang akaun {e}", cap=True),
    "es": Lang("es", [_syl("pal mon ter sab lor fen cas dir gue nol bar tiv")] * 3, "",
               ["el periodo de retención", "el código de escalamiento", "el ciclo de facturación", "la ventana de renovación", "la referencia de auditoría", "el nivel de soporte", "la ruta de envío", "la banda de descuento", "el responsable del contrato", "la etiqueta de cumplimiento"],
               "la mascota de la empresa", "Región", ("Cuenta", "Atributo", "Valor"),
               "{A} de la cuenta {e} es {v}.", "¿Cuál es {a} de la cuenta {e}?", "Información sobre la cuenta {e}", cap=True),
}


def render(lang: Lang, tpl: str, e: str, a: str = "", v: str = "") -> str:
    return tpl.format(e=e, a=a, A=a[:1].upper() + a[1:], v=v, t=_hangul_topic(a) if a else "")


@dataclass
class Fact:
    lang: str
    entity: str
    attr: str          # in the language's words
    attr_en: str
    value: str
    fmt: str
    group: int         # 1-based section / page / sheet inside its file

    def sentence(self) -> str:
        return render(LANGS[self.lang], LANGS[self.lang].fact, self.entity, self.attr, self.value)

    def q_own(self) -> str:
        return render(LANGS[self.lang], LANGS[self.lang].ask, self.entity, self.attr)

    def q_name(self) -> str:
        return render(LANGS[self.lang], LANGS[self.lang].about, self.entity)

    def q_en(self) -> str:
        return f"What is the {self.attr_en} for the {self.entity} account?"

    def locator(self) -> str:
        sec = LANGS[self.lang].section
        return {"md": f"{sec} {self.group}", "docx": f"{sec} {self.group}",
                "pdf": f"Page {self.group}", "xlsx": f"{sec}{self.group}"}[self.fmt]


def _name(lang: Lang, rng: random.Random, parts=None) -> str:
    picks = parts or [rng.choice(p) for p in lang.parts]
    n = lang.join.join(picks)
    return n.capitalize() if lang.cap else n


def _entities(lang: Lang, n_fact: int, n_dist: int, n_unans: int, seed: int):
    """Facts' names, look-alike names (one position changed) and unseen names."""
    rng = random.Random(f"{lang.code}:{seed}")
    used: set[str] = set()

    def fresh(make):
        for _ in range(10000):
            parts, name = make()
            if name not in used:
                used.add(name)
                return parts, name
        raise RuntimeError("name pool too small")

    def rand():
        parts = [rng.choice(p) for p in lang.parts]
        return parts, _name(lang, rng, parts)

    real = [fresh(rand) for _ in range(n_fact)]

    def mutate_of(i):
        def make():
            parts = list(real[i % len(real)][0])
            pos = rng.randrange(len(parts))
            parts[pos] = rng.choice([x for x in lang.parts[pos] if x != parts[pos]])
            return parts, _name(lang, rng, parts)
        return make

    dist = [fresh(mutate_of(i))[1] for i in range(n_dist)]
    unans = [fresh(rand)[1] for _ in range(n_unans)]
    return [n for _, n in real], dist, unans


def make_facts(code: str, n: int, seed: int = 1):
    lang = LANGS[code]
    rng = random.Random(f"value:{code}:{seed}")
    names, dist_names, unans = _entities(lang, n, N_DISTRACTORS, N_UNANSWERABLE, seed)
    facts: list[Fact] = []
    fmts = [f for f in FORMATS if (code, f) not in NO_FORMAT]
    per_fmt = {f: 0 for f in FORMATS}
    for i, name in enumerate(names):
        fmt = fmts[i % len(fmts)]
        pos = per_fmt[fmt]
        per_fmt[fmt] += 1
        value = f"{rng.choice('BCDFGHJKLMNPQRSTVWXZ')}{rng.choice('BCDFGHJKLMNPQRSTVWXZ')}-{rng.randint(1000, 9999)}{i:02d}"
        facts.append(Fact(code, name, lang.attrs[i % 10], ATTRS_EN[i % 10], value, fmt, pos // GROUP + 1))
    distractors = []
    for j, name in enumerate(dist_names):
        value = f"{rng.choice('BCDFGHJKLMNPQRSTVWXZ')}{rng.choice('BCDFGHJKLMNPQRSTVWXZ')}-{rng.randint(1000, 9999)}9{j:02d}"
        distractors.append(Fact(code, name, lang.attrs[j % 10], ATTRS_EN[j % 10], value, "md", 1))
    return facts, distractors, unans


# --- writers ---------------------------------------------------------------------

def _groups(facts: list[Fact]) -> list[list[Fact]]:
    out: list[list[Fact]] = []
    for f in facts:
        while len(out) < f.group:
            out.append([])
        out[f.group - 1].append(f)
    return out


def w_md(p: Path, facts: list[Fact], code: str):
    sec = LANGS[code].section
    parts = []
    for g, fs in enumerate(_groups(facts), 1):
        parts.append(f"## {sec} {g}\n\n" + "\n\n".join(f.sentence() for f in fs))
    p.write_text("\n\n".join(parts), encoding="utf-8")


def w_distractors(p: Path, facts: list[Fact], code: str):
    p.write_text("# " + LANGS[code].section + "\n\n" + "\n\n".join(f.sentence() for f in facts), encoding="utf-8")


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def w_docx(p: Path, facts: list[Fact], code: str):
    lang = LANGS[code]

    def para(text, style=None):
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'

    body = []
    for g, fs in enumerate(_groups(facts), 1):
        body.append(para(f"{lang.section} {g}", "Heading1"))
        if g % 2 == 0:
            rows = "".join(
                "<w:tr>" + "".join(f"<w:tc>{para(c)}</w:tc>" for c in (f.entity, f.attr, f.value)) + "</w:tr>"
                for f in fs
            )
            body.append(f"<w:tbl>{rows}</w:tbl>")
        else:
            body.extend(para(f.sentence()) for f in fs)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="xml" ContentType="application/xml"/></Types>')
        z.writestr("word/document.xml", f'<w:document xmlns:w="{_W}"><w:body>{"".join(body)}</w:body></w:document>')


def w_xlsx(p: Path, facts: list[Fact], code: str):
    import openpyxl

    lang = LANGS[code]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for g, fs in enumerate(_groups(facts), 1):
        ws = wb.create_sheet(f"{lang.section}{g}")
        ws.append(list(lang.header))
        for f in fs:
            ws.append([f.entity, f.attr, f.value])
    wb.save(p)


def unicode_pdf_bytes(pages: list[list[str]]) -> bytes:
    """A text PDF whose font is Type0 / Identity-H with a ToUnicode CMap, so the
    text layer holds any script. Each distinct character gets the next 2-byte code;
    the CMap maps the code back to the character, which is what pypdf reads."""
    codes: dict[str, int] = {}

    def hexstr(s: str) -> str:
        return "<" + "".join(f"{codes.setdefault(ch, len(codes) + 1):04X}" for ch in s) + ">"

    def runs(line: str) -> list[str]:
        """Right-to-left text is stored in visual order, one string per direction run,
        the way a real producer writes it. pypdf puts a right-to-left run back into
        reading order, and drops whatever came before a direction change inside one
        string, so a logical-order string would lose its Arabic."""
        out: list[str] = []
        for part in re.findall(r"[\u0590-\u08FF][\u0590-\u08FF\s]*|[^\u0590-\u08FF]+", line):
            rtl = "\u0590" <= part.lstrip()[:1] <= "\u08FF" if part.strip() else False
            out.append(part[::-1] if rtl else part)
        return out

    streams = []
    for lines in pages:
        body = " ".join("".join(f"{hexstr(r)} Tj " for r in runs(t)) + "T*" for t in lines)
        streams.append("BT /F1 11 Tf 50 760 Td 16 TL " + body + " ET")
    bf = "".join(f"<{c:04X}> <{ord(ch):04X}>\n" for ch, c in codes.items() if ord(ch) <= 0xFFFF)
    cmap = ("/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
            "/CMapName /Adobe-Identity-UCS def /CMapType 2 def\n"
            "1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
            f"{len(bf.splitlines())} beginbfchar\n{bf}endbfchar\nendcmap end end").encode("ascii")

    def stream(b: bytes) -> bytes:
        return b"<< /Length %d >>\nstream\n" % len(b) + b + b"\nendstream"

    # 1 catalog, 2 pages, 3 Type0 font, 4 CID font, 5 ToUnicode, then page pairs
    objs: list[bytes] = [b"", b"",
                         b"<< /Type /Font /Subtype /Type0 /BaseFont /AirGPTSans /Encoding /Identity-H "
                         b"/DescendantFonts [4 0 R] /ToUnicode 5 0 R >>",
                         b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /AirGPTSans /CIDToGIDMap /Identity "
                         b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /DW 600 >>",
                         stream(cmap)]
    kids = []
    for s in streams:
        objs.append(stream(s.encode("ascii")))
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


def w_pdf(p: Path, facts: list[Fact], code: str):
    p.write_bytes(unicode_pdf_bytes([[f.sentence() for f in fs] for fs in _groups(facts)]))


def pdf_rtl_probe(tmpdir: Path) -> dict:
    """Does Arabic followed by a Latin code on one PDF line survive rag.ingest?"""
    from rag import ingest

    p = tmpdir / "rtl_probe.pdf"
    p.write_bytes(unicode_pdf_bytes([["مدة الاحتفاظ للعميل خالد هو SQ-7911."]]))
    got = ingest._pdf_text(p)
    return {"arabic_survives": "الاحتفاظ" in got or "ظافتحالا" in got, "code_survives": "SQ-7911" in got,
            "extracted": got[:80]}


WRITERS = {"md": w_md, "docx": w_docx, "pdf": w_pdf, "xlsx": w_xlsx}


# --- scoring ---------------------------------------------------------------------

def _score_style(sid, facts, style, ask, top_k, retrieve, answer):
    row = {"n": len(facts), "recall_at_1": 0, "recall_at_5": 0, "answer_has_value": 0,
           "false_abstain": 0, "false_warn": 0, "locator_n": 0, "locator_ok": 0, "misses": []}
    for f in facts:
        q = ask(f)
        hits = retrieve.search(sid, q, depth="high", top_k=top_k).get("hits") or []
        rank = next((i for i, h in enumerate(hits) if f.value in str(h.get("text") or "")), None)
        if rank is not None:
            row["recall_at_5"] += 1
            row["recall_at_1"] += int(rank == 0)
            row["locator_n"] += 1
            row["locator_ok"] += int(f.locator().lower() in str(hits[rank].get("heading") or "").lower())
        else:
            row["misses"].append(q)
        if hits:
            if answer.abstention(q, hits):
                row["false_abstain"] += 1
            row["false_warn"] += int(bool(answer.unseen_terms_note(q, hits)))
            row["answer_has_value"] += int(f.value in answer.extractive_answer(q, hits))
    row["misses"] = row["misses"][:3]
    return row


def run(n: int = 30, seed: int = 1, top_k: int = 5, langs: list[str] | None = None) -> dict:
    os.environ["AIRGPT_RAG_EMBED"] = "hash"  # deterministic, offline
    import rag.store as store
    from rag import answer, embed, index_fingerprint, ingest, retrieve, sira

    embed.reset_embedder_cache()
    saved = (store.RAG_DIR, store.DB_PATH, store.BLOB_DIR)
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        root = Path(tmp.name)
        store.RAG_DIR = root / "rag"
        store.DB_PATH = store.RAG_DIR / "rag.db"
        store.BLOB_DIR = store.RAG_DIR
        store.init()
        sid = int(store.create_space("multilingual bench", depth_default="high")["id"])
        corpus = root / "corpus"
        corpus.mkdir()
        plan: dict[str, tuple[list[Fact], list[str]]] = {}
        paths = []
        for code in langs or list(LANGS):
            facts, dist, unans = make_facts(code, n, seed)
            plan[code] = (facts, unans)
            for fmt in FORMATS:
                mine = [f for f in facts if f.fmt == fmt]
                if mine:
                    path = corpus / f"register_{code}.{fmt}"
                    WRITERS[fmt](path, mine, code)
                    paths.append(path)
            path = corpus / f"lookalikes_{code}.md"
            w_distractors(path, dist, code)
            paths.append(path)
        out = ingest.ingest_paths(sid, paths)
        skipped = {Path(s["path"]).name: s["reason"] for s in out.get("skipped") or []}

        board: dict[str, dict] = {}
        for code, (facts, unans) in plan.items():
            lang = LANGS[code]
            row = {"n": len(facts), "skipped": {k: v for k, v in skipped.items() if f"_{code}." in k}}
            row["a_own"] = _score_style(sid, facts, "a", lambda f: f.q_own(), top_k, retrieve, answer)
            row["b_name"] = _score_style(sid, facts, "b", lambda f: f.q_name(), top_k, retrieve, answer)
            row["c_english"] = _score_style(sid, facts, "c", lambda f: f.q_en(), top_k, retrieve, answer)
            qs = [render(lang, lang.ask, e, lang.attrs[i % 10]) for i, e in enumerate(unans[: N_UNANSWERABLE // 2])]
            qs += [render(lang, lang.ask, f.entity, lang.absent) for f in facts[: N_UNANSWERABLE - len(qs)]]
            abst, warned, missed = 0, 0, []
            for q in qs:
                hits = retrieve.search(sid, q, depth="high", top_k=top_k).get("hits") or []
                if not hits or answer.abstention(q, hits):
                    abst += 1
                elif answer.unseen_terms_note(q, hits):
                    warned += 1  # answered, but told the user a word was not found
                else:
                    missed.append(q)
            row["unanswerable"] = {"n": len(qs), "abstained": abst, "warned": warned, "missed": missed[:3]}
            board[code] = row
        gaps = {"pdf_rtl": pdf_rtl_probe(root)}
        fp = index_fingerprint.fingerprint(extra={"pack": "multilingual_bench"})
        return {
            "bench": "multilingual_bench",
            "n_per_language": n, "seed": seed, "top_k": top_k,
            "n_distractors_per_language": N_DISTRACTORS,
            "index_fingerprint": fp,
            "ingest_gaps": gaps,
            "tokenizer_gaps": {"hi": "rag.sira.tokenize returns no tokens for Devanagari: "
                                     f"{sira.tokenize('किताब का नाम है')!r}; not in this board"},
            "honesty": "retrieval + offline extractive answer only, hash embedder, synthetic facts "
                       "in hand-written templates, no model call. Style c (English question about a "
                       "non-English document) keeps the entity name in its own script, so it finds the "
                       "passage by the name; it does NOT test an English paraphrase of the content, "
                       "which needs a cross-language embedder (P13) and is a named weakness. Counts, not rates: n per language is too small to claim zero error; "
                       "a native speaker has not reviewed the templates.",
            "languages": board,
        }
    finally:
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = saved
        embed.reset_embedder_cache()
        tmp.cleanup()


def render_board(result: dict) -> str:
    lines = [f"{'lang':<5} {'style':<10} {'r@1':>7} {'r@5':>7} {'answer':>7} {'falseabs':>8} {'locator':>8}"]
    for code, r in result["languages"].items():
        for key in ("a_own", "b_name", "c_english"):
            s = r[key]
            lines.append(f"{code:<5} {key:<10} {s['recall_at_1']:>4}/{s['n']:<2} {s['recall_at_5']:>4}/{s['n']:<2} "
                         f"{s['answer_has_value']:>4}/{s['n']:<2} {s['false_abstain']:>8} {s['locator_ok']:>4}/{s['locator_n']:<3}")
        u = r["unanswerable"]
        lines.append(f"{code:<5} {'abstain':<10} {u['abstained']:>4}/{u['n']}")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    res = run(args.n, args.seed)
    print(render_board(res))
    if not args.no_write:
        RESULTS.parent.mkdir(parents=True, exist_ok=True)
        RESULTS.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {RESULTS}")

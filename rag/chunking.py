"""Parent–child structural chunking for AirGPT RAG (Phase 1)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
CODE_FENCE_RE = re.compile(r"^```", re.MULTILINE)
# Top-level code symbol definitions — split code on function/class boundaries so
# each chunk is a coherent unit (and so '#' comments aren't mistaken for markdown
# headings, which would fragment functions).
CODE_SYM_RE = re.compile(
    r"^(?:async\s+def\s|def\s|class\s|func\s|type\s|impl\s|struct\s|enum\s|interface\s"
    r"|(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s"
    r"|(?:export\s+)?(?:const|let|var)\s+\w+\s*=)",
    re.MULTILINE,
)


@dataclass
class ChunkDraft:
    kind: str  # parent | child
    text: str
    heading: str = ""
    span_start: int = 0
    span_end: int = 0
    token_est: int = 0
    parent_index: int = -1  # index into parents list for children
    meta: dict = field(default_factory=dict)
    # Where the chunk sits: "Vendor policy > Security > Retention". Indexed with the
    # chunk, never shown in its text.
    context: str = ""


# Characters per token differ a lot by script. A flat 4 made a Chinese or Japanese
# chunk several times larger than the budget said, so these carry more meaning per
# character than Latin text does. Round figures, not a measured tokenizer: they only
# have to keep dense scripts from overshooting by a factor of three or four.
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")  # kana, han, hangul
_THAI_RE = re.compile(r"[\u0e00-\u0e7f]")
_ARABIC_RE = re.compile(r"[\u0600-\u06ff]")


def _weight(text: str) -> float:
    """Estimated tokens, unrounded: CJK 1 per char, Thai 1 per 2, Arabic 1 per 2.5, rest 1 per 4."""
    t = text or ""
    if t.isascii():
        return len(t) / 4.0
    cjk = len(_CJK_RE.findall(t))
    thai = len(_THAI_RE.findall(t))
    arab = len(_ARABIC_RE.findall(t))
    return cjk + thai * 0.5 + arab * 0.4 + (len(t) - cjk - thai - arab) / 4.0


def estimate_tokens(text: str) -> int:
    return max(1, int(_weight(text) + 0.75))


def _sections_from(text: str, matches: list, *, code: bool) -> list[tuple[str, str, int, int]]:
    sections: list[tuple[str, str, int, int]] = []
    if matches[0].start() > 0:
        pre = text[: matches[0].start()]
        if pre.strip():
            sections.append(("", pre, 0, matches[0].start()))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        heading = body.splitlines()[0].strip()[:80] if code else (m.group(2) or "").strip()
        sections.append((heading, body, start, end))
    return sections


def _split_sections(text: str, *, code: bool = False) -> list[tuple[str, str, int, int]]:
    """Return (heading, body, start, end) sections.

    Code files (code=True) split on top-level def/class/function SYMBOL boundaries
    so each chunk is a coherent function/class — and '#' comments are never treated
    as markdown headings. Prose/markdown splits on headings.
    """
    text = text or ""
    if code:
        sym = list(CODE_SYM_RE.finditer(text))
        if len(sym) >= 2:
            return _sections_from(text, sym, code=True)
        return [("", text, 0, len(text))]  # small code file — keep whole, don't split on comments
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [("", text, 0, len(text))]
    return _sections_from(text, matches, code=False)


_NUMERIC_CELL_RE = re.compile(r"^[-+(]?[\d][\d.,:/%\-\s)]*$")


_YEAR_CELL_RE = re.compile(r"^(?:FY\s?)?(?:19|20)\d{2}$", re.I)


def _table_header(heading: str, body: str) -> str:
    """The sheet's header row, or "" when the first row does not look like one.

    The extract is `## Sheet: name` then pipe-joined rows; nothing marks which row
    names the columns, so it is judged from the row itself. Row 1 counts as the
    header when it has two or more filled cells, no cell repeated, and at least 70%
    of its cells are not numbers or dates. That rejects a banner row (one cell once
    trailing blanks are trimmed), a headerless dump whose first row is data with
    numbers in it, and a repeated label row. It can still take an all-text first data
    row of a headerless sheet for a header; repeating one extra line is the cheaper
    mistake than leaving every row below it without column names.
    """
    if not (heading or "").startswith("Sheet:"):
        return ""
    lines = [ln for ln in (body or "").splitlines() if ln.strip()]
    if lines and lines[0].lstrip().startswith("#"):
        lines = lines[1:]
    if len(lines) < 2 or len(lines[0]) > 300:
        return ""
    filled = [c.strip() for c in lines[0].split(" | ") if c.strip()]
    if len(filled) < 2 or len({c.casefold() for c in filled}) < len(filled):
        return ""
    # A year is a column name far more often than a value in row 1: "Item | 2024 |
    # 2025" is the usual finance header and was read as a data row.
    labels = sum(1 for c in filled if not _NUMERIC_CELL_RE.match(c) or _YEAR_CELL_RE.match(c))
    return lines[0].strip() if labels >= 0.7 * len(filled) else ""


def _starts_with_header(text: str, header: str) -> bool:
    first = text.split("\n", 2)[:2]
    if first and first[0].lstrip().startswith("#"):
        first = first[1:]
    return bool(first) and first[0].strip() == header


def _window_rows(
    body: str, base_offset: int, *, target_tokens: int = 200, overlap_tokens: int = 40,
    header: str = "",
) -> list[tuple[str, int, int]]:
    """Pack whole lines into child windows. Never split a line (a sheet row).

    Spreadsheet extract (`## Sheet:` + pipe-joined rows) has no blank-line
    paragraphs, so `_window_children` used to fall into a character-count split
    and cut mid-row. This is the table half of parent/child: headings still
    make parents; children are row windows.

    `header` is the sheet's column-name row. Only the first window of a sheet held
    it, so a hit on row 400 was bare values with no names. Every window now starts
    with it (the span still covers only the rows), and its size comes off the budget.
    """
    if not (body or "").strip():
        return []
    target = max(50.0, float(target_tokens))
    if header:
        target = max(target - _weight(header), target / 2)
    overlap_n = 1 if overlap_tokens else 0
    lines = body.splitlines(keepends=True)
    windows: list[tuple[str, int, int]] = []
    buf: list[str] = []
    buf_w = 0.0
    buf_start = base_offset
    cursor = 0

    def emit(text: str, start: int, end: int) -> None:
        text = text.strip()
        rows = [ln for ln in text.split("\n") if ln.strip() and not ln.lstrip().startswith("#")]
        if not text or (header and all(ln.strip() == header for ln in rows)):
            return  # the header alone is not a chunk: it would match on column names and hold no value
        if header and not _starts_with_header(text, header):
            text = header + "\n" + text
        windows.append((text, start, end))

    def flush() -> None:
        nonlocal buf, buf_w, buf_start
        if not buf:
            return
        text = "".join(buf)
        emit(text, buf_start, buf_start + len(text))
        if overlap_n and len(buf) > overlap_n and buf[-1].strip() != header:
            keep = buf[-overlap_n:]
            keep_len = sum(len(x) for x in keep)
            buf_start = buf_start + len(text) - keep_len
            buf = keep
            buf_w = sum(_weight(x) for x in keep)
        else:
            buf = []
            buf_w = 0.0
            buf_start = base_offset + cursor

    for line in lines:
        lw = _weight(line)
        if buf and buf_w + lw > target:
            flush()
            if not buf:
                buf_start = base_offset + cursor
        if not buf:
            buf_start = base_offset + cursor
        buf.append(line)
        buf_w += lw
        cursor += len(line)
    flush()
    return [w for w in windows if w[0]]


# A sentence ends at a terminator plus any closing quote or bracket. CJK marks end
# a sentence with no space after them; the others only when whitespace follows, so
# "4410.5" and "a.b" are never cut. Arabic and Urdu marks are in the second group.
_SENT_END_RE = re.compile(
    r"[\u3002\uff01\uff1f]+[\"'\u201d\u2019)\]\u300d\u300f\uff09\u300b]*"
    r"|[.!?\u2026\u061f\u06d4]+[\"'\u201d\u2019)\]\u300d\u300f\uff09\u300b]*"
    r"|\n"
    r"|(?<=[\u0e00-\u0e7f])[ \t]+(?=[\u0e00-\u0e7f])"
)
_STOP_CHARS = ".!?\u2026\u3002\uff01\uff1f\u061f\u06d4:\"'\u201d\u2019)]\u300d\u300f\uff09\u300b"
_CLAUSE_BREAKS = " \t\u3000,;:\uff0c\u3001\uff1b\uff1a\u060c\u061b"


def _sentence_units(body: str, *, lines_are_units: bool = False) -> list[tuple[int, int]]:
    """Cut `body` into (start, end) sentence units that tile it with no gaps.

    A line end is a boundary unless the line is plainly a wrapped sentence: it has
    no terminator and the next line starts in lower case (a PDF page arrives as one
    paragraph with a newline at every wrap). Code and logs set `lines_are_units`.
    Trailing whitespace stays with the unit it follows. A period followed by a
    lower-case word ("e.g. x") is not an end. A space between two Thai letters is a
    boundary, since Thai separates phrases with a space and has no sentence mark.
    """
    n = len(body)
    ends: list[int] = []
    for m in _SENT_END_RE.finditer(body):
        tok = m.group(0)
        e = m.end()
        if tok == "\n":
            if not lines_are_units:
                a = m.start()
                while a > 0 and body[a - 1] in " \t\r":
                    a -= 1
                b = e
                while b < n and body[b] in " \t\r":
                    b += 1
                if a > 0 and body[a - 1] not in _STOP_CHARS and body[b:b + 1].islower():
                    continue
        elif tok[0] in " \t":
            pass  # Thai has no sentence mark; a space between two Thai letters is its phrase break
        elif tok[0] not in "。！？":
            if e < n and not body[e].isspace():
                continue
            if tok[0] == ".":
                gap = re.match(r"[ \t]+", body[e:e + 8])
                if gap and body[e + gap.end():e + gap.end() + 1].islower():
                    continue
        while e < n and body[e].isspace():
            e += 1
        if not ends or e > ends[-1]:
            ends.append(e)
    if not ends or ends[-1] < n:
        ends.append(n)
    units, start = [], 0
    for e in ends:
        if e > start:
            units.append((start, e))
            start = e
    return units


def _split_long(body: str, start: int, end: int, target: float, overlap: float = 0.0) -> list[tuple[int, int]]:
    """Cut one sentence that is over budget, at a space or clause mark if one is near.

    Only reached for a single sentence longer than the whole window: a PDF line with
    no punctuation, a Thai paragraph, a table dumped as text. There are no sentences
    to overlap by here, so the next piece starts at the first break inside the
    overlap, which keeps a fact that sits on the cut whole in one of the two.
    """
    out: list[tuple[int, int]] = []
    pos = start
    while pos < end:
        cut = min(end, pos + max(8, int(target * 4)))
        w = _weight(body[pos:cut])
        for _ in range(6):
            if w <= target or cut - pos <= 1:
                break
            cut = pos + max(1, int((cut - pos) * target / w * 0.98))
            w = _weight(body[pos:cut])
        if cut < end:
            floor = pos + (cut - pos) // 2
            best = max((body.rfind(ch, floor, cut) for ch in _CLAUSE_BREAKS), default=-1)
            if best >= floor:
                cut = best + 1
        out.append((pos, cut))
        if cut >= end:
            break
        nxt = cut
        if overlap > 0 and w > 0:
            c0 = max(pos + 1, cut - int(overlap * (cut - pos) / w))
            hits = [i for i in (body.find(ch, c0, cut - 1) for ch in _CLAUSE_BREAKS) if i >= 0]
            if hits:
                nxt = min(hits) + 1
        pos = nxt if nxt > pos else cut
    return out


def _window_children(
    body: str, base_offset: int, *, target_tokens: int = 200, overlap_tokens: int = 40,
    lines_are_units: bool = False,
) -> list[tuple[str, int, int]]:
    """Pack whole sentences into overlapping child windows, sized by estimated tokens.

    Used to cut by character count: a long paragraph (one PDF page) was hard-split
    mid-word, so a fact straddling the cut was whole in neither chunk, and the budget
    ignored that a Chinese character carries several times a Latin one. Now a window
    is a run of whole sentences; overlap is whole sentences; a sentence is cut only
    when it alone is over budget.
    """
    if not body.strip():
        return []
    target = max(50.0, float(target_tokens))
    overlap = float(overlap_tokens)
    units: list[tuple[int, int]] = []
    for s0, e0 in _sentence_units(body, lines_are_units=lines_are_units):
        if _weight(body[s0:e0]) > target:
            units.extend(_split_long(body, s0, e0, target, overlap))
        else:
            units.append((s0, e0))
    w = [_weight(body[a:b]) for a, b in units]
    out: list[tuple[str, int, int]] = []
    i, n = 0, len(units)
    while i < n:
        j, total = i, 0.0
        while j < n and (j == i or total + w[j] <= target):
            total += w[j]
            j += 1
        text = body[units[i][0]:units[j - 1][1]].strip()
        if text:
            out.append((text, base_offset + units[i][0], base_offset + units[j - 1][1]))
        if j >= n:
            break
        k, ov = j, 0.0
        # The last sentence is always carried when it is short, even if it is bigger
        # than the overlap: a fact whose first sentence is 41 tokens against an overlap
        # of 40 would otherwise sit on the cut with half of it in each window.
        while k - 1 > i and (ov + w[k - 1] <= overlap or (k == j and w[k - 1] <= target / 4)):
            k -= 1
            ov += w[k]
        if k < j and ov + w[j] > target:
            k = j
        i = k
    return out


def parent_child_chunk(
    text: str,
    *,
    child_tokens: int = 200,
    parent_max_tokens: int = 900,
    code: bool = False,
    table: bool = False,
    salience_terms: list[str] | None = None,
) -> tuple[list[ChunkDraft], list[ChunkDraft], dict]:
    """
    Build parent sections and child embed windows.
    Returns (parents, children, metrics) where children.parent_index points into parents.
    code=True aligns parent chunks to function/class SYMBOL boundaries.
    table=True packs whole rows (never mid-row char-split) under heading parents.
    Prose uses heading parents + paragraph windows. Never "regex the file" as one blob.
    Near-duplicate children (Jaccard >= 0.9) are demoted; salience_terms prefer rare phrases.
    """
    from rag import normalize as norm

    window = _window_rows if table else _window_children
    # Code and any other text where a line is the natural unit keeps every line end
    # as a boundary; only running prose may join wrapped lines.
    prose_kw = {"lines_are_units": True} if code else {}
    parents: list[ChunkDraft] = []
    children: list[ChunkDraft] = []
    demoted = 0
    seen_rows: set[str] = set()
    paths = {} if (code or table) else heading_paths(text)
    for heading, body, start, end in _split_sections(text, code=code):
        context = paths.get(start, "")
        # Cap oversized parents by further splitting on blank lines (or whole rows)
        parent_bodies: list[tuple[str, str, int, int]] = [(heading, body, start, end)]
        kw = {"header": _table_header(heading, body)} if table else dict(prose_kw)
        if estimate_tokens(body) > parent_max_tokens:
            parent_bodies = []
            for child_text, cs, ce in window(body, start, target_tokens=parent_max_tokens, overlap_tokens=80, **kw):
                parent_bodies.append((heading, child_text, cs, ce))

        for ph, pb, ps, pe in parent_bodies:
            pidx = len(parents)
            parents.append(
                ChunkDraft(
                    kind="parent",
                    text=pb.strip(),
                    heading=ph,
                    span_start=ps,
                    span_end=pe,
                    token_est=estimate_tokens(pb),
                    meta={"headings": [ph] if ph else [], "table": bool(table)},
                    context=context,
                )
            )
            prev_text = ""
            for ct, cs, ce in window(pb, ps, target_tokens=child_tokens, **kw):
                if table and ct in seen_rows:
                    continue  # parents overlap by a row; the same window twice is one hit shown twice
                seen_rows.add(ct)
                # Rows are records. Two rows that differ only in an id are two facts,
                # and dropping the "near-duplicate" took the second one out of search.
                if not table and prev_text and norm.jaccard_tokens(prev_text, ct) >= 0.9:
                    demoted += 1
                    continue
                # Prefer salient windows when terms provided (still keep all above floor)
                if salience_terms and estimate_tokens(ct) < 40:
                    if norm.salience_score(ct, salience_terms) < 0.15:
                        demoted += 1
                        continue
                children.append(
                    ChunkDraft(
                        kind="child",
                        text=ct,
                        heading=ph,
                        span_start=cs,
                        span_end=ce,
                        token_est=estimate_tokens(ct),
                        parent_index=pidx,
                        meta={"salience": round(norm.salience_score(ct, salience_terms), 3)},
                        context=context,
                    )
                )
                prev_text = ct
    # Fallback: if no children (tiny doc), embed parents as children too
    if parents and not children:
        for i, p in enumerate(parents):
            children.append(
                ChunkDraft(
                    kind="child",
                    text=p.text,
                    heading=p.heading,
                    span_start=p.span_start,
                    span_end=p.span_end,
                    token_est=p.token_est,
                    parent_index=i,
                    context=p.context,
                )
            )
    metrics = {
        "demoted_children": demoted,
        "child_count": len(children),
        "parent_count": len(parents),
        "table": bool(table),
        "code": bool(code),
    }
    return parents, children, metrics


def heading_paths(text: str) -> dict[int, str]:
    """Section start offset -> the chain of headings above and including that section."""
    stack: list[tuple[int, str]] = []
    out: dict[int, str] = {}
    for m in HEADING_RE.finditer(text or ""):
        level, title = len(m.group(1)), m.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        out[m.start()] = " > ".join(t for _, t in stack)
    return out


def extract_headings(text: str) -> list[str]:
    return [m.group(2).strip() for m in HEADING_RE.finditer(text or "") if m.group(2).strip()]

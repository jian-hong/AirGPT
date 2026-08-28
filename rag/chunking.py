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


def estimate_tokens(text: str) -> int:
    # Cheap approx: ~4 chars / token for English/code mix
    return max(1, (len(text or "") + 3) // 4)


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


def _window_rows(
    body: str, base_offset: int, *, target_tokens: int = 200, overlap_tokens: int = 40
) -> list[tuple[str, int, int]]:
    """Pack whole lines into child windows. Never split a line (a sheet row).

    Spreadsheet extract (`## Sheet:` + pipe-joined rows) has no blank-line
    paragraphs, so `_window_children` used to fall into a character-count split
    and cut mid-row. This is the table half of parent/child: headings still
    make parents; children are row windows.
    """
    if not (body or "").strip():
        return []
    target_chars = max(200, target_tokens * 4)
    overlap_n = 1 if overlap_tokens else 0
    lines = body.splitlines(keepends=True)
    windows: list[tuple[str, int, int]] = []
    buf: list[str] = []
    buf_len = 0
    buf_start = base_offset
    cursor = 0

    def flush() -> None:
        nonlocal buf, buf_len, buf_start
        if not buf:
            return
        text = "".join(buf)
        if text.strip():
            windows.append((text.strip(), buf_start, buf_start + len(text)))
        if overlap_n and len(buf) > overlap_n:
            keep = buf[-overlap_n:]
            keep_len = sum(len(x) for x in keep)
            buf_start = buf_start + len(text) - keep_len
            buf = keep
            buf_len = keep_len
        else:
            buf = []
            buf_len = 0
            buf_start = base_offset + cursor

    for line in lines:
        if buf and buf_len + len(line) > target_chars:
            flush()
            if not buf:
                buf_start = base_offset + cursor
        if not buf:
            buf_start = base_offset + cursor
        buf.append(line)
        buf_len += len(line)
        cursor += len(line)
    flush()
    return [w for w in windows if w[0]]


def _window_children(body: str, base_offset: int, *, target_tokens: int = 200, overlap_tokens: int = 40) -> list[tuple[str, int, int]]:
    """Split a section body into overlapping child windows by approx tokens."""
    if not body.strip():
        return []
    target_chars = max(200, target_tokens * 4)
    overlap_chars = max(40, overlap_tokens * 4)
    # Prefer paragraph boundaries
    paras = re.split(r"(\n\s*\n)", body)
    pieces: list[str] = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) <= target_chars:
            buf += p
        else:
            if buf.strip():
                pieces.append(buf)
            if len(p) > target_chars * 2:
                # hard-split long paragraph
                for i in range(0, len(p), target_chars - overlap_chars):
                    pieces.append(p[i : i + target_chars])
                buf = ""
            else:
                buf = p
    if buf.strip():
        pieces.append(buf)

    out: list[tuple[str, int, int]] = []
    cursor = 0
    for piece in pieces:
        idx = body.find(piece, cursor)
        if idx < 0:
            idx = cursor
        start = base_offset + idx
        end = start + len(piece)
        out.append((piece.strip(), start, end))
        cursor = idx + max(1, len(piece) - overlap_chars)
    return [x for x in out if x[0]]


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
    parents: list[ChunkDraft] = []
    children: list[ChunkDraft] = []
    demoted = 0
    for heading, body, start, end in _split_sections(text, code=code):
        # Cap oversized parents by further splitting on blank lines (or whole rows)
        parent_bodies: list[tuple[str, str, int, int]] = [(heading, body, start, end)]
        if estimate_tokens(body) > parent_max_tokens:
            parent_bodies = []
            for child_text, cs, ce in window(body, start, target_tokens=parent_max_tokens, overlap_tokens=80):
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
                )
            )
            prev_text = ""
            for ct, cs, ce in window(pb, ps, target_tokens=child_tokens):
                if prev_text and norm.jaccard_tokens(prev_text, ct) >= 0.9:
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


def extract_headings(text: str) -> list[str]:
    return [m.group(2).strip() for m in HEADING_RE.finditer(text or "") if m.group(2).strip()]

"""Parent–child structural chunking for AirGPT RAG (Phase 1)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
CODE_FENCE_RE = re.compile(r"^```", re.MULTILINE)


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


def _split_sections(text: str) -> list[tuple[str, str, int, int]]:
    """Return (heading, body, start, end) sections. Heading may be empty for preamble."""
    text = text or ""
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [("", text, 0, len(text))]
    sections: list[tuple[str, str, int, int]] = []
    if matches[0].start() > 0:
        pre = text[: matches[0].start()]
        if pre.strip():
            sections.append(("", pre, 0, matches[0].start()))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        heading = (m.group(2) or "").strip()
        body = text[start:end]
        sections.append((heading, body, start, end))
    return sections


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
) -> tuple[list[ChunkDraft], list[ChunkDraft]]:
    """
    Build parent sections and child embed windows.
    Returns (parents, children) where children.parent_index points into parents.
    """
    parents: list[ChunkDraft] = []
    children: list[ChunkDraft] = []
    for heading, body, start, end in _split_sections(text):
        # Cap oversized parents by further splitting on blank lines
        parent_bodies: list[tuple[str, str, int, int]] = [(heading, body, start, end)]
        if estimate_tokens(body) > parent_max_tokens:
            parent_bodies = []
            for child_text, cs, ce in _window_children(body, start, target_tokens=parent_max_tokens, overlap_tokens=80):
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
                    meta={"headings": [ph] if ph else []},
                )
            )
            for ct, cs, ce in _window_children(pb, ps, target_tokens=child_tokens):
                children.append(
                    ChunkDraft(
                        kind="child",
                        text=ct,
                        heading=ph,
                        span_start=cs,
                        span_end=ce,
                        token_est=estimate_tokens(ct),
                        parent_index=pidx,
                    )
                )
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
    return parents, children


def extract_headings(text: str) -> list[str]:
    return [m.group(2).strip() for m in HEADING_RE.finditer(text or "") if m.group(2).strip()]

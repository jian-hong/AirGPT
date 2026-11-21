"""Local hybrid retrieval: sparse FTS + lexical dense stub + file-level + RRF."""
from __future__ import annotations

import math
import re
import unicodedata
import uuid
from collections import Counter, defaultdict
from typing import Any

from rag import adaptive, authority, sira, store, vectors
from rag.fuse import RankedHit, fuse_channels
from rag.rerank import rerank_hits


def fold_text(text: str) -> str:
    """Make a question and a passage comparable word for word.

    sira.tokenize keeps ASCII letters and treats every other letter as a separate
    run, so "información" became "informaci" (the accented letter and what follows
    were cut off) and an Arabic question mark stayed glued to the last word of the
    question ("الراشد؟" never equals "الراشد"). Accents are taken off Latin letters
    only: Thai, Arabic and Devanagari marks are part of the letter and Hangul
    syllables must not be split. Punctuation outside ASCII (؟ ، « » “ ” —) becomes a
    space. Text that is already ASCII is returned untouched.
    """
    if not text or text.isascii():
        return text or ""
    out: list[str] = []
    for ch in text:
        o = ord(ch)
        if o < 0x80:
            out.append(ch)
        elif 0xC0 <= o <= 0x24F or 0x1E00 <= o <= 0x1EFF:
            base = unicodedata.normalize("NFD", ch)[0]
            out.append(base if base.isascii() else ch)
        elif 0x300 <= o <= 0x36F:
            continue  # an accent already written as a separate mark
        elif unicodedata.category(ch)[0] in "PS":
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def _tokens(text: str) -> list[str]:
    return sira.tokenize(fold_text(text))


def _fts_query(query: str) -> str:
    all_toks = [t for t in _tokens(query) if len(t) >= 2]
    # A 2-character piece of Chinese/Japanese/Thai only ever matches here when a cell
    # or a heading holds that piece as a whole word ("客户" in a spreadsheet header),
    # which put unrelated sheets at the top. script_search reads those scripts.
    toks = [t for t in all_toks if not _is_unseg(t)][:12]
    if not toks and any(_is_unseg(t) for t in all_toks):
        return '""'
    if not toks:
        return (query or "").replace('"', " ").strip()[:80]
    return " OR ".join(f'"{t}"' for t in toks)


def _overlap_score(query: str, text: str) -> float:
    q = Counter(_tokens(query))
    if not q:
        return 0.0
    d = Counter(_tokens(text))
    dot = sum(q[t] * d.get(t, 0) for t in q)
    if not dot:
        return 0.0
    qn = math.sqrt(sum(v * v for v in q.values()))
    dn = math.sqrt(sum(v * v for v in d.values())) or 1.0
    return float(dot / (qn * dn))


def sparse_search(space_id: int, query: str, *, k: int = 40) -> list[RankedHit]:
    store.init()
    fts_q = _fts_query(query)
    with store._conn() as conn:
        try:
            rows = conn.execute(
                """
                SELECT c.id, c.text, c.path, c.heading, c.parent_id, c.kind, c.source_id, c.authority,
                       bm25(chunks_fts) AS score
                FROM chunks_fts
                JOIN chunks c ON c.id = chunks_fts.chunk_id
                WHERE chunks_fts MATCH ? AND c.space_id=? AND c.kind='child'
                ORDER BY score, chunks_fts.rowid
                LIMIT ?
                """,
                (fts_q, int(space_id), int(k)),
            ).fetchall()
        except Exception:
            # MATCH syntax failure — fall back to LIKE
            like = f"%{(query or '')[:40]}%"
            rows = conn.execute(
                """
                SELECT id, text, path, heading, parent_id, kind, source_id, 0.0 AS score
                FROM chunks
                WHERE space_id=? AND kind='child' AND (text LIKE ? OR path LIKE ? OR heading LIKE ?)
                LIMIT ?
                """,
                (int(space_id), like, like, like, int(k)),
            ).fetchall()
    hits: list[RankedHit] = []
    for i, r in enumerate(rows):
        # sqlite bm25 is NEGATIVE, more negative = better. Clamping it at zero made
        # every sparse hit score exactly 1.0, so the trace showed a constant.
        raw = -float(r["score"] or 0.0)
        score = raw / (1.0 + raw) if raw > 0 else max(0.01, 1.0 / (i + 1))
        hits.append(
            RankedHit(
                doc_id=str(r["id"]),
                score=score,
                payload={
                    "chunk_id": int(r["id"]),
                    "text": r["text"],
                    "path": r["path"],
                    "heading": r["heading"],
                    "parent_id": int(r["parent_id"] or 0),
                    "source_id": int(r["source_id"] or 0),
                    "authority": r["authority"] or "",
                    "channel": "sparse",
                },
            )
        )
    return hits


# --- scripts written without spaces (Chinese, Japanese, Thai) ----------------------
#
# sira.tokenize cuts these into 2-character pieces (3 for Thai), but sqlite's FTS5
# sees one run of characters as ONE word, so a piece can never match inside a
# sentence: the keyword channel was blind to them and everything rested on the
# hashed-vector channel (r@1 for Chinese was 8 of 30). The pieces are indexed here
# instead, in memory, built on first use from the chunks the space already holds.
_UNSEG_RE = re.compile(r"[\u0e00-\u0e7f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")  # Thai, kana, CJK
# Above this many chunks the table is not built (memory) and the channel stays off.
SCRIPT_INDEX_MAX_CHUNKS = 50000
_script_cache: dict[tuple, tuple[tuple, dict[str, set[int]]]] = {}


def _is_unseg(token: str) -> bool:
    return bool(token) and bool(_UNSEG_RE.match(token[0]))


_HANGUL_RE = re.compile(r"[\uac00-\ud7af]")


def _script_tokens(text: str) -> list[str]:
    """Pieces for the script lane: Chinese/Japanese/Thai pieces as sira cuts them, and
    Hangul words cut into overlapping 2-character pieces, so a stem ("창고") finds the
    word with its ending attached ("창고에는")."""
    out: list[str] = []
    for t in sira.tokenize(fold_text(text)):
        if _is_unseg(t):
            out.append(t)
        elif _HANGUL_RE.match(t[:1]) and t not in QUESTION_FLUFF:
            out.extend(t[i : i + 2] for i in range(len(t) - 1))
    return out


def _script_index(conn, space_id: int) -> tuple[dict[str, set[int]] | None, int]:
    """(token -> ids of the chunks holding it, number of chunks), unsegmented tokens only."""
    sig = tuple(
        conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(id),0), COALESCE(SUM(id),0), COALESCE(SUM(LENGTH(text)),0) "
            "FROM chunks WHERE space_id=? AND kind='child'",
            (int(space_id),),
        ).fetchone()
    )
    key = (str(store.DB_PATH), int(space_id))
    cached = _script_cache.get(key)
    if cached and cached[0] == sig:
        return cached[1], sig[0]
    if sig[0] > SCRIPT_INDEX_MAX_CHUNKS:
        return None, sig[0]
    post: dict[str, set[int]] = defaultdict(set)
    for r in conn.execute("SELECT id, text FROM chunks WHERE space_id=? AND kind='child'", (int(space_id),)):
        text = r["text"] or ""
        if not (_UNSEG_RE.search(text) or _HANGUL_RE.search(text)):
            continue
        for t in set(_script_tokens(text)):
            post[t].add(int(r["id"]))
    if len(_script_cache) >= 8:
        _script_cache.pop(next(iter(_script_cache)))
    _script_cache[key] = (sig, post)
    return post, sig[0]


def _script_query_tokens(query: str) -> list[str]:
    return [t for t in _script_tokens(query) if t not in QUESTION_FLUFF]


def _chunk_rows(conn, ids: list[int]) -> dict[int, Any]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {
        int(r["id"]): r
        for r in conn.execute(
            f"SELECT id, text, path, heading, parent_id, source_id, authority FROM chunks WHERE id IN ({marks})",
            ids,
        )
    }


def _chunk_payload(r, channel: str) -> dict:
    return {
        "chunk_id": int(r["id"]),
        "text": r["text"],
        "path": r["path"],
        "heading": r["heading"],
        "parent_id": int(r["parent_id"] or 0),
        "source_id": int(r["source_id"] or 0),
        "authority": r["authority"] or "",
        "channel": channel,
    }


def script_search(space_id: int, query: str, *, k: int = 40) -> list[RankedHit]:
    """Chunks sharing the most character pieces with the question, rare pieces counting more."""
    qt = list(dict.fromkeys(_script_query_tokens(query)))
    if not qt:
        return []
    store.init()
    with store._conn() as conn:
        post, n = _script_index(conn, space_id)
        if not post:
            return []
        idf = {t: math.log(1.0 + n / len(post[t])) for t in qt if t in post}
        total = sum(idf.values())
        if not total:
            return []
        score: Counter = Counter()
        for t, w in idf.items():
            for cid in post[t]:
                score[cid] += w
        top = score.most_common(int(k))
        rows = _chunk_rows(conn, [cid for cid, _ in top])
    return [
        RankedHit(doc_id=str(cid), score=float(sc / total), payload=_chunk_payload(rows[cid], "script"))
        for cid, sc in top
        if cid in rows
    ]


def dense_weight() -> float:
    """Vector-channel weight for the embedder that is actually active."""
    try:
        from rag import embed

        return DENSE_WEIGHT_MODEL if embed.backend_name() == "model" else DENSE_WEIGHT_HASH
    except Exception:
        return DENSE_WEIGHT_HASH


# A code ("ZQ-4471", "frtr_0001", anything in quotes) or a name (capitalised somewhere
# other than the start of the question: "Halvorsen"). A bare number is neither: "2024"
# and "5" turn up by accident in chunks that have nothing to do with the question.
_WORD_RE = re.compile(r"[^\W_]+(?:[-_./][^\W_]+)*")
_QUOTED_RE = re.compile(r"[\"\u201c]([^\"\u201d]{2,60})[\"\u201d]")
EXACT_MAX_DF = 5
EXACT_WEIGHT = 3.0
# A capitalised name in at most this many chunks earns a plain vote even where the chunk
# shares none of the question's other words (see exact_term_search, relaxed).
NAME_MAX_DF = 3
NAME_WEIGHT = 1.5
# Weight of the vector channel in the fusion. The built-in hash embedder only matches
# shared word pieces, so its ranking is mostly noise next to the word-index channel;
# a real embedding model earns the full weight. See dense_weight(). Measured on
# tests/RAG/paraphrase_bench.py seeds 1-7 with the name channel on: of 0.25, 0.4, 0.6
# and 1.0, 0.6 is the lowest weight where no style finds fewer answers at rank 1 than
# at 1.0, and it finds more in the top five (0.4 and 0.25 find more still, but drop
# property questions at rank 1 to 0-2).
DENSE_WEIGHT_HASH = 0.6
DENSE_WEIGHT_MODEL = 1.0
_QUESTION_WORDS = frozenset(
    "what which when where does that this with from have about there their during will".split()
)
# The same job in other languages, as sira.tokenize cuts them: the words of a question
# that ask and say nothing about the thing asked ("what is", "tell me about",
# "information on"). Without them a Malay or Spanish question "Apakah X bagi akaun Y?"
# looked 50% uncovered because no passage contains "apakah", and the offline answer
# refused a question it could answer.
_FLUFF_WORDS = (
    # Chinese, Japanese, Korean
    "什么 是什么 哪个 如何 怎么 多少 请问 请告诉我 什麼 情况 情況 "
    "は何ですか 何ですか 何です とは 教えてください について 情報 "
    "무엇입니까 무엇인가요 알려 주세요 대해 대한 "
    # Thai: what / please tell / information about
    "คืออะไร อะไร บอก ข้อมูลของ "
    # Arabic
    "ما هو هي ماذا كم من هل أين متى عن معلومات "
    # Russian
    "что какой какая какое каков каковы расскажите указано где когда кто о "
    # Malay / Indonesian
    "apakah apa siapakah berapakah bagaimana maklumat tentang mengenai yang "
    # Spanish (accent-folded, as fold_text leaves them)
    "cual cuales que como informacion sobre dime donde cuando quien"
)
# Only for the scripts written without spaces: inside a word of a spaced script (Arabic
# "ماجد" holds "ما") cutting a phrase out would eat the name.
FLUFF_PHRASES = tuple(w for w in _FLUFF_WORDS.split() if len(w) >= 2 and _UNSEG_RE.match(w[0]))
# Cut the way sira.tokenize cuts a question, so a phrase like "คืออะไร" is recognised by
# the pieces it leaves ("ืออ", "ออะ", ...) and not only by the whole word.
QUESTION_FLUFF = frozenset(
    {w for w in _FLUFF_WORDS.split()} | {t for w in _FLUFF_WORDS.split() for t in sira.tokenize(w)}
)


def _is_code(term: str) -> bool:
    return " " in term or (any(c.isdigit() for c in term) and any(c.isalpha() for c in term))


def identifier_terms(query: str) -> list[str]:
    """The words in a question that name one specific thing."""
    q = query or ""
    out = [m.group(1).strip() for m in _QUOTED_RE.finditer(q)]
    for i, m in enumerate(_WORD_RE.finditer(q)):
        w = m.group(0)
        # A capital after a full stop opens a sentence ("... Give the code."); it is not a name.
        starts_sentence = bool(re.search(r"[.!?\u3002\uff01\uff1f]\s*$", q[: m.start()]))
        if _is_code(w) or (i > 0 and not starts_sentence and w[0].isupper() and len(w) >= 3 and not w.isdigit()):
            out.append(w)
    return list(dict.fromkeys(out))[:6]


def _content_tokens(query: str) -> set[str]:
    """What the question is about, minus the words that only ask it."""
    return {
        t
        for t in sira.tokenize(fold_text(query))
        if len(t) >= (4 if t.isascii() else 2)
        and t not in _QUESTION_WORDS
        and t not in QUESTION_FLUFF
        and not _is_unseg(t)
    }


def _script_name_slots(conn, space_id: int, query: str, found: dict[int, dict]) -> None:
    """The rare-word rule for Chinese, Japanese and Thai, which have no capitals.

    A name there is a run of consecutive character pieces that are all rare in the
    space (each in at most EXACT_MAX_DF chunks). A chunk counts for the run when it
    holds at least 60% of the run's pieces AS ONE UNBROKEN STRING. Holding the pieces
    is not enough: one chunk that lists many look-alike names holds every piece of
    every name and outscored the chunk with the real one. 60% rather than all of it,
    because the piece that straddles the name and the next word ("盛客" in "华兴盛客户")
    is missing when a table cell or the question words it differently. The usual
    coverage guard applies too: the chunk must hold half of the question's other pieces.
    """
    post, _n = _script_index(conn, space_id)
    toks = _script_query_tokens(query)
    if not post or not toks:
        return
    groups: list[list[str]] = [[]]
    for t in toks:
        if 1 <= len(post.get(t, ())) <= EXACT_MAX_DF:
            if groups[-1] and groups[-1][-1][1:] != t[:-1]:
                groups.append([])  # not the next overlapping piece of the same run
            groups[-1].append(t)
        elif groups[-1]:
            groups.append([])
    rare = {t for g in groups for t in g}
    rest = {t for t in toks if t not in rare}

    def string(pieces: list[str]) -> str:
        return pieces[0] + "".join(t[-1] for t in pieces[1:])

    for g in groups:
        if not g:
            continue
        need = math.ceil(0.6 * len(g))
        held = Counter(cid for t in dict.fromkeys(g) for cid in post[t])
        cands = [cid for cid, k in held.items() if k >= need]
        rows = _chunk_rows(conn, cands)
        for cid in cands:
            row = rows.get(cid)
            if row is None:
                continue
            if rest and sum(cid in post.get(t, ()) for t in rest) < 0.5 * len(rest):
                continue
            text = fold_text(row["text"] or "").lower()
            run = next(
                (
                    w
                    for w in range(len(g), need - 1, -1)
                    if any(string(g[a : a + w]).lower() in text for a in range(len(g) - w + 1))
                ),
                0,
            )
            if not run:
                continue
            slot = found.setdefault(cid, {"row": {**dict(row), "score": 0.0}, "terms": 0, "bm25": 0.0})
            slot["terms"] += 1
            slot["bm25"] += float(run)


_VALUE_LEAD = re.compile(r"(?:\b(?:equals?|named|called)|[=:])\s*[\"']?$", re.I)
_IS_LEAD = re.compile(r"(\w+)\s+(?:is|are|was|were)\s*[\"']?$", re.I)
_WH_WORDS = {"how", "what", "where", "who", "which", "when", "why", "whom", "whose"}
_MODIFIER_LEAD = re.compile(
    r"\b(?:in|at|near|from|during|around|within|inside|outside|since|until|before|after|on|by)\s+(?:the\s+)?[\"']?$", re.I)


def _named_as_value(query: str, term: str) -> bool:
    """Is this name a value that identifies something else, or a place or time that only
    sets the scene ("whose headquarters city is Tromso", "meals in Tromso")? Either way a
    chunk that merely says the name is not the answer. A name that is the subject ("how
    long does Mikulawex keep ...", "for the Mikulawex account") is neither."""
    for m in re.finditer(re.escape(term), query or ""):
        lead = query[max(0, m.start() - 24):m.start()]
        if _VALUE_LEAD.search(lead) or _MODIFIER_LEAD.search(lead):
            return True
        mi = _IS_LEAD.search(lead)
        if mi and mi.group(1).lower() not in _WH_WORDS:
            return True
    return False


def exact_term_search(
    space_id: int, query: str, *, lowercase: bool = False, relaxed: bool = False
) -> list[RankedHit]:
    """Chunks holding a name or code from the question that is RARE in this space.

    Someone who types "Halvorsen" or "ZQ-4471" wants the few places that say it.
    Rank fusion alone buries that chunk: it wins the keyword channel, but any chunk
    that is merely similar in two channels outvotes it. Common terms are left to the
    normal channels - a term in more than EXACT_MAX_DF chunks proves nothing.

    A code is never incidental, so it counts on its own. A capitalised word can be:
    "reimbursement for meals in Tromso" must not be pulled to a chunk that only
    says the office is in Tromso. A name therefore counts only where the chunk also
    covers at least half of what else the question asks about.

    `relaxed` is the reverse case: a name that sits in only NAME_MAX_DF chunks, held by
    a chunk that does not echo the question's other words. "For how long does Wexganpim
    keep its records" is answered by "The retention period for the Wexganpim account is
    ...", which shares nothing but the name. Those chunks get a vote of their own, at
    ordinary weight, so a rare name is not out-voted by chunks that only share
    "records" and "code" - and it stays a vote, not an override.
    """
    store.init()
    found: dict[int, dict] = {}
    terms = identifier_terms(query)
    content = _content_tokens(query)
    if lowercase:
        # A lowercase name is also where typos live ("halvorsn"). Correct words the
        # space has never seen against its own vocabulary before looking them up.
        try:
            from rag import spell

            query = spell.correct_query(query, space_id)
        except Exception:
            pass
        content = _content_tokens(query)
        # People type names in lowercase. Any longer word of the question may be one;
        # the rarity limit and the coverage rule decide, not the capital letter. Kept
        # as a separate, ordinary-weight channel: a rare lowercase word is weaker
        # evidence of a name than a capital or a code, and at full weight it took
        # rank 1 from the chunk that matched the capitalised name.
        # Longer than 4 letters for ASCII; a Korean or Arabic word says as much in 3.
        seen = {t for term in terms for t in sira.tokenize(fold_text(term))}
        terms = [
            t for t in sira.tokenize(fold_text(query))
            if len(t) >= (5 if t.isascii() else 3) and t in content and t not in seen
        ]
    with store._conn() as conn:
        for term in terms:
            parts = re.findall(r"[^\W_]+", term.lower())
            if not parts:
                continue
            try:
                rows = conn.execute(
                    """
                    SELECT c.id, c.text, c.path, c.heading, c.parent_id, c.source_id, c.authority,
                           bm25(chunks_fts) AS score
                    FROM chunks_fts
                    JOIN chunks c ON c.id = chunks_fts.chunk_id
                    WHERE chunks_fts MATCH ? AND c.space_id=? AND c.kind='child'
                    ORDER BY score, chunks_fts.rowid
                    LIMIT ?
                    """,
                    ('"' + " ".join(parts) + '"', int(space_id), EXACT_MAX_DF + 1),
                ).fetchall()
            except Exception:
                continue
            if not rows or len(rows) > (NAME_MAX_DF if relaxed else EXACT_MAX_DF):
                continue
            if relaxed and (_is_code(term) or lowercase):
                continue
            if relaxed and _named_as_value(query, term):
                # "...whose headquarters city is Tromso": the name is a value used to
                # identify something else, so a chunk that only says it is not the answer.
                continue
            rest = content - set(parts)

            def _thin(r) -> bool:
                # snake_case keys ("discount_band") are one token to the tokenizer
                have = set(sira.tokenize(fold_text(str(r["text"])).replace("_", " ")))
                return len(rest & have) < 0.5 * len(rest)

            if relaxed:
                # The index matches inside words ("Savich" inside "Savichev"); a name must
                # stand alone, or a look-alike person would be pulled in as the one asked for.
                whole = re.compile(r"(?<!\w)" + r"\W+".join(re.escape(x) for x in parts) + r"(?!\w)", re.I)
                rows = [r for r in rows if whole.search(str(r["text"]))]
                if not rows:
                    continue
            if relaxed and (not rest or any(not _thin(r) for r in rows)):
                # Some chunk with this name already echoes the question: the strict
                # channel has it. Only a name that NO chunk echoes needs the plain vote.
                continue
            for r in rows:
                if rest and not _is_code(term) and not relaxed and _thin(r):
                    continue
                slot = found.setdefault(int(r["id"]), {"row": r, "terms": 0, "bm25": 0.0})
                slot["terms"] += 1
                slot["bm25"] += -float(r["score"] or 0.0)
        if lowercase:
            _script_name_slots(conn, space_id, query, found)
    ranked = sorted(found.values(), key=lambda s: (-s["terms"], -round(s["bm25"], 6), int(s["row"]["id"])))
    return [
        RankedHit(
            doc_id=str(s["row"]["id"]),
            score=float(s["terms"]),
            payload={
                "chunk_id": int(s["row"]["id"]),
                "text": s["row"]["text"],
                "path": s["row"]["path"],
                "heading": s["row"]["heading"],
                "parent_id": int(s["row"]["parent_id"] or 0),
                "source_id": int(s["row"]["source_id"] or 0),
                "authority": s["row"]["authority"] or "",
                "channel": "name" if relaxed else "exact",
            },
        )
        for s in ranked
    ]


def dense_vector_search(space_id: int, query: str, *, k: int = 40) -> list[RankedHit]:
    """Prefer sqlite-vec / blob cosine; fall back to bag-of-tokens overlap."""
    vec_hits = vectors.search(space_id, query, k=k)
    hits: list[RankedHit] = []
    if vec_hits:
        ids = [cid for cid, _ in vec_hits]
        rows = {int(r["id"]): r for r in store.get_chunks_by_ids(ids)}
        for cid, score in vec_hits:
            r = rows.get(int(cid))
            if not r or (r.get("kind") and r.get("kind") != "child"):
                continue
            hits.append(
                RankedHit(
                    doc_id=str(cid),
                    score=float(score),
                    payload={
                        "chunk_id": int(cid),
                        "text": r.get("text"),
                        "path": r.get("path"),
                        "heading": r.get("heading"),
                        "parent_id": int(r.get("parent_id") or 0),
                        "source_id": int(r.get("source_id") or 0),
                        "channel": "dense_vector",
                    },
                )
            )
        if hits:
            return hits

    # Lexical fallback
    store.init()
    with store._conn() as conn:
        rows = conn.execute(
            "SELECT id, text, path, heading, parent_id, source_id FROM chunks "
            "WHERE space_id=? AND kind='child' ORDER BY id LIMIT 2000",
            (int(space_id),),
        ).fetchall()
    scored: list[tuple[float, Any]] = []
    for r in rows:
        s = _overlap_score(query, f"{r['heading']} {r['path']} {r['text']}")
        if s > 0:
            scored.append((s, r))
    scored.sort(key=lambda x: (-round(x[0], 6), int(x[1]["id"])))
    for s, r in scored[:k]:
        hits.append(
            RankedHit(
                doc_id=str(r["id"]),
                score=float(s),
                payload={
                    "chunk_id": int(r["id"]),
                    "text": r["text"],
                    "path": r["path"],
                    "heading": r["heading"],
                    "parent_id": int(r["parent_id"] or 0),
                    "source_id": int(r["source_id"] or 0),
                    "channel": "dense_lexical",
                },
            )
        )
    return hits


def file_level_search(space_id: int, query: str, *, k: int = 20) -> list[RankedHit]:
    store.init()
    fts_q = _fts_query(query)
    with store._conn() as conn:
        try:
            rows = conn.execute(
                """
                SELECT f.id, f.path, f.title, f.source_id, f.phrases, bm25(file_index_fts) AS score
                FROM file_index_fts
                JOIN file_index f ON f.id = file_index_fts.file_id
                WHERE file_index_fts MATCH ? AND f.space_id=?
                ORDER BY score, file_index_fts.rowid
                LIMIT ?
                """,
                (fts_q, int(space_id), int(k)),
            ).fetchall()
        except Exception:
            like = f"%{(query or '')[:40]}%"
            rows = conn.execute(
                "SELECT id, path, title, source_id, phrases, 0.0 AS score FROM file_index "
                "WHERE space_id=? AND (path LIKE ? OR title LIKE ? OR phrases LIKE ?) LIMIT ?",
                (int(space_id), like, like, like, int(k)),
            ).fetchall()
    hits: list[RankedHit] = []
    for i, r in enumerate(rows):
        raw = float(r["score"] or 0.0)
        score = 1.0 / (1.0 + max(raw, 0.0)) if raw else max(0.01, 1.0 / (i + 1))
        # Boost exact filename substring
        qlow = (query or "").lower()
        path = (r["path"] or "").lower()
        if qlow and (qlow in path or Path_name(r["path"]).lower() in qlow):
            score += 0.5
        hits.append(
            RankedHit(
                doc_id=f"file:{r['id']}",
                score=score,
                payload={
                    "file_index_id": int(r["id"]),
                    "path": r["path"],
                    "title": r["title"],
                    "source_id": int(r["source_id"] or 0),
                    "channel": "file",
                },
            )
        )
    return hits


def Path_name(path: str) -> str:
    from pathlib import Path

    return Path(path or "").name


def expand_parents(hits: list[dict], *, max_parents: int = 8) -> list[dict]:
    """Replace/augment child hits with parent context for generation."""
    out: list[dict] = []
    seen_parents: set[int] = set()
    for h in hits:
        pid = int(h.get("parent_id") or 0)
        if pid and pid not in seen_parents:
            parent = store.get_chunk(pid)
            if parent:
                seen_parents.add(pid)
                out.append(
                    {
                        **h,
                        "text": parent.get("text") or h.get("text"),
                        "parent_id": pid,
                        "expanded": True,
                        "heading": parent.get("heading") or h.get("heading"),
                    }
                )
                if len(out) >= max_parents:
                    break
                continue
        out.append(h)
        if len(out) >= max_parents:
            break
    return out


def search(
    space_id: int,
    query: str,
    *,
    depth: str | None = "high",
    top_k: int = 8,
    debug: bool = False,
    source_ids: list[int] | None = None,
) -> dict:
    """Hybrid search with optional SiRA-constrained expansion terms.

    source_ids narrows the answer to specific files — "ask this question of the lab
    report only" — instead of letting the whole space vote.
    """
    # All channels below share one connection instead of opening ~50 of their own.
    with store.session():
        return _search(
            space_id, query, depth=depth, top_k=top_k, debug=debug, source_ids=source_ids
        )


def _search(
    space_id: int,
    query: str,
    *,
    depth: str | None = "high",
    top_k: int = 8,
    debug: bool = False,
    source_ids: list[int] | None = None,
) -> dict:
    space = store.get_space(space_id)
    if not space:
        return {"ok": False, "error": "space not found"}

    if not depth or str(depth).strip().lower() == "auto":
        depth = adaptive.resolve_depth(space_id, depth)
    depth = str(depth).lower()
    arch = ""
    if depth == "manual":
        # Manual = user-picked architecture preset stored on the space; map to an
        # internal base pipeline. Never invented at runtime — preset ids only.
        arch = str(((space.get("config") or {}).get("architecture")) or "hybrid_rrf").lower()
        base = "max" if arch in ("agentic", "graph", "hybrid_kg") else "high"
    elif depth in ("basic", "high", "max"):
        base = depth
    else:
        depth = base = "high"

    # Collect phrases for constrained expansion (skipped on Basic: one-pass hybrid)
    expand_terms: list[str] = []
    expanded_q = query
    if base != "basic":
        store.init()
        with store._conn() as conn:
            phrase_rows = conn.execute(
                "SELECT phrases FROM file_index WHERE space_id=? LIMIT 200",
                (int(space_id),),
            ).fetchall()
        import json

        phrases_by_doc: list[list[str]] = []
        all_phrases: list[str] = []
        for r in phrase_rows:
            try:
                ph = json.loads(r["phrases"] or "[]")
            except Exception:
                ph = []
            phrases_by_doc.append(ph)
            all_phrases.extend(ph)
        df = sira.corpus_df(phrases_by_doc) if phrases_by_doc else {}
        expand_terms = sira.expand_query(
            query,
            index_phrases=all_phrases,
            df=df,
            n_docs=max(1, len(phrases_by_doc)),
        )
        expanded_q = " ".join([query] + [t for t in expand_terms if t.lower() not in (query or "").lower()])

    sparse_k = 60 if base == "max" else (20 if base == "basic" else 40)
    dense_k = sparse_k
    # Primary channels run the ORIGINAL query so exact matches keep their precise
    # rank; SiRA expansion is a SEPARATE recall channel that only adds candidates
    # the exact query missed — widening recall without diluting MRR.
    sparse = sparse_search(space_id, query, k=sparse_k)
    dense = dense_vector_search(space_id, query, k=dense_k)
    try:
        from rag.vector_backends import last_search_meta

        dense_meta = last_search_meta()
    except Exception:
        dense_meta = {}
    files = file_level_search(space_id, query, k=20)
    channels = {"sparse": sparse, "dense": dense, "file": files}
    scripted = script_search(space_id, query, k=sparse_k)
    if scripted:
        channels["script"] = scripted
    if expanded_q and expanded_q.strip() != (query or "").strip():
        channels["expand"] = sparse_search(space_id, expanded_q, k=sparse_k)

    exact = exact_term_search(space_id, query)
    if exact:
        channels["exact"] = exact
    rare = exact_term_search(space_id, query, lowercase=True)
    if rare:
        channels["rare"] = rare
    dense_w = dense_weight()
    named = exact_term_search(space_id, query, relaxed=True)
    if named:
        # The name says WHICH few chunks; it cannot say which of them answers. Its own
        # order is how strongly the name matched, so its first-place vote went to the
        # shortest chunk with the name. Order them by what the other channels already
        # found, at equal weight: among a handful of chunks the vector channel's
        # word-piece match is what tells the reworded attribute apart, whatever its
        # weight across the whole space.
        others = fuse_channels(
            channels, k=60, top_n=len(named) + 10**4,
            weights={"exact": EXACT_WEIGHT},
        )
        seen_at = {h.doc_id: i for i, h in enumerate(others)}
        named.sort(key=lambda h: seen_at.get(h.doc_id, len(seen_at)))  # stable
        channels["name"] = named

    fused = fuse_channels(
        channels,
        k=60,
        top_n=50 if base == "max" else (20 if base == "basic" else 30),
        weights={"exact": EXACT_WEIGHT, "name": NAME_WEIGHT, "dense": dense_w},
    )

    # Keep chunk hits primarily; attach file hits as metadata boosts
    chunk_hits: list[dict] = []
    file_hits: list[dict] = []
    for fh in fused:
        if fh.doc_id.startswith("file:"):
            file_hits.append({"doc_id": fh.doc_id, "score": fh.fused_score, **fh.payload, "channel_scores": fh.channel_scores})
            continue
        payload = dict(fh.payload)
        payload.update(
            {
                "doc_id": fh.doc_id,
                "score": fh.fused_score,
                "channel_scores": fh.channel_scores,
            }
        )
        chunk_hits.append(payload)

    # File scoping happens after fusion so every channel still contributes its ranking
    # within the chosen files, rather than each channel silently returning fewer hits.
    if source_ids:
        wanted = {int(s) for s in source_ids if str(s).strip()}
        if wanted:
            chunk_hits = [h for h in chunk_hits if int(h.get("source_id") or 0) in wanted]
            file_hits = [f for f in file_hits if int(f.get("source_id") or 0) in wanted]

    # Prefer files that match: chunks of a file the file-level search ranked high get
    # one more rank vote, sized like any other channel's. This was a flat +0.05,
    # three times a first-place vote, so with more than five files in a space every
    # chunk of a favoured file outranked the chunk that actually held the answer.
    hot_rank = {int(f.get("source_id") or 0): i for i, f in enumerate(file_hits[:5], start=1)}
    for h in chunk_hits:
        rank = hot_rank.get(int(h.get("source_id") or 0))
        if rank:
            h["score"] = float(h.get("score") or 0) + 1.0 / (60 + rank)

    # Tag and weight by source class. A space that has swallowed 1000+ chat transcripts
    # would otherwise rank the assistant's own past answers above fetched documents —
    # which is how a fabricated netie.ai description came back as cited evidence.
    space = store.get_space(space_id) or {}
    cfg = space.get("config") if isinstance(space.get("config"), dict) else {}
    # Default True: still retrieve (downweighted) for "what did we decide…".
    # False: zero conversation scores so they cannot compete with docs/web.
    chats_as_evidence = True if "chats_as_evidence" not in cfg else bool(cfg.get("chats_as_evidence"))
    for h in chunk_hits:
        # Prefer the class stored at ingest; fall back to path inference for rows
        # written before the column existed.
        kind = h.get("authority") or authority.classify(
            h.get("path") or "", h.get("heading") or ""
        )
        h["authority"] = kind
        w = authority.weight(kind)
        if kind == authority.CONVERSATION and not chats_as_evidence:
            w = 0.0
        h["score"] = float(h.get("score") or 0) * w

    if not chats_as_evidence:
        chunk_hits = [h for h in chunk_hits if h.get("authority") != authority.CONVERSATION]

    # Spreadsheet KPI bias: aggregation questions drown in detail-row chunks
    # (e.g. 100+ Revenue windows bury a 1-screen Summary sheet). Soft-boost
    # summary/KPI headings when the query looks numerical/aggregative.
    _kpi_q = re.search(
        r"\b(total|sum|revenue|expense|margin|quarter|kpi|percent|%|average|agg|highest|lowest)\b",
        query or "",
        re.I,
    )
    if _kpi_q:
        _kpi_head = re.compile(r"\b(summary|kpi|dashboard|overview|totals?)\b", re.I)
        for h in chunk_hits:
            head = str(h.get("heading") or "")
            text = str(h.get("text") or "")
            boost = 0.0
            if _kpi_head.search(head):
                boost += 0.35
            elif len(text) < 900 and _kpi_head.search(text[:240]):
                boost += 0.2
            if boost:
                h["score"] = float(h.get("score") or 0) + boost
                h["sheet_kpi_boost"] = boost

    # Rounded score; ties keep the fused order (stable sort). The same question must
    # rank the same on every machine: float noise in the last bits and undefined
    # database tie order did not guarantee that.
    chunk_hits.sort(key=lambda x: -round(float(x.get("score") or 0), 9))

    # Cross-encoder rerank after RRF (feature-flagged; soft-falls to RRF order)
    chunk_hits = rerank_hits(query, chunk_hits, top_n=min(len(chunk_hits), 40 if base == "max" else 30))

    expanded = expand_parents(chunk_hits, max_parents=top_k)
    clean_cites = []
    for h in expanded:
        cid = int(h.get("chunk_id") or h.get("doc_id") or 0)
        meta = store.get_chunk(cid) or {}
        clean_cites.append(
            {
                "chunk_id": cid,
                "path": h.get("path") or meta.get("path"),
                "heading": h.get("heading") or meta.get("heading"),
                "span_start": meta.get("span_start"),
                "span_end": meta.get("span_end"),
                "parent_id": meta.get("parent_id") or h.get("parent_id"),
                "score": h.get("score"),
                "excerpt": (h.get("text") or "")[:280],
            }
        )

    trace_id = uuid.uuid4().hex[:16]
    if depth == "manual":
        template_id = f"manual_{arch}"
    else:
        template_id = {
            "basic": "modular_hybrid_basic",
            "high": "modular_hybrid_high",
            "max": "modular_agentic_max",
        }[base]
    payload = {
        "expand_terms": expand_terms,
        "expanded_query": expanded_q,
        "n_sparse": len(sparse),
        "n_dense": len(dense),
        "n_file": len(files),
        "n_fused_chunks": len(chunk_hits),
        "dense_weight": dense_w,
        "fusion_note": (
            "Built-in word-piece matcher in use: its vector ranking counts for 0.6 of the "
            "word-index ranking (measured on the paraphrase test set: more questions found in "
            "the top five and none fewer at rank 1 than at full weight)."
            if dense_w < 1.0 else
            "Embedding model in use: vector ranking counts as much as the word index."
        ),
        "backend_fallback": dense_meta.get("backend_fallback"),
        "vector_profile": dense_meta.get("profile") or space.get("profile") or "local",
    }
    if debug:
        payload["top_fused"] = [
            {"doc_id": f.doc_id, "score": f.fused_score, "channels": f.channel_scores} for f in fused[:12]
        ]
    store.save_trace(
        trace_id,
        space_id=space_id,
        query=query,
        depth=depth,
        template_id=template_id,
        payload=payload,
    )
    return {
        "ok": True,
        "space_id": space_id,
        "query": query,
        "depth": depth,
        "template_id": template_id,
        "hits": expanded,
        "files": file_hits[:10],
        "citations": clean_cites,
        "trace_id": trace_id,
        "debug": payload if debug else {"expand_terms": expand_terms},
    }

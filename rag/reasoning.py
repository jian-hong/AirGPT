"""Founder-readable reasoning chains for RAG answers (EPIC-D01 #15).

The ontology lane already emitted steps, but they were op codes - `bind_entities`,
`select_logic` - which tell a founder that something happened without telling them
what. This turns the evidence the lanes already produce into sentences a
non-engineer can check: which sheet was read, which columns were bound, what ran,
how many rows it covered, and what was missing.

Nothing here computes an answer. It reports the provenance the SQL lane (#21) and
the retrieval lane already carry, so a chain can never claim a step the run did not
take. When a field is absent the step is omitted rather than filled in.
"""
from __future__ import annotations

from typing import Any

MAX_SOURCES_SHOWN = 4


def _step(n: int, title: str, detail: str) -> dict[str, Any]:
    return {"n": n, "title": title, "detail": detail}


def _where(workbook: Any, sheet: Any) -> str:
    """"the Sales sheet of book.xlsx", or "table 2 of memo.docx" for a table inside a document."""
    try:
        from rag.sheet_sql import where_phrase

        return where_phrase(str(workbook), str(sheet))
    except Exception:
        return f"the {sheet} sheet of {workbook}"


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _num(value: Any) -> str:
    """Same rounding the answer text uses - a chain that says 0.9440740740740741
    beside an answer of 0.9441 reads like two different results."""
    try:
        from rag.sheet_sql import _round  # noqa: SLF001

        return _round(float(value))
    except Exception:
        return str(value)


def _source_label(hit: dict) -> str:
    """What to call a source in the chain. Titles win; when a hit carries only a
    path, show the file name - a founder reading "what I read" wants
    wh_01_sales_core.xlsx, not D:\\AirGPT\\tests\\RAG\\warehouse\\wh_01_sales_core.xlsx."""
    title = str(hit.get("title") or "").strip()
    if title:
        return title
    path = str(hit.get("path") or "").strip()
    if not path:
        return ""
    return path.replace("\\", "/").rstrip("/").split("/")[-1] or path


def _summary_text(summary: Any) -> str:
    """The ontology summary is a counts dict, not prose. Say it in words rather than
    printing the repr at a founder."""
    if isinstance(summary, str):
        return summary.strip()
    if not isinstance(summary, dict):
        return ""
    ents = [str(e) for e in (summary.get("entity_ids") or []) if str(e).strip()]
    bits = []
    nw = summary.get("n_workbooks")
    if isinstance(nw, int) and nw:
        bits.append(f"{nw} {_plural(nw, 'workbook', 'workbooks')}")
    if ents:
        bits.append(f"{len(ents)} {_plural(len(ents), 'entity', 'entities')} ({', '.join(ents)})")
    nr = summary.get("n_relations")
    if isinstance(nr, int) and nr:
        bits.append(f"{nr} {_plural(nr, 'relation', 'relations')} between them")
    return ", ".join(bits)


def render(steps: list[dict]) -> str:
    """Numbered prose - what gets shown when there is no room for a table."""
    return "\n".join(f"{s['n']}. {s['title']}: {s['detail']}" for s in steps)


def chain_for_sql(query: str, prov: dict | None, *, ontology_summary: Any = "") -> dict:
    """Reasoning chain for the structured lane, from #21's SQL provenance."""
    prov = prov or {}
    linked = prov.get("linked") or {}
    steps: list[dict] = []
    n = 0

    metric = str(linked.get("metric") or "").strip()
    filters = [str(f) for f in (linked.get("filters") or []) if str(f).strip()]
    sheet = str(prov.get("sheet") or "").strip()
    workbook = str(prov.get("workbook") or "").strip()
    sql = str(prov.get("sql") or "").strip()

    n += 1
    if metric and filters:
        asked = f"{metric}, restricted by {', '.join(filters)}"
    elif metric:
        asked = metric
    elif linked.get("all_numeric"):
        asked = "no column was named, so every numeric column is in scope"
    else:
        asked = "a figure from the workbook"
    steps.append(_step(n, "What you asked for", asked))

    if workbook and sheet:
        n += 1
        steps.append(
            _step(n, "Where I found it", _where(workbook, sheet))
        )
    _onto = _summary_text(ontology_summary)
    if _onto:
        n += 1
        steps.append(_step(n, "What this space holds", _onto))

    if metric or filters:
        n += 1
        bound = []
        if metric:
            bound.append(f"{metric} as the figure to compute")
        for f in filters:
            bound.append(f"{f} as a filter")
        steps.append(
            _step(
                n,
                "Which columns I used",
                "; ".join(bound) + " - matched against the sheet header, not guessed from the wording",
            )
        )

    if sql:
        n += 1
        steps.append(_step(n, "What I ran", sql))

    matched = prov.get("rows_matched")
    total = prov.get("rows_total")
    if isinstance(matched, int) and isinstance(total, int) and total:
        n += 1
        pct = (matched / total) * 100 if total else 0.0
        detail = (
            f"{matched:,} of {total:,} {_plural(total, 'row', 'rows')} met the filter "
            f"({pct:.1f}% of the sheet)"
        )
        if matched == 0:
            detail += " - so there is nothing to average, and 0 would be a wrong answer, not a measurement"
        steps.append(_step(n, "How much of the sheet that covered", detail))

    row_note = str(prov.get("row_note") or "").strip()
    if row_note:
        n += 1
        steps.append(
            _step(
                n,
                "How spreadsheet rows map to data rows",
                f"{row_note} - these sheets carry a banner above the header, "
                f"so the spreadsheet row number is not the data row number",
            )
        )

    if prov.get("abstained"):
        n += 1
        amb = prov.get("ambiguous") or []
        reason = str(prov.get("abstain_reason") or "").strip()
        if amb:
            detail = (
                f"more than one column could be meant ({', '.join(str(a) for a in amb)}), "
                f"so I stopped rather than pick one"
            )
        elif reason:
            # The lane's own words. Paraphrasing here would let the chain and the
            # answer text drift apart on the one path where honesty is the point.
            detail = f"{reason} - so I stopped rather than answer from a guess"
        else:
            detail = "the schema resolved but no rows qualified, so I reported that instead of a number"
        steps.append(_step(n, "Why I did not give a number", detail))
    else:
        n += 1
        if prov.get("per_column"):
            cols = prov.get("per_column") or []
            detail = (
                f"reported {len(cols)} numeric {_plural(len(cols), 'column', 'columns')} "
                f"because none was named"
            )
        elif prov.get("value") is not None:
            detail = f"{_num(prov.get('value'))} - computed from the rows above, not from a text chunk"
        else:
            detail = "computed from the rows above, not from a text chunk"
        steps.append(_step(n, "The answer", detail))

    return {
        "lane": "sql",
        "steps": steps,
        "text": render(steps),
        "checkable": bool(sql and workbook and sheet),
    }


def chain_for_inventory(query: str, *, source_count: int, mode: str = "", depth: str = "") -> dict:
    """Reasoning chain for the 'what is in this space' lane, which does not retrieve."""
    steps = [
        _step(1, "What you asked for", "an inventory of this space, not an answer from inside it"),
        _step(
            2,
            "What I did instead of searching",
            "listed every indexed source directly - a topical search would rank files "
            "and quietly drop the ones it ranked last, which is the wrong answer to "
            "'what is in here'",
        ),
    ]
    if source_count:
        steps.append(
            _step(3, "What is indexed", f"{source_count:,} {_plural(source_count, 'source', 'sources')}, all listed below")
        )
    else:
        steps.append(_step(3, "What is indexed", "nothing yet - add sources on the Build tab"))
    steps.append(
        _step(4, "The answer", f"the full list, compiled by {mode or 'the inventory pass'}")
    )
    return {"lane": "inventory", "steps": steps, "text": render(steps), "checkable": True}


def chain_for_retrieval(
    query: str,
    *,
    depth: str = "",
    hits: list | None = None,
    citations: list | None = None,
    goal: dict | None = None,
    coverage: Any = None,
    stop_reason: str = "",
    model: str = "",
    faithfulness: Any = None,
    web_used: bool = False,
    ontology_summary: Any = "",
) -> dict:
    """Reasoning chain for the retrieval lane - what was searched, read, and withheld."""
    hits = hits or []
    citations = citations or []
    goal = goal or {}
    steps: list[dict] = []
    n = 0

    n += 1
    steps.append(_step(n, "What you asked for", (query or "").strip() or "(empty ask)"))

    _onto = _summary_text(ontology_summary)
    if _onto:
        n += 1
        steps.append(_step(n, "What this space holds", _onto))

    n += 1
    sources = {_source_label(h) for h in hits if isinstance(h, dict)}
    sources.discard("")
    if hits:
        detail = (
            f"searched the space at {depth or 'high'} depth and kept {len(hits)} "
            f"{_plural(len(hits), 'passage', 'passages')}"
        )
        if sources:
            detail += f" from {len(sources)} {_plural(len(sources), 'file', 'files')}"
    else:
        detail = f"searched the space at {depth or 'high'} depth and nothing matched"
    steps.append(_step(n, "Where I looked", detail))

    if sources:
        n += 1
        shown = sorted(sources)[:MAX_SOURCES_SHOWN]
        more = len(sources) - len(shown)
        detail = ", ".join(shown) + (f", and {more} more" if more > 0 else "")
        steps.append(_step(n, "What I read", detail))

    if web_used:
        n += 1
        steps.append(
            _step(n, "What I pulled from the web", "the local corpus was thin, so web results were ingested first")
        )

    verdict = str(goal.get("verdict") or "").strip()
    diagnosis = [str(d) for d in (goal.get("diagnosis") or []) if str(d).strip()]
    # A refusal is a policy decision, not an evidence verdict. "stopped because policy
    # refuse" alongside "Why I refused" says the same thing twice, the first time badly.
    if stop_reason != "policy_refuse" and (verdict or diagnosis or stop_reason):
        n += 1
        if verdict == "answerable":
            detail = "the passages cover the ask"
        elif verdict:
            detail = f"the evidence is {verdict.replace('_', ' ')}"
        elif stop_reason == "no_evidence":
            detail = "nothing in the space supports an answer"
        else:
            detail = f"stopped because {stop_reason.replace('_', ' ') or 'the evidence ran out'}"
        if isinstance(coverage, (int, float)):
            detail += f"; coverage {float(coverage):.2f}"
        if diagnosis:
            detail += ". Still missing: " + "; ".join(diagnosis[:3])
        steps.append(_step(n, "Whether that was enough", detail))

    if stop_reason == "policy_refuse":
        n += 1
        steps.append(
            _step(
                n,
                "Why I refused",
                "the ask was a destructive or injected instruction, not a question - "
                "so what the search found does not matter, and I did not act on it",
            )
        )
        return {"lane": "retrieval", "steps": steps, "text": render(steps), "checkable": True}

    n += 1
    detail = f"written from the passages above by {model or 'the model'}"
    if isinstance(faithfulness, (int, float)) and float(faithfulness) < 1.0:
        detail += f"; {float(faithfulness):.2f} of it traces back to a cited passage"
    if citations:
        detail += f", with {len(citations)} {_plural(len(citations), 'citation', 'citations')} you can open"
    steps.append(_step(n, "The answer", detail))

    return {"lane": "retrieval", "steps": steps, "text": render(steps), "checkable": bool(citations or hits)}

"""Paraphrase bench: can a fact be found when the user does NOT use the document's words?

filetype_bench asks "What is the retention period for the Halvorsen account?" against
"The retention period for the Halvorsen account is ZQ-4471." The question and the
answer share every key word, so it cannot see the case real users hit most: asking
in different words. This sibling plants the same kind of fact in md, docx, pdf and
xlsx (writers imported from filetype_bench) and asks each one four ways:

  verbatim   the document's own words (control; should stay at the top)
  synonym    the attribute reworded by hand ("retention period" -> "how long are
             records kept"); the entity name is kept exactly
  lower_typo the entity in lowercase with one character wrong ("halvorsen" -> "halvorzen")
  property   the entity is never named; it is identified by a property stated in a
             DIFFERENT section of the same document ("the account whose headquarters
             city is Tromso"). Needs two pieces of evidence to be joined.

All four types go into ONE space so they distract each other. No model is called, the
hash embedder is used, so this scores ingest + retrieval only. It MEASURES; it does
not tune rag/. A low number here is a recorded weakness, not a pass.

    python tests/RAG/paraphrase_bench.py              # writes results json
    python tests/RAG/paraphrase_bench.py --no-write
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import filetype_bench as fb  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results" / "paraphrase_bench_latest.json"
KINDS = ["md", "docx", "pdf", "xlsx"]
STYLES = ["verbatim", "synonym", "lower_typo", "property"]
N_PER_KIND = 16  # 64 planted facts in all

# Hand-written rewordings, two per attribute, none of which reuses the attribute's
# words. The entity is kept verbatim so only the attribute side is being tested.
SYNONYMS = {
    "retention period": ["How long are records kept for the {e} account?",
                         "For how much time does the {e} account hold on to its data before deleting it?"],
    "escalation code": ["Which code do I quote to push a problem up the chain on the {e} account?",
                        "If something goes wrong with the {e} account, what code gets it taken to a manager?"],
    "billing cycle": ["How often is the {e} account invoiced?",
                      "On what rhythm does {e} get sent a bill?"],
    "renewal window": ["When is the {e} account allowed to sign up for another term?",
                       "During which dates can the {e} contract be extended?"],
    "audit reference": ["Which number do inspectors use to look up the {e} account?",
                        "What ID should I cite when the {e} account is reviewed by auditors?"],
    "support tier": ["What level of help is the {e} account entitled to?",
                     "Which service class applies when the {e} account asks for assistance?"],
    "shipping lane": ["Which route do goods for the {e} account travel along?",
                      "How are parcels for {e} sent out?"],
    "discount band": ["What price reduction bracket is the {e} account placed in?",
                      "Which rebate level does the {e} account fall under?"],
    "contract owner": ["Which identifier marks the party that owns the {e} agreement?",
                       "Who is on the hook for the {e} contract, by their registered ID?"],
    "compliance tag": ["Which label marks the {e} account for regulatory purposes?",
                       "What regulatory marker is attached to the {e} account?"],
}

# Each entity also gets one property stated elsewhere in the document. Hand-picked
# so no two are alike and none is a common word.
CITIES = [
    "Tromso", "Kragero", "Lillesand", "Haugesund", "Odense", "Aalborg", "Esbjerg", "Vaasa",
    "Tampere", "Oulu", "Gdynia", "Torun", "Lodz", "Brno", "Plzen", "Ostrava",
    "Graz", "Linz", "Salzburg", "Innsbruck", "Basel", "Lugano", "Fribourg", "Neuchatel",
    "Porto", "Braga", "Faro", "Coimbra", "Girona", "Burgos", "Leon", "Vigo",
    "Cork", "Galway", "Limerick", "Derry", "Leeds", "Hull", "Bath", "Truro",
    "Parma", "Modena", "Bari", "Lecce", "Pisa", "Siena", "Trento", "Aosta",
    "Dijon", "Nantes", "Rennes", "Lille", "Metz", "Brest", "Arles", "Tours",
    "Bergen", "Skien", "Narvik", "Alta", "Kiruna", "Lulea", "Umea", "Visby",
]
PROP_ATTR = "headquarters city"


def _typo(name: str, rng: random.Random) -> str:
    """Lowercase, then change one interior letter to a different one."""
    s = name.lower()
    i = rng.randrange(1, len(s) - 1)
    repl = rng.choice([c for c in "abcdefghijklmnopqrstuvwxyz" if c != s[i]])
    return s[:i] + repl + s[i + 1:]


def build_plan(seed: int = 1):
    """-> {kind: (facts_for_writer, [question dicts])}. Main facts fill the first
    sections, their property lines come after them, so the two are never together."""
    rng = random.Random(f"paraphrase:{seed}")
    used_ent, used_val, plan = set(), set(), {}
    city_i = 0
    for kind in KINDS:
        mains, s = [], seed
        while True:  # entity names and values must be unique across ALL types
            cand = fb.make_facts(kind, N_PER_KIND, s)
            if not any(f.entity in used_ent or f.value in used_val for f in cand):
                mains = cand
                break
            s += 1000
        used_ent.update(f.entity for f in mains)
        used_val.update(f.value for f in mains)
        props = []
        for f in mains:
            props.append(fb.Fact(f.entity, PROP_ATTR, CITIES[city_i], 0))
            city_i += 1
        allf = mains + props
        for i, f in enumerate(allf):
            f.group = i // fb.GROUP
        qs = []
        for i, (f, p) in enumerate(zip(mains, props)):
            e = f.entity
            qs += [
                {"style": "verbatim", "q": f"What is the {f.attr} for the {e} account?", "f": f},
                {"style": "synonym", "q": SYNONYMS[f.attr][i % 2].format(e=e), "f": f},
                {"style": "lower_typo",
                 "q": f"what is the {f.attr} for the {_typo(e, rng)} account?", "f": f},
                {"style": "property",
                 "q": f"What is the {f.attr} for the account whose {PROP_ATTR} is {p.value}?", "f": f},
            ]
        plan[kind] = (allf, qs)
    return plan


def run(seed: int = 1, top_k: int = 5) -> dict:
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
        sid = int(store.create_space("paraphrase bench", depth_default="high")["id"])
        corpus = root / "corpus"
        corpus.mkdir()
        plan = build_plan(seed)
        for kind, (facts, _) in plan.items():
            fb.TYPES[kind](corpus / f"register_{kind}.{kind}", facts)
        ingest.ingest_paths(sid, [corpus / f"register_{k}.{k}" for k in plan])

        def cell():
            return {"n": 0, "recall_at_1": 0, "recall_at_5": 0}

        by_style = {s: cell() for s in STYLES}
        by_type = {k: {s: cell() for s in STYLES} for k in KINDS}
        misses = {s: [] for s in STYLES}
        for kind, (_, qs) in plan.items():
            for item in qs:
                hits = retrieve.search(sid, item["q"], depth="high", top_k=top_k).get("hits") or []
                rank = next((i for i, h in enumerate(hits) if item["f"].value in str(h.get("text") or "")), None)
                for c in (by_style[item["style"]], by_type[kind][item["style"]]):
                    c["n"] += 1
                    c["recall_at_5"] += int(rank is not None)
                    c["recall_at_1"] += int(rank == 0)
                if rank is None and len(misses[item["style"]]) < 4:
                    misses[item["style"]].append(f"[{kind}] {item['q']}")
        return {
            "bench": "paraphrase_bench",
            "seed": seed, "top_k": top_k,
            "n_facts": sum(len(q) for _, q in plan.values()) // len(STYLES),
            "n_questions": sum(len(q) for _, q in plan.values()),
            "index_fingerprint": index_fingerprint.fingerprint(extra={"pack": "paraphrase_bench"}),
            "honesty": "retrieval only, hash embedder, synthetic facts, hand-written paraphrases, "
                       "no model call. Counts on 64 facts, not rates: a score here says nothing "
                       "about real documents. Measures; rag/ was not tuned to it.",
            "styles": by_style, "types": by_type, "sample_misses": misses,
        }
    finally:
        store.RAG_DIR, store.DB_PATH, store.BLOB_DIR = saved
        embed.reset_embedder_cache()
        tmp.cleanup()


def render(res: dict) -> str:
    out = [f"{res['n_facts']} facts x {len(STYLES)} styles = {res['n_questions']} questions",
           "", f"{'style':<11}" + "".join(f"{k:>12}" for k in KINDS) + f"{'ALL r@1':>10}{'ALL r@5':>10}"]
    for s in STYLES:
        row = f"{s:<11}"
        for k in KINDS:
            c = res["types"][k][s]
            row += f"{c['recall_at_1']:>5}/{c['recall_at_5']:>2}/{c['n']:<2}"
        a = res["styles"][s]
        out.append(row + f"{a['recall_at_1']:>6}/{a['n']:<3}{a['recall_at_5']:>6}/{a['n']:<3}")
    out.append("(per type cells are r@1/r@5/n)")
    weak = [s for s in STYLES if res["styles"][s]["recall_at_5"] < res["styles"][s]["n"]]
    out.append("")
    out.append("styles that miss at r@5: " + (", ".join(
        f"{s} ({res['styles'][s]['n'] - res['styles'][s]['recall_at_5']} missed)" for s in weak) or "none"))
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    res = run(args.seed)
    print(render(res))
    if not args.no_write:
        RESULTS.parent.mkdir(parents=True, exist_ok=True)
        RESULTS.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {RESULTS}")

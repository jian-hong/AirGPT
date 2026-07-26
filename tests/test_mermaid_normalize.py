"""Tests for framed-flowchart Mermaid normalisation (no circle mindmaps)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mermaid_normalize import clean_label, mindmap_from_edges, normalize_block, normalize_text  # noqa: E402

BROKEN = """mindmap
  root((Jae Hoong & Netie.ai))
    Jae Hoong (Founder & CEO) --> LinkedIn Profile (https://linkedin.com/in/jhoo)
    Jae Hoong --> Experience (ML, AI, Entrepreneurship)
    Netie.ai (http://netie.ai/) --> AI-Powered Search
    Netie.ai --> Knowledge Discovery
    Netie.ai --> Semantic Search
"""


def test_broken_mindmap_becomes_flowchart():
    out = normalize_block(BROKEN)
    assert out.startswith("flowchart TD")
    assert "mindmap" not in out
    assert "root((" not in out
    assert '(["' in out  # stadium root / leaves


def test_repeated_parent_becomes_one_frame():
    out = normalize_block(BROKEN)
    # One subgraph (or node label) for Netie.ai, one for Jae Hoong
    assert out.count('["Netie.ai') + out.count('Netie.ai —') >= 1
    assert out.lower().count("netie.ai") >= 1
    assert out.count("Semantic Search") == 1
    assert out.count("Knowledge Discovery") == 1


def test_no_circle_roots():
    out = normalize_block(BROKEN)
    assert "((" not in out


def test_parentheses_become_em_dash_asides():
    out = normalize_block(BROKEN)
    assert "Experience — ML, AI, Entrepreneurship" in out
    assert "(Founder" not in out


def test_plain_mindmap_rewritten_to_frames():
    src = "mindmap\n  root((Ideas))\n    Research\n      Papers\n    Build\n"
    out = normalize_block(src)
    assert out.startswith("flowchart TD")
    assert "subgraph" in out
    assert "Ideas" in out
    assert "Research" in out and "Papers" in out


def test_mixed_indentation_and_arrows():
    src = "mindmap\n  root((App))\n    Backend\n      DB --> Postgres\n      DB --> Redis\n"
    out = normalize_block(src)
    assert out.count("Postgres") == 1 and out.count("Redis") == 1
    assert out.count('["DB"]') + out.count('(["DB"])') + out.count('DB"') >= 1


def test_missing_root_is_synthesised():
    out = normalize_block("mindmap\n  Project Netie\n    Cortex\n    Vanguard\n")
    assert "Project Netie" in out
    assert out.startswith("flowchart TD")


def test_flowchart_is_not_touched():
    src = "flowchart TD\n  A[Start] --> B{Choice}\n  B --> C[End]"
    assert normalize_block(src) == src


def test_goal_nodes_use_triangle():
    out = normalize_block("mindmap\n  root((Plan))\n    Goal Ship\n      Detail\n")
    assert "shape: tri" in out


def test_normalize_text_rewrites_only_mermaid_fences():
    md = "Intro\n\n```mermaid\n" + BROKEN + "```\n\n```python\nx = 1\n```\n"
    out = normalize_text(md)
    assert "x = 1" in out
    assert "flowchart TD" in out
    assert "mindmap" not in out.split("```python")[0]


def test_edges_helper_merges_parents():
    out = mindmap_from_edges(
        [("Netie.ai", "Cortex"), ("Netie.ai", "Vanguard"), ("Netie.ai", "Closer")],
        root_label="Netie",
    )
    assert out.startswith("flowchart TD")
    assert out.count("Cortex") == 1
    assert "Netie" in out


def test_clean_label_handles_markdown_links_and_length():
    assert clean_label("**[Netie](https://netie.ai)**") == "Netie"
    assert clean_label("- bullet item") == "bullet item"
    assert len(clean_label("x" * 200)) <= 60


def test_wired_into_the_answer_path():
    import ai_engine

    out = ai_engine._finalize_answer("Here you go:\n\n```mermaid\n" + BROKEN + "```\n")
    assert "flowchart TD" in out
    assert "mindmap" not in out


def test_empty_and_garbage_do_not_raise():
    assert normalize_block("") == ""
    assert normalize_block("mindmap").startswith("flowchart")
    assert normalize_text("no diagrams here") == "no diagrams here"

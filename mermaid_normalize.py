"""Normalise model-authored Mermaid so diagrams render cleanly.

Models reliably get `mindmap` wrong: flowchart arrows inside mindmaps, repeated
parents, and parentheses in labels. Worse, Mermaid mindmaps draw every node as a
circle — noisy and hard to scan. This module:

1. Parses broken mindmap-ish input into a tree (merge duplicate parents).
2. Emits a **flowchart** with framed subgraphs, stadiums, rects, diamonds, and
   triangles for goals — not a pile of circles.
3. Leaves already-valid flowcharts / sequence / class diagrams untouched.

    normalize_text(markdown)   -> markdown with every ```mermaid fence normalised
    normalize_block(src)       -> one mermaid source string, normalised
    mindmap_from_edges(pairs)  -> build a framed flowchart from (parent, child) pairs
"""
from __future__ import annotations

import re

__all__ = ["normalize_text", "normalize_block", "mindmap_from_edges", "MAX_LABEL"]

FENCE_RE = re.compile(r"```[ \t]*mermaid[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)
EDGE_RE = re.compile(r"^(\s*)(.+?)\s*(?:-->|--|->|==>)\s*(.+?)\s*$")
ROOT_RE = re.compile(r"^\s*root\s*\(\((.*)\)\)\s*$", re.IGNORECASE)
MAX_LABEL = 60
MAX_DEPTH = 6
_GOAL_RE = re.compile(r"^(goal|priority|key result|north star|outcome)\b", re.I)


def _merge_key(label: str) -> str:
    return label.split(" — ", 1)[0].casefold().strip(" .")


class _Node:
    """One tree node. Children keep insertion order; duplicates merge into one."""

    __slots__ = ("label", "children", "_index")

    def __init__(self, label: str) -> None:
        self.label = label
        self.children: list[_Node] = []
        self._index: dict[str, _Node] = {}

    def child(self, label: str) -> _Node:
        # Merge on the label's head, so `Netie.ai — http://netie.ai/` and a later bare
        # `Netie.ai` are the same node. The richer label wins, so no detail is lost.
        key = _merge_key(label)
        found = self._index.get(key)
        if found is None:
            found = _Node(label)
            self._index[key] = found
            self.children.append(found)
        elif len(label) > len(found.label):
            found.label = label
        return found


def clean_label(raw: str) -> str:
    """Make a label safe for Mermaid shapes without throwing its content away.

    Mermaid treats (), [] and {} as node-shape syntax, so a label like
    `Experience (ML, AI)` is a parse error. Promote the parenthetical to an
    em-dash aside rather than deleting it.
    """
    s = (raw or "").strip().strip("`").strip()
    s = re.sub(r"^[-*+]\s+", "", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\((?:[^)]*)\)", r"\1", s)
    s = re.sub(
        r"\s*[([{]\s*([^)\]}]*?)\s*[)\]}]",
        lambda m: f" — {m.group(1)}" if m.group(1) else "",
        s,
    )
    s = s.replace("(", " ").replace(")", " ").replace("[", " ").replace("]", " ")
    s = s.replace("{", " ").replace("}", " ").replace('"', "'")
    s = re.sub(r"\s+", " ", s).strip(" —-")
    if len(s) > MAX_LABEL:
        s = s[: MAX_LABEL - 1].rstrip() + "…"
    return s


def _bare_root(raw: str) -> str:
    s = (raw or "").strip()
    m = ROOT_RE.match(s) or re.match(r"^root\s*\(\((.*)\)\)\s*$", s, re.I)
    if m:
        return clean_label(m.group(1)) or "Overview"
    return clean_label(s) or "Overview"


def _esc(label: str) -> str:
    return (label or "").replace('"', "'").replace("\n", " ").strip() or "…"


def _fmt_node(nid: str, label: str, *, role: str) -> str:
    """Shape roles: root/leaf = stadium, decision = diamond, goal = triangle, else rect."""
    lab = _esc(label)
    if role == "root" or role == "leaf":
        return f'{nid}(["{lab}"])'
    if role == "decision" or "?" in lab:
        return f'{nid}{{"{lab}"}}'
    if role == "goal" or _GOAL_RE.match(lab):
        # Mermaid 11 shape API — triangle for goals/priorities (not a circle)
        return f'{nid}@{{shape: tri, label: "{lab}"}}'
    return f'{nid}["{lab}"]'


def _role_for(label: str, *, has_kids: bool) -> str:
    if "?" in (label or ""):
        return "decision"
    if _GOAL_RE.match(label or ""):
        return "goal"
    if not has_kids:
        return "leaf"
    return "node"


def _emit_flowchart(root: _Node) -> str:
    """Framed flowchart: stadium root, subgraph branches, rect/diamond/tri children."""
    lines = ["flowchart TD"]
    ctr = [0]

    def nid() -> str:
        ctr[0] += 1
        return f"n{ctr[0]}"

    root_id = nid()
    lines.append(f"  {_fmt_node(root_id, _bare_root(root.label), role='root')}")

    def walk_inside(node: _Node, parent_id: str, depth: int, indent: str) -> None:
        if depth >= MAX_DEPTH:
            return
        for kid in node.children:
            kid_id = nid()
            role = _role_for(kid.label, has_kids=bool(kid.children))
            lines.append(f"{indent}{_fmt_node(kid_id, kid.label, role=role)}")
            lines.append(f"{indent}{parent_id} --> {kid_id}")
            if kid.children:
                walk_inside(kid, kid_id, depth + 1, indent)

    for i, branch in enumerate(root.children):
        branch_role = _role_for(branch.label, has_kids=bool(branch.children))
        if branch.children and branch_role in ("goal", "decision"):
            # A subgraph frame is always drawn as a plain rectangle, so framing a
            # goal or a question would silently drop its triangle / diamond. Keep the
            # shape and hang the children off the node instead of framing it.
            bid = nid()
            lines.append(f"  {_fmt_node(bid, branch.label, role=branch_role)}")
            lines.append(f"  {root_id} --> {bid}")
            walk_inside(branch, bid, 1, "  ")
        elif branch.children:
            sg = f"g{i}"
            lines.append(f'  subgraph {sg}["{_esc(branch.label)}"]')
            lines.append("    direction TB")
            # No anchor node here. The subgraph frame already renders `branch.label`
            # as its title, so an extra node carrying the same text drew that label
            # twice and added one redundant arrow per child - the stray arrowheads
            # that made these diagrams look broken. The frame is the entry point;
            # `root_id --> sg` below connects to it.
            for kid in branch.children:
                kid_id = nid()
                role = _role_for(kid.label, has_kids=bool(kid.children))
                lines.append(f"    {_fmt_node(kid_id, kid.label, role=role)}")
                if kid.children:
                    walk_inside(kid, kid_id, 3, "    ")
            lines.append("  end")
            lines.append(f"  {root_id} --> {sg}")
        else:
            leaf = nid()
            role = _role_for(branch.label, has_kids=False)
            lines.append(f"  {_fmt_node(leaf, branch.label, role=role)}")
            lines.append(f"  {root_id} --> {leaf}")

    lines.append("  classDef frame fill:#111111,stroke:#3a3a3a,color:#f5f5f5")
    return "\n".join(lines)


def mindmap_from_edges(pairs, root_label: str = "Overview") -> str:
    """Build a framed flowchart from (parent, child) pairs, merging repeated parents."""
    root = _Node(_bare_root(root_label))
    for parent, child in pairs:
        p = clean_label(parent)
        c = clean_label(child)
        if not p:
            continue
        node = root.child(p)
        if c:
            node.child(c)
    return _emit_flowchart(root)


def _normalize_mindmap(src: str) -> str:
    lines = [ln for ln in src.splitlines() if ln.strip() and not ln.strip().startswith("%%")]
    if lines and lines[0].strip().lower().startswith("mindmap"):
        lines = lines[1:]
    if not lines:
        return _emit_flowchart(_Node("Overview"))

    root: _Node | None = None
    body: list[str] = []
    for ln in lines:
        m = ROOT_RE.match(ln)
        if m and root is None:
            root = _Node(_bare_root(m.group(1)))
            continue
        body.append(ln)

    if root is None:
        first = body[0] if body else ""
        if not EDGE_RE.match(first):
            root = _Node(_bare_root(first))
            body = body[1:]
        else:
            root = _Node("Overview")

    stack: list[_Node] = [root]
    indents: list[int] = [-1]

    for ln in body:
        edge = EDGE_RE.match(ln)
        indent = len(ln) - len(ln.lstrip())
        while len(indents) > 1 and indent <= indents[-1]:
            indents.pop()
            stack.pop()
        parent = stack[-1]

        if edge:
            head = clean_label(edge.group(2))
            tail = clean_label(edge.group(3))
            if not head and not tail:
                continue
            node = parent.child(head) if head else parent
            if tail:
                node.child(tail)
            stack.append(node)
            indents.append(indent)
            continue

        label = clean_label(ln)
        if not label:
            continue
        node = parent.child(label)
        stack.append(node)
        indents.append(indent)

    return _emit_flowchart(root)


def normalize_block(src: str) -> str:
    """Normalise one mermaid source string.

    Mindmaps (and mindmap-shaped junk) become framed flowcharts. Other diagram
    types pass through with whitespace trim only.
    """
    s = (src or "").replace("\r\n", "\n").replace("\t", "  ").strip("\n")
    if not s.strip():
        return s
    if not re.match(r"^\s*mindmap\b", s, re.IGNORECASE):
        return s.rstrip()
    try:
        return _normalize_mindmap(s)
    except Exception:
        return s.rstrip()


def normalize_text(text: str) -> str:
    """Rewrite every ```mermaid fence in a markdown answer."""
    if not text or "mermaid" not in text.lower():
        return text
    return FENCE_RE.sub(lambda m: "```mermaid\n" + normalize_block(m.group(1)) + "\n```", text)

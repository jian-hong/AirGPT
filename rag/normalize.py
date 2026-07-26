"""Type-aware strip + salience for RAG ingest (DSA-style density, offline).

Compression is deterministic heuristics — not a trained cross-entropy model.
Code imports move to an import-map sidecar (file_index phrases); bodies stay
symbol-dense for embedding.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


LICENSE_RE = re.compile(
    r"^\s*(?:/\*|<!--|#)\s*(?:copyright|licensed under|spdx-license|all rights reserved).*?(?:\*/|-->|\n(?:\s*\n|\s*(?:def |class |import |from |export |function |const |let |var )))",
    re.IGNORECASE | re.DOTALL,
)
IMPORT_JS_RE = re.compile(
    r"(?m)^\s*(?:import\s.+?;|import\s*.+?from\s+['\"].+?['\"]\s*;?|const\s+\w+\s*=\s*require\([^)]+\)\s*;?)\s*$"
)
IMPORT_PY_RE = re.compile(r"(?m)^\s*(?:from\s+\S+\s+import\s+.+|import\s+\S+.*)\s*$")
BLANK_RUN_RE = re.compile(r"\n{3,}")
HTML_CHROME_RE = re.compile(
    r"</?(?:nav|footer|aside|header|noscript|template|svg)\b[^>]*>.*?</(?:nav|footer|aside|header|noscript|template|svg)>|"
    r"<(?:nav|footer|aside|header)\b[^>]*>.*?</(?:nav|footer|aside|header)>",
    re.IGNORECASE | re.DOTALL,
)
PRIVATE_KEY_RE = re.compile(r"(?m)^[_\w.-]*_[_\w.-]*\s*[:=]")


@dataclass
class NormalizeResult:
    text: str
    import_map: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


def _collapse_blanks(text: str) -> str:
    return BLANK_RUN_RE.sub("\n\n", (text or "").strip())


def strip_license_banner(text: str) -> str:
    t = text or ""
    m = LICENSE_RE.match(t)
    if m and m.end() < len(t) * 0.4:
        return t[m.end() :].lstrip()
    # Drop leading license-ish comment lines only (not markdown ## headings)
    lines = t.splitlines()
    i = 0
    while i < min(40, len(lines)):
        s = lines[i].strip()
        low = s.lower()
        if any(k in low for k in ("copyright", "spdx-license", "licensed under", "all rights reserved")):
            i += 1
            continue
        if not s or s in ("*", "*/", "-->"):
            i += 1
            continue
        if s.startswith(("/*", "*", "//", "<!--")):
            i += 1
            continue
        # Python/shell comments: "# foo" but never markdown AT1–H6 ("# Title")
        if s.startswith("#") and not re.match(r"^#{1,6}\s+\S", s):
            i += 1
            continue
        break
    if 0 < i < 40:
        return "\n".join(lines[i:]).lstrip()
    return t


def _extract_imports_js(text: str) -> tuple[str, list[str]]:
    imports = [m.group(0).strip() for m in IMPORT_JS_RE.finditer(text or "")]
    body = IMPORT_JS_RE.sub("", text or "")
    return _collapse_blanks(body), imports


def _extract_imports_py(text: str) -> tuple[str, list[str]]:
    imports = [m.group(0).strip() for m in IMPORT_PY_RE.finditer(text or "")]
    body = IMPORT_PY_RE.sub("", text or "")
    return _collapse_blanks(body), imports


def normalize_code(text: str, *, suffix: str) -> NormalizeResult:
    t = strip_license_banner(text or "")
    imports: list[str] = []
    if suffix in (".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs"):
        t, imports = _extract_imports_js(t)
    elif suffix == ".py":
        t, imports = _extract_imports_py(t)
    elif suffix in (".go", ".rs", ".java"):
        # Keep package/import lines as a short map; strip from body for density
        lines = t.splitlines()
        keep: list[str] = []
        body: list[str] = []
        for ln in lines:
            s = ln.strip()
            if s.startswith(("import ", "package ", "use ", "using ")):
                imports.append(s)
            else:
                body.append(ln)
        t = _collapse_blanks("\n".join(body))
    else:
        t = _collapse_blanks(t)
    # Compact import map for file_index (not embedded as chunk spam)
    imap = []
    for imp in imports[:80]:
        # Prefer module path token
        m = re.search(r"['\"]([^'\"]+)['\"]", imp)
        if m:
            imap.append(m.group(1))
        else:
            imap.append(imp[:120])
    return NormalizeResult(text=t, import_map=imap, meta={"imports_stripped": len(imports)})


def normalize_html(text: str) -> NormalizeResult:
    """Further strip chrome from already-extracted HTML text or raw HTML."""
    t = text or ""
    if "<" in t and ">" in t:
        t = HTML_CHROME_RE.sub(" ", t)
        # Drop residual tags lightly
        t = re.sub(r"(?is)<script\b[^>]*>.*?</script>", " ", t)
        t = re.sub(r"(?is)<style\b[^>]*>.*?</style>", " ", t)
        t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = _collapse_blanks(t)
    return NormalizeResult(text=t, meta={"html_chrome_stripped": True})


def normalize_structured(text: str, *, suffix: str) -> NormalizeResult:
    """YAML/JSON/TOML-ish: drop private keys and empty noise when already flattened."""
    lines = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        # Drop underscore-prefixed leaf keys in path: value lines
        if re.match(r"^_[\w.-]+\s*:", s) or re.match(r".*\._[\w.-]+\s*:", s):
            continue
        if s in ("{}", "[]", "null", "Null", "~"):
            continue
        lines.append(ln)
    return NormalizeResult(text=_collapse_blanks("\n".join(lines)), meta={"structured": suffix})


def normalize_text(text: str, *, path: str | Path | None = None, suffix: str | None = None) -> NormalizeResult:
    """Entry point: type-aware strip. Returns body text + import_map sidecar."""
    suf = (suffix or (Path(path).suffix.lower() if path else "")).lower()
    raw = text or ""
    if suf in (".html", ".htm"):
        return normalize_html(raw)
    if suf in (
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".mjs",
        ".cjs",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
    ):
        return normalize_code(raw, suffix=suf if suf != ".mjs" else ".js")
    if suf in (".json", ".yaml", ".yml", ".toml"):
        return normalize_structured(raw, suffix=suf)
    return NormalizeResult(text=_collapse_blanks(strip_license_banner(raw)))


def jaccard_tokens(a: str, b: str) -> float:
    ta = set(re.findall(r"[a-zA-Z0-9_]{2,}", (a or "").lower()))
    tb = set(re.findall(r"[a-zA-Z0-9_]{2,}", (b or "").lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / float(len(ta | tb))


def salience_score(text: str, terms: list[str] | None = None) -> float:
    """Proxy information density: rare-term hits + unique token fraction."""
    toks = re.findall(r"[a-zA-Z0-9_]{2,}", (text or "").lower())
    if not toks:
        return 0.0
    uniq = len(set(toks)) / float(len(toks))
    hit = 0
    if terms:
        low = (text or "").lower()
        for t in terms:
            if t and t.lower() in low:
                hit += 1
        hit = hit / max(1, len(terms))
    return 0.55 * uniq + 0.45 * hit

"""#17-#19: index.html must call the six ops endpoints (P12 was zero callers).

The HTTP gate already proves the loop. This gate proves the founder can
reach it from Build without inventing a second ops product.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "index.html"

ENDPOINTS = (
    "/api/rag/ops/identify",
    "/api/rag/ops/confirm-identity",
    "/api/rag/ops/propose-amend",
    "/api/rag/ops/confirm-amend",
    "/api/rag/ops/continue",
    "/api/rag/ops/chain",
)


def test_index_html_calls_all_six_ops_endpoints():
    html = HTML.read_text(encoding="utf-8")
    for ep in ENDPOINTS:
        assert ep in html, ep
    assert "ragOpsIdentify" in html
    assert "is it that one" in html.lower() or "Yes, that one" in html
    assert "not a second ops product" in html
    assert "not OpenVault" in html
    assert "Cortex-direct" in html


def test_ops_http_gate_still_lists_the_six():
    src = (ROOT / "tests" / "test_ops_http_gate.py").read_text(encoding="utf-8")
    for ep in ENDPOINTS:
        assert ep in src

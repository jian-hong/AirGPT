# AirGPT Claude-Native — Gate Pass

**Date:** 2026-07-14 (Dominant Next sprint)
**Gates:** P0 chat reliability · P0.5 UI · P1 Cortex agents

## Criteria

| Criterion | Status |
|-----------|--------|
| Manual mode honest (no auto-flip to AI) | PASS |
| `has_ai_keys` only true with real LLM keys | PASS |
| Send failure reconciles DB before dropping optimistic UI | PASS |
| Scroll-to-bottom + user-message jump nodes | PASS |
| classyblack + light themes + liquid glass polish | PASS |
| Desktop left/right collapse chevrons | PASS |
| Per-session share QR (view/post ACL) | PASS |
| agent_runtime + Vault Summarizer + Cortex panel | PASS |
| Local APIs / tunnel smoke (`allcheck`) | PASS* |

\* `/api/info` may still time out under slow tunnel diagnostics; probe + messages + agents OK.

## Notes

- Hard-refresh browser: `Ctrl+Shift+R` at http://127.0.0.1:8765
- Roadmap P2–P5 documented in `ROADMAP.md`

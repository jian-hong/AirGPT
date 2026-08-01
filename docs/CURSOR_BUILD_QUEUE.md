# Cursor build queue — remaining work for the YC film

Status as of 2026-07-28 (build-all pass).

| Build | Backend | Frontend | Owner |
|---|---|---|---|
| 1 · Presence + authorship | ✅ done | ✅ done | shipped + verified |
| 4 · One access control | n/a | ✅ done | five-row; MP delegates to index |
| 3 · Hub demo mode | ✅ | ✅ demo grid + drawer | PROMPT A |
| 8 · Live App Card | ✅ scaffold/state/mount | ✅ separate card path | PROMPT B |
| 6 · OpenVault ship | ✅ | ✅ stepper + evidence | PROMPT C |
| 5 · Project share QR | ✅ issue/redeem | ✅ QR + access popover | PROMPT C |
| 2 · Emergency cut-off | ✅ **gates providers** | ✅ bar + draft preserved | PROMPT D |
| Mock data (12 peers) | ✅ | n/a | PROMPT E |

## Verification notes

- `tests/test_ai_lockdown.py` — 4 passed
- `scripts/_smoke_app_card.py` — scaffold + start on unique port; sanitiser still strips iframes
- Markdown sanitiser untouched; Live App Cards use `renderAppCard()` only
- `ec2_hint` never rendered as deploy target
- Access popover: `window.__openAccessPopover` = five-row index implementation

## How to demo Live App Card

```text
python -c "import agent_tools; print(agent_tools.app_scaffold('VDML Sheet'))"
# then POST /api/apps/<id>/mount {"session_id": N}
```

## PROMPT order (historical)

1. D first (correctness) → E → B → A → C

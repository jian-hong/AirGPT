# HR / CRM Governance Module

Purpose: define a future supervised company-brain layer for AirGPT without blocking the local demo app.

## Goals
- Track work progress, usage, daily insights, prompt quality, and contribution signals.
- Help managers understand whether work is moving, what files changed, and where knowledge is being created.
- Keep governance local-first by default, with clear audit logs before any company cloud sync.

## MVP Signals
- Daily activity: chats created, screenshots captured, files changed, summaries exported.
- Prompt quality: clear task framing, useful context, follow-up depth, source references.
- Contribution: reusable notes saved to vault, decisions recorded, ideas linked to projects.
- Work evidence: changed files, summaries, generated artifacts, and reviewed outputs.

## Guardrails
- Do not rank attitude or ethics from private chats alone.
- Show evidence with timestamps and source links instead of hidden scoring.
- Let employees export their own activity trail.
- Separate productivity analytics from sensitive personal data.

## Demo Scope
- Add a local dashboard after the core chat, QR, tunnel, media, and vault flows are stable.
- Use existing SQLite messages, sessions, vault metadata, and audit logs first.
- Avoid cloud CRM integration until local audit reports are reliable.

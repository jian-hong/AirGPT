# RAG retrieval hardening (2026-07-27)

Mirror of Cortex distill capture for AirGPT operators.

**Full handoff for Claude Code / Cortex:**  
`D:\Cortex\skill_distill\captures\2026-07-27_cursor_rag-retrieval-hardening.md`

## One-line verdict

Compound asks were retrieving the whole Demo kitchen-sink (resistors) and ingesting junk web goals (`+`, `hong`). Fix = entity-first goals + token overlap gates before ingest/cite + typo-tolerant web intent + inventory path for “list all files”.

## Retry

Hard-refresh AirGPT, prefer one goal per turn:

- `/search Jian Hong Netie AI founder`
- `/search Yann LeCun papers Google Scholar`
- `compare JEPA with transfer learning`
- `explain the cognition OpenStax file in this space`

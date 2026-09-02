---
status: accepted
date: 2026-08-25
accepted: 2026-09-03
decision-makers: founder
supersedes: none
relates-to: jian-hong/AirGPT#33 (D08 #38); retrieve-time presets in rag/demo_variants.py
---

# DR-0006 - Rebuild stamps the saved architecture; ingest does not invent a second index

## Context and Problem Statement

Settings persist `depth_default` and `config.architecture`. Rebuild then calls
`ingest_paths`, which always stamped the revision as `{profile}_hybrid_{depth}`.
The architecture key was never read. A founder who saved Manual / graph, hit
Rebuild, and inspected the revision saw `local_hybrid_manual` - the control
looked like it worked and the audit trail said it did not (R-0011).

Retrieve already maps `config.architecture` when depth is `manual`
(`rag/retrieve.py`). Demo variants are retrieve-time only and say so
(`rag/demo_variants.py`: "Selecting a variant only updates space config +
depth_default"). There is no graph / agentic / hybrid_kg *index* in this
repo. Building one inside #33 would be a second product, not a stamp fix.

## Considered Options

**Option A - build a graph (or agentic) index at ingest when architecture says
so.** Rejected for this ticket. No such indexer exists. Shipping a stub index
so the revision label matches would be the same lie in the opposite direction.

**Option B - stop writing architecture onto revisions and tell the founder
Rebuild cannot honour it.** Rejected. The depth half of the stamp already
changes; architecture is sitting on the same config object. Omitting it is
how the current bug was shipped.

**Option C - stamp the saved architecture on the revision, keep the hybrid
parent-child + SiRA + dense pipeline as the only ingest index.** Chosen.
Retrieve-time templates (`manual_graph`, …) keep doing the routing they
already do. The revision profile becomes an honest label of *what was
saved*, not a claim that a second index was built.

## Decision Outcome

1. `ingest.revision_profile(space)` reads `profile`, `config.architecture`
   (default `hybrid`), and `depth_default`. A space with no architecture set
   still stamps `local_hybrid_high` so existing rows do not rename.
2. Rebuild continues to ingest the same hybrid index. Graph / agentic /
   hybrid_kg remain retrieve-time template ids until a later epic owns a
   real ingest-time index.
3. `ingest.rebuild_source_paths` prefers a live original, then `meta.docs_path`,
   then the extracted `.txt` blob. That is #34's path, not a new architecture.

## Consequences

**Positive.** Settings -> Rebuild is auditable. A later graph indexer can
key off the stamp instead of rediscovering the ignored field.

**Negative and accepted.** A Manual / graph space still embeds like hybrid.
The honesty is in the revision label and in this record, not in a second
index.

## Confirmation

- `tests/test_rag_rebuild_config.py` - a space saved as `architecture=graph`
  then rebuilt has latest `revisions.profile` containing `graph` and not a
  hardcoded `_hybrid_` when architecture was set. A space with no
  architecture still stamps `_hybrid_`.
- The test drives `ingest_paths`, not a helper that forges the profile string
  (R-0001).
- Live host 2026-09-03: Save Manual+graph then Rebuild returned
  `revision_profile=local_graph_manual` on the HTTP body and the Rebuild toast
  names that stamp.

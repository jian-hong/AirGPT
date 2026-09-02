# Idea to Paper -- stage map

Spine: Idea -> DomainRouter -> PreciseResearch -> MethodSpec
-> Executor -> VerifierGate (retry) -> more phases?
-> VerifiedFactsCapture -> (optional Grounding) -> PaperAuthor -> PaperPackage

OpenHBM v0.2 is the reference proof. Artifact map:
[docs/cortex/examples/openhbm_v0.2.md](../../../docs/cortex/examples/openhbm_v0.2.md)

## 0. Idea lock

Write one sentence the paper must defend, plus non-goals.

OpenHBM example: open HBM4 controller IP with public cocotb + formal
evidence, no silicon PPA invented, no JEDEC text redistributed.

## 1. DomainRouter

**Owner:** Orchestrator
**Output:** `domain` pack id + `grounding_mode`

Packs: software, ml, semiconductor, design, lab_chem, humanities, culture_movement

| Mode | When |
|------|------|
| digital_only | Full auto in software/sim (OpenHBM default) |
| sim_plus_optional_sensor | Digital until a claim needs capture |
| requires_capture | Pause before paper claims that need the world |

Emit handoff JSON (`stage: route`). See agents/orchestrator.md.

## 2. PreciseResearch

**Owner:** Research agent (`docs/cortex/agents/research.md`)

Order: questions -> source tiers -> resolve-or-drop cites -> contradiction
pass -> claim inventory (`supported` / `inferred` / `unknown`) -> ethics flags.

Artifacts:

- `research/BRIEF.md`
- `research/CLAIMS.json`

OpenHBM: clean-room timing in `docs/spec/`; RFCs in `docs/rfcs/`; never
paste JEDEC PDFs.

## 3. MethodSpec (success criteria before code)

**Owner:** MethodSpec agent (`docs/cortex/agents/method_spec.md`)

Analog of assertion-first: define how you will know you are wrong first.

Artifacts:

- `method/PHASE_PLAN.md` -- P1..Pn, each with verifier + gate
- `method/SUCCESS.json` -- numeric/rubric gates

OpenHBM: `OPENHBM_CURSOR_PLAN_v0.2.md` (P1-P10) + CLAUDE.md section 13.

Prefer small phases that can fail independently.

## 4-5. Execute + VerifierGate (repeat per phase)

See [CODE_LOOP.md](CODE_LOOP.md).

Default gate **80/100**. Retry budget **3** then `blocked`.
On fail: read `tools/agent_eval/feedback/<ip>/` (or `feedback/<project>/`).
On pass: next phase. Do not advance on "looks good".

## 6. VerifiedFactsCapture

**Owner:** Facts agent (`docs/cortex/agents/facts.md`)

Only numbers from live runs. File must start with `Captured: <ISO-8601 UTC>`.

OpenHBM:

```bash
python -m tools.cortex_flow.capture_eval_artifacts --ip hbm4_ctrl
python -m tools.cortex_flow.gen_verified_facts --package arxiv_package
```

Canonical file: `arxiv_package/knowledge/00_verified_facts.md`

If a log is missing, write `Pending`. Never copy roadmap numbers.

## 7. Grounding (optional)

Only if claims need camera/sensor/lab. Checklist in GROUNDING.md.
Status while waiting: `awaiting_capture`.
Semiconductor silicon PPA requires `sc_summary.json` or measured silicon --
never invent. OpenHBM v0.2: digital_only; PPA marked Pending.

## 8. Freeze snapshot

Copy live RTL, tests, formal wrappers, and eval logs into a frozen package
so the paper is reproducible after the branch moves.

OpenHBM layout (`arxiv_package/`):

```
arxiv_package/
  paper.tex  references.bib  Makefile  README.md
  knowledge/00_verified_facts.md
  rtl/*.sv
  verification/          # cocotb + sby wrapper
  eval_results/          # harness + sim + formal logs
  figures/               # py scripts + png/pdf
  tables/                # .tex includes
```

## 9-13. Paper package and landing

See [PAPER_PACKAGE.md](PAPER_PACKAGE.md).

PaperAuthor refuses if facts file lacks `Captured:`.
Limitations section is mandatory.

## Handoff schema (every stage)

```json
{
  "stage": "verify",
  "domain": "semiconductor",
  "phase_id": "P6",
  "status": "fail",
  "score": 62,
  "gate": 80,
  "feedback_path": "tools/agent_eval/feedback/hbm4_ctrl/...",
  "next_action": "retry_executor",
  "claims_touched": ["C12"],
  "grounding_mode": "digital_only",
  "artifacts": []
}
```

`stage`: route | research | method | execute | verify | facts | ground | paper
`status`: pass | fail | blocked | awaiting_user | awaiting_capture

## OpenHBM v0.2 worked trace

| Spine | What happened |
|-------|----------------|
| DomainRouter | semiconductor, digital_only |
| Research | docs/spec/ clean-room; RFCs; no JEDEC paste |
| MethodSpec | OPENHBM_CURSOR_PLAN_v0.2.md P1-P10; SVA-first |
| Executor | Cursor RTL + cocotb per phase |
| Spec author | Claude: port tables, narratives, SVA stubs |
| VerifierGate | nieda-eval >=80; release 100/100 all 11 phases |
| Facts | Captured 2026-05-26 commit bc95d62 |
| Paper | arxiv_package/paper.tex IEEE two-column -> make pdf |
| Land | arXiv cs.AR; wait for DOI before grants |

Canonical P6 debug loop is in [CODE_LOOP.md](CODE_LOOP.md).

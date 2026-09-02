---
name: idea-to-paper
description: >-
  Runs the Cortex Idea-to-Paper pipeline: domain route, precise research,
  method spec, harness-gated code phases (nieda-eval), verified-facts freeze,
  then IEEE/arXiv package with charts, photos, and markdown-to-LaTeX. Use when
  the user says idea to paper, cortex flow, arxiv, research pipeline,
  harness-gated RTL, nieda-eval, convert markdown to latex, add figures or
  charts, or land a research preprint.
---

# Idea to Paper (full pipeline)

Act as **Orchestrator**. Do not skip gates. Do not invent metrics.

Load first:

1. [docs/cortex/UNIVERSAL_SPINE.md](../../../docs/cortex/UNIVERSAL_SPINE.md)
2. [docs/cortex/GROUNDING.md](../../../docs/cortex/GROUNDING.md)
3. Mode: [ONE_SHOT_PROMPT.md](../../../docs/cortex/ONE_SHOT_PROMPT.md) or [STEP_BY_STEP.md](../../../docs/cortex/STEP_BY_STEP.md)
4. Domain pack `docs/cortex/domains/<domain>/PACK.md`
5. Role prompts `docs/cortex/agents/`

Then this skill's references as needed:

- [PIPELINE.md](PIPELINE.md) -- stage map, artifacts, OpenHBM worked trace
- [CODE_LOOP.md](CODE_LOOP.md) -- assertion-first + nieda-eval code phases
- [PAPER_PACKAGE.md](PAPER_PACKAGE.md) -- facts, charts, photos, md-to-tex, arXiv

## AirGPT host (this repo)

Do **not** use Cursor as the generator. Cortex owns the brain. AirGPT is the shell.

```
python -m idea_to_paper
# or POST /api/research/idea-to-paper  {"idea":"...","domain":"software"}
# poll GET /api/research/runs?id=<run_id>
```

LLM calls: Cortex `POST /api/engine/run` with `prompt_id=research.idea_to_paper`
(stage in `params`). OpenVault holds keys. Route: Cortex constructor
`recommend` + `generate`. AirGPT verifies (pytest, gate 80) and packages
(facts `Captured:`, charts, IEEEtran inject, pdflatex). Fail closed if Cortex
is down -- no AirGPT system prompt fallback.

Load first: this folder (`PIPELINE.md`, `CODE_LOOP.md`, `PAPER_PACKAGE.md`). OpenHBM RTL/nieda-eval below is the semiconductor worked example, not the AirGPT default domain.

## Modes

| Mode | Stop when |
|------|-----------|
| One-shot | `blocked` / `awaiting_capture` / retry budget (3) |
| Step-by-step | After every stage; wait for `continue` / `debug` / `override` |

## Pipeline (copy and tick)

```
- [ ] 0  Idea lock (one sentence + non-goals)
- [ ] 1  DomainRouter  -> domain + grounding_mode
- [ ] 2  PreciseResearch -> research/BRIEF.md + research/CLAIMS.json
- [ ] 3  MethodSpec -> method/PHASE_PLAN.md + method/SUCCESS.json
- [ ] 4  Per phase: spec/SVA -> RTL/tests -> VerifierGate (>=80)
- [ ] 5  Retry Executor from feedback/ (max 3) or blocked
- [ ] 6  FactsCapture -> knowledge/00_verified_facts.md (Captured: UTC)
- [ ] 7  Optional Grounding capture (only if claims need it)
- [ ] 8  Freeze snapshot (rtl + logs + tests) into arxiv_package/
- [ ] 9  Charts from facts (matplotlib); tables as .tex
- [ ] 10 Photos/illustrations (decorative only; no invented stats)
- [ ] 11 Markdown/notes -> IEEEtran paper.tex + references.bib
- [ ] 12 make pdf (pdflatex x2); human review Limitations
- [ ] 13 arXiv submit (cs.AR or domain venue); wait for DOI
```

Dispatch specialists via Task when parallel helps. Keep **VerifierGate** serial.

## Semiconductor / OpenHBM activation

Never install EDA tools. Source the existing suite:

```bash
source ~/oss-cad-suite/environment && \
 PATH=~/OpenHBM/.venv/bin:~/oss-cad-suite/bin:/usr/bin:/bin:$PATH \
  bash tools/cortex_flow/run_phase_gate.sh hbm4_ctrl

python -m tools.cortex_flow.capture_eval_artifacts --ip hbm4_ctrl
python -m tools.cortex_flow.gen_verified_facts --package arxiv_package
```

Harness (VerifierGate):

```bash
python -m tools.agent_eval.harness.run --ip <ip> --no-mutation
# gate: score >= 80/100; release target often 100
```

Obey `CLAUDE.md` + `AGENTS.md` + `docs/agent-prompts/<ip>.md`.

## Tools by stage

| Stage | Tools |
|-------|-------|
| Research | resolve-or-drop DOI/arXiv/URL; clean-room spec `docs/spec/` |
| Spec | RFC `docs/rfcs/`; port table; SVA stubs before RTL |
| Code | Cursor Executor; SystemVerilog subset in CLAUDE.md |
| Lint/elab | verible-verilog-lint; Verilator; yosys synth-check |
| Sim | cocotb + Python golden `dv/env/<ip>_ref.py` |
| Formal | sv2v flatten then sby (never `import pkg::*` into Yosys) |
| Gate | nieda-eval `tools/agent_eval/harness/run.py` |
| Facts | `tools/cortex_flow/` |
| Charts | matplotlib (`figures/*.py`); numbers from facts only |
| Photos | optional Gemini/illustration; captions cannot add metrics |
| Paper | IEEEtran + pdflatex; BibTeX verified entries |
| Land | arXiv upload; cs.AR for this repo |

## Hard rules

- Never invent metrics, citations, PPA, yields, or silicon claims
- Never skip VerifierGate without recorded human override
- Paper numbers only from `knowledge/00_verified_facts.md` with `Captured:`
- Prefer digital; camera only per GROUNDING.md
- No JEDEC PDF paste; use clean-room summaries
- Decorative figures cannot invent stats
- Do not edit `Plan.md` unless the user asked

# Code loop -- assertion-first + harness gate

This is how OpenHBM generated RTL from a phase plan to a mergeable IP.
Other domains swap the verifier; keep the loop.

## Division of labour (OpenHBM)

| Role | Who | Does |
|------|-----|------|
| Spec | Claude (or Research/MethodSpec) | RFC, port table, cycle narrative, SVA stubs FIRST |
| Impl | Cursor Executor | SystemVerilog + cocotb + CI, one phase only |
| Gate | nieda-eval | Numeric merge criterion independent of both agents |
| Human | User | Override only; never advance on review-alone |

No phase advances on human code review alone.

## Per-phase order (CLAUDE.md section 13)

Do not skip. Harness will refuse to score if earlier artifacts are missing.

1. RFC at `docs/rfcs/` for non-obvious choices
2. Port and parameter table in `hw/ip/<ip>/doc/<ip>.md`
3. Cycle-by-cycle timing narrative in the RTL file header
4. SVA assertions first (`assert property`) -- make them fail, then pass
5. Implement RTL (IEEE 1800-2017 subset; see CLAUDE.md bans)
6. Python golden `dv/env/<ip>_ref.py`
7. Cocotb: directed, then pyvsc constrained-random
8. SymbiYosys: BMC (+ prove on small liveness)
9. Mutation `mcy` when in the gate (OpenHBM v0.2 release used `--no-mutation`)
10. `make synth-check` (yosys elaborate)
11. `make agent-eval IP=<ip>` -- score >= 80/100 then PR

Read before generating any IP code:

- `CLAUDE.md`, `AGENTS.md`
- `docs/agent-prompts/_preamble.md`
- `docs/agent-prompts/<ip>.md`

## nieda-eval stages (VerifierGate)

Entry: `python -m tools.agent_eval.harness.run --ip <ip>`

Default weights (sum 100):

| Stage | Weight | Tool |
|-------|-------:|------|
| lint | 10 | verible-verilog-lint |
| elab | 10 | Verilator -Wall |
| sim_pass | 25 | cocotb vs Python golden |
| func_cov | 20 | cocotb-coverage |
| formal | 20 | sv2v flatten + sby BMC |
| mutation | 15 | mcy (optional; `--no-mutation` for v0.2 gate) |

Pass: total >= **80**. Hard-fail formal classes can force score **0**.
Release target for OpenHBM v0.2: **100/100** every phase.

Feedback on fail: `tools/agent_eval/feedback/<ip>/<UTC>.md` + `.json`
with stage table and "What to fix next". Executor reads this before retry.

## Formal / Yosys traps (this repo)

- Yosys cannot parse `import pkg::*;` in module headers
- Every `.sby` target MUST read an `sv2v`-flattened file
- Pattern: `sv2v pkg.sv top.sv wrapper.sv > flat.v`, SBY reads `flat.v` only
- Never add `import` inside fpv/ wrappers
- `flat.v` is generated; gitignore `hw/ip/*/fpv/*_flat.v`
- sv2v order: pkg.sv -> top.sv -> fpv/abs.sv -> fpv/wrapper.sv
- SBY solver: smtbmc bitwuzla; keep depth bounded (v0.2: 24)
- `OPENHBM_FPV` guard for formal clock gen; no `#delay` in synth RTL

## Environment (WSL)

```bash
source ~/oss-cad-suite/environment && \
 PATH=~/OpenHBM/.venv/bin:~/oss-cad-suite/bin:/usr/bin:/bin:$PATH \
  python -m tools.agent_eval.harness.run --ip hbm4_ctrl --no-mutation
```

Or: `bash tools/cortex_flow/run_phase_gate.sh hbm4_ctrl`

Never `apt install` / reinstall OSS CAD. If a tool is missing, source PATH.

Windows venv is `.venv/Scripts/activate`; WSL venv is `~/OpenHBM/.venv/bin/activate`.
Activate BOTH OSS CAD and venv before harness, sby, verilator, yosys.

## Worked example: OpenHBM P6 (write leveling)

This is the canonical debug loop documented in `arxiv_package/paper.tex`.

1. **Assertion spec.** Four SVA properties before RTL: P6F1 inhibit during
   training; P6F2 TRAIN_ERR after 1024-cycle timeout; P6F3 no simultaneous
   wrlvl+rdlvl; P6F4 training_done is a one-cycle pulse.
2. **RTL.** Cursor implemented `hbm4_ctrl_training` (IDLE / WRLVL / RDLVL /
   DONE / ERR).
3. **Harness fail (<80).** `test_wrlvl_timeout` exposed missing TRAIN_ERR;
   P6F3 flagged overlapping request latches.
4. **Fix.** Clear sticky `wrlvl_req_q`; add five directed tests.
5. **Re-score 100/100.** Cumulative cocotb 25 -> 30. Advance.

The loop terminated on measurable evidence, not on review.

## OpenHBM v0.2 phase map (reference)

| Phase | Feature | Tests (new / total) | Score |
|-------|---------|---------------------|------:|
| v0.1 | Bank FSM + RR scheduler | 8 / 8 | 100 |
| P1 | AXI4 INCR/WRAP | 2 / 10 | 100 |
| P2 | Multi-channel scale-out | 2 / 12 | 100 |
| P3 | DFI 5.0 ctrlupd/phyupd | 5 / 15 | 100 |
| P4 | Power-down / self-refresh | 5 / 20 | 100 |
| P5 | Temperature-aware refresh | 5 / 25 | 100 |
| P6 | Write/read training | 5 / 30 | 100 |
| P7 | QoS DWRR | 5 / 35 | 100 |
| P8 | RAS / error injection | 5 / 40 | 100 |
| P9 | PHY/DRAM behavioural models | 5 / 45 | 100 |
| P10 | PMU | 5 / 50 | 100 |

Live RTL lives in `hw/ip/hbm4_ctrl/`. Frozen copy in `arxiv_package/rtl/`.

## Other domains

Replace nieda-eval with the pack verifier in
`docs/cortex/domains/<domain>/PACK.md`. Keep: small phases, machine-checkable
gate, structured feedback, facts-only paper numbers.

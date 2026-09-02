# Paper package -- facts, charts, photos, md-to-arXiv

PaperAuthor (`docs/cortex/agents/paper.md`) writes the preprint **only** from
verified facts + research/method artifacts. This file is the conversion
and landing recipe used for OpenHBM v0.2.

## Preconditions

Refuse to write metrics if any of these are missing:

- `knowledge/00_verified_facts.md` with `Captured: <ISO-8601 UTC>`
- `research/BRIEF.md` + `research/CLAIMS.json`
- `method/PHASE_PLAN.md`
- Domain venue hints in `docs/cortex/domains/<domain>/PACK.md`

Every metric line needs a facts-file match **and** an artifact path
(`eval_results/...`, `rtl/`, `wc -l`, ...).

## 1. Freeze facts and snapshot

Semiconductor path:

```bash
source ~/oss-cad-suite/environment
PATH=~/OpenHBM/.venv/bin:~/oss-cad-suite/bin:/usr/bin:/bin:$PATH \
  python -m tools.agent_eval.harness.run --ip hbm4_ctrl --no-mutation

python -m tools.cortex_flow.capture_eval_artifacts --ip hbm4_ctrl
python -m tools.cortex_flow.gen_verified_facts --package arxiv_package
# optional dry-run first:
python -m tools.cortex_flow.gen_verified_facts --package arxiv_package --dry-run
```

Also freeze a release note (`docs/releases/v0.2.0.md`) -- this is markdown
source material, **not** a metrics source. Numbers still come from facts.

## 2. Markdown / notes -> IEEE/arXiv LaTeX

Do not "pretty-print" a blog post. Rebuild as a venue paper.

OpenHBM venue: **IEEE two-column conference** (`IEEEtran`), arXiv **cs.AR**,
target <= 8 pages.

| Markdown / repo note | LaTeX landing |
|----------------------|---------------|
| Idea + claims | `\title`, `\begin{abstract}`, `\IEEEkeywords` |
| Related work in BRIEF.md | `\section{Related Work}` + `references.bib` |
| PHASE_PLAN.md | `\input{tables/table1_phase_summary.tex}` |
| Architecture / module list | `\section{Architecture}` + table3 + fig1-3 |
| Harness scorecard | `\section` verification + fig4 + fig5 |
| CODE_LOOP P6 story | `\section{AI-Assisted Development Methodology}` |
| Pending / not run | `\subsection{Limitations}` (mandatory) |
| Tool versions | `\input{tables/table2_toolchain.tex}` |

Skeleton:

```
Abstract -> Introduction -> Related Work -> Architecture
-> Verification (sim, formal, harness) -> Methodology
-> Silicon path (if any; else Pending) -> Conclusion + Limitations
```

Header used in OpenHBM:

```latex
\documentclass[conference]{IEEEtran}
\usepackage{graphicx,booktabs,cite,hyperref,amsmath}
\graphicspath{{figures/}}
```

Bibliography: APA/IEEE BibTeX with **resolved** DOI/arXiv/URL only.
Drop unresolved IDs. Never fabricate citations. Never paste JEDEC text.

Humanities packs may use essay structure; quantitative claims still bind
to facts.

## 3. Tables from facts

Write `tables/*.tex` as `\input{}` fragments. Example columns for a
harness project: Phase, Feature, New tests, Total tests, Score.

Comparison tables must not invent competitor numbers; cite papers or mark
unknown.

OpenHBM files:

- `tables/table1_phase_summary.tex`
- `tables/table2_toolchain.tex`
- `tables/table3_modules.tex`
- `tables/table4_comparison.tex`

## 4. Charts (quantitative)

Generate from facts-file numbers with matplotlib (`Agg` backend). Do not
hand-draw scores.

OpenHBM:

```bash
cd arxiv_package
python figures/fig5_score_progression.py   # PNG for includegraphics
python figures/score_chart.py              # PDF variant
python figures/arch_diagram.py             # optional vector architecture
python figures/verification_flow.py
```

Rules:

- Dual-axis "score vs cumulative tests" is the canonical harness chart
- Draw the gate line at 80
- Caption states the source (`eval_results/eval_output.txt`, table1)
- If a phase score is missing, omit the bar; do not invent 100

## 5. Photos and illustrations (decorative)

Optional publication-quality drawings (Gemini or similar) for architecture
block diagrams. OpenHBM: `figures/fig1.png` ... `fig4.png`.

Rules:

- Illustrations **cannot** add statistics, PPA, or "as-if" measurements
- Captions describe structure, not unpublished results
- Prefer PNG/PDF that pdflatex can include; SVG -> PDF via
  `python figures/convert_svg.py in.svg out.pdf` (svglib + reportlab)
- Page-proof screenshots (`page-1.png`, `audit-p1.png`) are for human
  layout check, not paper figures -- do not `\includegraphics` them
  unless the paper is about the audit UI

Prompt pattern for arch art: host bus -> controller -> DFI -> memory stack
+ verification layer. No numbers in the image.

## 6. Build PDF

```bash
cd arxiv_package
make pdf
# = pdflatex -interaction=nonstopmode paper.tex  (twice)
```

Needs TeX Live: `pdflatex`, `booktabs`, `IEEEtran`.
Check page count, figure overflow, and that every number matches facts.

## 7. arXiv landing

1. Human-read Limitations. Confirm Pending items stay Pending.
2. Upload source + PDF to arXiv (OpenHBM: **cs.AR** Hardware Architecture).
3. Include `paper.tex`, `references.bib`, `figures/`, `tables/`.
   Do not upload JEDEC PDFs or NDA netlists.
4. Wait for arXiv DOI (~1-2 weeks) before grant text that needs a cite.
5. Keep `arxiv_package/` as a frozen snapshot; live RTL stays in `hw/ip/`.

## Forbidden in the paper

- Invented benchmarks, PPA, yields, eye diagrams, tapeout
- Claiming silicon when only sim/formal ran
- Citing unresolved DOIs
- Decorative figures that imply extra experiments
- Softening a failed harness run into a pass
- JEDEC/standards full-text paste

## OpenHBM v0.2 facts snapshot (do not copy blindly; re-capture)

Re-run capture for a new paper. Historical freeze (2026-05-26, `bc95d62`):

- 14 RTL files, 2,654 source lines
- cocotb 50/50 PASS
- 30 SVA proved BMC depth 24 (bitwuzla)
- nieda-eval 100.0/100 (threshold 80)
- SKY130 / IHP PPA: Pending (no `sc_summary.json`)
- ECC chipkill: stub only; PHY: behavioural model, not silicon

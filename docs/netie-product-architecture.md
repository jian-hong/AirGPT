# Netie product architecture — ontology, IA, URL map, sync model

Decisive reference. Supersedes the earlier "separate `landing/` folder" plan:
**`netie-scroll-world/` merges INTO netie.ai as its `/airgpt` route.** There is
no second AirGPT landing site and no competing legal page.

---

## 1. Product ontology

| Entity | What it is | Lives at (code) | Lives at (web) | Buyer-facing? |
|---|---|---|---|---|
| **Netie** | Parent company/platform brand. Owns Sovereign AI Agents (Vanguard, Closer, Cortex), Solutions (Constructor, Ghost Mode, Semantic Explorer, The Forge), and the Web3×Hardware line (Talkie, AIM). | n/a (marketing org) | `netie.ai` (home) | Yes — top of funnel |
| **AirGPT** | Local-first clipboard/chat/agents product. One of Netie's shipping products, not the whole company. | `d:\AirGPT` (this repo) | `netie.ai/airgpt` (scroll-world) | Yes — the product page |
| **Netie Space** | QuickLook-like WPF desktop utility. Separate codebase, separate release cadence. Sibling utility under the Netie brand (star mark), not an enterprise "solution." | `C:\Users\OoiJianHong\Netie Space` | `netie.ai/space` (light stub, own repo owns its own content) | Yes — small utility page |
| **Netie Cortex** (enterprise) | The enterprise governance "brain": ingests audit/evidence from AirGPT installs (and other tools), applies licensing/IP-allowlist/audit policy, powered by Claude Opus. This is the thing netie.ai's homepage means by "Cortex." | External service, **not embedded** in AirGPT | `netie.ai/cortex` (or under Sovereign Agents) | Yes — enterprise sale |
| **AirGPT Cortex agents** (local) | The in-app agent tool-loop (Thinking modes, sandboxed tools, audit) that ships free inside AirGPT. Same brand word, one size smaller, one seat, no multi-tenant policy. | `docs/business-platform.md`, `docs/openforge.md`, in-app | Never named bare "Cortex" outward-facing — see §6 | No — it's a feature, not a product page |
| **OpenForge** | NL-spec → simulation-gated ngspice → netlist/schematic engine. Netie R&D asset (`Netie-AI/OpenForge`), vendored as an optional AirGPT module (`mod-openforge`). | `docs/openforge.md`, `third_party/openforge` (to vendor) | Branded on netie.ai as **The Forge** (see §7 naming ruling) | Indirect — engine name stays technical, "The Forge" is the sales name |
| **OpenIDE** | Cursor-like code workspace embedded in AirGPT (Monaco, path-jailed FS, terminal, optional `cursor-sdk` backend). | `docs/openforge.md`, in-app | Mentioned inside `/airgpt` (Agents section) only — no standalone nav item | No — in-product feature |
| **Netie Talkie / Netie AIM** | Coming Soon: plushie hardware + AI twin. Consumer Web3/hardware line, unrelated to engineering buyers. | n/a | `netie.ai` Coming Soon section / `/talkie`, `/aim` stubs | Yes — future consumer line |

**One-sentence ontology:** *Netie is the company and the enterprise governance brain (Cortex, Vanguard, Closer); AirGPT is Netie's local-first engineering product with its own small on-device Cortex agent loop; Netie Space is a small sibling utility; OpenForge/OpenIDE are AirGPT-internal engines, one of which (OpenForge) also has an enterprise-facing brand name, The Forge; Talkie/AIM are a separate future hardware line.*

---

## 2. Information architecture for netie.ai (AirGPT scroll-world = AirGPT's product page)

```
netie.ai/                         Home — Sovereign AI Agents pitch, Solutions grid, Coming Soon, #contact
├── /airgpt                       ← netie-scroll-world (Desk→Bridge→Vault→Agents→Tower→Hero), full-bleed, own nav
│   └── /airgpt/download          Download hosting (redirects to GitHub Releases / CDN)
├── /space                        Netie Space — light single-page (star mark), owns its own copy in its own repo
├── /cortex                       Netie Cortex enterprise brain — Vanguard, Closer, Cortex trio, Claude Opus
├── /solutions                    Constructor, Ghost Mode, Semantic Explorer, The Forge (OpenForge branded)
├── /talkie, /aim                 Coming Soon stubs (or one /coming-soon with both cards)
├── /legal/privacy
├── /legal/terms
├── /legal/security                Synced from AirGPT repo `legal/` — see §5
├── /#contact                      Anchor on home — CTA target already hardcoded in scroll-world, do not fork to a separate page
└── /press (later)                 Brand assets, low priority
```

Nav bar top-level: **Agents · Solutions · AirGPT · Space · Coming Soon · Contact**. AirGPT is a peer nav item, not a sub-page of Solutions — it is Netie's flagship shipping product and gets its own cinematic route.

---

## 3. URL map (concrete)

| URL | Owner | Source |
|---|---|---|
| `netie.ai/` | netie.ai CMS | Hand-authored corporate copy |
| `netie.ai/airgpt` | netie.ai build, **content from AirGPT repo** | `netie-scroll-world/` exported/mounted as a route |
| `netie.ai/airgpt/download` | netie.ai host | Redirect → GitHub Releases asset (versioned EXE/zip) |
| `netie.ai/space` | netie.ai CMS | Netie Space's own repo supplies copy/assets |
| `netie.ai/cortex` | netie.ai CMS | Hand-authored enterprise copy |
| `netie.ai/solutions` (incl. The Forge card) | netie.ai CMS | Hand-authored; The Forge card links out to OpenForge docs/demo if public |
| `netie.ai/talkie`, `netie.ai/aim` | netie.ai CMS | Hand-authored Coming Soon |
| `netie.ai/legal/privacy`, `/terms`, `/security` | **AirGPT repo `legal/` SSOT**, netie.ai chrome | Synced markdown, rendered in netie.ai's nav/footer |
| `netie.ai/#contact` | netie.ai CMS | Existing anchor, already the CTA target from scroll-world |

No `airgpt.netie.ai` subdomain, no `landing/` folder in this repo, no second contact form.

---

## 4. Content ownership

**Lives in the AirGPT repo (source of truth):**
- `netie-scroll-world/` — the entire `/airgpt` route: copy, section structure, assets, video plates. Marketing edits to AirGPT's *own* product narrative happen here, in version control, next to the product that makes the claims true.
- `legal/` (new, see §5) — Privacy, Terms, Security/data-handling. Authored here because only the codebase knows the actual data flow (what stays local, what the tunnel touches, what audit.jsonl logs, that input-notes are opt-in).
- `docs/*.md` — internal engineering/roadmap docs. Never published raw; may be quoted by netie.ai copywriters but not synced verbatim.
- `video-assets/` — raw and exported demo footage. Final cuts get pushed to netie.ai's video CDN; raw project files stay in-repo (or an asset bucket), not committed as netie.ai's copy.

**Must live on netie.ai CMS/host (not this repo):**
- All enterprise/company-level copy: Sovereign Agents (Vanguard, Closer, Cortex), Solutions (Constructor, Ghost Mode, Semantic Explorer, The Forge), Coming Soon (Talkie, AIM).
- Global nav, footer, contact form backend, lead capture/CRM, any blog/press.
- The actual deployed site (whatever stack netie.ai runs) — it *imports* `/airgpt` and `/legal/*` from AirGPT, it does not re-author them.
- Netie Space's own product copy (owned by that repo, not AirGPT's).

---

## 5. Sync model — legal SSOT → netie.ai (no second landing)

1. **SSOT**: `legal/` at AirGPT repo root — `privacy.md`, `terms.md`, `security.md`, `data-handling.md`. Each file has front-matter: `version`, `last_updated`, `applies_to: AirGPT`.
2. **Export**: `scripts/publish_legal.py` renders each Markdown file to the fragment format netie.ai's site consumes (MDX/JSON/HTML partial — whatever their stack takes) and writes a `legal/manifest.json` (doc → version → hash).
3. **Publish**: a CI job triggers on push to `main` touching `legal/**`, runs the export, and either (a) opens a PR against netie.ai's site repo with the updated fragments, or (b) pushes the rendered fragments to a shared content bucket that netie.ai's build fetches at deploy time. Pick (a) if netie.ai is a sibling repo you control; pick (b) if netie.ai is on a CMS you don't want to PR into directly.
4. **Render**: netie.ai renders the fragment inside its own page chrome at `/legal/privacy` etc. — same nav/footer as the rest of the site, body content verbatim from the repo.
5. **No fork**: netie.ai's team never hand-edits legal copy. If wording must change, it changes in `legal/` here first, bumps `version`, and flows out through the same pipeline — this is the mechanism that prevents a second, drifting legal page from ever existing.

---

## 6. Narrative bridge — enterprise Cortex vs AirGPT's local Cortex

**Rule, applied everywhere outward-facing:** never say bare "Cortex" without a qualifier.

- **Netie Cortex** = the enterprise brain on netie.ai. Cloud, multi-tenant, licensing + IP allowlist + evidence-based audit, Claude-Opus-powered. This is what a company *buys* to supervise many seats/tools.
- **AirGPT's local agent loop** = referred to as "AirGPT's agent loop" or "on-device agents" in outward copy; "Cortex agents" is fine in-product/dev docs (`docs/business-platform.md`) but gets rewritten in marketing copy per the delta below.

**The one sentence that resolves the collision for buyers:** *Cortex is one brain at two sizes — a free, single-seat version runs on-device inside AirGPT and produces the audit trail; Netie Cortex is the paid, multi-seat version that ingests that same audit trail across a whole team and adds licensing, allowlists, and policy.* AirGPT's local audit log is literally the evidence feed the enterprise Cortex consumes — that's the honest, non-confusing link, and it's already implied by the existing Tower section copy ("Netie's control plane adds licensing, IP allowlists and evidence-based audit").

The Agents section of the scroll-world currently says *"Cortex agents, OpenIDE and sandboxed tool loops"* — this is the one spot using bare "Cortex" and should be corrected (delta below).

---

## 7. Concrete plan deltas (apply now)

1. **Kill the standalone `landing/` folder plan.** No separate AirGPT landing site/domain. `netie-scroll-world/` is exported/mounted as netie.ai's `/airgpt` route, in netie.ai's own build — one deploy, one nav, one contact form.
2. **Create `legal/` at repo root**: `privacy.md`, `terms.md`, `security.md`, `data-handling.md`, each with `version`/`last_updated` front-matter. This is new — no legal folder exists in the repo today.
3. **Add `scripts/publish_legal.py`** (or `.ps1`) + `legal/manifest.json` to implement the sync in §5.
4. **Add `netie-scroll-world/README.md`** documenting that this folder is the canonical source for netie.ai's `/airgpt` route, with export/mount instructions for whoever owns the netie.ai build.
5. **Fix `netie-scroll-world/index.html` Agents section copy** — replace the bare "Cortex agents" eyebrow/body with qualified language ("AirGPT's agent loop") and add a one-line bridge + link to `netie.ai/cortex` ("Need this across a whole team? See Netie Cortex →"). This is the only copy delta required for the narrative bridge; the Tower section already avoids the collision correctly.
6. **Launcher plan**: download CTA on `/airgpt/download` points to GitHub Releases (versioned EXE/zip) or a CDN mirror of it — not to a self-hosted landing page. `DISTRIBUTE.md`'s `build_exe.bat` output is the artifact this URL redirects to.
7. **Update `docs/business-platform.md`** row `Company marketing site | Later | Separate static site` → `Merged into netie.ai/airgpt | Live | See docs/netie-product-architecture.md`.
8. **Add a `netie.ai/space` stub** sourced from the Netie Space repo, cross-linked only — do not pull its copy into this repo.
9. **Document the "The Forge" ↔ OpenForge naming ruling** in `docs/openforge.md` with one line: *"The Forge" on netie.ai is the enterprise-facing brand name for this engine; keep `OpenForge` as the technical/repo/API name.* Prevents future contributors from treating them as unrelated products.
10. **No change needed** to `README.md`'s `desk@netie.ai` / `hello@netie.ai` contact routing or to the scroll-world's existing `https://netie.ai/` and `https://netie.ai/#contact` CTA hrefs — both already point at the correct merged destination.

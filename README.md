<h1 align="center">MD-for-Dummies</h1>

<p align="center">
  <strong>A small but complete molecular-dynamics framework for reproducing physics papers — driven by an AI skill that turns a paper into a runnable experiment config.</strong>
</p>

<p align="center">
  <a href="#what-this-is">What this is</a> •
  <a href="#how-it-works">How it works</a> •
  <a href="#quickstart">Quickstart</a> •
  <a href="#the-ai-skill-workflow">AI Skill Workflow</a> •
  <a href="#adding-your-own-paper">Add Your Paper</a> •
  <a href="#references">References</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License"/>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/Taichi-1.7.4-orange" alt="Taichi"/>
  <img src="https://img.shields.io/badge/Claude%20Skill-paper--to--experiment-7b53d6" alt="Claude Skill"/>
</p>

---

## What this is

Most MD papers come with screenshots, a methods section, and a wave goodbye. **Reproducing them takes weeks.** You read the paper, decode the parameters, build a runner, glue together force fields, write analysis, plot figures, then realize you misread `T₀=0.3` as `T=0.3`.

`md-for-dummies` is a **paper-driven workflow** built on a minimal Taichi MD core. It is:

> **Not** another high-performance MD engine. There are excellent ones (LAMMPS, GROMACS, GPUMD).
>
> **Yes** a teaching framework that shows the full path: *paper → parameters → simulation → analysis → figure*, and lets you swap papers by writing one config file plus (when needed) one adapter.

It ships with two **end-to-end reproductions** of recent complex-plasma papers as worked examples:

- Ivlev et al., *Phys. Rev. X* **5**, 011035 (2015) — non-reciprocal Hertzian, two-temperature steady state
- Ivlev et al., *Phys. Rev. Lett.* **100**, 095003 (2008) — anisotropic Yukawa, chain formation

### What's inside

| | |
|---|---|
| 🧱 **4-layer architecture** | Config → Adapter → Platform → Infrastructure. Each layer talks only to the one below it. |
| 🤖 **AI skill** | A Claude Code skill (`paper-to-experiment`) that walks a paper into a validated config in 7 steps. |
| 📋 **Schema-validated configs** | JSON Schema + physics rules + budget guards. Bad configs fail before any GPU is touched. |
| 🔌 **Class-name dispatch** | Add a new analyzer / visualizer / aggregator? One file + one registry line. No central if-else. |
| 🧪 **Layered testing** | Schema gate, manifest gate, registry gate, runtime gate. Every contract has an enforcement point. |
| 📐 **Two reference papers** | PRX 2015 (slope_A=2/3 to within 1%) and PRL 2008 (chain phase, ⟨L⟩=5.15 at MT=0.8). |

---

## Why "for-Dummies"?

Because reproducing a physics paper shouldn't require:

- ❌ a custom 5000-line C++ runner per paper
- ❌ a 30-step manual lab notebook of "convert φ to N then to box length"
- ❌ guessing whether `dt` is in fs or τ
- ❌ rebuilding the analysis pipeline every time

It should look like:

```bash
# Tell the AI which paper to reproduce
$ /paper-to-experiment Ivlev_PRX_2015.pdf

# Skill walks the design template, asks ASK USER: questions if any,
# then emits a validated config file:
configs/plan_prx_t0sweep.json    ✓ schema valid
                                  ✓ physics rules pass
                                  ✓ within budget (4 hr/run)

# You launch it
$ python scripts/run_experiment.py configs/plan_prx_t0sweep.json
```

That's it. No new force class to write (PRX 2015's force already exists), no analyzer to plumb, no figure code to copy-paste.

---

## How it works

The framework is **strictly four-layered**. Each layer talks only to the one below. Mixing layers is the #1 source of bugs.

```
╔══════════════════════════════════════════════════════════════════════╗
║  Layer 4 — CONFIG     (data, no code)                                 ║   ← USER WRITES
║  configs/plan_*.json — campaign list, phases, class names             ║     this every paper
╠══════════════════════════════════════════════════════════════════════╣
║  Layer 3 — ADAPTER     (per-paper, follows TEMPLATE)                  ║   ← USER WRITES
║  prx_nonreciprocal_run.py, er_plasma_run.py                           ║     this for new papers
╠══════════════════════════════════════════════════════════════════════╣
║  Layer 2 — PLATFORM    (paper-agnostic, frozen unless bug)            ║   ← FRAMEWORK
║  scripts/run_experiment.py — orchestrator                              ║     OWNS this
║  tools/ — analyzers, plotters, aggregators, visualizers, registry      ║
╠══════════════════════════════════════════════════════════════════════╣
║  Layer 1 — INFRASTRUCTURE  (Taichi MD core, frozen)                   ║
║  systemClass, atomSystemClass, integratorClass, searchBox, forceField  ║
╚══════════════════════════════════════════════════════════════════════╝
```

A single run goes through six numbered phases:

```
0. validate config   (JSON Schema + physics + budget)        — no GPU touched
1. preflight         (resource estimate per run)             — no GPU touched
2. smoke             (default 100 steps, catches crashes)
3. production        (the real run, parallel-safe)
4. visualize         (optional, registry-dispatched)         — Taichi UI / mp4
5. aggregate         (optional, cross-run figures + report)
```

Full architecture spec: [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Quickstart

### Install

```bash
git clone https://github.com/thematteroftime/md-for-dummies
cd md-for-dummies
pip install -r requirements.txt
```

> **GPU note**: this project uses Taichi 1.7.4 with CUDA. CPU-only Taichi works for the smoke tests but is slow for production-scale runs. Tested on RTX 5060 Laptop (8 GB VRAM).

### Validate an example config (no compute)

Every config goes through three pre-launch gates before any GPU is touched. Try them:

```bash
# Schema + physics + budget validation. Exits 0 = ready to launch.
python scripts/validate_config.py configs/examples/plan_g_er_chains.json --strict
```

The validator prints a cost estimate (per-run wall + total VRAM). Re-run with `--strict` to fail on warnings.

### Run a small example

The PRL 2008 short ER plasma campaign (5 runs × 50k steps ≈ 20 min on RTX 5060):

```bash
python scripts/run_experiment.py configs/examples/plan_g_er_chains.json
```

Outputs go to `outputFiles/<TS>_<tag>/` per run (HDF5 trajectory + manifest.json + per-run report.md). Cross-run figures land in `docs/images/` once Phase 4 (aggregate) runs.

> **Heavier examples** (multi-hour, e.g. `plan_e_damping.json`, `plan_g2_er_long.json`) are listed in `configs/examples/` for reference. Validate them first; launch only when you've budgeted the wall time.

### Run the test suite

```bash
pytest tests/ -q
```

This exercises the schema, registry, validators, and contract conformance in seconds.

### Standalone utilities

Three CLI helpers under `scripts/` that don't fit in the main pipeline:

| Script | Purpose |
|--------|---------|
| `scripts/bench_neighbor.py` | Benchmark cell-list (`cho=1`) vs O(N²) (`cho=2`) at several N — picks the right `cho` for your hardware. |
| `scripts/compute_delta_eff.py` | Numerically integrate the PRX 2015 `Δ_eff` and `ε` fingerprints from the force kernel — sanity-check before launching a Hertzian non-reciprocal campaign. |
| `scripts/two_particle_calibration.py` | Two-particle controlled-collision test for the Hertzian non-reciprocal force — verifies single-pair energy injection against paper Eq. (5). |
| `scripts/visualize_er_h5.py` | Real-time Taichi-UI animation of any HDF5 trajectory; also wrapped as `TaichiTrajectoryViz` in `tools/visualizers/` for config-driven dispatch. |

---

## The AI Skill Workflow

The unique value of this repo is in `.claude/skills/paper-to-experiment/` — a [Claude Code skill](https://docs.claude.com/en/docs/claude-code/skills) that takes you from a PDF to a runnable config without you typing a single param twice.

### How AI uses the skill

```
1. You drop a paper in the conversation:
   "Reproduce Ivlev PRX 2015 Fig 1 — sweep T₀ at fixed φ=0.3, NVE."

2. Claude invokes paper-to-experiment skill, which:
   a. Reads .claude/skills/paper-to-experiment/SKILL.md (the contract)
   b. Reads references/force_types.md (which force types this repo knows)
   c. Reads references/examples/ (worked examples from existing papers)
   d. Reads the actual paper PDF you provided

3. Claude fills templates/physics_design.md (12 sections):
   §1 observables (with paper Eq. citations)
   §2 force field choice
   §3 simulation params
   §4 sweep dimensions
   §5-§7 phases, pass criteria, costs
   §10b ASK USER: items it can't decide alone

4. You review the design doc. If §10b is empty (auto-mode safe),
   Claude proceeds; otherwise it stops and asks.

5. Claude emits configs/plan_<topic>.json from the design doc.

6. Claude runs `validate_config.py --strict`. If exit ≠ 0, fix and retry.

7. Hands off the launch command. You decide when to spend GPU.
```

The skill enforces:

- **Citations are mandatory.** Every observable cites a paper Eq. or Fig. number.
- **No silent invention.** Missing param → `ASK USER:`, never a guess.
- **Smoke before production.** Always. No skipping.
- **Budget guards.** Single-run wall > 24 hr or VRAM > 8 GB → reject, propose smaller.
- **Reuse before extending.** New force class only when no existing one matches the paper's Eq.

### What if the paper needs a force type that doesn't exist yet?

The skill walks you through the 8-step extension process documented in `force_types.md` §4:

1. Add the force class to `forces/<your_force>.py` (template provided) + register in `forces/__init__.py:FORCE_REGISTRY` and `tools/registry.py:_REGISTRY`
2. Write tests
3. Create an entry script (Layer 3 adapter, template provided)
4. Update `scripts/run_experiment.py:_invoke_md` dispatcher AND `scripts/validate_config.py:check_force_type_specific`
5. Update the schema enum
6. Document in the registry
7. Add an analyzer (`tools/analyzers/<paper>.py`) producing `report.md`
8. Add a plotter (`tools/plotters/<paper>.py`) producing `fig*.png`

Each step has a template file under `.claude/skills/paper-to-experiment/templates/`.

---

## Adding your own paper

The fastest case (paper uses a force type already in the repo):

```
1.  cp configs/examples/plan_e_damping.json configs/plan_<your_topic>.json
2.  Edit campaign[0] params per the paper. Cite Eq./Fig. in `notes`.
3.  python scripts/validate_config.py configs/plan_<your_topic>.json --strict
4.  python scripts/run_experiment.py  configs/plan_<your_topic>.json
```

The bigger case (new force type, new analyzer, new figure):

| Goal | Copy template | Save as |
|------|---------------|---------|
| New force type | `templates/force_class.py.template` | save as `forces/<your_force>.py` |
| New paper adapter | `templates/adapter_run.py.template` | `<topic>_run.py` |
| New analyzer | `templates/analyzer.py.template` | `tools/analyzers/<topic>.py` |
| New visualizer | `templates/visualizer.py.template` | `tools/visualizers/<topic>.py` |
| New plotter | `templates/plotter.py.template` | `tools/plotters/<topic>.py` |
| New aggregator | (use plotter template + see `tools/aggregators/`) | `tools/aggregators/<topic>.py` |

Each template has TODO markers. Filling them in order produces a contract-compliant component. Then add one line to `tools/registry.py` to register the class name.

---

## Reference reproductions

The two papers below are reproduced as worked examples. Configs in `configs/examples/`, analyzers in `tools/analyzers/`, figures below.

### Ivlev et al., *Phys. Rev. X* 5, 011035 (2015)

**Non-reciprocal Hertzian binary mixture, two-temperature NVE asymptote.**

| Observable | Paper | Reproduced | Error |
|------------|-------|------------|-------|
| slope_A (T_A ∝ t^α) | 2/3 ≈ 0.667 | 0.6617 | 0.74% |
| τ_∞ = T_A/T_B | 3.10 | 2.86 | 7.9% |
| Δ_eff (analytical fingerprint) | 0.57 | 0.5714 | 0.25% |
| ε (analytical fingerprint) | 0.082 | 0.0822 | 0.19% |

<p align="center">
  <img src="docs/images/fig5_best_case_E2_showcase.png" width="600px" alt="PRX 2015 best-case showcase"/>
  <br><em>Figure 5 — Best-case showcase: slope=2/3 + τ asymptote + KE growing.</em>
</p>

<details>
<summary>More PRX figures (click to expand)</summary>

- `docs/images/fig1_multi_T0.png` — multi-T₀ trajectories
- `docs/images/fig2_multi_phi.png` — multi-φ + n^(2/3) collapse
- `docs/images/fig7_E2_engine_diagnostics.png` — momentum drift √t (Newton 3rd violation)
- `docs/images/fig8_damping_phase_diagram.png` — bifurcation across critical damping ν_c
- `docs/images/fig10_damping_ratio_invariance.png` — T_A/T_B independent of ν

</details>

### Ivlev et al., *Phys. Rev. Lett.* 100, 095003 (2008)

**Anisotropic Yukawa potential, chain formation in electrorheological complex plasmas.**

| Observable | Paper | Reproduced |
|------------|-------|------------|
| g_∥/g_⊥ ratio at chain peak (MT=0.8) | > 2× | **5.33×** |
| chain spacing r* | ≈ 4λ | 3.6 λ |
| optimal MT regime | [0.6, 0.9] | [0.7, 0.9] (Q-peak monotonic) |
| ⟨L⟩ at MT=0.8 (paper qualitative) | "chains form" | **5.15 particles, 84% of system** |
| Sonic instability (MT→1) | qualitative | **0 chains @ MT=1.0** |

<p align="center">
  <img src="docs/images/fig15_er_long_g_at_chain_peak.png" width="700px" alt="PRL 2008 chain signature"/>
  <br><em>Figure 15 — g_∥(r) vs g_⊥(r) at peak chain time. ER4L (MT=0.8) shows the textbook chain signature: dominant axial peak at r ≈ 3.6λ, suppressed transverse correlation.</em>
</p>

<p align="center">
  <img src="docs/images/fig17_er_chain_length_dist.png" width="700px" alt="PRL 2008 chain length stats"/>
  <br><em>Figure 17 — Chain length distribution. ⟨L⟩ peaks at MT=0.8; collapses at sonic limit MT=1.</em>
</p>

---

## Project layout

```
md-for-dummies/
├── README.md                       this file
├── ARCHITECTURE.md                 the 4-layer + 6-phase spec (~400 lines)
├── LICENSE                         MIT
├── requirements.txt
│
├── .claude/skills/
│   ├── paper-to-experiment/        the AI skill that drives the workflow
│   │   ├── SKILL.md                7-step process + hard rules
│   │   ├── templates/              physics_design.md, plan_config.schema.json
│   │   └── references/             force_types registry + worked examples
│   └── creator/                    meta-skill (generate a paper-to-experiment
│                                    skill for a different framework — WIP)
│
├── configs/examples/               worked example configs from the 2 papers
│
├── tools/                          platform package (registry-dispatched)
│   ├── analyzers/{prx,er}.py
│   ├── plotters/prx.py
│   ├── aggregators/{prx,er}.py
│   ├── visualizers/taichi_traj.py
│   ├── registry.py                 name → class lookup
│   ├── runner.py / resources.py / file_io.py
│   ├── validate_manifest.py        post-run §3.2 contract gate
│   └── migrate_manifests.py        backfill canonical fields in old manifests
│
├── scripts/
│   ├── run_experiment.py           the SOLE entry point
│   ├── validate_config.py          schema + physics + budget gate
│   └── analyze_er.py               ER analysis CLI (chain / long / length)
│
├── prx_nonreciprocal_run.py        Layer 3 adapter — PRX 2015
├── er_plasma_run.py                Layer 3 adapter — PRL 2008
│
├── forces/                         Layer 1 — one file per force class (HertzianNonreciprocal, ERPotential, LJ)
├── systemClass.py                  Layer 1 — MD orchestrator
├── atomSystemClass.py              Layer 1 — particle state
├── integratorClass.py              Layer 1 — BAOAB
├── searchBox.py                    Layer 1 — cell-list / O(N²) neighbor table
├── constSet.py                     Layer 1 — units (reduced / macro)
├── toolClass.py                    backward-compat shim for the tools/ split
│
├── tests/                          pytest contract + regression tests
└── docs/images/                    reproduction figures (8 selected)
```

---

## Contributing

This is a teaching framework — the goal is **clarity over performance, reproducibility over feature count**. Pull requests welcome, especially:

- new paper reproductions (with worked example config + adapter + analyzer)
- new analyzers / visualizers / aggregators
- documentation / explanatory diagrams in `ARCHITECTURE.md`

Less welcome:

- alternative integrators / accelerators (the Layer 1 core is intentionally frozen)
- giant abstraction layers — the simplicity is a feature

When opening a PR for a new paper:

1. Add a config under `configs/examples/`
2. If the paper needs a new force, follow `force_types.md` §3 (the 6-step process)
3. Add tests under `tests/`
4. Add 1-2 reproduction figures to `docs/images/` and reference them in your example config's `_design_doc`

---

## References

- Ivlev, A. V. *et al.* "Statistical mechanics where Newton's third law is broken." *Phys. Rev. X* **5**, 011035 (2015). [DOI:10.1103/PhysRevX.5.011035](https://doi.org/10.1103/PhysRevX.5.011035)
- Ivlev, A. V. *et al.* "First Observation of Electrorheological Plasmas." *Phys. Rev. Lett.* **100**, 095003 (2008). [DOI:10.1103/PhysRevLett.100.095003](https://doi.org/10.1103/PhysRevLett.100.095003)
- Hu, Y. *et al.* "Taichi: a Language for High-Performance Computation on Spatially Sparse Data Structures." *ACM Trans. Graph.* **38**, 6 (2019). The Taichi compiler powering Layer 1.

---

## License

MIT — see [`LICENSE`](LICENSE).

If you use this framework in published work, citing the framework is appreciated but not required. Citing the original physics papers (above) is required.

# Contributing to MD-for-Dummies

Thanks for considering a contribution. This is a small framework with strong opinions about what belongs where, so a few minutes reading this guide saves a lot of review back-and-forth.

## Project ethos (please read once)

- **Clarity over performance.** A 5-line readable function beats a 50-line optimized one. Optimize only when there's a measured bottleneck.
- **Reproducibility over feature count.** Every contribution should make some paper *easier to reproduce*, not add another knob.
- **Layered, not entangled.** New code goes in exactly one layer (see `ARCHITECTURE.md` §1). If you find yourself crossing layers, refactor first.
- **AI skill is a first-class user.** Don't add patterns that the `paper-to-experiment` skill cannot describe in `force_types.md`. If a new mechanism needs explanation in 5 places, simplify it.

## Most welcome contributions

| Kind | What you'd do | Touchpoints |
|------|---------------|-------------|
| **New paper reproduction** | Add a config, possibly an adapter or analyzer, plot the figure | `configs/examples/`, `tools/analyzers/`, `tools/plotters/`, optional `<topic>_run.py` |
| **New analyzer or plotter** | Pure post-processing class registered in `tools/registry.py` | `tools/analyzers/<x>.py` + 1 line in registry |
| **New visualizer** | Real-time or recorded animation class | `tools/visualizers/<x>.py` + 1 line in registry |
| **Architecture diagrams** | Educational figures explaining a layer or phase | `docs/images/` referenced from `ARCHITECTURE.md` |
| **Skill improvements** | Better questions, better critique surfacing | `.claude/skills/paper-to-experiment/` |
| **Bug fixes + tests** | always | wherever |

## Less welcome

- **Alternative integrators / accelerators.** The Layer 1 core is intentionally frozen. There are excellent fast MD engines elsewhere; this isn't trying to be one.
- **Giant abstraction layers.** Prefer one focused module per concept.
- **Force classes without tests.** Every new `forces/<your_force>.py` needs at least 4 test cases (analytic 2-particle force, symmetry, cutoff boundary, regression).

## Step-by-step: contributing a new paper reproduction

This is the most common contribution path.

### 1. Pick the paper

Open an issue first describing:
- Citation
- Which figure(s) you'll claim to reproduce
- Whether it needs a new force type (compare to `references/force_types.md`)

This lets maintainers flag scope concerns before you write code.

### 2. Use the AI skill (recommended)

In Claude Code:

```
/paper-to-experiment
```

The skill walks the design doc + emits a config. Save the design doc as part of your PR — it's documentation as much as code.

If you don't have Claude Code, use the templates manually:

```
.claude/skills/paper-to-experiment/templates/physics_design.md
.claude/skills/paper-to-experiment/templates/plan_config.schema.json
```

### 3. If your paper needs a new force type

Follow `references/force_types.md` §4 — the 8-step extension process:

1. Add force class (use `templates/force_class.py.template`)
2. Write tests (`tests/test_<class>_4cases.py`)
3. Create entry script (use `templates/adapter_run.py.template`)
4. Update `scripts/run_experiment.py:_invoke_md` dispatcher
5. Update `templates/plan_config.schema.json` enum + conditional required fields
6. Document in `references/force_types.md`

Each step has a template. Do them in order; the platform refuses to run a force type that's only halfway plumbed.

### 4. Add tests

| What you added | What test | Where |
|----------------|-----------|-------|
| Force class | 4-case (analytic, symmetry, cutoff) | `tests/test_<class>_4cases.py` |
| Analyzer | round-trip on a known fixture | `tests/test_<analyzer>.py` |
| Schema field | validation passes/fails as expected | `tests/test_skill_regression.py` |
| Entry script | smoke (100 steps, no GPU required if mockable) | `tests/test_<topic>_smoke.py` |

Tests must run on CPU when possible. GPU-only tests are tolerated only if the kernel-under-test is GPU-bound.

```
pytest tests/ -q   # all tests under 10 seconds total (excluding GPU smokes)
```

### 5. Add reproduction figures

Pick **at most 3 figures** for `docs/images/`. Pick the ones a reader needs to believe the reproduction worked. Reference them from your config's `_design_doc` field.

### 6. Open the PR

Include:

- Link to the design doc (committed as part of the PR)
- Output of `validate_config.py --strict` on your new config (paste the stdout)
- Link to the reproduced figure(s) showing the published result
- The numeric metric (slope, ratio, ⟨L⟩, ...) and the % error vs paper

Maintainers will mostly comment on whether the layering is clean and whether the design doc cites the paper precisely.

## Code style

- **Python 3.10+.** Type hints encouraged on public class methods.
- **No semicolons.** No `from X import *` outside backward-compat shims.
- **Docstrings**: one-line summary + maybe a short example. No 50-line preludes.
- **Comments**: only when the *why* isn't obvious. Don't comment what the code says.
- **Imports**: stdlib → third-party → local, blank line between groups.
- **No emoji** in code. Emoji in markdown is fine, sparingly.

## Commit messages

Conventional-commits style:

```
feat(prx): add Plan H runs covering supercritical damping
fix(er): correct cutoff sign at large MT
docs(arch): clarify §3.5 aggregator contract for run_dirs
test(force): regression for HertzianNonreciprocal A-B asymmetry
```

Subject ≤ 70 chars. Body wraps at 72.

## Reviewing PRs (for maintainers)

The most common rejection reasons:

1. **Layering violation** — adapter calls analyzer in-process, or analyzer reaches into force class internals
2. **Hardcoded paper-specific values in `tools/`** — if it's paper-specific, it lives in a config or in `tools/<paper>/`
3. **No design doc** — for new papers, the design doc is the spec
4. **Skill registry not updated** — new class without one-line entry in `tools/registry.py`
5. **Missing citations** — observables without paper Eq./Fig. reference

When approving:

- Check `pytest tests/ -q` is green on a fresh checkout
- Check `validate_config.py --strict` passes on each new config
- Check the contributor's reproduction figure is **shown in the PR description**, not just linked

## Questions

Open an issue. Describe what you're trying to do, what you tried, and what surprised you. The framework is small enough that there's almost always one right answer.

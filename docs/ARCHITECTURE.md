# md-for-dummies Architecture

> 2026-05-08 — Framework reorganization spec.
> Reading order: §1 layers → §2 phase flow → §3 contracts → §4 templates → §5 decisions → §6 migration.

---

## §1 Four-layer architecture

The framework is **strictly layered**. Each layer talks ONLY to the layer below it, never up. Mixing layers is the #1 source of bugs.

```
╔══════════════════════════════════════════════════════════════════════╗
║  Layer 4 — CONFIG (data, no code)                                     ║   ←  USER WRITES
║  configs/plan_*.json  (YAML supported via _ext field, JSON canonical) ║      ALL OF THIS
║  • Multi-run campaign list                                            ║
║  • Pipeline phases (preflight/smoke/production/visualize/analyze/agg) ║
║  • Class-name registration: analyzer / visualizer / force_type        ║
║  • Pass criteria + budget guards                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  Layer 3 — ADAPTER (per-paper, user-written, follows TEMPLATE)         ║   ←  USER WRITES
║  prx_nonreciprocal_run.py (PRX 2015), er_plasma_run.py (PRL 2008)      ║      WHEN ADDING
║  Responsibility:                                                       ║      A NEW PAPER
║  • Paper-specific defaults (PRX_PARAMS / ER_PARAMS dict)               ║
║  • Lattice prep (paper-specific initial config)                        ║
║  • Force class + parameter mapping                                     ║
║  • Manifest fields specific to this paper                              ║
║  • Paper-specific figure list                                          ║
║  Responsibility BOUNDARY:                                              ║
║  • MUST implement `run_one(params: dict) -> manifest_dict` contract    ║
║  • MUST NOT directly call analyzers/plotters — let platform dispatch   ║
║  • MUST NOT touch GPU / HDF5 / threading directly — use tools/         ║
╠══════════════════════════════════════════════════════════════════════╣
║  Layer 2 — PLATFORM (paper-agnostic, reusable, FROZEN unless bugs)     ║   ←  PROJECT
║  scripts/run_experiment.py    — campaign orchestrator                  ║      MAINTAINER
║  scripts/validate_config.py   — schema + physics + budget gate         ║      OWNS
║  tools/runner.py              — ExperimentRunner class                 ║
║  tools/resources.py           — ResourceEstimator + PriorRunsDB        ║
║  tools/registry.py            — name → class lookup                    ║
║  Provides:                                                             ║
║  • Phase scheduling (validate → preflight → smoke → production →      ║
║    visualize → aggregate)                                              ║
║  • Parallel scheduling (LPT, max_parallel)                             ║
║  • Class-name dispatch via registry                                    ║
║  • Manifest writing, log redirection, halt-on-fail                     ║
╠══════════════════════════════════════════════════════════════════════╣
║  Layer 1 — INFRASTRUCTURE (FROZEN — physics core, do not modify)       ║
║  systemClass.py, atomSystemClass.py, integratorClass.py,               ║
║  searchBox.py, forces/, constSet.py                                    ║
║  • Taichi 1.7.4 kernels: BAOAB integrator, cell-list/O(N²) neighbors   ║
║  • HDF5 async chunked writer                                           ║
║  • Force classes (one file each in forces/):                           ║
║    HertzianNonreciprocal, ERPotential, lennardJones                    ║
║  Out of scope for now: integrators, accelerators (current sufficient)  ║
╚══════════════════════════════════════════════════════════════════════╝
                                  ▲
                                  │ tools/analyzers/, tools/visualizers/,
                                  │ tools/plotters/  ←  USER EXTENDS
                                  │ (registered by name in tools/registry.py;
                                  │  follow contracts in §3)
```

**Three classes of additions** the user makes, in increasing complexity:

| Type | Files touched | Time | Example |
|---|---|---|---|
| **新参数扫描** | `configs/plan_*.json` only | 5 min | Plan G3 covering MT={0.5, 0.7} |
| **新分析/可视化** | `tools/analyzers/<x>.py` + 1 line in `tools/registry.py` + config block | 30 min | Add chain-length analyzer |
| **新论文复现** | `<paper>_run.py` (Layer 3) + maybe new force class (Layer 1) + analyzers (extend) | 1-3 days | PRL 2008 → ER plasma |

---

## §2 Phase flow (single run)

```
USER:  python scripts/run_experiment.py configs/plan_X.json
        │
        ▼
╔════════════════════════ Layer 2: PLATFORM ════════════════════════════╗
║                                                                       ║
║  ┌──────────────────────────────────────────────────────────────┐     ║
║  │ Phase 0: CONFIG VALIDATE (validate_config.py --strict)       │     ║
║  │   • JSON Schema  (templates/plan_config.schema.json)         │     ║
║  │   • Physics rules (ν<ν_c, MT∈chain regime, smoke≥100, …)     │     ║
║  │   • Budget guards (wall<24hr, VRAM<8GB, disk<50GB)           │     ║
║  │   • Cost estimate (re-calibrated step-rate model)            │     ║
║  │   FAILS  →  exit 1   (no GPU touched)                        │     ║
║  │   PASSES →  proceed                                          │     ║
║  └─────────────────────────────┬────────────────────────────────┘     ║
║                                │                                      ║
║                                ▼                                      ║
║  ┌──────────────────────────────────────────────────────────────┐     ║
║  │ Phase 1: PREFLIGHT (resource estimate per campaign entry)    │     ║
║  │   ResourceEstimator.print_preflight(exp)                     │     ║
║  │   prints:  N | steps | RAM | VRAM | wall hr | disk           │     ║
║  └─────────────────────────────┬────────────────────────────────┘     ║
║                                │                                      ║
║                                ▼                                      ║
║  ┌──────────────────────────────────────────────────────────────┐     ║
║  │ Phase 2: SMOKE (default 100 steps per entry, serial)         │     ║
║  │   Catches crashes before paying for full run                 │     ║
║  │   halt_on_fail=true → first failure stops campaign           │     ║
║  └─────────────────────────────┬────────────────────────────────┘     ║
║                                │                                      ║
║                                ▼                                      ║
║  ┌──────────────────────────────────────────────────────────────┐     ║
║  │ Phase 3: PRODUCTION                                          │     ║
║  │   For each campaign entry:                                   │     ║
║  │     1. Dispatch by exp.force_type                            │     ║
║  │     2. Invoke Layer 3 ADAPTER as subprocess                  │ ────╬───▶ Layer 3
║  │        env: PYTHONIOENCODING=utf-8                           │     ║       (per-paper
║  │        cmd: python <adapter>.py --tag X --param Y ...        │     ║        adapter)
║  │     3. Read manifest.json adapter wrote                      │     ║       │
║  │     4. Optionally run in parallel (max_parallel=2-3)         │     ║       │
║  └─────────────────────────────┬────────────────────────────────┘     ║       │
║                                │                                      ║       │
║                                ▼                                      ║       │
║  ┌──────────────────────────────────────────────────────────────┐     ║       │
║  │ Phase 3.5: VISUALIZE (optional, class-dispatched, NEW)       │     ║       │
║  │   if pipeline.visualize.enabled:                             │     ║       │
║  │     VizCls = registry.resolve(pipeline.visualize.class)      │     ║       │
║  │     VizCls(**params).render(run_dir)                         │     ║       │
║  └─────────────────────────────┬────────────────────────────────┘     ║       │
║                                │                                      ║       │
║                                ▼                                      ║       │
║  ┌──────────────────────────────────────────────────────────────┐     ║       │
║  │ Phase 4: AGGREGATE (optional, cross-run)                     │     ║       │
║  │   if aggregation.enabled:                                    │     ║       │
║  │     pull all run_dir manifest.json                           │     ║       │
║  │     Pcfg.aggregator_class.aggregate(records, …)              │     ║       │
║  │     write master report .md + cross-run figures              │     ║       │
║  └──────────────────────────────────────────────────────────────┘     ║       │
║                                                                       ║       │
╚════════════════════════════════════════════════════════════════════════╝       │
                                                                                  │
        ╔════════════════ Layer 3: ADAPTER (per-paper) ═══════════════════╗◀─────┘
        ║                                                                  ║
        ║  Sequence (10 mandatory steps, see §3.1):                        ║
        ║   1. Parse CLI / params                                          ║
        ║   2. Create per-run output dir (timestamp + tag)                 ║
        ║   3. Call ResourceEstimator.print_preflight (re-checks)          ║
        ║   4. Prepare lattice / initial config                            ║
        ║   5. Write run.in (physics params for systemRun)                 ║
        ║   6. systemRun(paramFile, coorFile)                              ║
        ║   7. system.register(...) and system.initParams(...)             ║
        ║   8. system.runWithData(outputPath, withData=True)               ║
        ║   9. Write manifest.json                                         ║
        ║  10. (NO direct analyzer calls — return; Phase 3.5/4 dispatches) ║
        ║                                                                  ║
        ╚══════════════════════════════════════════════════════════════════╝
                                  │
                                  ▼ uses
        ╔════════════════ Layer 1: INFRASTRUCTURE ════════════════════════╗
        ║   Taichi MD core (BAOAB + cell-list + HDF5 writer)               ║
        ╚══════════════════════════════════════════════════════════════════╝
```

---

## §3 Contracts (the strict interfaces)

### §3.1 Adapter contract (Layer 3 → Layer 2)

A "paper adapter" is any script in the project root named `<topic>_run.py`. To be platform-compatible it MUST satisfy:

**INPUT** (from CLI flags injected by `run_experiment.py`):

| Flag | Type | Meaning |
|------|------|---------|
| `--tag <str>` | str, [A-Za-z0-9_]{2,32} | unique campaign-entry id |
| `--steps <int>` | int | total integration steps |
| `--stride <int>` | int | HDF5 frames |
| `(force-specific)` | mixed | the keys defined in `references/force_types.md` for this `force_type` |

**OUTPUT** (written before exit):

| Path | Required | Format | Content |
|------|----------|--------|---------|
| `outputFiles/<TS>_<tag>/manifest.json` | ✓ | JSON | see §3.2 |
| `outputFiles/<TS>_<tag>/<base>_<step>.h5` | ✓ | HDF5 | trajectory (pos, vel, time, T, …) |
| `outputFiles/<TS>_<tag>/run.in` | ✓ | text | archived physics params |
| `outputFiles/<TS>_<tag>/lattice.xyz` | ✓ | text | archived initial config |
| stdout | ✓ | text | progress lines, manifest summary |
| exit code | ✓ | int | 0 = OK, non-zero = halt-on-fail trigger |

**FORBIDDEN**:
- Calling analyzers/plotters/visualizers directly. Platform decides via Phase 3.5 / 4.
- Touching `outputFiles/<other_run>/...`. One adapter == one run dir.
- Modifying anything outside `outputFiles/<TS>_<tag>/`, `dataFiles/<adapter>_<tag>.*`, and `stdout`.

### §3.2 Manifest schema (Layer 3 → Layer 2 → Layer 4)

`manifest.json` is the SOLE communication channel from adapter to platform. Required fields:

```json
{
  "tag":            "<from CLI>",
  "run_type":       "<force_type>",
  "force_class":    "<exact class name from forces/ — see tools/registry.py>",
  "units":          "reduced | macro",
  "run_dir":        "<absolute path>",
  "h5_path":        "<absolute path to trajectory>",
  "started_at":     "<ISO datetime>",
  "finished_at":    "<ISO datetime>",
  "wall_seconds":   <float>,
  "git_sha":        "<short SHA or 'unknown'>",
  "steps":          <int>,
  "write_stride":   <int>,
  "actual_step_rate": <float, steps/sec>,

  "<paper-specific>": "..."
}
```

Adapter MAY add paper-specific fields (e.g., `phi_target`, `MT`, `Z_eff`). Platform never reads them — they're for the analyzer in Phase 4.

### §3.3 Analyzer contract (Layer 2 → tools/analyzers)

Any class registered in `tools/registry.py` as an analyzer MUST implement:

```python
class MyAnalyzer:
    @staticmethod
    def full_analysis(run_dir: str | Path, **params) -> dict:
        """Read trajectory at run_dir, compute observables, return summary dict.

        run_dir: absolute path containing manifest.json + *.h5
        params:  forwarded from pipeline.analyzer_params in config
        Returns: {"verdict": "PASS|NEAR|FAIL", **metrics}
        """
        ...
```

Optional but recommended:

```python
    @staticmethod
    def load_run(run_dir) -> dict:        # raw data load
    @staticmethod
    def aggregate(records, **params) -> dict:  # cross-run summary
```

### §3.4 Visualizer contract

```python
class MyViz:
    def __init__(self, **params):
        ...
    def render(self, run_dir: str | Path) -> None:
        """Open interactive window OR write file (if self.record set)."""
```

Optional: `.show(run_dir)` alias.

### §3.5 Plotter contract

```python
class MyPlotter:
    @staticmethod
    def fig_<name>(records: list[dict], out_path: str | Path,
                   title: str = "...", **params) -> None:
        """Read multiple run records, write a publication figure to out_path."""
```

Recommended: name methods `fig_<thesis_section>_<topic>` so `pipeline.aggregation.plots` can reference them by short name.

### §3.6 Documented limitations

These behaviors are intentional but surprising. Read once.

1. **Aggregator output paths are caller-relative.** `aggregate(output="master.md")` lands in `cwd`, not project root. Always pass an absolute path or one with at least one parent directory (e.g. `"docs/master.md"`).
2. **Mixed-force-type campaigns** are allowed at config + dispatch level (one PRX entry + one ER entry coexist in one JSON). But `aggregation.class` is single-valued, so a single aggregator only ever sees one paper's records. For mixed campaigns, set `aggregation.enabled=false` and run the two aggregators separately.
3. **Registry resolution is deferred-failure.** Schema lets any string through for `pipeline.visualize.class` and `aggregation.class`. `tools.registry.resolve()` raises `KeyError` only at dispatch time. Acceptable trade-off for plug-in architecture; consider a `--registry-check` flag in `validate_config.py` if pre-flight class checking becomes important.
4. **Per-class params are not pre-flight checked.** `params` is `{"type": "object"}` in schema with no per-class shape. Visualizer / analyzer constructors enforce their own contract — for example `TaichiTrajectoryViz` raises `TypeError` on unknown kwargs. New extensions should follow the same rule.

---

## §4 Templates (copy these when adding new things)

The framework ships templates at `.claude/skills/paper-to-experiment/templates/`. To add a new artifact:

| Goal | Copy this template | Save as |
|------|--------------------|---------|
| New paper (Layer 3 adapter) | `templates/adapter_run.py.template` | `<topic>_run.py` (project root) |
| New analyzer | `templates/analyzer.py.template` | `tools/analyzers/<x>.py` |
| New visualizer | `templates/visualizer.py.template` | `tools/visualizers/<x>.py` |
| New plotter | `templates/plotter.py.template` | `tools/plotters/<x>.py` |
| New force class | `templates/force_class.py.template` | save as `forces/<your_force>.py` |

Each template has ALL contract requirements as `# TODO:` markers. Filling them in order produces a working, contract-compliant component.

---

## §5 Decision points (open for user review)

These were resolved by the framework maintainer in auto-mode. Override at any time.

| ID | Decision | Chosen | Alternative |
|----|----------|--------|-------------|
| **D1** | Config format | **JSON canonical** (Schema-validated) | YAML supported via auto-convert |
| **D2** | Adapter shape | **Function-based** (script with `main()` + CLI args) | Class-based (subclass `BaseAdapter`) |
| **D3** | Adapter dispatch | **Subprocess** (each entry script in fresh Python) | In-process import |
| **D4** | Registry single source | **`tools/registry.py`** | Skill-side `force_types.md` (now references registry) |
| **D5** | Analyzer auto-invoke | **Platform decides** via Phase 3.5/4 | Adapter calls in-process |
| **D6** | Output of analyzer | **Returns `dict`**, platform writes report | Analyzer writes report itself |
| **D7** | Multi-run config | **Single JSON listing campaign entries** | One JSON per entry + glob |
| **D8** | Communication channel | **`manifest.json` + stdout** | RPC / shared memory |

If any of these conflict with your intended workflow, propose a switch and I'll update the architecture + migration steps.

---

## §6 Compliance enforcement

Contracts are enforced at four gates. Anything that bends a contract is rejected before it can pollute outputs.

| Gate | Tool | Catches |
|------|------|---------|
| Schema | `scripts/validate_config.py --strict` | malformed config; missing `force_type`; out-of-range params; budget violations |
| Physics | `validate_config.py` (rule layer) | super-critical damping; insufficient run length for chain regime; smoke too short |
| Manifest | `tools/validate_manifest.py` | adapter-emitted manifest missing required §3.2 fields |
| Runtime | `tools/registry.resolve()` | unregistered analyzer / visualizer / aggregator class names |

If a paper-specific adapter writes legacy fields (e.g. `T0_K` but not canonical `T0`), `tools/migrate_manifests.py` adds the canonical aliases without removing the originals. Run it once after upgrading.

---

## §7 Quick reference — single page

```
USER WRITES                    PLATFORM PROVIDES                      USER EXTENDS
═══════════                    ═════════════════                      ════════════
configs/plan_*.json    ─────▶  scripts/run_experiment.py    ─────▶  prx_nonreciprocal_run.py
                                                                      er_plasma_run.py
                                tools/registry.py    ◀────────────  tools/analyzers/<x>.py
                                tools/runner.py                       tools/visualizers/<x>.py
                                tools/resources.py                    tools/plotters/<x>.py
                                                                      (one-line registry entry each)

Phase 0:   validate_config.py --strict      (always; pure check)
Phase 1:   preflight                         (resource estimate)
Phase 2:   smoke (100 steps)                (catches crashes)
Phase 3:   production (parallel)            (calls adapter via subprocess)
   └── adapter writes manifest.json + .h5   (sole communication channel)
Phase 3.5: visualize  (NEW, registry-dispatched, per-run, optional)
Phase 4:   aggregate  (registry-dispatched, cross-run, optional)
              ├── PRXAggregator  → fig1/fig2/ratio/stability + master.md
              └── ERAggregator   → fig11-17 + extended_results.md

Adapter contract:   §3.1 + manifest §3.2
Analyzer contract:  full_analysis(run_dir, **params) -> dict
Visualizer contract: __init__(**params) → .render(run_dir)
Plotter contract:    static fig_<name>(records, out_path, **params)

To add a new paper:    copy templates/adapter_run.py.template
To add an analyzer:    copy templates/analyzer.py.template
To add a viz:          copy templates/visualizer.py.template
To add a force class:  copy templates/force_class.py.template + 8-step process
                       in references/force_types.md §4
To add a sweep only:   write configs/plan_X.json + python scripts/run_experiment.py
```

---

End of architecture spec. For paper-to-config workflow see `.claude/skills/paper-to-experiment/SKILL.md`. For run flow walkthroughs see prior `_mapping_table.md`.

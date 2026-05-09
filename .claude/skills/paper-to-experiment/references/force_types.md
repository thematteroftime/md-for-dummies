# Force-type registry

Authoritative source for which `force_type` strings are valid in `configs/plan_*.json` and what fields each requires. Skill must consult this BEFORE proposing any config field.

When adding a new force type, follow §4 below (8-step extension) — registry is the gatekeeper, schema and skill follow.

---

## 1. `hertzian_nonreciprocal`  (PRX 2015)

- **paper**: Ivlev et al. *Phys. Rev. X* 5, 011035 (2015), Eq. (1)
- **entry script**: `prx_nonreciprocal_run.py`
- **force class**: `forces.hertzian_nonreciprocal:HertzianNonreciprocal`
- **analyzer**: `toolClass.PRXAnalyzer` (in-process via `PRXAnalyzer.full_analysis`)
- **compat**: `ndim=3`, `units_regime=reduced_lj`
- **box**: derived from N and φ
- **integrator**: BAOAB (NVE if ν=0, Langevin else)

### Required fields per experiment

| field | type | range | meaning |
|-------|------|-------|---------|
| `tag` | str | `[A-Za-z0-9_]{2,32}` | unique run id |
| `phi` | float | (0, 1.0] | reduced number density |
| `T0`  | float | (0, 100] | initial temperature (reduced) |
| `steps` | int | [100, 5e7] | total integration steps |
| `stride` | int | [1, 1e5] | frames between HDF5 writes |

### Optional fields

| field | type | default | meaning |
|-------|------|---------|---------|
| `nu` | float | 0 | Langevin damping; 0 = pure NVE |
| `N` | int | 10000 | **per-species count**: `--N` arg sets `N_A = N_B = N`, **total particles = 2 × N**. Default 10000 → total 20000. Critical: setting `N=20000` yields total 40000, NOT 20000. |
| `dt` | float | 0.004 (PRX_PARAMS default in `prx_nonreciprocal_run.py`) | time step in τ |
| `chunk_size` | int | 200 | HDF5 chunk frames; cap 200 unless RAM allows |
| `write_stride` | int | 100 | frames per disk flush |
| `profiler` | bool | false | enable Taichi profiler (warning: OOM risk on long runs) |

### Critical pre-flight rules

- **`nu > 0` requires `nu ≤ ν_c = c/(2*T0^1.5)`** with `c ≈ 1.5e-4`. Skill MUST compute ν_c and warn if exceeded.
- **`steps × dt > 50000 τ`**: cap RAM via `chunk_size: 200` and `profiler: false`.
- **Damping experiments**: ALWAYS confirm corresponding NVE run at same (φ, T0) reached `slope_A ≥ 0.6` first (P3 invariant).

### Example (E14, sub-critical damping)

```json
{
  "force_type": "hertzian_nonreciprocal",
  "tag": "E14_nu1em5",
  "phi": 0.3,
  "T0": 0.3,
  "nu": 1e-5,
  "steps": 10000000,
  "stride": 1000
}
```

---

## 2. `er_plasma`  (PRL 2008)

- **paper**: Ivlev et al. *Phys. Rev. Lett.* 100, 095003 (2008)
- **entry script**: `er_plasma_run.py`
- **force class**: `forces.er_potential:ERPotential` (anisotropic Yukawa, Eq. (1))
- **analyzers**: `scripts/analyze_er.py` (CLI, accepts `--runs` glob), `tools.analyzers.er.ERAnalyzer` (registry-callable wrapper)
- **compat**: `ndim=3`, `units_regime=macro_dust` — required, ERPotential hard-codes 3D and the macro mm/ms/K scale
- **integrator**: BAOAB with Langevin damping (default `nu=0.1 /ms`)
- **lattice**: 1000-atom 10×10×10 lattice file expected at `dataFiles/<lattice>.xyz`

### Required fields per experiment

| field | type | range | meaning |
|-------|------|-------|---------|
| `tag` | str | `[A-Za-z0-9_]{2,32}` | unique run id |
| `MT` | float | [0, 1.2] | dimensionless ion-flow Mach number |
| `Z_eff` | float | [1, 1e5] | effective dust charge in units of e |
| `lambda_mm` | float | [0.001, 10] | Debye screening length in mm |
| `T0_K` | float | [1, 1e4] | initial temperature in Kelvin |
| `dt_ms` | float | [1e-4, 1] | time step in ms |
| `steps` | int | [100, 5e7] | total integration steps |
| `stride` | int | [1, 1e5] | frames between HDF5 writes |

### Optional fields

| field | type | default | meaning |
|-------|------|---------|---------|
| `nu` | float | 0.1 (1/ms) | Langevin damping; for ER plasmas always ≠ 0 |
| `N` | int | 1000 | particle count (must match lattice file) |
| `cho` | enum {1,2} | 2 | 1 = cell-list (N>3000), 2 = O(N²) (small N) |

### Critical pre-flight rules

- **N=1000 corresponds to `xyz_1000_3.in` lattice; box ≈ 1.07 mm cube**. Different N requires new lattice file.
- **cutoff = 12·λ_mm, cutoffNegh = 18·λ_mm** auto-set by entry script.
- **`MT > 1.0` is the sonic limit** — chains destabilize, expect early Q peak then collapse. Skill must flag this in design doc §6 pass criteria.
- **Run length**: 50k steps (=500 ms with dt=0.01) is INSUFFICIENT due to initial-lattice / chain-spacing coincidence. Use ≥100k steps for chain-phase reproduction.

### Example (ER4L, MT=0.8 main result)

```json
{
  "force_type": "er_plasma",
  "tag": "ER4L_MT08",
  "MT": 0.8,
  "Z_eff": 10000,
  "lambda_mm": 0.05,
  "N": 1000,
  "T0_K": 348,
  "dt_ms": 0.01,
  "steps": 100000,
  "stride": 200,
  "nu": 0.1,
  "cho": 2
}
```

---

## 3. Engine integration notes (read before adding a new force type)

These platform behaviours are non-obvious and have caught autonomous extension agents. Worth reading once.

### Units handshake (3-way coupling)

Every force_type ties together three labels that MUST match:

1. The `units` keyword in the adapter-emitted `run.in` file (e.g. `units macro`)
2. The exact filename under `units/<name>.yaml` that constSet loads (e.g. `units/macro.yaml`)
3. The schema's `units_regime` enum value declared in the force_type's compat block (e.g. `macro_dust`)

Adding a new regime requires creating a new yaml under `units/`, then emitting that yaml's stem in `run.in:units` AND in the manifest's `units` field, while the schema-side `units_regime` is the human-readable enum label that maps to it.

### `ndim=2` requires `Lz ≥ cutoffNegh`

Even though z is force-zeroed every integrator step (`integratorClass.inteBegin`), the underlying searchBox neighbour pass still runs through the 3D MIC kernel. If the lattice file's z-extent is below `cutoffNegh`, `atomSystemClass.addNegh` asserts at startup. **2D adapters must set the lattice's `Lz ≥ cutoffNegh`** (a flat slab is fine — z stays zero throughout integration). Document `cutoffNegh` ≈ 1.3·`cutoff` ≈ 6·λ as a reasonable default, then size Lz accordingly.

### Full-list pattern

`requires_full_list = True` means the neighbour list visits both `(i, j)` AND `(j, i)` for every unordered pair. The kernel must:
- Write force ONLY to `force[i]` (never to `force[j]`) — the reverse visit handles `j` separately.
- Accumulate PE as `pe_per_atom[i] += 0.5 * U_pair` (the 0.5 factor compensates for the duplicate visit).

Read `lennardJones.updateOneF_reciprocal` (`forces/lennard_jones.py`) for the canonical reciprocal pattern. The template `force_class.py.template` documents this in detail.

### Initial state

`AtomSystem.initData(positions, masses, T0, boxList, groups=...)` calls `scaleVel` internally — velocities are randomized to T0. Tests that need zero initial velocity must call `A.vel.fill(0.0)` AFTER `initData`.

### Long-range repulsive IC caveat

For force types whose pair potential diverges (or stays large) as `r→0` — Coulomb, Yukawa, screened-dipole, anything with a hard core — random uniform initial positions inevitably contain small-r overlaps. On step 1 these get converted into kinetic energy:

- A few overlapping pairs at `r ~ 0.1·a` produce orders-of-magnitude force spikes.
- The integrator turns the spurious PE into spurious KE within a single step, leaving `T_init ≫ T0_target`.
- If the run is short (≤ a few `1/ω_p`) and Langevin damping is heavy (`ν > 0.05`), the damping over-cools relative to the fluctuation-dissipation balance and the steady-state `T_meas` ends up *below* `T0_target`. Observed shortfall in autonomous-Yukawa-OCP test: `T_meas ≈ T0/10` after 100·`1/ω_p`.

**Mitigation, in order of preference:**
1. **Lattice IC + brief NVE warmup**: use `tools/lattices/<lattice>_<dim>.py` (default `square_2d` / `simple_cubic_3d`; or `triangular_2d` for hexatic phases) followed by NVE for `~10·(1/ω_p)` to dissipate any residual lattice-mode energy.
2. **Random IC + soft repulsion ramp**: scale the potential by `λ(t)` ramping from 0 → 1 over `~5·(1/ω_p)` to avoid the step-1 overlap spike.
3. **Random IC + heavy short Langevin equilibration THEN swap to weak**: legitimate but parameter-sensitive.

Any new force class subclassing `forceField` whose potential diverges at the origin SHOULD declare its IC expectation in the design doc §3 `initial_state` field (not random). Adapter default for ndim=2 is `square_2d`, ndim=3 is `simple_cubic_3d`; override only when paper specifies otherwise.

---

## 4. Adding a new force type

When a new paper requires a force class not listed above, walk these **8 steps** in order. **A reproduction that stops at step 6 has only proved the engine wires up — no `report.md`, no plots.** By SKILL.md Hard rule #9, that is incomplete. Flag the entire chain in design doc §2a as a status checklist.

1. **Force class implementation**
   - Write `forces/<your_force>.py` with class subclassing `forceField` (`forces/base.py`), declaring `requires_full_list` and `PREFLIGHT_FIELDS`.
   - Pattern: copy nearest existing class (`forces/hertzian_nonreciprocal.py` for non-reciprocal, `forces/er_potential.py` for anisotropic radial, `forces/lennard_jones.py` for simple radial).
   - **Register**: add the class to `forces/__init__.py:FORCE_REGISTRY` AND to `tools/registry.py:_REGISTRY`. Both, in sync.

2. **Tests** (mandatory before any production run)
   - `tests/test_<class>_<N>cases.py` covering: 2-particle force vs analytic; F symmetry/antisymmetry; cutoff boundary.
   - Run `pytest tests/test_<class>_*.py` until green.

3. **Entry script (adapter)**
   - Create `<topic>_run.py` at project root mirroring `prx_nonreciprocal_run.py` / `er_plasma_run.py`.
   - CLI flags must include all required fields from §1 above.
   - Use `tools.lattices.LATTICE_REGISTRY[design_doc.initial_state]` for the initial configuration. Default IC: `square_2d` for ndim=2, `simple_cubic_3d` for ndim=3.

4. **Dispatch in run_experiment + validator**
   - Edit `scripts/run_experiment.py:_invoke_md` — add a new branch for the new `force_type`.
   - Edit `scripts/run_experiment.py:EXP_DEFAULTS_BY_TYPE` — add per-force-type defaults so PRX-shaped values don't silently rewrite your campaign entries.
   - Update `EXP_REQUIRED_<TYPE>` constant with required fields.
   - Edit `scripts/validate_config.py:check_force_type_specific` — add the parallel `elif force_type == "<your_type>":` branch. (Forgetting this causes a silent `else: res.err("unknown force_type")` and the validator rejects every campaign with the new type.)

5. **Schema update**
   - Edit `templates/plan_config.schema.json`:
     - Add new value to `force_type` enum.
     - Add new `if/then` block in `allOf` mapping force_type → required-fields + `ndim` + `units_regime` constants.
     - If a brand-new units regime is needed, also extend the top-level `units_regime` enum.

6. **Registry section in this file**
   - Add a new section here (`## N. <new_type>`) with paper ref, fields, **compat block** (`ndim=...`, `units_regime=...`), examples, pre-flight rules.

7. **Analyzer (per-run)**
   - Write `tools/analyzers/<paper>.py` exposing `<Paper>Analyzer.full_analysis(run_dir, **params) -> dict`. The returned dict's fields drive the per-run `report.md` written in `<run_dir>/report.md`.
   - **Register**: add to `tools/registry.py:_REGISTRY` under the analyzers section. Without this step the run dir gets only `manifest.json + h5` — engine wires up but nothing is measured.
   - In your config, set `pipeline.analyze.class = "<Paper>Analyzer"`.

8. **Visualizer + aggregator**
   - Write `tools/plotters/<paper>.py` exposing `<Paper>Plotter.render(run_dir, **params) -> None` writing `figN_*.png` into the run dir.
   - Optional but recommended: write `tools/aggregators/<paper>.py:<Paper>Aggregator.aggregate(run_dirs, output, plots, title, **params)` for the cross-run master report.
   - **Register both** in `tools/registry.py:_REGISTRY`.
   - In your config, set `pipeline.visualize.class = "<Paper>Plotter"` AND `aggregation.class = "<Paper>Aggregator"`.

After all 8 steps:
- Each production run dir contains `manifest.json` + `report.md` + at least one `fig*.png`.
- The cross-run report (e.g. `docs/<paper>_campaign_report.md`) renders a coherent answer to the paper's question.
- `python scripts/validate_config.py --strict` passes.

### Anti-pattern: reuse-with-degenerate-parameter

There is a tempting third option to "reuse" vs "extend": pick an existing force class that algebraically reduces to the target physics under a parameter setting (e.g. `ERPotential` with `MT=0` is mathematically a pure isotropic Yukawa). This produces a strict-validating config in 5 minutes WITHOUT going through Steps 1-8.

**Do not do this for thesis-quality reproductions.** The manifest will lie about which physics ran (`force_class=ERPotential` instead of `YukawaIsotropic`), the dead anisotropy machinery is allocated and integrated even though it contributes zero, and downstream analyzers may misinterpret the data because they were written for the more general class. Surface this trade-off in design doc §10b as an `ASK USER:` decision, with the recommendation that thesis or published work should go through the full 8 steps.

---

## 5. Legacy configs (pre-`force_type`)

Configs written before the `force_type` field was introduced (e.g., `plan_e_damping.json`, several Plan B/C configs) will fail strict validation because their experiments lack `force_type`. They were all `hertzian_nonreciprocal` by default — that was the only force the framework supported at the time.

**Migration**: add `"force_type": "hertzian_nonreciprocal"` to each campaign entry. No other changes needed; physics is unchanged.

Skill MUST NOT auto-rewrite legacy configs. If user is migrating, flag it explicitly and let user merge the change.

---

## 6. Cross-reference

- **Schema**: `templates/plan_config.schema.json`
- **Skill main**: `SKILL.md`
- **Force forwarding station**: `tools/registry.py:_REGISTRY` (single source of truth for forces / lattices / analyzers / plotters / aggregators / visualizers)
- **Force package**: `forces/__init__.py:FORCE_REGISTRY` (local registry, kept in sync with forwarding station)
- **Lattice package**: `tools/lattices/__init__.py:LATTICE_REGISTRY` + `DEFAULT_LATTICE_BY_NDIM`
- **Run dispatcher**: `scripts/run_experiment.py:_invoke_md`
- **Validator**: `scripts/validate_config.py:check_force_type_specific`

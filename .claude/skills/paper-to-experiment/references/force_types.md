# Force-type registry

Authoritative source for which `force_type` strings are valid in `configs/plan_*.json` and what fields each requires. Skill must consult this BEFORE proposing any config field.

When adding a new force type, follow §3 below — registry is the gatekeeper, schema and skill follow.

---

## 1. `hertzian_nonreciprocal`  (PRX 2015)

- **paper**: Ivlev et al. *Phys. Rev. X* 5, 011035 (2015), Eq. (1)
- **entry script**: `prx_nonreciprocal_run.py`
- **force class**: `forceFieldClass.HertzianNonreciprocal`
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
- **force class**: `forceFieldClass.ERPotential` (anisotropic Yukawa, Eq. (1))
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

## 3. Adding a new force type

When a new paper requires a force class not listed above, walk through these 6 steps in order. **The skill cannot ship a strict-validating config until at least Step 5 is merged**, so flag the entire chain in design doc §2a as a status checklist.

1. **Force class implementation**
   - Add `<NewClass>` to `forceFieldClass.py` with `requires_full_list` attribute and `@ti.kernel updateAllF`.
   - Pattern: copy nearest existing class (`HertzianNonreciprocal` for non-reciprocal, `ERPotential` for anisotropic radial, `LJ` for simple radial).

2. **Tests** (mandatory before any production run)
   - `tests/test_<class>_<N>cases.py` covering: 2-particle force vs analytic; F symmetry/antisymmetry; cutoff boundary.
   - Run `pytest tests/test_<class>_*.py` until green.

3. **Entry script**
   - Create `<topic>_run.py` mirroring `prx_nonreciprocal_run.py` / `er_plasma_run.py` structure.
   - CLI flags must include all required fields from §1 above.

4. **Dispatch in run_experiment**
   - Edit `scripts/run_experiment.py:_invoke_md` — add a new branch for the new `force_type`.
   - Update `EXP_REQUIRED_<TYPE>` constant with required fields.

5. **Schema update**
   - Edit `templates/plan_config.schema.json`:
     - Add new value to `force_type` enum.
     - Add new `if/then` block in `allOf` mapping force_type → required-fields + `ndim` + `units_regime` constants.
     - If a brand-new units regime is needed, also extend the top-level `units_regime` enum.

6. **Registry update**
   - Add a new section here (`## N. <new_type>`) with paper ref, fields, **compat block** (`ndim=...`, `units_regime=...`), examples, pre-flight rules.

After all 6 steps, the new force_type is usable in `configs/*.json` and the skill will recognize it.

### Anti-pattern: reuse-with-degenerate-parameter

There is a tempting third option to "reuse" vs "extend": pick an existing force class that algebraically reduces to the target physics under a parameter setting (e.g. `ERPotential` with `MT=0` is mathematically a pure isotropic Yukawa). This produces a strict-validating config in 5 minutes WITHOUT going through Steps 1-6.

**Do not do this for thesis-quality reproductions.** The manifest will lie about which physics ran (`force_class=ERPotential` instead of `YukawaIsotropic`), the dead anisotropy machinery is allocated and integrated even though it contributes zero, and downstream analyzers may misinterpret the data because they were written for the more general class. Surface this trade-off in design doc §10b as an `ASK USER:` decision, with the recommendation that thesis or published work should go through the full 6 steps.

---

## 4. Legacy configs (pre-`force_type`)

Configs written before the `force_type` field was introduced (e.g., `plan_e_damping.json`, several Plan B/C configs) will fail strict validation because their experiments lack `force_type`. They were all `hertzian_nonreciprocal` by default — that was the only force the framework supported at the time.

**Migration**: add `"force_type": "hertzian_nonreciprocal"` to each campaign entry. No other changes needed; physics is unchanged.

Skill MUST NOT auto-rewrite legacy configs. If user is migrating, flag it explicitly and let user merge the change.

---

## 5. Cross-reference

- **Schema**: `templates/plan_config.schema.json`
- **Skill main**: `SKILL.md`
- **Run dispatcher**: `scripts/run_experiment.py:_invoke_md`
- **Validator**: `scripts/validate_config.py`

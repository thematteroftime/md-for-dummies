# Worked example: PRX 2015 non-reciprocal Hertzian (Plan C / E1v3)

Companion to `worked_example_PRL2008.md`. Same template, different force type — covers `hertzian_nonreciprocal` conventions, NVE long-time runs, and the critical-damping rule.

This walks through how the existing approved `configs/plan_c_long_time.json` (or its E1v3 equivalent) would be produced by the skill.

---

## §0 Metadata (filled)

```yaml
paper_title: Statistical mechanics where Newton's third law is broken
citation: Ivlev et al., Phys. Rev. X 5, 011035 (2015)
doi: 10.1103/PhysRevX.5.011035
paper_pdf: papers/MD—PRX_Nonreciprocal (2).pdf
rendered_pages: papers/rendered/page_*.png
key_equations: [Eq.(1), Eq.(10), Eq.(11)]
key_figures: [Fig.1, Fig.2, Fig.3]
legacy_data: none
thesis_chapter: §5
```

## §1 Physics observables (filled)

| ID | Observable | Paper ref | Type | Target | Tolerance | Analyzer |
|----|------------|-----------|------|--------|-----------|----------|
| O1 | T_A(t) slope α | Eq.(10) §II.B | scalar | dlogT_A/dlogt → 2/3 | 10% (i.e. [0.60, 0.74]) | PRXAnalyzer.full_analysis |
| O2 | T_B(t) slope β | Eq.(10) §II.B | scalar | dlogT_B/dlogt → 2/3 | 10% | PRXAnalyzer.full_analysis |
| O3 | T_A/T_B asymptote | Eq.(11) §II.B | scalar | τ_∞ ≈ 3.1 | 10% | PRXAnalyzer.full_analysis |
| O4 | A-species velocity dist deviation from MB | Fig.1 lower | qualitative | high-v² tail below line | visual | scripts/build_velocity_dist.py |
| O5* | total \|P\| ∝ √t | (paper-external) | scalar | random walk exponent ≈ 0.5 | ±20% | `PRXAnalyzer.extension_diagnostics` |

`*` O5 is original to this thesis (paper does not show momentum drift).

## §2 Force field (filled)

```yaml
name: HertzianNonreciprocal
class_path: forces.hertzian_nonreciprocal:HertzianNonreciprocal
registered_force_type: hertzian_nonreciprocal
units: reduced  # σ=ε=m=k_B=1
new_class_required: false
paper_eq_for_force: Eq.(1)
```

## §3 Simulation setup (filled)

```yaml
N: 10000               # = N_A = N_B; total particles = 20000 ≈ paper N=20000
                       # CRITICAL: registry says "N is per-species, total = 2N".
                       # Don't write N: 20000 unless you want a 40000-particle run.
box: derived from φ and N_total
dt: 0.004              # PRX_PARAMS default; do not override unless paper demands
T0: 0.3                # paper Fig.1 fastest-converging value
density (φ): 0.3       # paper Fig.1 dominant case
boundary_conditions: periodic
thermostat: NVE        # ν=0 explicit; damping experiments come later (P3)
integrator: BAOAB
write_stride: 1000     # log-time-friendly; matches E1v3
chunk_size: 200        # OOM-safe; never raise unless RAM headroom proven
cho: 1                 # cell-list at N_total=20000 (~10× faster than O(N²))
steps_per_run: 5000000 # 5M steps × 0.004 = 20000 τ (matches paper Fig.1 plot extent)
t_total: 20000 τ
```

## §4 Sweep dimensions (filled)

### §4a Fixed parameters

| Parameter | Value | Source |
|-----------|-------|--------|
| `force_type` | `hertzian_nonreciprocal` | registry |
| `phi` | 0.3 | paper Fig.1 caption |
| `T0` | 0.3 | paper Fig.1 fastest-converging panel |
| `nu` | 0 (NVE) | paper Fig.1 explicit |
| `dt` | 0.004 | PRX_PARAMS default |
| `cho` | 1 | required for N_total≥3000 |

### §4b Swept dimensions

| Dim | Variable | Values | Count | Rationale |
|-----|----------|--------|-------|-----------|
| (none — single best-case run) | — | — | 1 | Plan C E1v3: single PASS validation, not a sweep |

**Total runs**: 1 (E1v3). For a sweep see Plan D (φ-sweep at fixed T0=1).

## §5 Run phases (filled)

| Phase | Enabled | Steps | Purpose |
|-------|---------|-------|---------|
| preflight | yes | — | print VRAM/RAM/wall (~0.3 GB / 0.3 GB / 4.3 hr) |
| smoke | yes | 100 | crash check |
| production | yes | 5000000 | main run |
| analyze | yes | — | `PRXAnalyzer.full_analysis` auto-invoked at run end |

`halt_on_fail: true`, `max_parallel: 1` (single run).

## §6 Pass criteria (filled)

| Obs | Metric | PASS | NEAR | FAIL |
|-----|--------|------|------|------|
| O1 | slope_A from rolling-window fit | 0.60–0.74 | 0.50–0.85 | else |
| O2 | slope_B | 0.60–0.74 | 0.50–0.85 | else |
| O3 | τ at last quartile | 2.79–3.41 | 2.50–3.70 | else |
| O4 | f(v_A)/v vs v² high-v deviation | systematically below MB line | partial | flat (no deviation) |
| O5 | log\|P\| vs log t fit slope | 0.4–0.6 | 0.3–0.7 | else |

E1v3 actual (post-hoc): slope_A=0.6617, slope_B=0.687, τ=2.86 — all PASS.

## §7 Expected costs (filled, post-hoc from manifest)

- per-run wall: 4.27 hr (15349 s) — actual; predicted 4.6 hr by recalibrated validator
- per-run RAM peak: 0.3 GB (post-OOM-fix v3)
- per-run VRAM peak: 0.32 GB (cell-list cho=1)
- per-run disk: 0.45 GB (HDF5 LZF)
- total runs: 1
- wall: 4.27 hr
- disk: 0.45 GB

**All within budget.**

## §8 Existing assets reused (filled)

| Asset | Path | Status |
|-------|------|--------|
| force class | `forces.hertzian_nonreciprocal:HertzianNonreciprocal` | reused (verified line-by-line vs Eq.(1)) |
| entry script | `prx_nonreciprocal_run.py` | reused; `--N --phi --T0 --nu --steps` overrides |
| analyzer | `toolClass.PRXAnalyzer.full_analysis` | reused (auto-invoked) |
| run dispatcher | `scripts/run_experiment.py:_invoke_md` | reused (force_type=hertzian_nonreciprocal branch) |
| analytical fingerprints | `scripts/compute_delta_eff.py` | Δ_eff=0.5714, ε=0.0822 (paper 0.57, 0.082; <0.25%) |

## §9 Deliverables (filled)

- figures: fig1, fig2, fig3, fig4, fig5, fig6, fig7 in `docs/images/`
- results doc: `docs/PRX_plan_c_results.md`, `docs/PRX_final_full_coverage.md`
- thesis chapter: §5
- new code: none (existing entry script + analyzer reused)
- mapping_table.md update: yes (Section 一-七)

## §10 Decision log

### §10a Auto-decisions taken

1. **`N: 10000` (per-species)** → matches paper N=20000 total; halves wall vs paper-faithful 40000-total without losing slope quality (P2 R5 confirmed slope is N-invariant from N=2000 to N=40000).
2. **`steps: 5000000`** → 20000 τ matches paper Fig.1 plot extent.
3. **`stride: 1000`** → 5000 frames sampled, sufficient for log-binned slope fit.
4. **`chunk_size: 200, profiler: false`** → mandatory for long runs; from `force_types.md` pre-flight rules.

### §10b Open questions for human

`N/A — no open questions`.

## §11 Validation plan (filled)

| Paper fig | Our fig | Visual criterion |
|-----------|---------|------------------|
| Fig.1 top (T_A,T_B vs t) | fig5 (best-case showcase) | overlap with paper t^(2/3) reference within 10% |
| Fig.1 lower (velocity dist) | fig6 | high-v² A-species deviation visible |
| Fig.1 inset (T_A/T_B) | fig3 | plateau ≈ 2.86 (paper 3.1) |

## §12 Output config

`configs/plan_c_e1v3.json`:

```json
{
  "_comment": "PRX 2015 best-case validation — single 20000τ run at (φ=0.3, T0=0.3) targeting slope_A=2/3 and τ=3.1. See docs/specs/<date>-PRX_E1v3-design.md.",
  "_paper_ref": "Ivlev PRX 2015",
  "_design_doc": "docs/specs/<date>-PRX_E1v3-design.md",
  "_force_type_doc": "hertzian_nonreciprocal (registry §1)",
  "_units_doc": "reduced (σ=ε=m=k_B=1)",
  "campaign": [{
    "force_type": "hertzian_nonreciprocal",
    "tag": "E1v3",
    "phi": 0.3,
    "T0": 0.3,
    "nu": 0,
    "N": 10000,
    "dt": 0.004,
    "steps": 5000000,
    "stride": 1000,
    "chunk_size": 200,
    "profiler": false,
    "notes": "Plan C / E1v3 — best-case PRX validation"
  }],
  "pipeline": {
    "preflight": true,
    "smoke": true,
    "smoke_steps": 100,
    "production": true,
    "analyze": true,
    "halt_on_fail": true,
    "max_parallel": 1
  },
  "aggregation": { "enabled": false }
}
```

After validation:
```
python scripts/validate_config.py configs/plan_c_e1v3.json --strict
python scripts/run_experiment.py configs/plan_c_e1v3.json
```

---

## Critical conventions for `hertzian_nonreciprocal`

These are easy to get wrong; always re-read.

1. **`N` is per-species, total = 2N.** Setting `N: 10000` gives 20000 particles. To match paper N=20000, set `N: 10000` (NOT `N: 20000`).
2. **`dt: 0.004` is the framework default**; only override if paper specifies a different dt-in-τ.
3. **Long runs (>50000 τ) require `chunk_size: 200, profiler: false`** to avoid the OOM bugs that killed E1v1/v2 (see commits bfa0292, 058c10d).
4. **Damping experiments must follow an NVE PASS at the same (φ, T₀)** — P3 hard rule.
5. **Critical damping**: when `nu > 0`, validator computes `ν_c = c/(2*T₀^1.5)` with `c≈1.5e-4`. `ν > ν_c` triggers a warning (super-critical: T collapses to 0).
6. **`cho: 1` (cell-list) for N_total ≥ 3000**, else 9.85× slower.

---

End of worked example.

# Worked example: PRL 2008 ER plasma chain reproduction

This is a retrospective walkthrough of how the existing `configs/plan_g2_er_long.json` would have been produced by following the skill. Use it as a reference when you're unsure whether you have enough information to fill the template.

---

## §0 Metadata (filled)

```yaml
paper_title: First Observation of Electrorheological Plasmas
citation: Ivlev et al., Phys. Rev. Lett. 100, 095003 (2008)
doi: 10.1103/PhysRevLett.100.095003
paper_pdf: papers/MD—Ivlev_PRL_2008.pdf
rendered_pages: papers/rendered/page_*.png
key_equations: [Eq.(1)]
key_figures: [Fig.1, Fig.2, Fig.4]
legacy_data: dataFiles/ER_Sim_MT12_F_direction_100000.xyz
thesis_chapter: §4
```

## §1 Physics observables (filled)

| ID | Observable | Paper ref | Type | Target | Tolerance | Analyzer |
|----|------------|-----------|------|--------|-----------|----------|
| O1 | g_∥/g_⊥ ratio at chain peak | Fig.2 §III | scalar | >2× indicates chains | qualitative | analyze_er_long.py |
| O2 | chain spacing r* / λ | Fig.4 inset | scalar | 3–4 λ in chain regime | ±25% | analyze_er_long.py |
| O3 | Q(t) monotonic late-time growth | §III obs #5 | curve | dQ/dt > 0 in t∈[600,1000] ms for MT≈0.8 | qualitative | analyze_er_long.py |
| O4 | chain length ⟨L⟩(MT) | §III obs #3 | scalar | ⟨L⟩ > 4 in chain regime | qualitative | analyze_chain_length.py |
| O5 | sonic instability MT→1 | §IV | qualitative | Q decays after t<200ms for MT≥0.9 | visual | analyze_er_long.py |

## §2 Force field (filled)

```yaml
name: ERPotential
class_path: forceFieldClass.ERPotential
registered_force_type: er_plasma
units: macro  # mm, ms, K
new_class_required: false
paper_eq_for_force: Eq.(1)
```

## §3 Simulation setup (filled)

```yaml
N: 1000          # matches xyz_1000_3.in lattice
box: ~1.07 mm cube (derived from lattice)
dt: 0.01 ms
T0: 348 K
density: fixed by lattice file
boundary_conditions: periodic
thermostat: Langevin(ν=0.1 /ms)   # ER plasma always damped
integrator: BAOAB
write_stride: 200
chunk_size: 200
cho: 2           # O(N²), N=1000 small enough
steps_per_run: 100000
t_total: 1000 ms (= legacy ER_Sim_MT12 length)
```

## §4 Sweep dimensions (filled)

| Dim | Variable | Values | Count | Rationale |
|-----|----------|--------|-------|-----------|
| D1 | MT | [0.0, 0.8, 1.0] | 3 | bracket the chain regime: control, optimal, sonic |

Total runs: 3 (Plan G2). A follow-up Plan G3 added MT∈{0.4, 0.6, 0.9} for ΔMT=0.2 resolution.

## §5 Run phases (filled)

| Phase | Enabled | Steps | Purpose |
|-------|---------|-------|---------|
| preflight | yes | — | VRAM/RAM/wall estimate |
| smoke | no | 0 | already smoked in Plan G |
| production | yes | 100000 | main |
| analyze | no | — | ER analyzer is paper-specific, run separately |

`halt_on_fail: true`, `max_parallel: 2`.

## §6 Pass criteria (filled)

| Obs | Metric | PASS | NEAR | FAIL |
|-----|--------|------|------|------|
| O1 | max g_∥ / max g_⊥ at Q-peak | ≥ 4× for MT=0.8 | 2.5–4× | < 2.5× |
| O2 | r_peak / λ in chain regime | 3–4 | 2–5 | else |
| O3 | dQ/dt over t∈[600,1000] | > 0 | weakly + | < 0 |
| O4 | ⟨L⟩ at Q-peak | ≥ 4 | 2–4 | < 2 |
| O5 | Q at t=t_end vs Q_peak | Q_end / Q_peak < 0.5 for MT≥0.9 | 0.5–0.8 | ≥ 0.8 |

## §7 Expected costs (filled, post-hoc)

- per-run wall: ~3 min (50–60 step/s × 100k = ~30 min single-thread, ~3 min @ cho=2 cell-list-equivalent on RTX 5060)
- per-run RAM peak: 1.6 GB
- per-run VRAM peak: 0.3 GB
- per-run disk: ~12 MB (HDF5 LZF)
- total runs: 3
- wall (parallel x2): ~5 min
- disk: ~36 MB

All within budget.

## §8 Existing assets reused (filled)

| Asset | Path | Status |
|-------|------|--------|
| force class | `forceFieldClass.ERPotential` | reused |
| entry script | `er_plasma_run.py` | reused |
| analyzer | `scripts/analyze_er_long.py` | extended for G2 |
| legacy ground truth | `dataFiles/ER_Sim_MT12_F_direction_100000.xyz` | cross-validation |
| run dispatcher | `scripts/run_experiment.py:_invoke_md` | extended for `force_type=er_plasma` |

## §9 Deliverables (filled)

- figures: fig14, fig15, fig16, fig17 in `docs/images/`
- results doc: `docs/PRL2008_extended_results.md`, `docs/PRL2008_chain_length.md`
- thesis chapter: §4
- new code: `scripts/analyze_er_long.py`, `scripts/analyze_chain_length.py`
- mapping_table.md update: yes (Section 八-十二)

## §10 Decision log (filled)

1. **Run length**: paper does not state simulation length; legacy `ER_Sim_MT12` is 100k steps × 0.01 ms = 1000 ms. Decision: match legacy → 100k steps. *(user-confirmed)*
2. **MT sweep granularity**: paper Fig 4 implies ΔMT~0.1. Decision: start with ΔMT=0.2 (4 points) for budget; expand if needed. *(actual: started with 3, added 3 more in Plan G3)*

## §11 Validation plan (filled)

| Paper fig | Our fig | Visual criterion |
|-----------|---------|------------------|
| Fig.2 (g_∥, g_⊥) | fig15 | ER4L panel must show single dominant g_∥ peak with g_⊥ flat |
| Fig.4 (chain phase) | fig16 left | Q_peak vs MT must show optimum near MT=0.8 |
| Fig.4 inset | fig16 right | r*/λ in chain regime must be ~3-4 |

## §12 Output config

`configs/plan_g2_er_long.json` (this file). After approval, validate via:
```
python scripts/validate_config.py configs/plan_g2_er_long.json --strict
```
Then launch via:
```
python scripts/run_experiment.py configs/plan_g2_er_long.json
```

---

End of worked example.

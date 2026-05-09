#!/usr/bin/env python3
"""validate_config.py — schema + physics validation for plan_*.json before
the campaign launches. Used by paper-to-experiment skill as the gate
between "AI emitted JSON" and "GPU starts spinning".

Usage:
    python scripts/validate_config.py configs/plan_topic.json
    python scripts/validate_config.py configs/plan_topic.json --strict
    python scripts/validate_config.py configs/plan_topic.json --preflight

Exit codes:
    0 = all checks pass
    1 = schema or physics validation failed
    2 = warnings only (non-strict mode passes; strict fails)
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / ".claude" / "skills" / "paper-to-experiment" / "templates" / "plan_config.schema.json"

GREEN = "\033[32m"; RED = "\033[31m"; YELLOW = "\033[33m"; CYAN = "\033[36m"; END = "\033[0m"

NU_C_COEFF_C = 1.5e-4
HARD_BUDGET_WALL_HR = 24.0
HARD_BUDGET_VRAM_GB = 8.0

# Heuristic cross-over between the O(N²) all-pairs and cell-list neighbor algorithms.
# Below this N_total, O(N²) (cho=2) is faster due to lower per-step overhead;
# above it, the cell list (cho=1) wins. The exact crossover depends on hardware
# and force cutoff; this default is a reasonable middle for RTX-class GPUs.
# Override via top-level "_cell_list_threshold_N" key in the campaign config if
# your hardware crosses over differently.
DEFAULT_CELL_LIST_THRESHOLD_N = 3000
HARD_BUDGET_DISK_GB = 50.0


class Result:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.notes = []

    def err(self, msg):  self.errors.append(msg)
    def warn(self, msg): self.warnings.append(msg)
    def note(self, msg): self.notes.append(msg)

    @property
    def passed(self):
        return not self.errors

    def report(self):
        for n in self.notes:    print(f"  {CYAN}note{END}: {n}")
        for w in self.warnings: print(f"  {YELLOW}warn{END}: {w}")
        for e in self.errors:   print(f"  {RED}ERR {END}: {e}")
        if self.passed and not self.warnings:
            print(f"  {GREEN}all checks passed.{END}")


def load_schema():
    if not SCHEMA.exists():
        sys.exit(f"schema not found at {SCHEMA}")
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def schema_validate(cfg, schema, res: Result):
    """Use jsonschema if available; else fall back to a minimal manual check."""
    try:
        import jsonschema
        try:
            jsonschema.validate(cfg, schema)
        except jsonschema.ValidationError as e:
            res.err(f"schema: {e.message} (path: {'/'.join(str(p) for p in e.absolute_path)})")
        return
    except ImportError:
        res.note("jsonschema not installed — running minimal manual checks")

    if "campaign" not in cfg:
        res.err("missing top-level 'campaign'")
    if "pipeline" not in cfg:
        res.err("missing top-level 'pipeline'")
    if not isinstance(cfg.get("campaign"), list) or not cfg["campaign"]:
        res.err("'campaign' must be non-empty list")


def check_unique_tags(cfg, res: Result):
    tags = [exp.get("tag") for exp in cfg.get("campaign", [])]
    seen = set()
    for t in tags:
        if t in seen:
            res.err(f"duplicate tag '{t}' — every run needs a unique tag")
        seen.add(t)


def check_force_type_specific(cfg, res: Result):
    for exp in cfg.get("campaign", []):
        ft = exp.get("force_type")
        tag = exp.get("tag", "<no-tag>")

        if ft == "hertzian_nonreciprocal":
            phi = exp.get("phi", 0)
            T0 = exp.get("T0", 0)
            nu = exp.get("nu", 0)
            steps = exp.get("steps", 0)

            if nu > 0:
                nu_c = NU_C_COEFF_C / (2 * T0 ** 1.5) if T0 > 0 else 0
                ratio = nu / nu_c if nu_c > 0 else float("inf")
                if ratio > 1.0:
                    res.warn(
                        f"[{tag}] ν={nu:.2e} > ν_c={nu_c:.2e} (ν/ν_c={ratio:.2f}) — "
                        f"super-critical, expect collapse to T→0. Confirm this is intentional."
                    )
                else:
                    res.note(f"[{tag}] ν/ν_c = {ratio:.3f} (sub-critical, will reach steady state)")

            if steps * 0.005 > 50000 and exp.get("chunk_size", 200) > 200:
                res.warn(f"[{tag}] long run (>50000 τ) with chunk_size>200 — RAM OOM risk")

            if exp.get("profiler") and steps > 1_000_000:
                res.err(f"[{tag}] profiler=true with steps>{1e6:.0g} → guaranteed OOM. Set profiler=false.")

        elif ft == "er_plasma":
            MT = exp.get("MT", 0)
            N = exp.get("N", 1000)
            steps = exp.get("steps", 0)
            dt_ms = exp.get("dt_ms", 0.01)

            if MT > 1.0:
                res.warn(
                    f"[{tag}] MT={MT} > 1.0 (super-sonic) — chains destabilize per "
                    f"PRL 2008 §IV. Useful as control point but Q_peak will appear at early t."
                )

            t_total_ms = steps * dt_ms
            if t_total_ms < 800 and MT >= 0.7 and MT <= 0.9:
                res.warn(
                    f"[{tag}] in chain-regime (MT={MT}) but t_total={t_total_ms:.0f} ms < 800 ms. "
                    f"Plan G (50k=500ms) was insufficient; use ≥100k steps."
                )

            if N != 1000 and "lattice" not in str(exp.get("notes", "")):
                res.warn(
                    f"[{tag}] N={N} ≠ 1000 — default lattice xyz_1000_3.in may not match. "
                    f"Confirm a matching lattice file exists in dataFiles/."
                )

            threshold = cfg.get("_cell_list_threshold_N", DEFAULT_CELL_LIST_THRESHOLD_N)
            if exp.get("cho", 2) == 1 and N < threshold:
                res.note(f"[{tag}] cho=1 (cell-list) at small N={N} — O(N²) mode (cho=2) is faster "
                          f"below N={threshold} (configurable via _cell_list_threshold_N)")

        elif ft == "kalj":
            T0 = exp.get("T0", 0)
            rho = exp.get("rho", 1.2)
            N = exp.get("N", 1000)
            steps = exp.get("steps", 0)
            fB = exp.get("fraction_B", 0.20)

            if T0 < 0.3:
                res.warn(
                    f"[{tag}] T0={T0} is deep glassy regime (T_m≈1.028 at ρ=1.2). "
                    f"Engine drag-only Langevin will undercool; expect MSD plateau."
                )
            if rho < 0.8 or rho > 1.5:
                res.warn(
                    f"[{tag}] ρ={rho} outside KA paper isochore range (paper Fig.4 covers 0.93–1.44). "
                    f"Verify this is intentional."
                )
            if not (0.0 < fB < 0.5):
                res.err(
                    f"[{tag}] fraction_B={fB} out of range (0, 0.5). "
                    f"KA paper studies up to 50% B."
                )
            threshold = cfg.get("_cell_list_threshold_N", DEFAULT_CELL_LIST_THRESHOLD_N)
            if exp.get("cho", 2) == 1 and N < threshold:
                res.note(f"[{tag}] cho=1 (cell-list) at small N={N} — O(N²) mode (cho=2) is "
                          f"faster below N={threshold}")

        else:
            res.err(f"[{tag}] unknown force_type '{ft}' — see references/force_types.md")


def check_pipeline(cfg, res: Result):
    pipe = cfg.get("pipeline", {})
    if pipe.get("smoke", True):
        ss = pipe.get("smoke_steps", 100)
        if ss == 0:
            res.warn("pipeline.smoke=true but smoke_steps=0 — smoke is a no-op. Set smoke_steps≥100.")
        elif ss < 100:
            res.warn(f"pipeline.smoke=true with smoke_steps={ss} < 100 — SKILL §1 hard rule 3 requires ≥100.")
    if not pipe.get("halt_on_fail", False):
        res.warn("pipeline.halt_on_fail=false — campaign will continue past failures (you may waste GPU)")
    n_runs = len(cfg.get("campaign", []))
    max_par = pipe.get("max_parallel", 1)
    if max_par > 4:
        res.err(f"pipeline.max_parallel={max_par} > 4 (RTX 5060 Laptop has 8GB VRAM, 2-3 is safe)")
    if max_par > n_runs:
        res.warn(f"max_parallel={max_par} > n_runs={n_runs} — parallel scheduler will idle")


def check_physics_provenance(cfg, res: Result):
    """Skill-emitted configs MUST cite a paper. Hand-written configs may not — info-level only."""
    if not cfg.get("_paper_ref"):
        res.warn("missing '_paper_ref' — strongly recommended (links campaign to source paper)")
    if not cfg.get("_design_doc"):
        res.note("missing '_design_doc' — recommended for skill-emitted configs")
    if not cfg.get("_comment"):
        res.warn("missing '_comment' — one-paragraph rationale prevents future you from forgetting why")


_STEP_RATE_MULTIPLIER = {
    # force_type-specific kernel cost multiplier vs the PRX baseline below.
    # 1.0 = same cost; >1 = cheaper (faster step rate); <1 = more expensive.
    # Calibrate against a real run by reading manifest.json:wall_seconds.
    "hertzian_nonreciprocal": 1.0,    # baseline (the anchor below was measured against PRX)
    "er_plasma":              1.0,    # anisotropic Yukawa, similar cost
    "kalj":                   1.0,    # binary LJ truncated, similar cost to PRX baseline
    # New force_types may add their own factor here. Defaults to 1.0 (PRX
    # baseline) when missing — over-estimate is safer than under-estimate.
}


def _step_rate(N_total: int, cho: int, force_type: str | None = None) -> int:
    """Step rate (step/s) calibrated from real outputFiles/*/manifest.json data.
    Anchor points: E1v3 N_tot=20000 cho=1 → 326 step/s; ER N=1000 cho=2 → ~500 step/s.
    Per-force-type multipliers in `_STEP_RATE_MULTIPLIER` adjust the baseline.
    """
    if cho == 1:  # cell-list, near-linear in N
        if   N_total <= 1000:  base = 500
        elif N_total <= 5000:  base = 400
        elif N_total <= 20000: base = 300
        elif N_total <= 50000: base = 150
        else:                  base = 60
    else:  # cho=2, O(N^2)
        if   N_total <= 1000:  base = 500
        elif N_total <= 3000:  base = 200
        elif N_total <= 10000: base = 50
        else:                  base = 15
    factor = _STEP_RATE_MULTIPLIER.get(force_type or "", 1.0)
    return max(1, int(base * factor))


def estimate_costs(cfg, res: Result):
    """Per-run wall + VRAM estimate without launching simulation. Step-rate model
    calibrated against existing manifest.json data; recalibrate if real wall ≠ estimate by >2x."""
    n_runs = len(cfg.get("campaign", []))
    if not n_runs:
        return
    per_run_walls = []
    max_N_total = 0
    for exp in cfg.get("campaign", []):
        ft = exp.get("force_type")
        # N convention is force-type-specific:
        #   hertzian_nonreciprocal → N is per-species (total = 2N)
        #   er_plasma, kalj         → N is total
        N_per = exp.get("N", 10000 if ft == "hertzian_nonreciprocal" else 1000)
        N_tot = 2 * N_per if ft == "hertzian_nonreciprocal" else N_per
        max_N_total = max(max_N_total, N_tot)
        threshold = cfg.get("_cell_list_threshold_N", DEFAULT_CELL_LIST_THRESHOLD_N)
        cho = exp.get("cho", 1 if N_tot > threshold else 2)
        rate = _step_rate(N_tot, cho, exp.get("force_type"))
        steps = exp.get("steps", 0)
        per_run_walls.append(steps / rate / 3600)

    avg_wall_hr = sum(per_run_walls) / n_runs
    max_par = cfg.get("pipeline", {}).get("max_parallel", 1)
    total_wall_hr = sum(per_run_walls) / max_par

    vram_gb = max_N_total * 1.6e-4 + 0.2
    res.note(f"cost estimate: {n_runs} runs, ~{avg_wall_hr:.2f} hr/run avg, "
             f"total wall ~{total_wall_hr:.1f} hr (parallel x{max_par}), "
             f"VRAM ~{vram_gb:.2f} GB. "
             f"[Cross-check vs design doc §7; if mismatch >2x, validator step-rate model is stale.]")

    if max(per_run_walls) > HARD_BUDGET_WALL_HR:
        res.err(f"longest-run wall {max(per_run_walls):.1f} hr > {HARD_BUDGET_WALL_HR} hr budget — "
                f"reduce N or steps")
    if vram_gb > HARD_BUDGET_VRAM_GB:
        res.err(f"VRAM {vram_gb:.2f} GB > {HARD_BUDGET_VRAM_GB} GB — use cho=1 or smaller N")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config", help="path to configs/plan_*.json")
    ap.add_argument("--strict", action="store_true",
                    help="treat warnings as errors (skill-mode default)")
    ap.add_argument("--preflight", action="store_true",
                    help="also run scripts/run_experiment.py --preflight-only (slower)")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        sys.exit(f"config not found: {cfg_path}")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    schema = load_schema()
    res = Result()

    print(f"{CYAN}validating{END} {cfg_path}")
    schema_validate(cfg, schema, res)
    check_unique_tags(cfg, res)
    check_force_type_specific(cfg, res)
    check_pipeline(cfg, res)
    check_physics_provenance(cfg, res)
    estimate_costs(cfg, res)
    res.report()

    if args.preflight and res.passed:
        import subprocess
        print(f"{CYAN}preflight{END} via run_experiment.py --preflight-only ...")
        rc = subprocess.call([sys.executable, str(ROOT / "scripts" / "run_experiment.py"),
                              str(cfg_path), "--preflight-only"])
        if rc != 0:
            res.err(f"preflight subprocess returned {rc}")

    if not res.passed:
        sys.exit(1)
    if args.strict and res.warnings:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()

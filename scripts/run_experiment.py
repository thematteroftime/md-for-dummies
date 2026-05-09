#!/usr/bin/env python3
"""PRX experiment runner — single entry point.

Manages the full lifecycle: preflight → smoke → run → analyze → aggregate.
All other CLI scripts have been merged into this one.

Quick start:
    python scripts/run_experiment.py configs/plan_c_remaining.json

For complete documentation (config schema, flowchart, parameter reference,
troubleshooting), see  docs/EXPERIMENT_RUNNER.md.

Four sub-modes (see --help):
    (no flag)            full pipeline driven by a JSON / YAML config
    --preflight-only     print resource estimate, no run
    --analyze RUN_DIR    re-analyze an existing run dir
    --aggregate "GLOB"   aggregate existing runs into a master report
"""
import argparse
import datetime as dt
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)

from toolClass import (PRXAnalyzer, PRXPlotter, PriorRunsDB,
                        ResourceEstimator)


PYTHON = sys.executable
MD_SCRIPT_PRX = _ROOT / "prx_nonreciprocal_run.py"          # PRX 2015 Hertzian non-reciprocal
MD_SCRIPT_ER  = _ROOT / "er_plasma_run.py"                  # PRL 2008 anisotropic Yukawa
MD_SCRIPT_KALJ = _ROOT / "pedersen_kalj_run.py"             # PRL 2018 Pedersen KA-LJ
# Backward compat alias used by older paths
MD_SCRIPT = MD_SCRIPT_PRX
OUT_ROOT = _ROOT / "outputFiles"


# ---------------------------------------------------------------------------
# Config loading (JSON or YAML, distinguished by extension)
# ---------------------------------------------------------------------------

DEFAULT_PIPELINE = {
    "preflight": True,
    "smoke": True,
    "smoke_steps": 2000,
    "production": True,
    "analyze": True,
    "halt_on_fail": True,
    "max_parallel": 1,  # 1 = serial. 2 = 2-way GPU sharing (recommended for
                        # N=20000-class runs where single process uses ~56%
                        # GPU, leaving ~44% headroom). 3+ saturates GPU
                        # without throughput gain. See EXPERIMENT_RUNNER.md §5.6.
}

DEFAULT_AGGREGATION = {
    "enabled": False,
    "output": "docs/PRX_campaign_report.md",
    "plots": ["fig1", "fig2"],
    "runs": None,
    "title": "PRX Campaign Report",
}

# Defaults that apply regardless of force_type (administrative bookkeeping).
EXP_DEFAULTS_COMMON = {
    "chunk_size": 200,
    "notes": "",
}

# Per-force-type defaults. The platform merges
#   EXP_DEFAULTS_COMMON ∪ EXP_DEFAULTS_BY_TYPE[force_type] ∪ user_entry.
# Adapters set their own physics-correct defaults internally; these are only
# the values run_experiment.py needs to pass through CLI when the user
# omits them at the campaign-entry level.
EXP_DEFAULTS_BY_TYPE = {
    "hertzian_nonreciprocal": {
        "N": 10000,
        "stride": 600,
        "nu": 0.0,
        "dt": 0.004,
        "cho": 1,
    },
    "er_plasma": {
        "N": 1000,
        "stride": 200,
        "nu": 0.1,
        "dt_ms": 0.01,
        "cho": 2,
    },
    "kalj": {
        "N": 1000,
        "stride": 200,
        "nu": 0.1,
        "dt": 0.005,
        "rho": 1.2,
        "fraction_B": 0.20,
        "cho": 2,
    },
}
# Legacy alias kept so callers that import EXP_DEFAULTS continue to work.
# Resolves to the PRX defaults (most common historic case).
EXP_DEFAULTS = {**EXP_DEFAULTS_COMMON, **EXP_DEFAULTS_BY_TYPE["hertzian_nonreciprocal"]}

EXP_REQUIRED_PRX  = ("tag", "phi", "T0", "steps")
EXP_REQUIRED_ER   = ("tag", "MT", "steps")
EXP_REQUIRED_KALJ = ("tag", "T0", "rho", "steps")
EXP_REQUIRED = EXP_REQUIRED_PRX  # legacy alias used by callers that don't dispatch


def load_config(path):
    """Read JSON or YAML config from disk. Raises on schema errors."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config not found: {p}")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        import yaml
        cfg = yaml.safe_load(text)
    elif p.suffix.lower() == ".json":
        cfg = json.loads(text)
    else:
        raise ValueError(f"unsupported config extension: {p.suffix} "
                          f"(use .json / .yaml / .yml)")
    return _normalize_config(cfg)


def _normalize_config(cfg):
    """Fill in defaults; validate required fields. Returns sanitized dict."""
    if "campaign" not in cfg:
        raise ValueError("config missing required top-level 'campaign' list")
    if not isinstance(cfg["campaign"], list) or not cfg["campaign"]:
        raise ValueError("'campaign' must be a non-empty list")

    out = {
        "campaign": [],
        "pipeline": {**DEFAULT_PIPELINE, **(cfg.get("pipeline") or {})},
        "aggregation": {**DEFAULT_AGGREGATION,
                         **(cfg.get("aggregation") or {})},
    }

    for i, exp in enumerate(cfg["campaign"]):
        # Resolve defaults by force_type so PRX-shaped values don't silently
        # rewrite a non-PRX entry's intended timestep / particle count.
        force_type = exp.get("force_type", "hertzian_nonreciprocal")
        type_defaults = EXP_DEFAULTS_BY_TYPE.get(force_type, {})
        merged = {**EXP_DEFAULTS_COMMON, **type_defaults, **exp}
        # Required fields depend on force_type
        if force_type == "er_plasma":
            required = EXP_REQUIRED_ER
        elif force_type == "kalj":
            required = EXP_REQUIRED_KALJ
        else:
            required = EXP_REQUIRED_PRX
        for key in required:
            if key not in merged or merged[key] is None:
                raise ValueError(
                    f"campaign[{i}] missing required field '{key}' "
                    f"(force_type={force_type})")
        out["campaign"].append(merged)

    return out


def config_from_cli(args):
    """Single-run config built from CLI flags (no file)."""
    if not (args.tag and args.steps is not None
            and args.phi is not None and args.T0 is not None):
        raise SystemExit("error: ad-hoc single run needs --tag --steps "
                         "--phi --T0 (or pass a config file)")
    exp = {**EXP_DEFAULTS,
           "tag": args.tag, "phi": args.phi, "T0": args.T0,
           "steps": args.steps,
           "N": args.N or EXP_DEFAULTS["N"],
           "stride": args.stride or EXP_DEFAULTS["stride"]}
    return _normalize_config({"campaign": [exp]})


# ---------------------------------------------------------------------------
# Lifecycle stages
# ---------------------------------------------------------------------------

def stage_preflight(exp):
    """Print + return ResourceEstimate."""
    return ResourceEstimator.print_preflight(exp)


def _simulate_lpt(walls, M):
    """Simulate Longest-Processing-Time-first scheduling on M parallel slots.

    walls: list of solo-mode wall times (hours).
    M:     number of parallel slots.

    Speed model (from observed RTX 5060 Laptop, N=20000-class runs):
      - n_active=1: 1.0× per slot (solo, total = 1.0×)
      - n_active=2: 0.89× per slot (total = 1.78×, GPU saturated)
      - n_active=k≥3: 1.78/k× per slot (total stays at 1.78×, just split
                         more thinly with no extra throughput)

    Each job's "work" is its solo wall time. While in a slot, it consumes
    `dt × speed` units of work per `dt` wall time.

    Returns: predicted makespan (wall hours).
    """
    if M <= 1 or not walls:
        return sum(walls)
    queue = sorted(walls, reverse=True)  # LPT: longest first
    slots = [None] * M  # remaining work per slot, or None if free
    t = 0.0
    while queue or any(s is not None for s in slots):
        for i in range(M):
            if slots[i] is None and queue:
                slots[i] = queue.pop(0)
        n_active = sum(1 for s in slots if s is not None)
        if n_active == 0:
            break
        if n_active == 1:
            speed = 1.0
        elif n_active == 2:
            speed = 0.89
        else:
            # GPU saturated at total 1.78× single throughput; just split
            # the throughput across n_active slots.
            speed = 1.78 / n_active
        min_work = min(s for s in slots if s is not None)
        dt = min_work / speed
        for i in range(M):
            if slots[i] is not None:
                slots[i] -= dt * speed
                if slots[i] <= 1e-9:
                    slots[i] = None
        t += dt
    return t


def _campaign_preflight(experiments, max_parallel):
    """Print per-experiment estimates + parallel-mode summary if applicable."""
    print("\n=== Phase 1: PREFLIGHT (per-run estimates) ===")
    estimates = []
    cum_vram = cum_ram = cum_disk = 0.0
    worst_wall = total_serial_wall = 0.0
    for exp in experiments:
        est = stage_preflight(exp)
        estimates.append(est)
        cum_vram += est.get("vram_gb", 0)
        cum_ram += est.get("ram_peak_gb", 0)
        cum_disk += est.get("disk_gb", 0)
        worst_wall = max(worst_wall, est.get("wall_hours", 0))
        total_serial_wall += est.get("wall_hours", 0)

    if not experiments:
        return estimates

    avg_vram = cum_vram / len(experiments)
    avg_ram = cum_ram / len(experiments)

    # Time prediction: simulate LPT scheduling with N parallel slots.
    # Model assumes:
    #   1 active slot:  solo speed (1.0× rate)
    #   2 active slots: 0.89× rate each (1.78× total throughput)
    #   3+ active:      1/n rate each (saturated, no extra throughput)
    walls = [e.get("wall_hours", 0) for e in estimates]
    wall_pred = _simulate_lpt(walls, max_parallel)
    if max_parallel <= 1:
        per_slot_slowdown = 1.0
    elif max_parallel == 2:
        per_slot_slowdown = 1.12
    else:
        per_slot_slowdown = max_parallel / 1.78

    print()
    print(f"  ╔═══════════════════════════════════════════════════════════╗")
    print(f"  ║   CAMPAIGN SUMMARY  ({len(experiments)} runs, max_parallel={max_parallel})")
    print(f"  ╠═══════════════════════════════════════════════════════════╣")
    print(f"  ║ Peak VRAM (at any one time): ~{avg_vram * max_parallel:>6.2f} GB")
    print(f"  ║ Peak RAM (at any one time):  ~{avg_ram * max_parallel:>6.2f} GB")
    print(f"  ║ Total disk to write:         ~{cum_disk:>6.2f} GB")
    print(f"  ║ Per-slot slowdown (parallel): {per_slot_slowdown:>5.2f}x")
    print(f"  ║ Sum of solo wall times:      ~{total_serial_wall:>6.2f} hr  (= serial)")
    print(f"  ║ Predicted parallel wall:     ~{wall_pred:>6.2f} hr")
    if max_parallel > 1 and total_serial_wall > 0:
        savings = (1 - wall_pred / total_serial_wall) * 100
        print(f"  ║ Time saving vs serial:        {savings:>5.1f} %")
    print(f"  ╚═══════════════════════════════════════════════════════════╝")
    return estimates


def stage_smoke(exp, smoke_steps):
    """Quick verification run.

    Smoke proof-of-life (per ARCHITECTURE.md §3.1) is the manifest.json that
    the adapter writes — NOT the analyzer's report.md. Adapters that follow
    §3.1 forbidden ("MUST NOT call analyzers in-process") only emit
    manifest.json + the trajectory; checking for report.md here would
    penalise correct adapters.
    """
    smoke_exp = {**exp, "tag": f"{exp['tag']}_smoke", "steps": int(smoke_steps)}
    print(f"[smoke] {smoke_exp['tag']}: {smoke_steps} steps")
    rc = _invoke_md(smoke_exp)
    if rc != 0:
        print(f"[smoke] FAILED rc={rc}")
        return None
    rd = _latest_run_dir(smoke_exp["tag"])
    if rd is None or not (rd / "manifest.json").exists():
        print(f"[smoke] no run_dir / manifest.json produced (§3.2 contract)")
        return None
    print(f"[smoke] OK: {rd.name}")
    return rd


def stage_production(exp):
    """Full production MD run via prx_nonreciprocal_run.py subprocess."""
    print(f"[run] {exp['tag']}: production")
    rc = _invoke_md(exp)
    if rc != 0:
        print(f"[run] FAILED rc={rc}")
        return None
    rd = _latest_run_dir(exp["tag"])
    if rd is None:
        print(f"[run] no run_dir produced for {exp['tag']}")
        return None
    print(f"[run] OK: {rd.name}")
    return rd


def stage_analyze(run_dir, analyzer_class="PRXAnalyzer", params=None):
    """Re-run analysis. Class name is resolved via tools.registry, so users can
    specify any registered analyzer in the campaign config:

        "pipeline": { "analyzer_class": "ERAnalyzer", "analyzer_params": {...} }

    Defaults to PRXAnalyzer for back-compat with existing plan_*.json files.
    """
    print(f"[analyze] {run_dir}  (class={analyzer_class})")
    from tools.registry import resolve
    AnalyzerCls = resolve(analyzer_class)
    fields = AnalyzerCls.full_analysis(run_dir, **(params or {}))
    return fields


def stage_visualize(run_dir, visualizer_class, params=None):
    """Optional visualisation stage, dispatched by class name from config.
    Skipped when no visualizer_class is configured.

    Resolution preference:
    1. If the class has a static/classmethod `render` → call it directly with
       `(run_dir, **params)`. This is the canonical plotter pattern (see
       templates/plotter.py.template) and avoids needing a no-arg __init__.
    2. Else, instantiate with `**params` and call `.render(run_dir)` or
       `.show(run_dir)` (back-compat for `TaichiTrajectoryViz`-style classes
       that hold instance state).
    """
    if not visualizer_class:
        return None
    print(f"[visualize] {run_dir}  (class={visualizer_class})")
    from tools.registry import resolve
    VizCls = resolve(visualizer_class)
    params = params or {}

    # Path 1: class-method dispatch (preferred for paper plotters).
    render_attr = VizCls.__dict__.get("render")
    if isinstance(render_attr, (staticmethod, classmethod)):
        return VizCls.render(run_dir, **params)

    # Path 2: instance dispatch (back-compat for visualizers with __init__).
    inst = VizCls(**params)
    if hasattr(inst, "render"):
        return inst.render(run_dir)
    if hasattr(inst, "show"):
        return inst.show(run_dir)
    raise AttributeError(f"{visualizer_class} must implement .render() or .show()")


def stage_aggregate(run_dirs, output, plots, title, aggregator_class="PRXAggregator", **params):
    """Phase 4: cross-run aggregator. Class name dispatched via tools.registry.

    Default `PRXAggregator` preserves prior behavior. Other papers register
    their own aggregator class (e.g. `ERAggregator`) and select via:

        "aggregation": {"enabled": true, "class": "ERAggregator", "plots": [...]}
    """
    print(f"[aggregate] dispatching to {aggregator_class}")
    from tools.registry import resolve
    AggCls = resolve(aggregator_class)
    AggCls.aggregate(run_dirs, output, plots, title, **params)


# Master-report rendering lives in tools/aggregators/<paper>.py — each
# paper-specific aggregator owns its own report layout.

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _invoke_md(exp):
    """Dispatch to the appropriate MD entry script based on force_type.

    Default = "hertzian_nonreciprocal" → prx_nonreciprocal_run.py (PRX 2015)
              "er_plasma"               → er_plasma_run.py (PRL 2008)
    """
    force_type = exp.get("force_type", "hertzian_nonreciprocal")

    if force_type == "er_plasma":
        cmd = [
            PYTHON, str(MD_SCRIPT_ER),
            "--tag", str(exp["tag"]),
            "--MT", str(exp["MT"]),
            "--steps", str(exp["steps"]),
            "--stride", str(exp["stride"]),
        ]
        for ck, ek in [("Z_eff", "--Z-eff"), ("lambda_mm", "--lambda-mm"),
                        ("T0_K", "--T0-K"), ("dt_ms", "--dt-ms"),
                        ("nu", "--nu"), ("N", "--N"), ("cho", "--cho")]:
            if ck in exp and exp[ck] is not None:
                cmd.extend([ek, str(exp[ck])])
    elif force_type == "kalj":
        cmd = [
            PYTHON, str(MD_SCRIPT_KALJ),
            "--tag", str(exp["tag"]),
            "--T0", str(exp["T0"]),
            "--rho", str(exp["rho"]),
            "--steps", str(exp["steps"]),
            "--stride", str(exp["stride"]),
        ]
        for ck, ek in [("nu", "--nu"), ("N", "--N"),
                        ("fraction_B", "--fraction-B"), ("cho", "--cho")]:
            if ck in exp and exp[ck] is not None:
                cmd.extend([ek, str(exp[ck])])
    else:
        # PRX-style default
        cmd = [
            PYTHON, str(MD_SCRIPT_PRX),
            "--tag", str(exp["tag"]),
            "--N", str(exp["N"]),
            "--steps", str(exp["steps"]),
            "--phi", str(exp["phi"]),
            "--T0", str(exp["T0"]),
            "--stride", str(exp["stride"]),
            "--cho", str(exp["cho"]),
        ]
        if exp.get("nu", 0.0) != 0.0:
            cmd.extend(["--nu", str(exp["nu"])])
    print(f"  cmd: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(_ROOT)).returncode


def _latest_run_dir(tag):
    matches = sorted(OUT_ROOT.glob(f"*_{tag}"))
    return matches[-1] if matches else None


def _run_production_parallel(experiments, max_parallel, halt_on_fail):
    """N-way parallel production runs via ThreadPoolExecutor.

    Each worker spawns a subprocess to prx_nonreciprocal_run.py. Since
    we're I/O-bound (waiting on subprocess), threads are sufficient.

    Important constraints (rationale in EXPERIMENT_RUNNER.md §5.6):
    - max_parallel=2 saturates an 8 GB GPU at N=20000-class runs
    - max_parallel=3+ adds context-switch overhead without throughput gain
    - halt_on_fail=True stops queueing new runs after first failure;
      already-running subprocesses finish naturally (we don't kill them
      to avoid corrupting their HDF5 files).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    print(f"\n=== Phase 3: PRODUCTION (parallel, max={max_parallel}) ===")
    print(f"  {len(experiments)} runs queued; up to {max_parallel} concurrent.")

    def _one(exp):
        # Re-print which one is launching (threaded interleave)
        print(f"  [{exp['tag']}] launching production")
        return stage_production(exp)

    completed = []
    failed = False
    # LPT order — submit longest jobs first so they get parallel acceleration
    # instead of running solo at the tail. See EXPERIMENT_RUNNER.md §5.6.
    ordered = sorted(experiments, key=lambda e: -int(e.get("steps", 0)))
    print(f"  LPT submit order: {[e['tag'] for e in ordered]}")
    with ThreadPoolExecutor(max_workers=max_parallel) as ex:
        futures = {ex.submit(_one, exp): exp for exp in ordered}
        for fut in as_completed(futures):
            exp = futures[fut]
            try:
                rd = fut.result()
            except Exception as e:
                print(f"  [{exp['tag']}] CRASHED: {e}")
                rd = None
            if rd is None:
                failed = True
                print(f"  [{exp['tag']}] FAILED")
                if halt_on_fail:
                    # Don't queue more; already-running ones will finish
                    print("  [parallel] halt_on_fail set — no more runs will queue")
            else:
                completed.append(rd)
                print(f"  [{exp['tag']}] OK: {rd}")
    return completed


def _expand_runs(patterns):
    out = []
    for pat in patterns:
        if any(c in pat for c in "*?["):
            for m in sorted(glob.glob(pat)):
                if os.path.isdir(m):
                    out.append(m)
        else:
            if os.path.isdir(pat):
                out.append(pat)
    seen = set(); uniq = []
    for r in out:
        if r not in seen:
            uniq.append(r); seen.add(r)
    return uniq


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(cfg, smoke_override=None, no_aggregate=False,
                  continue_on_fail=False, max_parallel_override=None):
    """Main pipeline driver. cfg already normalized.

    Phases:
      1. preflight (serial, fast)
      2. smoke (serial — fast feedback if config broken)
      3. production (serial OR N-way parallel via max_parallel)
      4. aggregation (after all production)
    """
    pipeline = cfg["pipeline"]
    aggr = cfg["aggregation"]

    smoke_steps = (smoke_override if smoke_override is not None
                    else (pipeline["smoke_steps"] if pipeline["smoke"] else 0))
    halt = pipeline["halt_on_fail"] and not continue_on_fail
    max_parallel = (max_parallel_override
                     if max_parallel_override is not None
                     else int(pipeline.get("max_parallel", 1)))

    # Phase 1+2: preflight + smoke (always serial — they're cheap)
    if pipeline["preflight"]:
        _campaign_preflight(cfg["campaign"], max_parallel)

    if smoke_steps > 0:
        print(f"\n=== Phase 2: SMOKE TESTS (serial, {smoke_steps} steps each) ===")
        for exp in cfg["campaign"]:
            if stage_smoke(exp, smoke_steps) is None:
                if halt:
                    print(f"[pipeline] smoke failed for {exp['tag']} — halt")
                    return []

    # Phase 3: production
    completed = []
    if pipeline["production"]:
        if max_parallel <= 1:
            print(f"\n=== Phase 3: PRODUCTION (serial) ===")
            for i, exp in enumerate(cfg["campaign"]):
                print(f"\n  [{i+1}/{len(cfg['campaign'])}] {exp['tag']}")
                rd = stage_production(exp)
                if rd is None:
                    if halt:
                        print(f"[pipeline] production failed for {exp['tag']} — halt")
                        break
                    continue
                completed.append(rd)
        else:
            completed = _run_production_parallel(
                cfg["campaign"], max_parallel, halt)

    print(f"\n[pipeline] {len(completed)}/{len(cfg['campaign'])} runs completed")

    # Phase 3.4: per-run analysis (optional, class-dispatched via tools.registry).
    # Triggers when BOTH `pipeline.analyze=True` AND `pipeline.analyzer_class` is set.
    # Existing PRX/ER configs that set analyze=True without an explicit analyzer_class
    # are unaffected — they ran the analyzer inline in the adapter, so this phase
    # remains opt-in to avoid duplicate work.
    analyzer_class = pipeline.get("analyzer_class")
    if pipeline.get("analyze") and analyzer_class and completed:
        print(f"\n=== Phase 3.4: ANALYZE (class={analyzer_class}) ===")
        for rd in completed:
            try:
                stage_analyze(rd, analyzer_class, pipeline.get("analyzer_params"))
            except Exception as e:
                print(f"[analyze] error on {rd}: {e}")
                if halt:
                    print(f"[pipeline] analyze failed — halt")
                    return completed

    # Phase 3.5: per-run visualization (optional, class-dispatched via tools.registry)
    viz_cfg = pipeline.get("visualize", {}) if isinstance(pipeline.get("visualize"), dict) else {}
    if viz_cfg.get("enabled") and viz_cfg.get("class") and completed:
        print(f"\n=== Phase 3.5: VISUALIZE (class={viz_cfg['class']}) ===")
        for rd in completed:
            try:
                stage_visualize(rd, viz_cfg["class"], viz_cfg.get("params", {}))
            except Exception as e:
                print(f"[visualize] error on {rd}: {e}")

    if not no_aggregate and aggr["enabled"] and completed:
        runs = aggr.get("runs")
        if runs is None:
            runs = [str(rd) for rd in completed]
        elif isinstance(runs, str):
            runs = _expand_runs([runs])
        elif isinstance(runs, list):
            runs = _expand_runs(runs)
        stage_aggregate(runs, aggr["output"], aggr["plots"], aggr["title"],
                        aggregator_class=aggr.get("class", "PRXAggregator"))

    return completed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("config", nargs="?",
                   help="Path to JSON or YAML config file (.json/.yaml/.yml)")

    # Sub-modes
    p.add_argument("--preflight-only", action="store_true",
                   help="Print resource estimates, no run")
    p.add_argument("--analyze", metavar="RUN_DIR",
                   help="Re-analyze an existing run dir (skip everything else)")
    p.add_argument("--aggregate", metavar="GLOB", nargs="+",
                   help="Aggregate existing runs into a master report")

    # Pipeline overrides (only meaningful with config)
    p.add_argument("--no-smoke", action="store_true",
                   help="Skip smoke test (overrides config)")
    p.add_argument("--smoke-steps", type=int,
                   help="Smoke test step count (overrides config)")
    p.add_argument("--no-aggregate", action="store_true",
                   help="Skip aggregation stage")
    p.add_argument("--continue-on-fail", action="store_true",
                   help="Continue campaign past failures")
    p.add_argument("--max-parallel", type=int,
                   help="Override max_parallel from config "
                        "(1=serial, 2=2-way GPU sharing, 3+=saturated)")

    # Aggregate-mode options
    p.add_argument("--output", help="Master report path (aggregate mode)")
    p.add_argument("--plots", nargs="+",
                   choices=["fig1", "fig2", "stability"],
                   help="Plot types to generate (aggregate mode)")
    p.add_argument("--title", help="Report title (aggregate mode)")

    # Ad-hoc single-run
    p.add_argument("--tag")
    p.add_argument("--N", type=int)
    p.add_argument("--steps", type=int)
    p.add_argument("--phi", type=float)
    p.add_argument("--T0", type=float)
    p.add_argument("--stride", type=int)

    return p.parse_args()


def main():
    args = parse_args()

    # Sub-mode 1: --analyze RUN_DIR
    if args.analyze:
        stage_analyze(args.analyze)
        return

    # Sub-mode 2: --aggregate "GLOB"...
    if args.aggregate:
        runs = _expand_runs(args.aggregate)
        if not runs:
            print(f"[aggregate] no runs matched: {args.aggregate}")
            sys.exit(1)
        plots = args.plots or ["fig1", "fig2"]
        output = args.output or "docs/PRX_campaign_report.md"
        title = args.title or "PRX Campaign Report"
        stage_aggregate(runs, output, plots, title)
        return

    # Sub-mode 3 / 4: full pipeline (config file or ad-hoc)
    if args.config:
        cfg = load_config(args.config)
    elif args.tag:
        cfg = config_from_cli(args)
    else:
        print("error: provide a config file or --tag/--phi/... for ad-hoc")
        sys.exit(2)

    if args.preflight_only:
        max_par = (args.max_parallel
                    if args.max_parallel is not None
                    else int(cfg["pipeline"].get("max_parallel", 1)))
        _campaign_preflight(cfg["campaign"], max_par)
        return

    smoke_override = (0 if args.no_smoke
                       else args.smoke_steps if args.smoke_steps is not None
                       else None)
    run_pipeline(cfg, smoke_override=smoke_override,
                  no_aggregate=args.no_aggregate,
                  continue_on_fail=args.continue_on_fail,
                  max_parallel_override=args.max_parallel)


if __name__ == "__main__":
    main()

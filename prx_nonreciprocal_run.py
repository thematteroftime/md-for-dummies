#!/usr/bin/env python3
"""PRX 2015 non-reciprocal Hertzian — Layer 3 adapter.

Pipeline: lattice gen → run.in → MD simulation → HDF5 output → manifest.

Units:        reduced (m = r0 = phi0 = k_B = 1; τ = sqrt(m·r0²/φ0) = 1)
Reduced map:  T* = k_B·T/φ0, t* = t/τ, φ = π·r0²·n (2D area fraction)
Paper case:   φ=0.3, T0*=1, NVE — asymptote T ∝ t^(2/3), τ_∞ ≈ 3.1

CLI:
  python prx_nonreciprocal_run.py --tag <id> [--phi 0.3 --T0 1.0 --steps N ...]
"""
import math
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
os.chdir(SCRIPT_DIR)

import constSet as cs
from constSet import *
from atomSystemClass import AtomSystem
from integratorClass import integrator
from forceFieldClass import HertzianNonreciprocal
from systemClass import simulator, systemRun
from searchBox import searchBox
from toolClass import fileOperator
from dataFiles.lattice_gen import make_prx_square2d

# ---------------------------------------------------------------------------
# PRX_PARAMS — defaults for the PRX 2015 non-reciprocal Hertzian reproduction.
# All keys are CLI-overridable (see argparse block at file end). Override any
# value via configs/plan_*.json — these defaults are a reference only.
#
# Paper Eq.(1) F kernel; reduced units (m = r0 = phi0 = k_B = 1).
# `N_A`, `N_B` are PER-SPECIES counts; total = N_A + N_B. Paper uses 20000+20000.
# ---------------------------------------------------------------------------
PRX_PARAMS = {
    "phi_target": 0.3,    # 2D area fraction
    "T0_star": 1.0,       # reduced initial temperature
    "N_A": 10000,         # per-species count; total = N_A + N_B
    "N_B": 10000,
    "mass": 1.0,
    "r0": 1.0,
    "phi0": 1.0,
    "nu": 0.0,            # 0 = NVE; >0 = Langevin damping (1/τ)
    "dt": 0.004,          # in τ units
    "run_steps": 750000,  # ~3000 τ at default dt
    "write_stride": 30,   # frames per HDF5 flush
    "output_format": "hdf5",
}
# Paper anchors (PRX 2015 §II.D): asymptotic T_A/T_B → 3.1, slope_A = 2/3.
# Reproduction reaches asymptote in ≳1000 τ at NVE; below that you'll see transient.

DATA_DIR = "./dataFiles"
OUTPUT_DIR = "./outputFiles"


def main():
    import datetime as _dt
    import json as _json
    import shutil as _shutil
    import subprocess as _subprocess

    p = PRX_PARAMS
    tag = p.get("_tag", "")
    suffix = f"_{tag}" if tag else ""
    # Per-run unique paths so multiple parallel runs don't race on intermediate files.
    run2_name = f"run2{suffix}.in"
    lattice_name = f"prx_lattice{suffix}.xyz"
    out_base = f"PRX_nonreciprocal{suffix}"

    # NEW (Plan C 2026-05-02): every run gets a dedicated subdir
    # outputFiles/<YYYYMMDD_HHMMSS>_<tag>/  containing every artifact.
    _ts_now = _dt.datetime.now()
    _ts_str = _ts_now.strftime("%Y%m%d_%H%M%S")
    _run_dir_name = f"{_ts_str}_{tag}" if tag else _ts_str
    RUN_DIR = os.path.join(OUTPUT_DIR, _run_dir_name)
    os.makedirs(RUN_DIR, exist_ok=True)
    print(f"[run] artifact dir: {RUN_DIR}")
    _started_at_iso = _ts_now.isoformat(timespec="seconds")
    _wall_begin = time.time()

    # NEW: preflight — predict resources before paying for compilation.
    # Persisted into manifest.json + report.md so future searches can find
    # experiments by cost.
    try:
        from toolClass import ResourceEstimator
        _preflight = ResourceEstimator.print_preflight({
            "tag": tag,
            "N": p["N_A"],
            "steps": p["run_steps"],
            "stride": p["write_stride"],
            "phi": p["phi_target"],
            "T0": p["T0_star"],
            "chunk_size": 200,
            "dt": p["dt"],
        })
    except Exception as _e:
        print(f"[preflight] skipped: {_e}")
        _preflight = None

    N_tot = p["N_A"] + p["N_B"]
    r0, phi0, phi_target = p["r0"], p["phi0"], p["phi_target"]

    # 1. 由面积分数 φ 计算盒子尺寸：φ=π*r0²*N/(Lx*Ly) => L²=π*r0²*N/φ
    L = math.sqrt(math.pi * r0 * r0 * N_tot / phi_target)
    Lx = Ly = L
    # Lz must be >= cutoffNegh (1.2*r0) for the 2D neighbour-list assertion.
    # In reduced units r0=1, so Lz=1.3*r0 satisfies the check.
    Lz = 1.3 * r0

    # 晶格常数：n=ceil(sqrt(N_A))，L=n*a => a=L/n
    n = math.ceil(math.sqrt(max(1, p["N_A"])))
    a = L / n

    # 2. 生成晶格并写入 dataFiles
    print(f"[1/4] 生成 PRX 穿插正方晶格...  tag={tag!r}")
    print(f"      φ={phi_target}, Lx=Ly={L:.2f} r0, a={a:.4f} r0, n={n}")
    xyz_path = os.path.join(DATA_DIR, lattice_name)
    positions, names, masses, groups = make_prx_square2d(
        xyz_path,
        a=a, N_A=p["N_A"], N_B=p["N_B"], mass=p["mass"],
        Lx=Lx, Ly=Ly, Lz=Lz,
    )
    print(f"      写入 {xyz_path}，{len(positions)} 粒子 (A={p['N_A']}, B={p['N_B']})")

    # 3. 写入 run2.in（reduced units: T0* directly, units reduced）
    run2_path = os.path.join(DATA_DIR, run2_name)
    with open(run2_path, "w", encoding="utf-8") as f:
        f.write(f"velocity  {p['T0_star']}   # reduced T0*\n")
        f.write(f"time_step {p['dt']}\n")
        f.write(f"run       {p['run_steps']}\n")
        f.write(f"dimension 2\n")
        f.write(f"units     reduced\n")
        # profiler off: long runs (>1M steps) accumulate 100s of M kernel
        # records that OOM Taichi at print_kernel_profiler_info(). Was the
        # root cause of E1 v2 crash 2026-05-02 after 5M steps completed.
        f.write(f"profiler  off\n")
        f.write(f"nu        {p['nu']}\n")
    print(f"[2/4] 写入 {run2_path}: reduced T0*={p['T0_star']}")

    # 4. 构建系统并运行
    system = systemRun(paramFile=run2_path, coorFile=xyz_path)
    system.register(AtomSystem, integrator, simulator, HertzianNonreciprocal, searchBox)

    cutoff = r0
    cutoffNegh = 1.2 * r0

    cho = p.get("_cho", 1)   # 1=cell-list (default), 2=O(N^2). Bench shows cell-list wins for N>3000.
    system.initParams(
        fFieldParams={"r0": r0, "phi0": phi0, "reciprocal": False},
        boxParams={"choose": cho, "cutoffNegh": cutoffNegh},
        atomParams={"cutoff": cutoff},
        inteParams={"nu": p["nu"]},
        simuParams={"write_stride": p["write_stride"],
                    "output_format": p["output_format"],
                    "chunk_size": 200},
    )

    os.makedirs(RUN_DIR, exist_ok=True)
    out_path_abs = os.path.abspath(os.path.join(RUN_DIR, out_base))
    print("[3/4] 运行非互易 Hertzian MD（无阻尼）...")
    system.runWithData(outputPath=out_path_abs, withData=True)

    run_step_int = int(system.runStep)
    out_ext = ".h5" if p["output_format"] == "hdf5" else ".xyz"
    out_file = os.path.abspath(os.path.join(RUN_DIR, f"{out_base}_{run_step_int}{out_ext}"))
    _wall_end = time.time()
    _wall_seconds = _wall_end - _wall_begin
    print(f"[4/4] 完成，输出: {out_file}")
    print(f"[wall] {_wall_seconds:.1f} s = {_wall_seconds/3600:.2f} hr")

    # NEW: archive inputs + manifest, then invoke auto-analyzer
    try:
        _shutil.copy2(run2_path, os.path.join(RUN_DIR, "run.in"))
        _shutil.copy2(xyz_path, os.path.join(RUN_DIR, "lattice.xyz"))
    except Exception as _e:
        print(f"[warn] could not archive inputs: {_e}")

    _git_sha = "unknown"
    try:
        _git_sha = _subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=SCRIPT_DIR, text=True).strip()
    except Exception:
        pass

    # ARCHITECTURE.md §3.2 contract: write all required + canonical fields.
    # Paper-specific keys (phi_target, T0_star, N_A, ...) preserved alongside.
    _manifest = {
        # §3.2 required
        "tag": tag,
        "run_type": "hertzian_nonreciprocal",
        "force_class": "HertzianNonreciprocal",
        "units": "reduced",
        "run_dir": RUN_DIR,
        "h5_path": out_file,
        "started_at": _started_at_iso,
        "finished_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "wall_seconds": _wall_seconds,
        "git_sha": _git_sha,
        "steps": int(p["run_steps"]),
        "write_stride": int(p["write_stride"]),
        "actual_step_rate": (int(p["run_steps"]) / _wall_seconds
                              if _wall_seconds > 0 else None),
        # canonical numeric fields (per §3.2 recommended)
        "T0": p["T0_star"],
        "dt": p["dt"],
        "nu": p["nu"],
        "N":  p["N_A"],          # per-species; total = 2*N (registry §1)
        # paper-specific (analyzer reads these)
        "phi_target": p["phi_target"],
        "T0_star":    p["T0_star"],
        "N_A":        p["N_A"],
        "N_B":        p["N_B"],
        "r0":         p["r0"],
        "phi0":       p["phi0"],
        "mass":       p["mass"],
        # bookkeeping
        "chunk_size": 200,
        "cho":        p.get("_cho", 1),
        "notes":      p.get("_notes", ""),
        "preflight":  _preflight,
    }
    with open(os.path.join(RUN_DIR, "manifest.json"), "w", encoding="utf-8") as _f:
        _json.dump(_manifest, _f, indent=2)
    print(f"[manifest] wrote {os.path.join(RUN_DIR, 'manifest.json')}")

    # ARCHITECTURE.md §3.1: adapter MUST NOT call analyzer in-process.
    # Platform's Phase 4 (aggregate) handles that. The `--auto-analyze` CLI
    # flag is preserved for legacy callers and will eventually be removed.
    if p.get("_auto_analyze"):
        print("[auto_analyze] using legacy in-process PRXAnalyzer call; "
              "prefer `python scripts/run_experiment.py --analyze RUN_DIR`.")
        try:
            from toolClass import PRXAnalyzer
            PRXAnalyzer.full_analysis(RUN_DIR)
        except Exception as _e:
            import traceback
            print(f"[auto_analyze] failed (non-fatal): {_e}")
            traceback.print_exc()

    print(f"[done] full report at: {os.path.join(RUN_DIR, 'report.md')}")


def _parse_cli():
    """CLI overrides for PRX_PARAMS so multiple parallel runs can share this script.

    Each --tag NAME run produces independent intermediate files
    (`dataFiles/run2_NAME.in`, `dataFiles/prx_lattice_NAME.xyz`,
    `outputFiles/PRX_nonreciprocal_NAME_<runStep>.h5`) so two simultaneous
    invocations don't race on PRX_nonreciprocal.h5 / run2.in.

    Usage examples:
        python prx_nonreciprocal_run.py
            # default — uses PRX_PARAMS at top of file
        python prx_nonreciprocal_run.py --tag phase2quick --N 20000 --steps 375000
            # paper-N (1/2 each), 1500 tau quick run, parallel-safe filenames
    """
    import argparse
    parser = argparse.ArgumentParser(description="PRX 2015 Fig 1 reproduction (CLI overrides for parallel runs)")
    parser.add_argument("--tag", default="", help="Suffix for output filenames (enables parallel runs)")
    parser.add_argument("--N", type=int, help="Override N_A=N_B (default: PRX_PARAMS['N_A'])")
    parser.add_argument("--steps", type=int, help="Override run_steps")
    parser.add_argument("--phi", type=float, help="Override phi_target")
    parser.add_argument("--T0", type=float, help="Override T0_star")
    parser.add_argument("--nu", type=float, help="Override nu (drag)")
    parser.add_argument("--stride", type=int, help="Override write_stride")
    parser.add_argument("--cho", type=int, choices=[1, 2], help="Neighbor algo: 1=cell-list, 2=O(N^2)")
    parser.add_argument("--auto-analyze", action="store_true", dest="auto_analyze",
                         help="(legacy) call PRXAnalyzer in-process at end of run; "
                              "prefer platform-side analysis")
    args = parser.parse_args()
    if args.auto_analyze:
        PRX_PARAMS["_auto_analyze"] = True

    if args.N is not None:
        PRX_PARAMS["N_A"] = PRX_PARAMS["N_B"] = args.N
    if args.steps is not None:
        PRX_PARAMS["run_steps"] = args.steps
    if args.phi is not None:
        PRX_PARAMS["phi_target"] = args.phi
    if args.T0 is not None:
        PRX_PARAMS["T0_star"] = args.T0
    if args.nu is not None:
        PRX_PARAMS["nu"] = args.nu
    if args.stride is not None:
        PRX_PARAMS["write_stride"] = args.stride
    if args.cho is not None:
        PRX_PARAMS["_cho"] = args.cho      # consumed by main()
    PRX_PARAMS["_tag"] = args.tag           # consumed by main()


if __name__ == "__main__":
    _parse_cli()
    main()

#!/usr/bin/env python3
"""ER plasma (PRL 2008) full-pipeline adapter.

Layer 3 entry script for the anisotropic Yukawa force class. Mirrors the
per-run subdir / manifest layout of prx_nonreciprocal_run.py.

Units: macro (mm, ms, K). dt defaults to 0.01 ms; total time = steps · dt.

Reproduction target: Ivlev et al. *Phys. Rev. Lett.* 100, 095003 (2008) —
chain formation in anisotropic Yukawa potential
V = α[exp(-r/λ)/r - 0.43·MT²·λ²·(3cos²θ-1)/r³].

CLI:
  python er_plasma_run.py --tag ER1_MT04 --MT 0.4 --steps 50000 --stride 100
"""
import math
import os
import sys
import time
import shutil
import json
import datetime as _dt
import subprocess as _subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
os.chdir(SCRIPT_DIR)

import constSet as cs
from constSet import *
from atomSystemClass import AtomSystem
from integratorClass import integrator
from forces import ERPotential
from systemClass import simulator, systemRun
from searchBox import searchBox

# ---------------------------------------------------------------------------
# Default parameters (PRL 2008 anisotropic Yukawa, macro units mm/ms/K)
# ---------------------------------------------------------------------------
ER_PARAMS = {
    "N":             1000,
    "T0_K":          348,        # initial temperature (Kelvin)
    "dt_ms":         0.01,       # integrator timestep (ms)
    "run_steps":     50000,      # default run length
    "write_stride":  100,
    "Z_eff":         10000.0,    # effective charge in electron units
    "lambda_mm":     0.05,       # Debye screening length (mm)
    "MT":            0.8,        # Mach number (paper PRL 2008 anisotropy parameter)
    "nu":            0.1,        # Langevin drag coefficient (1/ms)
    "box_mm":        3.0,        # cubic-box edge (mm)
    "lattice_file":  "xyz_1000_3.in",  # use legacy 1000-atom lattice
    "output_format": "hdf5",
}

DATA_DIR = "./dataFiles"
OUTPUT_DIR = "./outputFiles"


def main():
    p = ER_PARAMS
    tag = p.get("_tag", "")
    suffix = f"_{tag}" if tag else ""
    run2_name = f"run2_er{suffix}.in"

    # NEW (mirror prx_nonreciprocal_run.py 2026-05-02 layout): per-run subdir
    _ts_now = _dt.datetime.now()
    _ts_str = _ts_now.strftime("%Y%m%d_%H%M%S")
    _run_dir_name = f"{_ts_str}_{tag}" if tag else _ts_str
    RUN_DIR = os.path.join(OUTPUT_DIR, _run_dir_name)
    os.makedirs(RUN_DIR, exist_ok=True)
    print(f"[run] artifact dir: {RUN_DIR}")
    _started_at_iso = _ts_now.isoformat(timespec="seconds")
    _wall_begin = time.time()

    # Resource estimate
    try:
        from toolClass import ResourceEstimator
        _preflight = ResourceEstimator.print_preflight({
            "tag": tag,
            "N": p["N"] // 2,  # ResourceEstimator expects per-species
            "steps": p["run_steps"],
            "stride": p["write_stride"],
            "phi": "n/a (ER plasma, macro units)",
            "T0": p["T0_K"],
            "chunk_size": 200,
            "dt": p["dt_ms"] * 1e-3,  # macro→fake reduced for est
        })
    except Exception as _e:
        print(f"[preflight] skipped: {_e}")
        _preflight = None

    # Step 1: copy legacy lattice (xyz_1000_3.in) — already a 3D 1000-atom config
    lattice_src = os.path.join(DATA_DIR, p["lattice_file"])
    lattice_dst = os.path.join(DATA_DIR, f"er_lattice{suffix}.xyz")
    if not os.path.exists(lattice_src):
        raise FileNotFoundError(
            f"Required lattice file not found: {lattice_src}\n"
            f"Should be the legacy 1000-atom 3D lattice from xyz_1000_3.in.")
    shutil.copy2(lattice_src, lattice_dst)
    print(f"[1/4] lattice: {lattice_dst} (1000 atoms in {p['box_mm']}mm cube)")

    # Step 2: write run2.in (macro units)
    run2_path = os.path.join(DATA_DIR, run2_name)
    with open(run2_path, "w", encoding="utf-8") as f:
        f.write(f"velocity   {p['T0_K']}        # initial T (K)\n")
        f.write(f"time_step  {p['dt_ms']}       # dt (ms)\n")
        f.write(f"run        {p['run_steps']}\n")
        f.write(f"dimension  3\n")
        f.write(f"units      macro\n")
        f.write(f"profiler   off\n")
        f.write(f"nu         {p['nu']}\n")
    print(f"[2/4] {run2_path}: T0={p['T0_K']}K, dt={p['dt_ms']}ms, "
          f"steps={p['run_steps']}, ν={p['nu']}/ms")

    # Step 3: build system + ER force
    system = systemRun(paramFile=run2_path, coorFile=lattice_dst)
    system.register(AtomSystem, integrator, simulator, ERPotential, searchBox)

    cutoff = 12.0 * p["lambda_mm"]      # = 0.6 mm = 12λ for the default lattice
    cutoffNegh = 18.0 * p["lambda_mm"]  # = 0.9 mm = 18λ

    cho = p.get("_cho", 2)  # default O(N²) for small N (override via --cho 1 for cell list)
    # Resolve E-field direction
    E_dir = ti.Vector([0.0, 0.0, 1.0])

    system.initParams(
        fFieldParams={
            "Z_eff": p["Z_eff"],
            "lambda_screen": p["lambda_mm"],
            "MT": p["MT"],
            "E_dir": E_dir,
        },
        boxParams={"choose": cho, "cutoffNegh": cutoffNegh},
        atomParams={"cutoff": cutoff},
        inteParams={"nu": p["nu"]},
        simuParams={
            "write_stride": p["write_stride"],
            "output_format": p["output_format"],
            "chunk_size": 200,
        },
    )

    out_base = f"ER_plasma{suffix}"
    out_path_abs = os.path.abspath(os.path.join(RUN_DIR, out_base))
    print(f"[3/4] running ER MD: MT={p['MT']}, λ={p['lambda_mm']}mm, "
          f"Z_eff={p['Z_eff']:.0f}e, cutoff={cutoff}mm")
    system.runWithData(outputPath=out_path_abs, withData=True)

    run_step_int = int(system.runStep)
    out_ext = ".h5" if p["output_format"] == "hdf5" else ".xyz"
    out_file = os.path.abspath(os.path.join(
        RUN_DIR, f"{out_base}_{run_step_int}{out_ext}"))
    _wall_end = time.time()
    _wall_seconds = _wall_end - _wall_begin
    print(f"[4/4] done. output: {out_file}")
    print(f"[wall] {_wall_seconds:.1f} s = {_wall_seconds/3600:.2f} hr")

    # Archive run.in + lattice into run dir + write manifest
    try:
        shutil.copy2(run2_path, os.path.join(RUN_DIR, "run.in"))
        shutil.copy2(lattice_dst, os.path.join(RUN_DIR, "lattice.xyz"))
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
    # Paper-specific keys (T0_K, dt_ms, nu_inv_ms, MT, ...) preserved alongside.
    _manifest = {
        # §3.2 required
        "tag": tag,
        "run_type": "er_plasma",
        "force_class": "ERPotential",
        "units": "macro",
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
        # canonical numeric fields (§3.2 recommended; analyzer-agnostic)
        "T0": p["T0_K"],
        "dt": p["dt_ms"],
        "nu": p["nu"],
        "N":  p["N"],
        # paper-specific (analyzer reads these; macro units suffix preserved)
        "Z_eff":            p["Z_eff"],
        "lambda_screen_mm": p["lambda_mm"],
        "MT":               p["MT"],
        "T0_K":             p["T0_K"],
        "nu_inv_ms":        p["nu"],
        "dt_ms":            p["dt_ms"],
        # bookkeeping
        "chunk_size":   200,
        "box_mm":       p["box_mm"],
        "cho":          cho,
        "cutoff_mm":    cutoff,
        "cutoffNegh_mm": cutoffNegh,
        "notes":        p.get("_notes", ""),
        "preflight":    _preflight,
    }
    with open(os.path.join(RUN_DIR, "manifest.json"), "w", encoding="utf-8") as _f:
        json.dump(_manifest, _f, indent=2)
    print(f"[manifest] wrote {os.path.join(RUN_DIR, 'manifest.json')}")

    # NOTE: PRXAnalyzer.full_analysis assumes binary species + asymptotic
    # power-law fit. For ER plasma (single species, structural observables),
    # the analysis is different. We skip auto-analyze here; use
    # `scripts/verify_er_chains.py`-style angular pair correlation instead
    # (will be invoked by Plan G aggregation step).
    print("[done] er_plasma_run finished. "
          "Use scripts/analyze_er_chain.py for chain analysis.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PRL 2008 ER plasma reproduction")
    parser.add_argument("--tag", default="", help="output subdir tag")
    parser.add_argument("--N", type=int, help="atom count (default 1000)")
    parser.add_argument("--MT", type=float, help="Mach number (default 0.8)")
    parser.add_argument("--Z-eff", type=float, dest="Z_eff",
                         help="effective charge (default 10000 e)")
    parser.add_argument("--lambda-mm", type=float, dest="lambda_mm",
                         help="Debye length (mm, default 0.05)")
    parser.add_argument("--T0-K", type=float, dest="T0_K",
                         help="initial T (K, default 348)")
    parser.add_argument("--dt-ms", type=float, dest="dt_ms",
                         help="dt (ms, default 0.01)")
    parser.add_argument("--steps", type=int, help="MD steps (default 50000)")
    parser.add_argument("--stride", type=int, help="write_stride (default 100)")
    parser.add_argument("--nu", type=float, help="drag coefficient (default 0.1)")
    parser.add_argument("--cho", type=int, choices=[1, 2],
                         help="neighbor algo (1=cell-list, 2=O(N^2), default 2)")
    args = parser.parse_args()

    if args.tag is not None:
        ER_PARAMS["_tag"] = args.tag
    if args.N is not None:
        ER_PARAMS["N"] = args.N
    if args.MT is not None:
        ER_PARAMS["MT"] = args.MT
    if args.Z_eff is not None:
        ER_PARAMS["Z_eff"] = args.Z_eff
    if args.lambda_mm is not None:
        ER_PARAMS["lambda_mm"] = args.lambda_mm
    if args.T0_K is not None:
        ER_PARAMS["T0_K"] = args.T0_K
    if args.dt_ms is not None:
        ER_PARAMS["dt_ms"] = args.dt_ms
    if args.steps is not None:
        ER_PARAMS["run_steps"] = args.steps
    if args.stride is not None:
        ER_PARAMS["write_stride"] = args.stride
    if args.nu is not None:
        ER_PARAMS["nu"] = args.nu
    if args.cho is not None:
        ER_PARAMS["_cho"] = args.cho

    main()

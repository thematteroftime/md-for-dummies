#!/usr/bin/env python3
"""Pedersen et al., PRL 120, 165501 (2018) — Kob-Andersen binary LJ adapter.

Reduced LJ units (σ_AA = ε_AA = m = k_B = 1).  Pair potential per paper p.2:
    v_pq(r) = 4 ε_pq [(σ_pq/r)^12 - (σ_pq/r)^6],  truncated and shifted at 2.5 σ_pq
KA standard: σ_AA=1.0, σ_BB=0.88, σ_AB=0.8, ε_AA=1.0, ε_BB=0.5, ε_AB=1.5.

NOTE: framework engine has BAOAB drag-only Langevin (no Wiener noise) and no
NPT. We therefore run NVT-Langevin at fixed ρ; results are qualitative for
RDF (structure) and MSD trend. Paper's NPT coexistence-line method (Fig.1) is
out of engine scope — see design doc §11.

CLI:
    python pedersen_kalj_run.py --tag T07 --T0 0.7 --N 1000 --steps 100000
"""
import datetime as _dt
import json as _json
import os
import shutil as _shutil
import subprocess as _subprocess
import sys
import time

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
os.chdir(SCRIPT_DIR)

import constSet as cs
from constSet import *
from atomSystemClass import AtomSystem
from integratorClass import integrator
from systemClass import simulator, systemRun
from searchBox import searchBox
from forces import KobAndersenLJ
from tools.lattices import LATTICE_REGISTRY


# ===========================================================================
# §1 PARAMS — paper defaults (KA-LJ, ρ=1.2 isochore, harness scope)
# ===========================================================================
PARAMS = {
    "_tag":             "",
    "_notes":           "",

    # Physics — Kob-Andersen 80:20 (paper p.2)
    "fraction_B":       0.20,    # 20% B particles per KA convention
    "rho":              1.2,     # density at which the KA paper does Fig.1
    "sigma_AA":         1.0,
    "sigma_AB":         0.8,
    "sigma_BB":         0.88,
    "eps_AA":           1.0,
    "eps_AB":           1.5,
    "eps_BB":           0.5,
    "cutoff_factor":    2.5,     # paper-specified

    # MD numerics
    "N":                1000,    # total particle count (harness scope)
    "dt":               0.005,   # τ = sqrt(m σ²/ε) = 1
    "T0":               1.0,     # KA paper Tm ≈ 1.028 at ρ=1.2 (Fig.1)
    "nu":               0.1,     # Langevin damping (drag-only — see §11 of design doc)
    "run_steps":        100000,
    "write_stride":     200,

    # Output
    "output_format":    "hdf5",
    "chunk_size":       200,

    # Lattice / IC
    "initial_state":    "simple_cubic_3d",
    "species_seed":     0,       # deterministic A/B assignment for reproducibility
}

DATA_DIR = "./dataFiles"
OUTPUT_DIR = "./outputFiles"


# ===========================================================================
# §2 LATTICE PREP — use simple_cubic_3d generator + random A/B labels
# ===========================================================================
def _prepare_lattice(p, suffix):
    """Build a simple-cubic lattice at density p['rho'] with N atoms,
    randomly labelled 80% A / 20% B (deterministic seed for reproducibility),
    and write to dataFiles/pedersen_kalj_lattice<suffix>.xyz."""
    LatticeCls = LATTICE_REGISTRY[p["initial_state"]]
    positions, box = LatticeCls.generate(p["N"], {"density": p["rho"]})
    Lx = float(box[0, 0]); Ly = float(box[1, 1]); Lz = float(box[2, 2])

    # KA species assignment: pick N_B random indices to be B (group=2),
    # the rest are A (group=1). Deterministic by seed.
    N = p["N"]
    N_B = int(round(p["fraction_B"] * N))
    N_A = N - N_B
    rng = np.random.default_rng(p["species_seed"])
    perm = rng.permutation(N)
    species = np.ones(N, dtype=np.int32)
    species[perm[:N_B]] = 2  # mark first N_B as B
    name_for = {1: "A", 2: "B"}

    lattice_dst = os.path.join(DATA_DIR, f"pedersen_kalj_lattice{suffix}.xyz")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(lattice_dst, "w", encoding="utf-8") as f:
        f.write(f"{N}\n")
        f.write(f"{Lx} 0.0 0.0 0.0 {Ly} 0.0 0.0 0.0 {Lz}\n")
        for i in range(N):
            x, y, z = positions[i]
            name = name_for[int(species[i])]
            f.write(f"{name} {x:.6f} {y:.6f} {z:.6f} 1.0\n")

    return lattice_dst, N_A, N_B, (Lx, Ly, Lz)


def _write_run_in(p, suffix):
    run_in_path = os.path.join(DATA_DIR, f"run_pedersen_kalj{suffix}.in")
    with open(run_in_path, "w", encoding="utf-8") as f:
        f.write(f"velocity   {p['T0']}        # initial T (reduced)\n")
        f.write(f"time_step  {p['dt']}\n")
        f.write(f"run        {p['run_steps']}\n")
        f.write(f"dimension  3\n")
        f.write(f"units      reduced\n")
        f.write(f"profiler   off\n")
        f.write(f"nu         {p['nu']}\n")
    return run_in_path


# ===========================================================================
# §3 MAIN
# ===========================================================================
def main():
    p = PARAMS
    tag = p.get("_tag", "")
    suffix = f"_{tag}" if tag else ""

    _ts_now = _dt.datetime.now()
    _ts_str = _ts_now.strftime("%Y%m%d_%H%M%S")
    RUN_DIR = os.path.join(OUTPUT_DIR, f"{_ts_str}_{tag}" if tag else _ts_str)
    os.makedirs(RUN_DIR, exist_ok=True)
    print(f"[run] artifact dir: {RUN_DIR}")
    _started_at_iso = _ts_now.isoformat(timespec="seconds")
    _wall_begin = time.time()

    _preflight = None
    try:
        from toolClass import ResourceEstimator
        _preflight = ResourceEstimator.print_preflight({
            "tag": tag,
            "N": p["N"] // 2,  # estimator expects per-species; use half for the budget
            "steps": p["run_steps"],
            "stride": p["write_stride"],
            "phi": "n/a (KA-LJ density-driven)",
            "T0": p["T0"],
            "chunk_size": p["chunk_size"],
            "dt": p["dt"],
        })
    except Exception as e:
        print(f"[preflight] skipped: {e}")

    lattice_dst, N_A, N_B, (Lx, Ly, Lz) = _prepare_lattice(p, suffix)
    print(f"[1/4] lattice: {lattice_dst} (N={p['N']}, A={N_A}, B={N_B}, "
          f"box={Lx:.3f}^3, ρ={p['rho']})")

    run_in_path = _write_run_in(p, suffix)
    print(f"[2/4] {run_in_path}: T0={p['T0']}, dt={p['dt']}, "
          f"steps={p['run_steps']}, ν={p['nu']}")

    # Build system
    system = systemRun(paramFile=run_in_path, coorFile=lattice_dst)
    system.register(AtomSystem, integrator, simulator, KobAndersenLJ, searchBox)

    # cutoff = max pair r_c = 2.5 · σ_AA = 2.5; cutoffNegh slightly larger.
    cutoff = p["cutoff_factor"] * p["sigma_AA"]
    cutoffNegh = cutoff * 1.15

    cho = p.get("_cho", 1 if p["N"] > 3000 else 2)

    system.initParams(
        fFieldParams={
            "sigma_AA": p["sigma_AA"], "sigma_AB": p["sigma_AB"], "sigma_BB": p["sigma_BB"],
            "eps_AA":   p["eps_AA"],   "eps_AB":   p["eps_AB"],   "eps_BB":   p["eps_BB"],
            "cutoff_factor": p["cutoff_factor"],
        },
        boxParams={"choose": cho, "cutoffNegh": cutoffNegh},
        atomParams={"cutoff": cutoff},
        inteParams={"nu": p["nu"]},
        simuParams={
            "write_stride": p["write_stride"],
            "output_format": p["output_format"],
            "chunk_size": p["chunk_size"],
        },
    )

    out_base = f"pedersen_kalj{suffix}"
    out_path_abs = os.path.abspath(os.path.join(RUN_DIR, out_base))
    print(f"[3/4] running KA-LJ MD: T0={p['T0']}, ρ={p['rho']}, "
          f"N={p['N']} (A:B = {N_A}:{N_B}), cutoff={cutoff}")
    system.runWithData(outputPath=out_path_abs, withData=True)

    run_step_int = int(system.runStep)
    out_ext = ".h5" if p["output_format"] == "hdf5" else ".xyz"
    out_file = os.path.abspath(os.path.join(
        RUN_DIR, f"{out_base}_{run_step_int}{out_ext}"))
    _wall_end = time.time()
    _wall_seconds = _wall_end - _wall_begin
    print(f"[4/4] done. output: {out_file}")
    print(f"[wall] {_wall_seconds:.1f} s = {_wall_seconds/3600:.2f} hr")

    try:
        _shutil.copy2(run_in_path, os.path.join(RUN_DIR, "run.in"))
        _shutil.copy2(lattice_dst, os.path.join(RUN_DIR, "lattice.xyz"))
    except Exception as e:
        print(f"[warn] could not archive inputs: {e}")

    _git_sha = "unknown"
    try:
        _git_sha = _subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=SCRIPT_DIR, text=True).strip()
    except Exception:
        pass

    manifest = {
        # contract §3.2 required
        "tag":              tag,
        "run_type":         "kalj",
        "force_class":      "KobAndersenLJ",
        "units":            "reduced",
        "run_dir":          RUN_DIR,
        "h5_path":          out_file,
        "started_at":       _started_at_iso,
        "finished_at":      _dt.datetime.now().isoformat(timespec="seconds"),
        "wall_seconds":     _wall_seconds,
        "git_sha":          _git_sha,
        "steps":            int(p["run_steps"]),
        "write_stride":     int(p["write_stride"]),
        "actual_step_rate": (int(p["run_steps"]) / _wall_seconds
                              if _wall_seconds > 0 else None),
        # canonical
        "T0":               p["T0"],
        "dt":               p["dt"],
        "nu":               p["nu"],
        "N":                p["N"],
        # paper-specific
        "rho":              p["rho"],
        "fraction_B":       p["fraction_B"],
        "N_A":              N_A,
        "N_B":              N_B,
        "sigma_AA":         p["sigma_AA"], "sigma_AB": p["sigma_AB"], "sigma_BB": p["sigma_BB"],
        "eps_AA":           p["eps_AA"],   "eps_AB":   p["eps_AB"],   "eps_BB":   p["eps_BB"],
        "cutoff_factor":    p["cutoff_factor"],
        "Lx":               Lx, "Ly": Ly, "Lz": Lz,
        # bookkeeping
        "notes":            p.get("_notes", ""),
        "preflight":        _preflight,
        "chunk_size":       p["chunk_size"],
        "cho":              cho,
        "species_seed":     p["species_seed"],
        "initial_state":    p["initial_state"],
    }
    with open(os.path.join(RUN_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        _json.dump(manifest, f, indent=2)
    print(f"[manifest] wrote {os.path.join(RUN_DIR, 'manifest.json')}")

    print("[done] pedersen_kalj_run finished. "
          "Platform's Phase 3.4 + 3.5 will run analyzer + plotter.")


# ===========================================================================
# §4 CLI
# ===========================================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="KA-LJ binary mixture adapter (Pedersen PRL 2018)")
    parser.add_argument("--tag", default="", help="run id (matches campaign entry tag)")
    parser.add_argument("--steps", type=int, help="MD steps (default 100000)")
    parser.add_argument("--stride", type=int, help="HDF5 write_stride (default 200)")
    parser.add_argument("--N", type=int, help="total particle count (default 1000)")
    parser.add_argument("--T0", type=float, help="initial temperature (default 1.0)")
    parser.add_argument("--rho", type=float, help="density (default 1.2)")
    parser.add_argument("--nu", type=float, help="Langevin damping (default 0.1)")
    parser.add_argument("--fraction-B", type=float, dest="fraction_B",
                         help="B species fraction (default 0.20 = standard KA)")
    parser.add_argument("--cho", type=int, choices=[1, 2],
                         help="neighbor algo (1=cell-list, 2=O(N²))")

    args = parser.parse_args()
    if args.tag is not None:        PARAMS["_tag"] = args.tag
    if args.steps is not None:      PARAMS["run_steps"] = args.steps
    if args.stride is not None:     PARAMS["write_stride"] = args.stride
    if args.N is not None:          PARAMS["N"] = args.N
    if args.T0 is not None:         PARAMS["T0"] = args.T0
    if args.rho is not None:        PARAMS["rho"] = args.rho
    if args.nu is not None:         PARAMS["nu"] = args.nu
    if args.fraction_B is not None: PARAMS["fraction_B"] = args.fraction_B
    if args.cho is not None:        PARAMS["_cho"] = args.cho

    main()

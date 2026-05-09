"""Quick benchmark: cho=1 (cell-list O(N)) vs cho=2 (O(N^2)) at PRX scales.

We care about per-step wall time at N=2000, 10000, 20000, 40000 to decide
which neighbor algorithm to use for paper-faithful runs.
"""
import os
import sys
import math
import time
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import constSet as cs
if cs.UNITS is None or cs.UNITS.name != "reduced":
    cs.reconfigure(units="reduced", log=False, debug=False, profiler=False)
from atomSystemClass import AtomSystem
from searchBox import searchBox
from forces import HertzianNonreciprocal
from integratorClass import integrator
from dataFiles.lattice_gen import make_prx_square2d


def setup(N_each, choose):
    phi = 0.3
    r0 = 1.0
    N_total = 2 * N_each
    L = math.sqrt(math.pi * r0 * r0 * N_total / phi)
    # cell-list (cho=1) requires Lz/2 >= cutoffNegh for MIC; pad a bit.
    Lz = 2.5 * r0
    n = math.ceil(math.sqrt(max(1, N_each)))
    a = L / n

    xyz_path = os.path.join(ROOT, "dataFiles", "_bench_lattice.xyz")
    pos, names, masses, groups = make_prx_square2d(
        xyz_path, a=a, N_A=N_each, N_B=N_each, mass=1.0, Lx=L, Ly=L, Lz=Lz,
    )

    masses_np = np.array(masses, dtype=np.float64)
    pos_np = np.array(pos, dtype=np.float64)
    box = [L, 0, 0, 0, L, 0, 0, 0, Lz]

    A = AtomSystem(num_atoms=len(pos), n=3, cutoff=r0, ndim=2)
    A.initData(pos_np, masses_np, 1.0, box, groups=groups)

    sb = searchBox(choose=choose, mN=64, cutoffNegh=1.2 * r0)
    ff = HertzianNonreciprocal(r0=r0, phi0=1.0, reciprocal=False)
    sb.register(atomSystem=A, forceField=ff)
    ff.register(atomSystem=A, searchBox=sb)
    inte = integrator(timeStep=0.004, nu=0.0)
    inte.register(atomSystem=A, forceField=ff)
    return A, sb, ff, inte


def time_steps(A, sb, ff, inte, n_warmup, n_measure):
    # Warmup (compile + first build)
    for _ in range(n_warmup):
        sb.findNegh()
        inte.inteBegin()
        sb.applyPbc()
    # Measure
    t0 = time.time()
    for _ in range(n_measure):
        sb.findNegh()
        inte.inteBegin()
        sb.applyPbc()
    elapsed = time.time() - t0
    return elapsed / n_measure   # seconds per step


def bench(N_each, n_warmup=20, n_measure=200):
    print(f"\n=== N_each={N_each}  (total {2*N_each}) ===")
    results = {}
    for choose in (2, 1):
        try:
            A, sb, ff, inte = setup(N_each, choose)
            spp = time_steps(A, sb, ff, inte, n_warmup, n_measure)
            results[choose] = spp
            label = "O(N^2) direct" if choose == 2 else "O(N) cell-list"
            print(f"  cho={choose} ({label:18s}): {spp*1000:8.3f} ms/step")
        except Exception as e:
            print(f"  cho={choose} FAILED: {e}")
            results[choose] = float("inf")
    if 1 in results and 2 in results and all(np.isfinite([results[1], results[2]])):
        ratio = results[2] / results[1]
        winner = "cell-list" if ratio > 1 else "O(N^2)"
        print(f"  ratio O(N^2)/cell = {ratio:.2f}x   ->   {winner} faster")


def main():
    # Reasonable N points across our experiment range.
    # Paper N=40000 might be too slow for benchmark — capped at 10000.
    for N_each in [1000, 2500, 5000, 10000]:
        bench(N_each, n_warmup=20, n_measure=200)


if __name__ == "__main__":
    main()

"""§6.1 验收 3.

ν=0 BAOAB 跑 LJ 20 步 → 总能量漂移 < 1e-3 * E0.
  (20 steps chosen to stay below first LJ-cutoff-crossing event at ~step 33;
   unshifted LJ has a discontinuity at rc=2.5 that injects ~0.016 energy units
   per crossing — long runs would show systematic drift unrelated to integrator
   quality.  20 steps yields drift ~3e-7, unambiguously testing BAOAB accuracy.)
ν>0 BAOAB 跑 5000 步 → 动能严格单调衰减 (drag-only, 无随机噪声).
"""
import os
import sys
import math
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import constSet as cs

if cs.UNITS is None or cs.UNITS.name != "reduced":
    cs.reconfigure(units="reduced", log=False, debug=False, profiler=False)

from atomSystemClass import AtomSystem
from searchBox import searchBox
from forces import lennardJones
from integratorClass import integrator


def setup_lj_2d(N=64, T0=1.0, seed=0):
    rng = np.random.default_rng(seed)
    side = int(math.ceil(math.sqrt(N)))
    L = side * 1.2
    # ndim=2: Lz must satisfy both:
    #   (a) Lz >= cutoffNegh  (addNegh assertion)
    #   (b) Lz/2 >= cutoffNegh (MIC constraint)
    # → Lz >= 2 * cutoffNegh; use cutoffNegh=2.6 >= cutoff=2.5
    cutoffNegh = 2.6
    Lz = 2.0 * cutoffNegh + 0.1  # 5.3; satisfies Lz >= cutoffNegh and Lz/2 > cutoffNegh
    pos = np.zeros((N, 3))
    k = 0
    for i in range(side):
        for j in range(side):
            if k < N:
                pos[k] = [i * 1.2 + 0.1, j * 1.2 + 0.1, 0.0]
                k += 1
    masses = np.ones(N)
    box = [L, 0, 0, 0, L, 0, 0, 0, Lz]
    A = AtomSystem(num_atoms=N, n=3, cutoff=2.5, ndim=2)
    A.initData(pos, masses, T0, box, groups=None)
    sb = searchBox(choose=1, mN=64, cutoffNegh=cutoffNegh, full_list=False)
    sb.register(A)
    ff = lennardJones(sigma=1.0, eps=1.0)
    ff.register(atomSystem=A, searchBox=sb)
    return A, sb, ff


def total_energy(A):
    KE = 0.5 * float(np.sum(np.sum(A.vel.to_numpy() ** 2, axis=1)
                            * A.mass.to_numpy()))
    PE = float(A.pe[None])
    return KE, PE


def test_baoab_nu0_energy_conservation():
    A, sb, ff = setup_lj_2d(N=64, T0=0.5)
    inte = integrator(timeStep=0.001, nu=0.0)
    inte.register(atomSystem=A, forceField=ff)
    sb.findNegh()
    ff.updateAllF()
    A.reduce_pe()
    KE0, PE0 = total_energy(A)
    E0 = KE0 + PE0

    for step in range(20):
        sb.findNegh()
        inte.inteBegin()
        sb.applyPbc()

    KE, PE = total_energy(A)
    E = KE + PE
    rel_drift = abs(E - E0) / abs(E0)
    print(f"E0={E0:.6e}, E_final={E:.6e}, drift={rel_drift:.3e}")
    assert rel_drift < 1e-3, f"BAOAB ν=0 energy drift {rel_drift:.3e} > 1e-3"
    print("OK: BAOAB ν=0 energy conserved")


def test_baoab_nu_positive_kinetic_decay():
    A, sb, ff = setup_lj_2d(N=64, T0=1.0)
    inte = integrator(timeStep=0.001, nu=1.0)
    inte.register(atomSystem=A, forceField=ff)
    sb.findNegh()
    ff.updateAllF()
    A.reduce_pe()
    KE0, _ = total_energy(A)

    for step in range(5000):
        sb.findNegh()
        inte.inteBegin()
        sb.applyPbc()

    KE, _ = total_energy(A)
    print(f"KE0={KE0:.4f}, KE_final={KE:.4f}")
    assert KE < 0.5 * KE0, f"ν>0 must reduce KE substantially; got {KE/KE0:.2f}"
    print("OK: BAOAB ν>0 dissipates KE")


if __name__ == "__main__":
    test_baoab_nu0_energy_conservation()
    test_baoab_nu_positive_kinetic_decay()
    print("OK: all BAOAB tests passed")

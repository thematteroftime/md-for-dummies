"""§6.1 验收 2: N=4 AABB体系 Hertzian 力 4 组合手算对比.

Layout (used below):
  0: A (0.0, 0.0, 0)
  1: B (0.3, 0.0, 0)            AB pair, r=0.3, x=0.6
  2: A (5.0, 0.0, 0)
  3: B (5.3, 0.0, 0)            AB pair, r=0.3, x=0.6
  cutoff r0=0.5; box 10x10x1; isolated pairs.

Expected (per Hertzian, full_list path):
  phi0/r0 = 1.0/0.5 = 2.0 (prefactor)
  x = r/r0 = 0.3/0.5 = 0.6
  F_r = (phi0/r0)*(1-x) = 2.0*(0.4) = 0.8
  F_n = (phi0/r0)*(1-x)^2 = 2.0*0.16 = 0.32
  pair (0,1): atom 0=A's neighbor j=1=B → mag(0) = F_r + F_n = 1.12
              direction r̂_{0→1} = +x̂; force[0] += -mag * r̂ = -1.12 x̂
  atom 1=B's neighbor j=0=A → mag(1) = F_r - F_n = 0.48
              direction r̂_{1→0} = -x̂; force[1] += -mag * r̂ = +0.48 x̂
"""
import os
import sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import constSet as cs
from atomSystemClass import AtomSystem
from searchBox import searchBox
from forces import HertzianNonreciprocal


def test_hertzian_4cases():
    cs.reconfigure(units="reduced", log=False, debug=False, profiler=False)

    pos = np.array([
        [0.0, 0.0, 0.0],
        [0.3, 0.0, 0.0],
        [5.0, 0.0, 0.0],
        [5.3, 0.0, 0.0],
    ])
    masses = np.ones(4)
    groups = np.array([1, 2, 1, 2], dtype=np.int32)
    box = [10.0, 0, 0, 0, 10.0, 0, 0, 0, 1.0]

    A = AtomSystem(num_atoms=4, n=3, cutoff=0.5, ndim=2)
    A.initData(pos, masses, 0.0, box, groups=groups)
    A.vel.fill(0.0)
    sb = searchBox(choose=2, mN=8, cutoffNegh=0.6, full_list=True)
    sb.register(A)
    ff = HertzianNonreciprocal(r0=0.5, phi0=1.0, reciprocal=False)
    ff.register(atomSystem=A, searchBox=sb)

    sb.findNegh()
    ff.updateAllF()

    F = A.force.to_numpy()
    print("forces:", F[:, 0])

    expected = np.array([-1.12, 0.48, -1.12, 0.48])
    err = np.max(np.abs(F[:, 0] - expected))
    assert err < 1e-9, f"force mismatch: got {F[:, 0]}, expected {expected}"
    print(f"OK: 4-case Hertzian force matches PRX Eq.1, max err={err:.2e}")


def test_hertzian_AA_pair_no_F_n():
    """AA pair: even single A at small r — current buggy code applies +F_n.

    Layout: 2 atoms both group=1, r=0.3 → x=0.6
    phi0/r0 = 1.0/0.5 = 2.0, F_r = 2.0*0.4 = 0.8, F_n = 2.0*0.16 = 0.32
    Expected: AA same-species ⇒ pure reciprocal F_r only.
      force[0] = -F_r * r̂ = -0.8 x̂
      force[1] = -F_r * (-r̂) = +0.8 x̂
    Buggy (gi-only): both gi==1 ⇒ +F_n applied even though gj is also A.
      force[0] = -(F_r+F_n) * r̂ = -1.12 x̂
      force[1] = -(F_r+F_n) * (-r̂) = +1.12 x̂
    """
    cs.reconfigure(units="reduced", log=False, debug=False, profiler=False)
    pos = np.array([[0.0, 0, 0], [0.3, 0, 0]])
    masses = np.ones(2)
    groups = np.array([1, 1], dtype=np.int32)
    box = [10.0, 0, 0, 0, 10.0, 0, 0, 0, 1.0]

    A = AtomSystem(num_atoms=2, n=3, cutoff=0.5, ndim=2)
    A.initData(pos, masses, 0.0, box, groups=groups)
    A.vel.fill(0.0)
    sb = searchBox(choose=2, mN=4, cutoffNegh=0.6, full_list=True)
    sb.register(A)
    ff = HertzianNonreciprocal(r0=0.5, phi0=1.0, reciprocal=False)
    ff.register(atomSystem=A, searchBox=sb)
    sb.findNegh()
    ff.updateAllF()
    F = A.force.to_numpy()
    expected = np.array([-0.8, 0.8])  # F_r only, no F_n; phi0/r0=2.0, F_r=2.0*0.4=0.8
    err = np.max(np.abs(F[:, 0] - expected))
    assert err < 1e-9, f"AA pair must NOT include F_n: got {F[:, 0]}, expected {expected}"
    print(f"OK: AA pair = pure F_r, max err={err:.2e}")


if __name__ == "__main__":
    test_hertzian_4cases()
    test_hertzian_AA_pair_no_F_n()

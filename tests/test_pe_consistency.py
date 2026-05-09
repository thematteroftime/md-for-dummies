"""§6.1 验收 7: total PE via pe_per_atom matches manual sum of pair potentials.

Sets up a deterministic 4-atom LJ ring; computes ground-truth PE by enumeration;
asserts force kernel + reduce_pe gives the same number.
"""
import os
import sys
import math
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import constSet as cs
from atomSystemClass import AtomSystem
from searchBox import searchBox
from forces import lennardJones


def lj_pair(r, sigma=1.0, eps=1.0):
    s6 = (sigma / r) ** 6
    return 4 * eps * s6 * (s6 - 1.0)


def test_total_PE_matches_manual_sum():
    cs.reconfigure(units="reduced", log=False, debug=False, profiler=False)
    pos = np.array([
        [0.0, 0.0, 0.0],
        [1.2, 0.0, 0.0],
        [1.2, 1.2, 0.0],
        [0.0, 1.2, 0.0],
    ])
    masses = np.ones(4)
    box = [10.0, 0, 0, 0, 10.0, 0, 0, 0, 10.0]

    A = AtomSystem(num_atoms=4, n=3, cutoff=2.5, ndim=3)
    A.initData(pos, masses, 0.0, box, groups=None)
    A.vel.fill(0.0)
    sb = searchBox(choose=2, mN=8, cutoffNegh=3.0)
    ff = lennardJones(sigma=1.0, eps=1.0)
    sb.register(A, forceField=ff)
    ff.register(atomSystem=A, searchBox=sb)
    sb.findNegh()
    ff.updateAllF()
    A.reduce_pe()

    manual_pe = 0.0
    for i in range(4):
        for j in range(i + 1, 4):
            r = float(np.linalg.norm(pos[i] - pos[j]))
            if r <= 2.5:
                manual_pe += lj_pair(r)

    pe_kernel = float(A.pe[None])
    err = abs(pe_kernel - manual_pe) / max(abs(manual_pe), 1e-30)
    print(f"PE_manual={manual_pe:.6e}, PE_kernel={pe_kernel:.6e}, rel_err={err:.2e}")
    assert err < 1e-9, f"PE mismatch beyond float roundoff: {err:.3e}"


if __name__ == "__main__":
    test_total_PE_matches_manual_sum()
    print("OK")

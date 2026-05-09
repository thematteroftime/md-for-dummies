"""3-case unit test for `forces.kalj.KobAndersenLJ` — pair-force magnitudes.

Layout (each pair isolated in a 20x20x20 cube):
  AA pair: atoms 0 (A) and 1 (A) at r = 1.0          ⇒ at the σ_AA·2^{1/6} *not* — at r=σ_AA where F should be ε·24/r·(2-1) = 24
  AB pair: atoms 2 (A) and 3 (B) at r = 0.85         ⇒ inside cutoff
  BB pair: atoms 4 (B) and 5 (B) at r = 0.95         ⇒ inside cutoff

Analytic LJ force magnitude (from j toward j, repulsive at small r):
    F = 24·ε·(2·s12/r^13 - s6/r^7),   s = σ.
At r = σ: F = 24·ε·(2 - 1) / σ = 24·ε / σ.

Expected magnitudes with KA defaults:
  AA at r=1.0 σ_AA=1: F = 24·1·(2 - 1)/1 = 24
  AB at r=0.85, σ=0.8, ε=1.5: 0.8/0.85=0.9412..; (0.8/0.85)^6=0.6961; (0.8/0.85)^12=0.4845
                              F = 24·1.5·(2·0.4845 - 0.6961)/0.85 = 24·1.5·(0.969 - 0.6961)/0.85
                                ≈ 24·1.5·0.2729/0.85 ≈ 11.55
  BB at r=0.95, σ=0.88, ε=0.5: σ/r = 0.9263; (σ/r)^6=0.6320; (σ/r)^12=0.3994
                                F = 24·0.5·(2·0.3994 - 0.6320)/0.95 = 24·0.5·0.1668/0.95
                                  ≈ 2.107

Cutoff check: AB pair at r = 2.5·0.8 + 0.01 = 2.01 should give F = 0.
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
from forces import KobAndersenLJ


def _build_three_pair_system():
    """6 atoms in 3 isolated pairs (AA / AB / BB), 3D box, far enough that
    no cross-pair force escapes the cutoff."""
    pos = np.array([
        [1.0, 1.0, 1.0],   # 0: A
        [2.0, 1.0, 1.0],   # 1: A — AA pair, r = 1.0 along x

        [1.0, 6.0, 1.0],   # 2: A
        [1.85, 6.0, 1.0],  # 3: B — AB pair, r = 0.85 along x

        [1.0, 12.0, 1.0],  # 4: B
        [1.95, 12.0, 1.0], # 5: B — BB pair, r = 0.95 along x
    ])
    masses = np.ones(6)
    groups = np.array([1, 1, 1, 2, 2, 2], dtype=np.int32)
    box = [20.0, 0, 0, 0, 20.0, 0, 0, 0, 20.0]
    return pos, masses, groups, box


def test_kalj_three_pair_forces():
    cs.reconfigure(units="reduced", log=False, debug=False, profiler=False)

    pos, masses, groups, box = _build_three_pair_system()

    # Cutoff = 2.5·σ_AA = 2.5 (largest pair). cutoffNegh slightly larger.
    A = AtomSystem(num_atoms=6, n=3, cutoff=2.5, ndim=3)
    A.initData(pos, masses, 0.0, box, groups=groups)
    A.vel.fill(0.0)

    sb = searchBox(choose=2, mN=16, cutoffNegh=3.0, full_list=True)
    sb.register(A)
    ff = KobAndersenLJ()
    ff.register(atomSystem=A, searchBox=sb)

    sb.findNegh()
    ff.updateAllF()

    F = A.force.to_numpy()

    # Expected magnitudes computed by hand above.
    # The LJ pair force pushes the two atoms apart along x; expected x-components:
    #   atom 0: -24    (force toward -x)            atom 1: +24
    #   atom 2: -11.55                               atom 3: +11.55
    #   atom 4: -2.107                               atom 5: +2.107
    expected_F_AA = 24.0
    expected_F_AB = 24.0 * 1.5 * (2.0 * (0.8 / 0.85) ** 12 - (0.8 / 0.85) ** 6) / 0.85
    expected_F_BB = 24.0 * 0.5 * (2.0 * (0.88 / 0.95) ** 12 - (0.88 / 0.95) ** 6) / 0.95

    print("force x-components:", F[:, 0])
    print("expected (AA, AB, BB):", expected_F_AA, expected_F_AB, expected_F_BB)

    # Atom 0: force points from 1→0 i.e. -x;  Atom 1: opposite.
    assert abs(F[0, 0] - (-expected_F_AA)) < 1e-6, f"AA force atom 0 mismatch: {F[0,0]}"
    assert abs(F[1, 0] - (+expected_F_AA)) < 1e-6, f"AA force atom 1 mismatch: {F[1,0]}"

    assert abs(F[2, 0] - (-expected_F_AB)) < 1e-6, f"AB force atom 2 mismatch: {F[2,0]}"
    assert abs(F[3, 0] - (+expected_F_AB)) < 1e-6, f"AB force atom 3 mismatch: {F[3,0]}"

    assert abs(F[4, 0] - (-expected_F_BB)) < 1e-6, f"BB force atom 4 mismatch: {F[4,0]}"
    assert abs(F[5, 0] - (+expected_F_BB)) < 1e-6, f"BB force atom 5 mismatch: {F[5,0]}"

    print(f"OK KA-LJ 3-pair forces match analytic values "
          f"(AA={expected_F_AA:.4f}, AB={expected_F_AB:.4f}, BB={expected_F_BB:.4f})")


def test_kalj_force_zero_past_cutoff():
    """Two A atoms with r > 2.5·σ_AA must give F = 0 (truncate-and-shift)."""
    cs.reconfigure(units="reduced", log=False, debug=False, profiler=False)

    # r = 2.6 > 2.5 ⇒ outside cutoff for AA pair.
    pos = np.array([
        [1.0, 1.0, 1.0],
        [3.6, 1.0, 1.0],
    ])
    masses = np.ones(2)
    groups = np.array([1, 1], dtype=np.int32)
    box = [20.0, 0, 0, 0, 20.0, 0, 0, 0, 20.0]

    A = AtomSystem(num_atoms=2, n=3, cutoff=2.5, ndim=3)
    A.initData(pos, masses, 0.0, box, groups=groups)
    A.vel.fill(0.0)

    sb = searchBox(choose=2, mN=8, cutoffNegh=3.0, full_list=True)
    sb.register(A)
    ff = KobAndersenLJ()
    ff.register(atomSystem=A, searchBox=sb)

    sb.findNegh()
    ff.updateAllF()
    F = A.force.to_numpy()

    print("force outside cutoff:", F[:, 0])
    assert np.max(np.abs(F)) < 1e-12, f"force should be zero past cutoff but got {F}"
    print("OK KA-LJ force is exactly zero past 2.5σ cutoff")


def test_kalj_potential_continuous_at_cutoff():
    """V_pair must be continuous at r = r_c (truncate-and-shift)."""
    cs.reconfigure(units="reduced", log=False, debug=False, profiler=False)

    # Test pe-per-atom contribution at r barely below r_c — should equal -(some small number)
    # Easier: just construct the force class and check Vshift is correct.
    ff = KobAndersenLJ()

    # V_LJ_unshifted(r_c) for each pair must equal the stored shift constant.
    for sigma, eps, vshift in (
        (ff.sigma_AA, ff.eps_AA, ff.Vshift_AA),
        (ff.sigma_AB, ff.eps_AB, ff.Vshift_AB),
        (ff.sigma_BB, ff.eps_BB, ff.Vshift_BB),
    ):
        rc = 2.5 * sigma
        v_at_rc = 4.0 * eps * ((sigma / rc) ** 12 - (sigma / rc) ** 6)
        assert abs(v_at_rc - vshift) < 1e-12, \
            f"shift mismatch: V_LJ({rc})={v_at_rc} vs stored {vshift}"
    print("OK KA-LJ Vshift constants make V continuous at r_c per pair")


if __name__ == "__main__":
    test_kalj_three_pair_forces()
    test_kalj_force_zero_past_cutoff()
    test_kalj_potential_continuous_at_cutoff()
    print("\nAll 3 KA-LJ pair tests passed.")

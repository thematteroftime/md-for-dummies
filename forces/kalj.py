"""Kob-Andersen binary Lennard-Jones — Pedersen et al., PRL 120, 165501 (2018).

Pair potential (paper p.2):
    v_pq(r) = 4·ε_pq · [(σ_pq/r)^12 - (σ_pq/r)^6],   r < r_c_pq = 2.5 σ_pq,
    v_pq(r) = 0,                                      r ≥ r_c_pq.

Standard KA parameters:
    σ_AA = 1.0,       ε_AA = 1.0
    σ_BB = 0.88,      ε_BB = 0.5
    σ_AB = 0.8,       ε_AB = 1.5
mass_A = mass_B = 1, k_B = 1, time τ = sqrt(m·σ_AA²/ε_AA).

Truncated-and-shifted: V is shifted by V(r_c_pq) so it is continuous at the cutoff.
For consistency the kernel reads `atomSystem.cutoff` for the neighbour-list cutoff
(must be ≥ max r_c_pq = 2.5·σ_AA = 2.5 in reduced units).
"""
from constSet import *
from forces.base import forceField


@ti.data_oriented
class KobAndersenLJ(forceField):
    """Binary Lennard-Jones with per-species pair (σ, ε) — Kob-Andersen 80:20.

    Group convention (set by the adapter when assembling the lattice):
        group[i] == 1 → species A
        group[i] == 2 → species B
    """
    requires_full_list = True
    PREFLIGHT_FIELDS = ("N", "T0", "rho", "steps")

    def __init__(self, sigma_AA: float = 1.0, sigma_AB: float = 0.8, sigma_BB: float = 0.88,
                 eps_AA: float = 1.0, eps_AB: float = 1.5, eps_BB: float = 0.5,
                 cutoff_factor: float = 2.5):
        # Store the three pair-types as plain Python floats; these become
        # ti.f64 attributes on the @ti.data_oriented instance and are
        # accessible inside @ti.func as `self.sigma_AA` etc.
        self.sigma_AA = float(sigma_AA)
        self.sigma_AB = float(sigma_AB)
        self.sigma_BB = float(sigma_BB)
        self.eps_AA = float(eps_AA)
        self.eps_AB = float(eps_AB)
        self.eps_BB = float(eps_BB)
        self.cutoff_factor = float(cutoff_factor)

        # Per-pair cutoffs and the V(r_c) shift constant for truncate-and-shift.
        self.rc_AA = self.cutoff_factor * self.sigma_AA
        self.rc_AB = self.cutoff_factor * self.sigma_AB
        self.rc_BB = self.cutoff_factor * self.sigma_BB

        # V_LJ(rc) for the shift. (σ/rc)^6 = 1/cutoff_factor^6 by construction.
        sr6 = 1.0 / (self.cutoff_factor ** 6)
        self.Vshift_AA = 4.0 * self.eps_AA * sr6 * (sr6 - 1.0)
        self.Vshift_AB = 4.0 * self.eps_AB * sr6 * (sr6 - 1.0)
        self.Vshift_BB = 4.0 * self.eps_BB * sr6 * (sr6 - 1.0)

        # Powers of sigma we'll use inside the kernel (avoid pow at runtime).
        self.s6_AA = self.sigma_AA ** 6
        self.s6_AB = self.sigma_AB ** 6
        self.s6_BB = self.sigma_BB ** 6
        self.s12_AA = self.s6_AA * self.s6_AA
        self.s12_AB = self.s6_AB * self.s6_AB
        self.s12_BB = self.s6_BB * self.s6_BB

        self.reciprocal = True
        return

    @ti.func
    def _pair_params(self, gi: ti.i32, gj: ti.i32):
        """Branchless dispatch by species pair → (eps, sigma6, sigma12, rc^2, Vshift)."""
        eps = self.eps_AA
        s6 = self.s6_AA
        s12 = self.s12_AA
        rc = self.rc_AA
        vshift = self.Vshift_AA
        if gi == 1 and gj == 1:
            eps = self.eps_AA; s6 = self.s6_AA; s12 = self.s12_AA
            rc = self.rc_AA;   vshift = self.Vshift_AA
        elif gi == 2 and gj == 2:
            eps = self.eps_BB; s6 = self.s6_BB; s12 = self.s12_BB
            rc = self.rc_BB;   vshift = self.Vshift_BB
        else:
            eps = self.eps_AB; s6 = self.s6_AB; s12 = self.s12_AB
            rc = self.rc_AB;   vshift = self.Vshift_AB
        return eps, s6, s12, rc * rc, vshift

    @ti.func
    def updateOneF_reciprocal(self, i: ti.i32, j: ti.i32):
        rij = self.atomSystem.pos[j] - self.atomSystem.pos[i]
        rij = self.searchBox.applyMic(rij)
        r = rij.norm()
        r2 = r * r

        gi = self.atomSystem.group[i]
        gj = self.atomSystem.group[j]
        eps, s6, s12, rc2, vshift = self._pair_params(gi, gj)

        if r2 <= rc2 and r > 1e-12:
            r6 = r * r * r * r * r * r       # r^6, no pow
            r12 = r6 * r6
            r7 = r6 * r
            r13 = r12 * r

            # F_LJ pointing from j → i: F = -dV/dr * r_hat_ji
            # V = 4ε[(σ/r)^12 - (σ/r)^6] = 4ε[s12/r^12 - s6/r^6]
            # dV/dr = 4ε[-12·s12/r^13 + 6·s6/r^7]
            # F_mag (positive = repulsive, pushes i away from j when small r) =
            #   24·ε·(2·s12/r^13 - s6/r^7)
            force_mag = 24.0 * eps * (2.0 * s12 / r13 - s6 / r7)
            rij_unit = rij / r
            # rij = r_j - r_i. force_mag·rij_unit pushes i toward j; we want the
            # opposite (LJ repulsive at small r pushes i AWAY from j).
            fij = -force_mag * rij_unit

            # Full-list pattern: write only force[i]; the (j, i) visit handles j.
            self.atomSystem.force[i] += fij

            # PE per-atom (truncated-and-shifted): 0.5 factor for full-list double-visit.
            U_pair = 4.0 * eps * (s12 / r12 - s6 / r6) - vshift
            self.atomSystem.pe_per_atom[i] += 0.5 * U_pair
        return

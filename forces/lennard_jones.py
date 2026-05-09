"""Lennard-Jones 12-6 pair potential.

V(r) = 4ε [(σ/r)^12 - (σ/r)^6]
F(r) = 24ε [2(σ/r)^12 - (σ/r)^6] / r
"""
from constSet import *
from forces.base import forceField


@ti.data_oriented
class lennardJones(forceField):
    requires_full_list = True    # full-list, eliminates force[j] atomic writes
    PREFLIGHT_FIELDS = ("N", "T0", "rho", "steps")

    def __init__(self, sigma, eps):
        self.sigma6 = np.power(sigma, 6)
        self.sigma12 = self.sigma6 * self.sigma6
        self.sigma = sigma
        self.eps = eps
        self.reciprocal = True

        return

    @ti.func
    def updateOneF_reciprocal(self, i: ti.i32, j: ti.i32):
        rij = self.atomSystem.pos[j] - self.atomSystem.pos[i]
        rij = self.searchBox.applyMic(rij)
        rij_norm = rij.norm()
        rij_norm_sq = rij_norm * rij_norm

        if rij_norm_sq <= self.cutoffSquare:
            s6rij6 = self.sigma6 / ti.pow(rij_norm, 6)
            force_mag = self.calForce(rij_norm)
            rij_unit = rij / rij_norm
            fij = -force_mag * rij_unit

            # Full-list: write only force[i]; neighbour list has both (i,j) and (j,i).
            self.atomSystem.force[i] += fij

            # PE per-atom: 0.5*U on i side only; full-list visits each ordered pair once,
            # so sum over all (i,j) with 0.5 gives the unordered-pair sum.
            self.atomSystem.pe_per_atom[i] += 0.5 * self.calPotential(s6rij6)

        return

    @ti.func
    def calForce(self, r_norm: ti.f64) -> ti.f64:
        r6 = ti.pow(r_norm, 6)
        r7 = r6 * r_norm
        r13 = ti.pow(r_norm, 13)
        return 24 * self.eps * (2 * self.sigma12 / r13 - self.sigma6 / r7)

    @ti.func
    def calPotential(self, s6rij6):
        return 4 * self.eps * s6rij6 * (s6rij6 - 1)

"""Non-reciprocal Hertzian repulsion — Ivlev et al. PRX 5, 011035 (2015) Eq. (1).

For r < r0: F_AB ≠ F_BA (cross-species only); intra-species reciprocal.
"""
from constSet import *
from forces.base import forceField


@ti.data_oriented
class HertzianNonreciprocal(forceField):
    requires_full_list = True
    PREFLIGHT_FIELDS = ("phi", "T0", "nu", "N", "steps")

    def __init__(self, r0, phi0, reciprocal=False):
        self.r0 = r0
        self.phi0 = phi0
        self.reciprocal = reciprocal
        return

    @ti.func
    def updateOneF_nonreciprocal(self, i: ti.i32, j: ti.i32):
        rij = self.searchBox.applyMic(self.atomSystem.pos[j] - self.atomSystem.pos[i])
        r = rij.norm()
        if r >= self.r0:
            pass
        else:
            r_hat = rij / r
            x = r / self.r0
            F_r = (self.phi0 / self.r0) * (1.0 - x)
            F_n = (self.phi0 / self.r0) * (1.0 - x) ** 2
            gi = self.atomSystem.group[i]
            gj = self.atomSystem.group[j]
            mag = F_r
            if gi != gj:                          # cross-species only
                sign = 1.0 if gi == 1 else -1.0   # A: +F_n, B: -F_n
                mag += sign * F_n
            self.atomSystem.force[i] += -mag * r_hat
            self.atomSystem.pe_per_atom[i] += 0.25 * self.phi0 * (1.0 - x) ** 2
        return

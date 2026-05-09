"""Anisotropic Yukawa (ER plasma) pair potential — Ivlev et al. PRL 100, 095003 (2008) Eq. (1).

W(r,θ) = α [exp(-r/λ)/r - 0.43 M_T² λ² (3cos²θ - 1)/r³]
where α = K_E · Z_eff² (resolved at register-time from the active units regime)
"""
from constSet import *
from forces.base import forceField


@ti.data_oriented
class ERPotential(forceField):
    requires_full_list = True
    PREFLIGHT_FIELDS = ("MT", "Z_eff", "lambda_mm", "T0_K", "N", "steps")

    def __init__(self, Z_eff, lambda_screen, MT, E_dir=ti.Vector([0.0, 0.0, 1.0])):
        self.Z_eff = Z_eff
        self.lb = lambda_screen
        self.MT2 = MT ** 2
        self.E_dir = E_dir
        self.reciprocal = True

    def register(self, atomSystem, searchBox):
        # Resolve alpha at register-time so cs.UNITS reflects run.in choice.
        import constSet as cs
        self.alpha = cs.UNITS.KE_E2 * (self.Z_eff ** 2)
        super().register(atomSystem, searchBox)

    @ti.func
    def updateOneF_reciprocal(self, i: ti.i32, j: ti.i32):
        rij_vec = self.searchBox.applyMic(self.atomSystem.pos[j] - self.atomSystem.pos[i])
        r = rij_vec.norm()

        cos_theta = rij_vec.dot(self.E_dir) / r
        cos2_theta = cos_theta ** 2

        # Radial force component: F_r = -dW/dr
        term1_r = (1 / r + 1 / self.lb) * ti.exp(-r / self.lb) / (r)
        term2_r = -3.0 * 0.43 * self.MT2 * (self.lb ** 2) * (3 * cos2_theta - 1) / (r ** 4)
        Fr = self.alpha * (term1_r + term2_r)

        # Angular force coefficient: F_θ from -dW/d(cosθ)
        F_angular_coeff = self.alpha * (0.43 * self.MT2 * self.lb ** 2 / r ** 3) * (6 * cos_theta)

        f_vec = (Fr / r) * rij_vec
        f_vec += (F_angular_coeff / r) * (self.E_dir - cos_theta * (rij_vec / r))

        self.atomSystem.force[i] -= f_vec

        cos2 = cos_theta ** 2
        U_pair = self.alpha * (
            ti.exp(-r / self.lb) / r
            - 0.43 * self.MT2 * (self.lb ** 2) * (3 * cos2 - 1) / (r ** 3)
        )
        self.atomSystem.pe_per_atom[i] += 0.5 * U_pair

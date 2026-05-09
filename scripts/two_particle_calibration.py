"""Sanity-check per-collision energy injection for our Hertzian non-reciprocal force.

Set up a controlled 2-particle A-B collision: place A at (0,0,0) and B at
(b, ρ, 0) where b is far enough that they're outside cutoff, give them an
approach velocity (along x), and let them swing past each other.

Paper Eq. (5):  M·δV = ∫ 2·F_n(r(t)) dt  along the relative-motion trajectory
                = 4·f_n(ρ)             (small-angle approximation)
where f_n(ρ) is the scattering integral from Appendix A.

We measure (a) the actual δV produced by integrating one full collision and
(b) compare to the analytical 4·f_n(ρ).

Successful match (within ~10%) means the force kernel + integrator together
correctly inject the per-collision energy that drives the asymptotic t^(2/3)
heating. A mismatch would localize the slope-cap problem to the dynamics
loop rather than the underlying potential.

Usage:
    python scripts/two_particle_calibration.py
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
from forces import HertzianNonreciprocal
from integratorClass import integrator


def f_n_analytical(rho, r_max=1.0, n_pts=2000):
    """Reproduce f_n(rho) = rho * int F_n / sqrt(r^2 - rho^2) dr  via cosh substitution."""
    if rho >= r_max:
        return 0.0
    u_max = np.arccosh(r_max / rho)
    u = np.linspace(0.0, u_max, n_pts)
    r = rho * np.cosh(u)
    F_n = np.where(r < 1.0, (1.0 - r) ** 2, 0.0)
    return rho * np.trapezoid(F_n, u)


def measure_collision(rho, v_approach=2.0, x_init=3.0, dt=1e-4, n_steps=200000):
    """Place A at origin, B at (x_init, rho, 0); shoot B toward A with -v_approach along x.

    Returns delta_V_AB (CoM velocity after - before, A=group1, B=group2).
    """
    pos = np.array([
        [0.0, 0.0, 0.0],          # A at origin
        [x_init, rho, 0.0],       # B at impact-parameter rho
    ])
    masses = np.ones(2)
    groups = np.array([1, 2], dtype=np.int32)   # A=1, B=2

    # Box big enough that PBC doesn't matter for the brief swing.
    L = 100.0
    box = [L, 0, 0, 0, L, 0, 0, 0, 1.3]

    A = AtomSystem(num_atoms=2, n=3, cutoff=1.0, ndim=2)
    A.initData(pos, masses, 0.0, box, groups=groups)
    A.vel.fill(0.0)
    # Manually set initial velocities: A at rest; B moving in -x.
    vel = A.vel.to_numpy()
    vel[0] = [0.0, 0.0, 0.0]
    vel[1] = [-v_approach, 0.0, 0.0]
    A.vel.from_numpy(vel)

    sb = searchBox(choose=2, mN=4, cutoffNegh=1.2, full_list=False)
    ff = HertzianNonreciprocal(r0=1.0, phi0=1.0, reciprocal=False)
    sb.register(atomSystem=A, forceField=ff)
    ff.register(atomSystem=A, searchBox=sb)
    inte = integrator(timeStep=dt, nu=0.0)
    inte.register(atomSystem=A, forceField=ff)

    # Initial CoM velocity (= 0.5*(0 + -v_approach) = -v_approach/2 in x).
    v_com_x_init = -v_approach / 2.0

    # Integrate enough steps that B has swept past A (typical sweep takes
    # ~ 2·x_init / v_approach time units).
    t_target = 2.0 * x_init / v_approach
    n_steps_actual = int(math.ceil(t_target / dt)) + 1000  # margin
    if n_steps_actual > n_steps:
        n_steps_actual = n_steps

    for _ in range(n_steps_actual):
        sb.findNegh()
        inte.inteBegin()
        sb.applyPbc()

    vel_final = A.vel.to_numpy()
    v_com_final = 0.5 * (vel_final[0] + vel_final[1])
    delta_V_x = v_com_final[0] - v_com_x_init
    delta_V_y = v_com_final[1]
    return delta_V_x, delta_V_y, v_com_final, vel_final


def main():
    print("Two-particle A-B collision calibration")
    print("Setup: A at origin, B at (3.0, ρ, 0), v_B = (-2, 0, 0)")
    print()
    print("Per paper Eq. (5):  M·δV = 4·f_n(ρ)   (small-angle)")
    print("With m_A = m_B = 1, M = 2, so δV = 2·f_n(ρ).")
    print()
    print(f"  {'ρ':>6}  {'measured δV_y':>14}  {'predicted 2·f_n(ρ)':>20}  {'ratio':>8}")
    for rho in (0.1, 0.2, 0.3, 0.5, 0.7, 0.9):
        try:
            dvx, dvy, vcom_final, vfinal = measure_collision(rho)
        except Exception as e:
            print(f"  rho={rho}: FAILED: {e}")
            continue
        # Note: collision is symmetric in x (B comes in, swings past, exits),
        # so net δV_x for CoM is small. The non-reciprocal kick is along
        # the line from A→B at closest approach, mostly y-direction.
        # That's the relevant component for the asymptotic theory.
        f_n = f_n_analytical(rho)
        predicted = 2.0 * f_n
        magnitude = math.sqrt(dvx * dvx + dvy * dvy)
        ratio = magnitude / predicted if predicted > 1e-12 else float("inf")
        print(f"  {rho:>6.2f}  "
              f"|({dvx:+.4f},{dvy:+.4f})|={magnitude:>7.5f}  "
              f"2·f_n={predicted:>10.5f}  "
              f"ratio={ratio:>6.3f}")


if __name__ == "__main__":
    main()

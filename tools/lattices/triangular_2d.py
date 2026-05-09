"""2D triangular (hexagonal) lattice — for systems with 6-fold symmetry preference.

The two primitive vectors are a1 = (a, 0, 0) and a2 = (a/2, a√3/2, 0), giving
number density n = 2 / (a²·√3). Used for 2D Yukawa / hard-disk / Wigner-crystal
initial conditions where the equilibrium phase is hexatic or solid.

params:
  density (float)          — atoms per unit area; n = 2/(a²·√3) ⇒ a = √(2/(n·√3))
  lattice_constant (float) — alternative: a directly
  Lz (float, optional)     — default 1.0
  jitter (float, optional) — default 0.0
"""
import numpy as np


class TriangularLattice2D:
    ndim = 2
    name = "triangular_2d"

    @classmethod
    def generate(cls, N: int, params: dict) -> tuple[np.ndarray, np.ndarray]:
        if "lattice_constant" in params:
            a = float(params["lattice_constant"])
        elif "density" in params:
            density = float(params["density"])
            a = np.sqrt(2.0 / (density * np.sqrt(3.0)))
        else:
            raise ValueError(
                "TriangularLattice2D needs either `density` or `lattice_constant` "
                f"in params (got keys: {sorted(params.keys())})"
            )

        # Two-atom basis on rectangular supercell of edges (a, a√3) ⇒ density = 2/(a²√3).
        # Need ceil(sqrt(N/2)) cells per side.
        n_cells = int(np.ceil(np.sqrt(N / 2.0)))
        Lx = n_cells * a
        Ly = n_cells * a * np.sqrt(3.0)

        positions = np.zeros((N, 3), dtype=np.float64)
        idx = 0
        for i in range(n_cells):
            for j in range(n_cells):
                if idx >= N:
                    break
                # First basis atom at cell corner + half-cell offset
                positions[idx, 0] = (i + 0.25) * a
                positions[idx, 1] = (j + 0.25) * a * np.sqrt(3.0)
                positions[idx, 2] = 0.0
                idx += 1
                if idx >= N:
                    break
                # Second basis atom: shifted by (a/2, a√3/2) primitive offset
                positions[idx, 0] = (i + 0.75) * a
                positions[idx, 1] = (j + 0.75) * a * np.sqrt(3.0)
                positions[idx, 2] = 0.0
                idx += 1

        jitter = float(params.get("jitter", 0.0))
        if jitter > 0:
            rng = np.random.default_rng(0)
            positions[:, 0:2] += rng.uniform(-jitter * a, jitter * a, size=(N, 2))

        Lz = float(params.get("Lz", 1.0))
        box = np.array(
            [[Lx, 0.0, 0.0],
             [0.0, Ly, 0.0],
             [0.0, 0.0, Lz]],
            dtype=np.float64,
        )
        return positions, box

"""2D square lattice — default IC for ndim=2 papers.

params:
  density (float)        — atoms per unit area; required if `lattice_constant`
                           absent
  lattice_constant (float) — alternative to density; cell edge a where n = 1/a²
  Lz (float, optional)   — z-extent of the box (default 1.0; caller must
                           ensure Lz ≥ cutoffNegh per atomSystemClass.addNegh)
  jitter (float, optional) — fractional displacement per coordinate to break
                             exact-lattice degeneracy (default 0.0)
"""
import numpy as np


class SquareLattice2D:
    ndim = 2
    name = "square_2d"

    @classmethod
    def generate(cls, N: int, params: dict) -> tuple[np.ndarray, np.ndarray]:
        if "lattice_constant" in params:
            a = float(params["lattice_constant"])
            density = 1.0 / (a ** 2)
        elif "density" in params:
            density = float(params["density"])
            a = 1.0 / np.sqrt(density)
        else:
            raise ValueError(
                "SquareLattice2D needs either `density` or `lattice_constant` "
                f"in params (got keys: {sorted(params.keys())})"
            )

        # Make a square grid that fits N points: side = ceil(sqrt(N))
        side = int(np.ceil(np.sqrt(N)))
        Lxy = side * a

        positions = np.zeros((N, 3), dtype=np.float64)
        idx = 0
        for i in range(side):
            for j in range(side):
                if idx >= N:
                    break
                positions[idx, 0] = (i + 0.5) * a
                positions[idx, 1] = (j + 0.5) * a
                positions[idx, 2] = 0.0
                idx += 1

        jitter = float(params.get("jitter", 0.0))
        if jitter > 0:
            rng = np.random.default_rng(0)
            positions[:, 0:2] += rng.uniform(-jitter * a, jitter * a, size=(N, 2))

        Lz = float(params.get("Lz", 1.0))
        box = np.array(
            [[Lxy, 0.0, 0.0],
             [0.0, Lxy, 0.0],
             [0.0, 0.0, Lz]],
            dtype=np.float64,
        )
        return positions, box

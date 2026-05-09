"""3D simple cubic lattice — default IC for ndim=3 papers.

Each atom sits on an integer (i, j, k) site times the lattice constant,
so density n = 1/a³. Side count = ceil(N^(1/3)); leftover sites stay empty
when N is not a perfect cube.

params:
  density (float)          — atoms per unit volume; required if `lattice_constant` absent
  lattice_constant (float) — alternative to density; n = 1/a³
  jitter (float, optional) — fractional displacement per coord (default 0.0)
"""
import numpy as np


class SimpleCubicLattice3D:
    ndim = 3
    name = "simple_cubic_3d"

    @classmethod
    def generate(cls, N: int, params: dict) -> tuple[np.ndarray, np.ndarray]:
        if "lattice_constant" in params:
            a = float(params["lattice_constant"])
        elif "density" in params:
            density = float(params["density"])
            a = (1.0 / density) ** (1.0 / 3.0)
        else:
            raise ValueError(
                "SimpleCubicLattice3D needs either `density` or `lattice_constant` "
                f"in params (got keys: {sorted(params.keys())})"
            )

        side = int(np.ceil(N ** (1.0 / 3.0)))
        L = side * a

        positions = np.zeros((N, 3), dtype=np.float64)
        idx = 0
        for i in range(side):
            for j in range(side):
                for k in range(side):
                    if idx >= N:
                        break
                    positions[idx, 0] = (i + 0.5) * a
                    positions[idx, 1] = (j + 0.5) * a
                    positions[idx, 2] = (k + 0.5) * a
                    idx += 1

        jitter = float(params.get("jitter", 0.0))
        if jitter > 0:
            rng = np.random.default_rng(0)
            positions += rng.uniform(-jitter * a, jitter * a, size=(N, 3))

        box = np.array(
            [[L, 0.0, 0.0],
             [0.0, L, 0.0],
             [0.0, 0.0, L]],
            dtype=np.float64,
        )
        return positions, box
